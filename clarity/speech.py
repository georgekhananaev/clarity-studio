"""Speech connections, public model discovery, and credential isolation."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .config import ConfigStore
from .store import Store, atomic_write

Provider = Literal["openrouter", "local"]
OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_LOCAL_URL = "http://127.0.0.1:8880/v1"
DEFAULT_INSTRUCTIONS = "Speak clearly and naturally, as a concise software tutorial."


def local_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Enter a local HTTP(S) server URL without credentials, query parameters, or fragments.")
    host = parsed.hostname.lower()
    if host not in ("localhost", "localhost."):
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError("Use localhost or a private IP address for the local speech server.") from None
        private_networks = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")]
        if not address.is_loopback and not any(address in n for n in private_networks):
            raise ValueError("Local speech servers must use a loopback or private LAN address.")
    try:
        parsed.port
    except ValueError:
        raise ValueError("The local server port is invalid.") from None
    path = parsed.path.rstrip("/") or "/v1"
    if path.endswith("/audio/speech"):
        path = path[:-13]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class SpeechPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="", max_length=256)
    voice: str = Field(default="", max_length=256)
    instructions: str = Field(default=DEFAULT_INSTRUCTIONS, max_length=2000)


class SpeechSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider = "openrouter"
    local_base_url: str = DEFAULT_LOCAL_URL
    openrouter: SpeechPreferences = Field(default_factory=lambda: SpeechPreferences(model="fish-audio/drama-3"))
    local: SpeechPreferences = Field(default_factory=SpeechPreferences)

    @field_validator("local_base_url")
    @classmethod
    def validate_url(cls, value):
        return local_url(value)


@dataclass(frozen=True)
class Connection:
    provider: str
    base_url: str
    key: str = field(repr=False)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}


class Credentials:
    """Session keys never touch disk. Remembered keys use the macOS Keychain."""
    def __init__(self):
        self.session: dict[str, str] = {}
        self.session_sources: dict[str, str] = {}
        self.lock = threading.Lock()

    @staticmethod
    def keychain():
        import sys
        if sys.platform != "darwin":
            raise ValueError("Remembering keys requires macOS Keychain. Use a session key or environment variable on this system.")
        try:
            from keyring.backends.macOS import Keyring
            return Keyring()
        except Exception:
            raise ValueError("macOS Keychain is unavailable. Use a session key instead.") from None

    def get(self, provider: str, endpoint: str) -> tuple[str, str]:
        account = provider if provider == "openrouter" else f"local:{endpoint}"
        with self.lock:
            if account in self.session:
                return self.session[account], self.session_sources.get(account, "session") if self.session[account] else "none"
            prefer_keychain = self.session_sources.get(account) == "keychain"
        env = "OPENROUTER_API_KEY" if provider == "openrouter" else "CLARITY_LOCAL_API_KEY"
        value = "" if prefer_keychain else os.environ.get(env, "").strip()
        if value:
            return value, "environment"
        try:
            value = self.keychain().get_password("Clarity Studio Speech", account)
        except Exception:
            value = None
        # Query on every read: the browser and independent CLI processes must
        # observe remembered-key additions, replacements, and removals.
        return (value, "keychain") if value else ("", "none")

    def set(self, provider: str, endpoint: str, key: str, remember: bool = False):
        if not isinstance(key, str) or not key.strip() or any(character.isspace() for character in key.strip()):
            raise ValueError("Enter a nonempty API key without whitespace.")
        key = key.strip()
        account = provider if provider == "openrouter" else f"local:{endpoint}"
        if remember:
            try:
                self.keychain().set_password("Clarity Studio Speech", account, key)
            except Exception:
                raise ValueError("Could not save this key in macOS Keychain. Try session-only storage.") from None
        with self.lock:
            if remember:
                self.session.pop(account, None)
            else:
                self.session[account] = key
            self.session_sources[account] = "keychain" if remember else "session"

    def clear(self, provider: str, endpoint: str):
        account = provider if provider == "openrouter" else f"local:{endpoint}"
        try:
            backend = self.keychain()
            if backend.get_password("Clarity Studio Speech", account):
                backend.delete_password("Clarity Studio Speech", account)
        except Exception:
            raise ValueError("Could not remove the saved key from Keychain. No settings were changed.") from None
        with self.lock:
            # Mask an inherited environment key only in this process. Keep
            # reading Keychain so a later external CLI update becomes visible.
            self.session.pop(account, None)
            self.session_sources[account] = "keychain"


class SpeechService:
    def __init__(self, store: Store, credentials: Credentials | None = None):
        self.store = store
        self.credentials = credentials or Credentials()
        self.config = ConfigStore(store.root)
        self.config.import_legacy("speech", store.root / "_speech-settings.json", lambda value: SpeechSettings.model_validate(value).model_dump())
        self.path = self.config.path
        self.cache = store.root / "_speech-catalog.json"
        self.lock = threading.Lock()

    def settings(self) -> SpeechSettings:
        saved = self.config.get("speech")
        return self._validated_settings(saved or {})

    @staticmethod
    def _validated_settings(values: dict) -> SpeechSettings:
        try:
            if not isinstance(values, dict):
                raise ValueError
            return SpeechSettings.model_validate({"local_base_url": os.environ.get("CLARITY_LOCAL_BASE_URL", DEFAULT_LOCAL_URL), **values})
        except (ValidationError, ValueError):
            raise ValueError("Invalid speech settings. Check the supported fields, provider, and local server URL.") from None

    def configure(self, patch: dict) -> dict:
        """Validate and merge a settings-only patch in a single transaction."""
        if not isinstance(patch, dict):
            raise ValueError("Speech settings must be a JSON object.")
        self.config.update("speech", patch, nested=True, validate=lambda values: self._validated_settings(values).model_dump())
        return self.public_settings()

    @staticmethod
    def _provider(provider: str) -> Provider:
        if provider not in ("openrouter", "local"):
            raise ValueError("Choose openrouter or local as the speech provider.")
        return provider

    def set_key(self, provider: Provider, key: str, remember: bool = True) -> dict:
        """Change only the credential at the provider's current endpoint."""
        provider = self._provider(provider)
        if not isinstance(key, str) or not key.strip() or len(key.strip()) > 8192 or any(character.isspace() for character in key.strip()):
            raise ValueError("The key must be a nonempty, single token of at most 8192 characters.")
        settings = self.settings()
        endpoint = OPENROUTER_URL if provider == "openrouter" else settings.local_base_url
        self.credentials.set(provider, endpoint, key.strip(), remember)
        return self.public_settings()

    def remember_key(self, provider: Provider) -> dict:
        """Persist an existing session/environment key without resaving settings."""
        connection = self.connection(self._provider(provider))
        if not connection.key:
            raise ValueError("Enter an API key before choosing Keychain storage.")
        self.credentials.set(connection.provider, connection.base_url, connection.key, True)
        return self.public_settings()

    def clear_key(self, provider: Provider) -> dict:
        """Remove only the current endpoint's credential, leaving settings intact."""
        provider = self._provider(provider)
        settings = self.settings()
        endpoint = OPENROUTER_URL if provider == "openrouter" else settings.local_base_url
        self.credentials.clear(provider, endpoint)
        return self.public_settings()

    def save_choices(self, provider: Provider, preferences: SpeechPreferences) -> dict:
        # Background model/voice saves cannot change connection URLs or keys.
        return self.configure({"provider": provider, provider: preferences.model_dump()})

    def public_settings(self) -> dict:
        settings = self.settings()
        statuses = {}
        for provider, endpoint in [("openrouter", OPENROUTER_URL), ("local", settings.local_base_url)]:
            key, source = self.credentials.get(provider, endpoint)
            statuses[provider] = {"configured": bool(key), "source": source}
        return {**settings.model_dump(), "keys": statuses}

    def save(self, settings: SpeechSettings, key: str | None = None, remember: bool = False, clear: bool = False, credential_provider: Provider | None = None) -> dict:
        # Configuring an integration must not select it for narration.
        provider = credential_provider or settings.provider
        endpoint = OPENROUTER_URL if provider == "openrouter" else settings.local_base_url
        if clear:
            self.credentials.clear(provider, endpoint)
        elif key and key.strip():
            self.credentials.set(provider, endpoint, key.strip(), remember)
        elif remember:
            existing, _ = self.credentials.get(provider, endpoint)
            if not existing:
                raise ValueError("Enter an API key before choosing Keychain storage.")
            self.credentials.set(provider, endpoint, existing, True)
        with self.lock:
            self.config.set("speech", settings.model_dump())
        return self.public_settings()

    def connection(self, provider: Provider | None = None, base_url: str | None = None) -> Connection:
        settings = self.settings()
        provider = self._provider(provider or settings.provider)
        if base_url is not None and provider != "local":
            raise ValueError("A base URL override requires the local speech provider.")
        endpoint = OPENROUTER_URL if provider == "openrouter" else local_url(base_url or settings.local_base_url)
        key, _ = self.credentials.get(provider, endpoint)
        return Connection(provider, endpoint, key)

    def resolve(self, provider=None, model=None, voice=None, instructions=None, base_url=None) -> tuple[Connection, str, str, str]:
        settings = self.settings()
        connection = self.connection(provider, base_url)
        preferences = getattr(settings, connection.provider)
        model = (model if model is not None else preferences.model).strip()
        default_voice = preferences.voice or (os.environ.get("OPENROUTER_VOICE", "") if connection.provider == "openrouter" else "")
        voice = (voice if voice is not None else default_voice).strip()
        if not model:
            raise ValueError("Select a speech model first.")
        if not voice:
            raise ValueError("Choose a voice or enter a voice ID supported by the selected speech model.")
        if connection.provider == "openrouter" and not connection.key:
            raise ValueError("Add your OpenRouter API key in Preferences → Integrations, or set OPENROUTER_API_KEY.")
        return connection, model, voice, instructions if instructions is not None else preferences.instructions

    def test_connection(self, provider: Provider, client=None) -> dict:
        connection = self.connection(provider)
        if provider == "local":
            catalog = self.discover("local", client=client)
            return {"connected": True, "message": f"Local server responded. Found {len(catalog['models'])} models and {len(catalog['voices'])} voices. No audio was generated.", "warnings": catalog["warnings"]}
        if not connection.key:
            raise ValueError("Add an OpenRouter API key before testing authentication.")
        context = client or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)
        try:
            response = context.get(OPENROUTER_URL + "/key", headers=connection.headers)
            check_response(response, connection)
            return {"connected": True, "message": "OpenRouter accepted your key. No audio was generated or credits spent."}
        except httpx.HTTPError:
            raise ValueError("OpenRouter could not be reached. Check your connection.") from None
        finally:
            if client is None:
                context.close()

    def discover(self, provider: Provider = "openrouter", base_url: str | None = None, model: str | None = None, client=None) -> dict:
        connection = Connection("openrouter", OPENROUTER_URL, "") if provider == "openrouter" else self.connection(provider, base_url)
        context = client or httpx.Client(timeout=httpx.Timeout(20, connect=4), follow_redirects=False, trust_env=False)
        warnings = []
        models, voices = [], []
        try:
            params = {"output_modalities": "speech"} if provider == "openrouter" else {}
            response = context.get(connection.base_url + "/models", params=params, headers=connection.headers if provider == "local" else {})
            if response.status_code == 404 and provider == "local":
                warnings.append("This server does not publish a model list. Enter its speech model ID manually.")
            else:
                check_response(response, connection)
                data = response.json()
                entries = data.get("data", data.get("models", []))
                for item in entries:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    modalities = item.get("architecture", {}).get("output_modalities", [])
                    task = item.get("task") or item.get("pipeline_tag")
                    if provider == "openrouter" and "speech" not in modalities:
                        continue
                    if provider == "local" and task and task not in ("text-to-speech", "text_to_speech", "tts", "speech-generation"):
                        continue
                    models.append({"id": item["id"], "name": item.get("name") or item["id"], "description": str(item.get("description") or "")[:1400], "voices": normalize_voices(item.get("supported_voices") or item.get("voices") or []), "pricing": item.get("pricing") or {}})
            if provider == "local":
                response = context.get(connection.base_url + "/audio/voices", params={"model": model} if model else {}, headers=connection.headers)
                if response.status_code not in (404, 405):
                    check_response(response, connection)
                    data = response.json()
                    voices = normalize_voices(data if isinstance(data, list) else data.get("voices", data.get("data", [])))
                if not voices:
                    warnings.append("No voice list was returned. You can enter a supported voice ID manually.")
                if any(not (m.get("voices")) for m in models):
                    warnings.append("A model list alone does not establish speech support; the server must provide POST /audio/speech.")
            result = {"provider": provider, "base_url": connection.base_url, "models": sorted(models, key=lambda m: (m["id"] != "fish-audio/drama-3", m["name"].lower())), "voices": voices, "warnings": warnings, "cached": False}
            if provider == "openrouter":
                atomic_write(self.cache, json.dumps(result))
            return result
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            if provider == "openrouter" and self.cache.is_file():
                result = json.loads(self.cache.read_text())
                result.update(cached=True, warnings=["OpenRouter could not be reached. Showing the last saved speech catalog."])
                return result
            raise ValueError("Could not load speech models. Check the connection URL, API key, and whether the server is running.") from None
        finally:
            if client is None:
                context.close()


