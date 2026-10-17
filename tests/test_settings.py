from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from clarity.server import create_app
from clarity.settings import editor_preferences, update_editor_preferences
from clarity.speech import SpeechService
from clarity.store import Store


@pytest.fixture
def speech(tmp_path, monkeypatch):
    for name in ("OPENROUTER_API_KEY", "CLARITY_LOCAL_API_KEY", "CLARITY_LOCAL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    return SpeechService(Store(tmp_path / "projects"))


def test_editor_settings_are_shared_with_api_and_clear_last_project(speech):
    updated = update_editor_preferences(speech, {"appearance": "light", "last_project": "demo-123", "sidebar_width": 280})
    assert updated["appearance"] == "light"
    assert updated["storage"]["projects"] == str(speech.store.root)
    with TestClient(create_app(speech.store, speech)) as client:
        assert client.get("/api/preferences").json() == updated
        assert client.put("/api/preferences", json={"last_project": None}).status_code == 200
    restarted = editor_preferences(SpeechService(speech.store))
    assert restarted["last_project"] is None
    assert restarted["appearance"] == "light"
    assert restarted["sidebar_width"] == 280


@pytest.mark.parametrize("patch", [{"appearance": "private-invalid-value"}, {"api_key": "private-invalid-value"}, {"sidebar_width": True}, ["private-invalid-value"]])
def test_editor_patch_validation_is_redacted_and_preserves_previous_settings(speech, patch):
    update_editor_preferences(speech, {"caption_size": 28})
    previous = speech.config.get("editor")
    with pytest.raises(ValueError) as error:
        update_editor_preferences(speech, patch)
    assert "private-invalid-value" not in str(error.value)
    assert speech.config.get("editor") == previous
    assert b"private-invalid-value" not in speech.config.path.read_bytes()


def test_speech_patch_preserves_nested_fields_provider_and_environment_url(speech, monkeypatch):
    monkeypatch.setenv("CLARITY_LOCAL_BASE_URL", "http://localhost:9000/v1")
    speech.configure({"openrouter": {"voice": "cloud-voice", "instructions": "Explain clearly."}})
    result = speech.configure({"openrouter": {"model": "example/tts"}, "local": {"model": "kokoro"}})
    assert result["provider"] == "openrouter"
    assert result["openrouter"] == {"model": "example/tts", "voice": "cloud-voice", "instructions": "Explain clearly."}
    assert result["local"]["model"] == "kokoro"
    assert result["local_base_url"] == "http://localhost:9000/v1"
    assert SpeechService(speech.store).settings().openrouter.voice == "cloud-voice"


def test_nested_speech_patches_from_separate_services_preserve_concurrent_changes(speech):
    speech.configure({"local": {"instructions": "Keep this instruction."}})
    other = SpeechService(speech.store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        updates = [pool.submit(speech.configure, {"local": {"model": "kokoro"}}), pool.submit(other.configure, {"local": {"voice": "af_heart"}})]
        for update in updates:
            update.result()
    assert speech.settings().local.model_dump() == {"model": "kokoro", "voice": "af_heart", "instructions": "Keep this instruction."}


@pytest.mark.parametrize("patch", [
    {"provider": "private-invalid-value"},
    {"local_base_url": "http://user:private-invalid-value@localhost/v1"},
    {"local_base_url": "http://localhost/v1?token=private-invalid-value"},
    {"openrouter": {"api_key": "private-invalid-value"}},
    {"keys": {"openrouter": "private-invalid-value"}},
    {"local": None},
    ["private-invalid-value"],
])
def test_speech_patch_validation_is_redacted_and_transactional(speech, patch):
    speech.configure({"local": {"voice": "af_heart"}})
    previous = speech.config.get("speech")
    with pytest.raises(ValueError) as error:
        speech.configure(patch)
    assert "private-invalid-value" not in str(error.value)
    assert speech.config.get("speech") == previous
    assert b"private-invalid-value" not in speech.config.path.read_bytes()


def test_credential_commands_leave_settings_unchanged_and_isolate_local_endpoints(speech):
    speech.configure({"local_base_url": "http://localhost:8000/v1", "openrouter": {"voice": "cloud"}})
    previous = speech.config.get("speech")
    result = speech.set_key("local", "local-remembered-test-key")
    assert result["provider"] == "openrouter"
    assert result["keys"]["local"] == {"configured": True, "source": "keychain"}
    assert speech.config.get("speech") == previous
    assert speech.connection("local").key == "local-remembered-test-key"
    assert speech.connection("local", "http://localhost:8001/v1").key == ""
    speech.clear_key("local")
    assert not speech.connection("local").key
    assert speech.config.get("speech") == previous
    assert b"local-remembered-test-key" not in speech.config.path.read_bytes()


def test_running_service_observes_external_keychain_add_replace_and_remove(speech):
    other = SpeechService(speech.store)
    assert not speech.connection("openrouter").key  # Negative reads cannot cache forever.
    other.set_key("openrouter", "first-remembered-test-key")
    assert speech.connection("openrouter").key == "first-remembered-test-key"
    speech.set_key("openrouter", "second-remembered-test-key")
    other.set_key("openrouter", "third-remembered-test-key")
    assert speech.connection("openrouter").key == "third-remembered-test-key"
    other.clear_key("openrouter")
    assert not speech.connection("openrouter").key
    other.set_key("openrouter", "fourth-remembered-test-key")
    assert speech.connection("openrouter").key == "fourth-remembered-test-key"
    assert speech.public_settings()["keys"]["openrouter"]["source"] == "keychain"


def test_deliberate_session_key_still_overrides_external_remembered_changes(speech):
    speech.set_key("openrouter", "session-only-test-key", remember=False)
    other = SpeechService(speech.store)
    other.set_key("openrouter", "external-remembered-test-key")
    assert speech.connection("openrouter").key == "session-only-test-key"
    assert speech.public_settings()["keys"]["openrouter"]["source"] == "session"
    other.clear_key("openrouter")
    assert speech.connection("openrouter").key == "session-only-test-key"


def test_key_removal_masks_environment_only_in_current_process(speech, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-test-key")
    assert speech.public_settings()["keys"]["openrouter"]["source"] == "environment"
    speech.clear_key("openrouter")
    assert not speech.connection("openrouter").key
    other = SpeechService(speech.store)
    assert other.connection("openrouter").key == "environment-test-key"
    other.set_key("openrouter", "new-remembered-test-key")
    assert speech.connection("openrouter").key == "new-remembered-test-key"


def test_resolve_local_url_override_is_ephemeral_and_uses_endpoint_specific_key(speech):
    speech.configure({"provider": "local", "local": {"model": "kokoro", "voice": "af_heart"}})
    speech.set_key("local", "saved-endpoint-test-key")
    previous = speech.settings().model_dump()
    connection, model, voice, _ = speech.resolve(base_url="http://localhost:8001/v1")
    assert connection.base_url == "http://localhost:8001/v1"
    assert connection.key == ""
    assert model == "kokoro" and voice == "af_heart"
    assert speech.settings().model_dump() == previous
    with pytest.raises(ValueError, match="local speech provider"):
        speech.resolve(provider="openrouter", base_url="http://localhost:8001/v1")


def test_server_credential_only_lifecycle_preserves_concurrent_settings(speech):
    speech.configure({"provider": "local", "local": {"model": "before", "voice": "af_heart"}})
    with TestClient(create_app(speech.store, speech)) as client:
        client.get("/api/speech/settings")  # An older client snapshot must not be resubmitted.
        speech.configure({"local": {"model": "newer", "instructions": "Keep this edit"}})
        expected = speech.config.get("speech")
        saved = client.put("/api/speech/settings", json={"credential_provider": "openrouter", "api_key": "session-only-test-key", "remember_key": False})
        assert saved.status_code == 200
        assert saved.json()["provider"] == "local"
        assert saved.json()["local"]["model"] == "newer"
        assert saved.json()["keys"]["openrouter"]["source"] == "session"
        assert speech.config.get("speech") == expected
        assert SpeechService(speech.store).connection("openrouter").key == ""
        remembered = client.put("/api/speech/settings", json={"credential_provider": "openrouter", "remember_key": True})
        assert remembered.status_code == 200
        assert remembered.json()["keys"]["openrouter"]["source"] == "keychain"
        assert SpeechService(speech.store).connection("openrouter").key == "session-only-test-key"
        removed = client.put("/api/speech/settings", json={"credential_provider": "openrouter", "clear_key": True})
        assert removed.status_code == 200
        assert not removed.json()["keys"]["openrouter"]["configured"]
        assert not SpeechService(speech.store).connection("openrouter").key
        assert speech.config.get("speech") == expected
        assert "session-only-test-key" not in saved.text + remembered.text + removed.text
        assert b"session-only-test-key" not in speech.config.path.read_bytes()


@pytest.mark.parametrize("payload,status", [
    ({}, 422), ({"api_key": "private-test-value"}, 422), ({"remember_key": True}, 422),
    ({"credential_provider": "local"}, 400), ({"credential_provider": "local", "api_key": "   "}, 400),
])
def test_server_credential_only_requests_require_clear_intent(speech, payload, status):
    previous = speech.settings()
    with TestClient(create_app(speech.store, speech)) as client:
        result = client.put("/api/speech/settings", json=payload)
    assert result.status_code == status
    assert "private-test-value" not in result.text
    assert speech.settings() == previous