def normalize_voices(entries) -> list[dict]:
    voices = {}
    for item in entries:
        if isinstance(item, str):
            voices[item] = {"id": item, "name": item}
        elif isinstance(item, dict) and (item.get("id") or item.get("voice_id")):
            identity = str(item.get("id") or item["voice_id"])
            voices[identity] = {"id": identity, "name": str(item.get("name") or identity)}
    return list(voices.values())


def check_response(response: httpx.Response, connection: Connection) -> None:
    if 200 <= response.status_code < 300:
        return
    label = "OpenRouter" if connection.provider == "openrouter" else "Local speech server"
    hints = {401: "Check your API key.", 402: "Check your account credits.", 404: "Check the endpoint and selected speech model.", 429: "Wait before retrying; the provider is rate-limiting requests."}
    message = ""
    try:
        data = response.json()
        error = data.get("error", data.get("detail", ""))
        message = error.get("message", "") if isinstance(error, dict) else str(error)
    except (ValueError, AttributeError):
        pass
    if connection.key:
        message = message.replace(connection.key, "[redacted]")
    message = re.sub(r"sk-[\w-]+", "[redacted]", message)[:400]
    raise ValueError(f"{label} returned HTTP {response.status_code}. {hints.get(response.status_code, 'Check the selected model, voice, and request settings.')} {message}".strip())
