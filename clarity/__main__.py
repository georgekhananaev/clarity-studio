from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import math
import os
import re
import shutil
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import ValidationError

from .media import doctor, frame, inspect_video, probe
from .models import Cue
from .output import browser_preview, export, export_audio, narrate, narration_status, render
from .speech import SpeechService
from .store import ROOT, ConflictError, Store


class CLIError(ValueError):
    """An intentionally public, input-free error message."""


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error repeats argv, which could contain a pasted key.
        raise CLIError("Invalid command or arguments. Run './clarity-cli --help' for usage.")


def build_parser() -> argparse.ArgumentParser:
    parser = JSONArgumentParser(description="Clarity Studio — control recordings, captions, preferences, and narration without a browser. Results are JSON; errors are JSON on stderr.")
    parser.add_argument("--projects-dir", type=Path, help="Isolated projects and settings directory (otherwise CLARITY_PROJECTS_DIR or projects/)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capabilities", help="Read the machine-readable command and API coverage inventory")
    sub.add_parser("doctor", help="Check video tools and narration configuration")
    command = sub.add_parser("health", help="Read local health, or inspect an exact running server with --server")
    command.add_argument("--server", help="Read health from this loopback Clarity server instead of local settings")
    command = sub.add_parser("list", help="List local projects")
    command.add_argument("--search", default="", help="Filter titles, case-insensitively")
    sub.add_parser("speech-settings", help="Read speech preferences and key status (alias for speech-config show)")
    for name, description in (("preferences", "Read or patch editor preferences"), ("speech-config", "Read or patch speech connections and model choices; never include API keys")):
        command = sub.add_parser(name, help=description)
        actions = command.add_subparsers(dest="action", required=True)
        show = actions.add_parser("show")
        if name == "speech-config":
            show.add_argument("--server", help="Read settings and session credential status from this loopback Clarity server")
        change = actions.add_parser("set", help="Merge only the supplied fields; preserve other preferences")
        source = change.add_mutually_exclusive_group(required=True)
        source.add_argument("--json", dest="patch_json", help="JSON object containing non-secret preference fields")
        source.add_argument("--file", dest="patch_file", type=Path, help="Path to a JSON object containing non-secret preference fields")
    command = sub.add_parser("speech-key", help="Manage Keychain or running-server session keys; key values never go in argv")
    actions = command.add_subparsers(dest="action", required=True)
    for name in ("set", "remove", "remember"):
        action = actions.add_parser(name)
        action.add_argument("--provider", choices=["openrouter", "local"], required=True)
        action.add_argument("--server", required=name == "remember", help="Use this loopback Clarity server's credential session")
        if name == "set":
            action.add_argument("--stdin", action="store_true", help="Read one key from stdin instead of a hidden terminal prompt")
            action.add_argument("--session", action="store_true", help="Keep the key only in the specified running server; requires --server")
    command = sub.add_parser("speech-test", help="Check the saved connection/authentication without generating audio or spending speech credits")
    command.add_argument("--provider", choices=["openrouter", "local"], required=True)
    command.add_argument("--server", help="Test this loopback Clarity server's current credential session")
    command = sub.add_parser("speech-models", help="Discover speech models and voices without generating audio")
    command.add_argument("--provider", choices=["openrouter", "local"], default="openrouter")
    command.add_argument("--server", help="Discover models using this loopback Clarity server's current credential session")
    command.add_argument("--base-url", help="Transient local speech API base URL, such as http://127.0.0.1:8880/v1")
    command.add_argument("--model", help="Fetch local voices for a specific model")
    command = sub.add_parser("import", help="Import a local video; references the original unless --copy is supplied")
    command.add_argument("video", type=Path)
    command.add_argument("--title")
    command.add_argument("--copy", action="store_true", help="Copy the video into the project store, matching browser upload behavior")
    for name in ("show", "validate", "inspect", "frame", "cues", "add", "edit", "delete-cue", "rename", "export", "render", "narrate", "audio", "preview", "assets", "asset", "media"):
        command = sub.add_parser(name)
        command.add_argument("project")
        if name in ("edit", "delete-cue"):
            command.add_argument("cue", help="Existing caption ID")
        if name == "inspect":
            command.add_argument("--every", type=float, default=5)
            command.add_argument("--max-frames", type=int, default=48)
        if name == "frame":
            command.add_argument("--time", type=float, required=True)
            command.add_argument("--width", type=int, default=1600, help="Maximum image width; use 0 for original resolution")
        if name == "cues":
            command.add_argument("--file", type=Path, required=True, help="JSON array or object with a cues array")
        if name in ("cues", "rename", "edit", "delete-cue", "add"):
            command.add_argument("--revision", type=int, required=name != "add", help="Revision last read with show; prevents overwriting newer edits")
        if name in ("add", "edit"):
            for field in ("start", "end", "text"):
                command.add_argument(f"--{field}", type=str if field == "text" else float, required=name == "add")
        if name == "rename":
            command.add_argument("--title", required=True)
        if name == "export":
            command.add_argument("--format", choices=["srt", "vtt", "json", "txt"], default="srt")
        if name == "render":
            command.add_argument("--narrated", action="store_true", help="Replace original audio with generated narration")
        if name == "narrate":
            command.add_argument("--server", help="Queue narration using this loopback Clarity server's credentials; returns a job_id")
            command.add_argument("--provider", choices=["openrouter", "local"])
            command.add_argument("--base-url", help="Transient local speech endpoint override; direct mode only, requires the local provider")
            command.add_argument("--voice")
            command.add_argument("--model")
            command.add_argument("--instructions")
            command.add_argument("--cue", action="append", help="Generate only these caption IDs; may be repeated")
        if name == "audio":
            command.add_argument("--format", choices=["mp3", "wav"], default="mp3")
        if name == "asset":
            command.add_argument("--path", required=True, help="File path relative to this project; traversal outside the project is rejected")
    for name in ("job", "job-wait"):
        command = sub.add_parser(name, help="Read a task started by the local HTTP API" if name == "job" else "Wait for a task started by the local HTTP API")
        command.add_argument("job_id")
        command.add_argument("--server", default="http://localhost:8765", help="Loopback-only local Clarity server URL")
        if name == "job-wait":
            command.add_argument("--timeout", type=float, default=300, help="Maximum wait in seconds (0 to check once)")
            command.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds, between 0.05 and 60")
    command = sub.add_parser("serve", help="Start the local review app and HTTP API")
    command.add_argument("--port", type=int, default=8765)
    command.add_argument("--open", action="store_true")
    return parser


def read_patch(args) -> dict:
    try:
        value = json.loads(args.patch_json if args.patch_json is not None else args.patch_file.read_text())
    except json.JSONDecodeError:
        raise CLIError("Invalid JSON. Supply a JSON object containing non-secret preference fields.") from None
    if not isinstance(value, dict):
        raise CLIError("A preferences patch must be a JSON object.")
    return value


def read_key(use_stdin: bool, remember: bool = True) -> str:
    if use_stdin:
        key = sys.stdin.read(8193).strip()
    else:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise CLIError("A hidden terminal prompt is unavailable. Use speech-key set --stdin with a secure input source.")
        destination = "saved in macOS Keychain" if remember else "running server session only"
        key = getpass.getpass(f"Speech API key (hidden; {destination}): ").strip()
    if not key or len(key) > 8192 or any(character.isspace() for character in key):
        raise CLIError("The key must be a nonempty, single token of at most 8192 characters.")
    return key


def server_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        loopback = host.lower() in ("localhost", "localhost.") or ipaddress.ip_address(host).is_loopback
        valid = parsed.scheme in ("http", "https") and loopback and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in ("", "/")
        port = parsed.port
    except ValueError:
        valid, port = False, None
    if not valid or (port is not None and not 1 <= port <= 65535):
        raise CLIError("Use a loopback HTTP(S) Clarity server URL without credentials, paths, query parameters, or fragments.")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def get_server_json(url: str, path: str, client=None, *, method="GET", body=None) -> dict:
    context = client or httpx.Client(timeout=5, follow_redirects=False, trust_env=False)
    try:
        response = context.request(method, url + path, json=body) if body is not None else context.request(method, url + path)
        if not response.is_success:
            raise CLIError(f"The local Clarity server returned HTTP {response.status_code}. Check the requested operation and the local server.")
        try:
            result = response.json()
        except ValueError:
            raise CLIError("The local server did not return JSON.") from None
        if not isinstance(result, dict):
            raise CLIError("The local server returned an invalid response.")
        return result
    except httpx.HTTPError:
        raise CLIError("Could not reach the local Clarity server.") from None
    finally:
        if client is None:
            context.close()


def execute_server(args) -> dict:
    """Operate on a specific server session without opening any local store."""
    if args.command == "narrate":
        if args.base_url is not None:
            raise CLIError("--base-url cannot be combined with narrate --server. Configure the server's local connection or use direct narration.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.project):
            raise CLIError("Invalid project ID.")
    if args.command == "speech-models" and args.base_url is not None and args.provider != "local":
        raise CLIError("--base-url is supported only with the local speech provider.")
    url = server_url(args.server)
    health = get_server_json(url, "/api/health")
    if health.get("app") != "clarity-studio":
        raise CLIError("The local server is not Clarity Studio.")
    if args.command == "health":
        return health
    if args.command == "speech-test":
        return get_server_json(url, "/api/speech/test", method="POST", body={"provider": args.provider})
    if args.command == "speech-models":
        body = {key: value for key, value in {"provider": args.provider, "base_url": args.base_url, "model": args.model}.items() if value is not None}
        return get_server_json(url, "/api/speech/discover", method="POST", body=body)
    if args.command == "narrate":
        body = {key: value for key, value in {"provider": args.provider, "model": args.model, "voice": args.voice, "instructions": args.instructions, "cue_ids": args.cue}.items() if value is not None}
        return get_server_json(url, f"/api/projects/{args.project}/narrate", method="POST", body=body)
    if args.command == "speech-config":
        return get_server_json(url, "/api/speech/settings")
    # Credential-only writes leave concurrently updated connection/model choices intact.
    body = {"credential_provider": args.provider}
    if args.action == "set":
        body.update(api_key=read_key(args.stdin, remember=not args.session), remember_key=not args.session)
    elif args.action == "remember":
        body["remember_key"] = True
    else:
        body["clear_key"] = True
    return get_server_json(url, "/api/speech/settings", method="PUT", body=body)


def read_job(args) -> dict:
    url = server_url(args.server)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.job_id):
        raise CLIError("Invalid task ID.")
    waiting = args.command == "job-wait"
    if waiting and (not math.isfinite(args.timeout) or not 0 <= args.timeout <= 86400 or not math.isfinite(args.interval) or not 0.05 <= args.interval <= 60):
        raise CLIError("Task timeout must be 0–86400 seconds and polling interval must be 0.05–60 seconds.")
    deadline = time.monotonic() + (args.timeout if waiting else 0)
    while True:
        result = get_server_json(url, "/api/jobs/" + args.job_id)
        if result.get("id") != args.job_id or result.get("status") not in ("running", "done", "error"):
            raise CLIError("The local server returned an invalid task response.")
        if not waiting or result["status"] == "done":
            return result
        if result["status"] == "error":
            raise CLIError("The task failed. Inspect its saved status with the job command; no task was retried.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CLIError("Timed out waiting for the task. It may still be running; inspect it with the job command.")
        time.sleep(min(args.interval, remaining))


def import_video(store: Store, path: Path, title: str | None, copy: bool) -> dict:
    if not copy:
        return store.create(probe(path), title).model_dump()
    if path.suffix.lower() not in (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"):
        raise CLIError("Choose an MP4, MOV, M4V, WebM, MKV, or AVI video to copy.")
    if path.stat().st_size > 10 * 1024 ** 3:
        raise CLIError("This recording exceeds the 10 GB copy limit. Import it by reference instead.")
    directory = store.root / "_uploads" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    target = directory / path.name
    try:
        shutil.copyfile(path, target)
        return store.create(probe(target), title).model_dump()
    except Exception:
        target.unlink(missing_ok=True)
        directory.rmdir()
        raise


def execute(args, store: Store, speech: SpeechService):
    if args.command == "serve":
        import uvicorn
        from .server import create_app
        if not 1 <= args.port <= 65535:
            raise CLIError("Port must be between 1 and 65535.")
        url = f"http://localhost:{args.port}"
        try:
            running = get_server_json(url, "/api/health")
        except CLIError:
            running = None
        if running and running.get("app") == "clarity-studio" and running.get("workspace") == str(ROOT) and running.get("projects_directory") == str(store.root):
            if args.open:
                webbrowser.open(url)
            return {"url": url, "status": "already running"}
        if running is not None:
            raise CLIError("Another service or projects directory is already using this port. Choose another --port.")
        if args.open:
            threading.Timer(1, lambda: webbrowser.open(url)).start()
        try:
            uvicorn.run(create_app(store, speech), host="127.0.0.1", port=args.port, access_log=False, log_level="critical")
        except SystemExit as error:
            if error.code:
                raise CLIError("Could not start the local server. Check that the port is available.") from None
        return None
    if args.command == "doctor":
        return {**doctor(), "narration_configured": speech.public_settings()["keys"]["openrouter"]["configured"], "projects_directory": str(store.root)}
    if args.command == "health":
        return {"app": "clarity-studio", "version": "0.1.0", "workspace": str(ROOT), "projects_directory": str(store.root), "narration_configured": speech.public_settings()["keys"]["openrouter"]["configured"], "default_voice": os.environ.get("OPENROUTER_VOICE", "")}
    if args.command == "list":
        return [project.model_dump() for project in store.list() if args.search.strip().casefold() in project.title.casefold()]
    if args.command == "preferences":
        from .settings import editor_preferences, update_editor_preferences
        return editor_preferences(speech) if args.action == "show" else update_editor_preferences(speech, read_patch(args))
    if args.command in ("speech-config", "speech-settings"):
        return speech.configure(read_patch(args)) if args.command == "speech-config" and args.action == "set" else speech.public_settings()
    if args.command == "speech-key":
        return speech.set_key(args.provider, read_key(args.stdin), remember=True) if args.action == "set" else speech.clear_key(args.provider)
    if args.command == "speech-test":
        return speech.test_connection(args.provider)
    if args.command == "speech-models":
        if args.base_url and args.provider != "local":
            raise CLIError("--base-url is supported only with the local speech provider.")
        return speech.discover(args.provider, args.base_url, args.model)
    if args.command == "import":
        return import_video(store, args.video, args.title, args.copy)

    project = store.get(args.project)
    if args.command == "show":
        return {**project.model_dump(), "warnings": project.warnings(), "narration": narration_status(store, project)}
    if args.command == "validate":
        return {"valid": True, "revision": project.revision, "warnings": project.warnings(), "narration": narration_status(store, project)}
    if args.command == "inspect":
        return inspect_video(store, project, args.every, args.max_frames)
    if args.command == "frame":
        return {"path": str(frame(store, project, args.time, args.width)), "time": args.time}
    if args.command == "cues":
        data = json.loads(args.file.read_text())
        cues = data["cues"] if isinstance(data, dict) else data
        if not isinstance(cues, list):
            raise CLIError("Captions must be a JSON array, or an object with a cues array.")
        return store.update(project.id, [Cue.model_validate(cue) for cue in cues], args.revision).model_dump()
    if args.command == "add":
        cue = Cue(start=args.start, end=args.end, text=args.text)
        return store.update(project.id, [*project.cues, cue], project.revision if args.revision is None else args.revision).model_dump()
    if args.command == "rename":
        return store.update(project.id, project.cues, args.revision, args.title).model_dump()
    if args.command in ("edit", "delete-cue"):
        existing = next((cue for cue in project.cues if cue.id == args.cue), None)
        if existing is None:
            raise CLIError("Caption not found. Read the project to get current caption IDs.")
        if args.command == "edit":
            patch = {field: getattr(args, field) for field in ("start", "end", "text") if getattr(args, field) is not None}
            if not patch:
                raise CLIError("Supply at least one of --start, --end, or --text.")
            updated = Cue.model_validate({**existing.model_dump(), **patch})
            cues = [updated if cue.id == existing.id else cue for cue in project.cues]
        else:
            cues = [cue for cue in project.cues if cue.id != existing.id]
        return store.update(project.id, cues, args.revision).model_dump()
    if args.command == "export":
        return {"path": str(export(store, project, args.format))}
    if args.command == "render":
        return {"path": str(render(store, project, args.narrated))}
    if args.command == "narrate":
        connection, model, voice, instructions = speech.resolve(args.provider, args.model, args.voice, args.instructions, base_url=args.base_url)
        return narrate(store, project, voice, model, instructions, connection=connection, cue_ids=args.cue)
    if args.command == "audio":
        return {"path": str(export_audio(store, project, args.format))}
    if args.command == "preview":
        return {"path": str(browser_preview(store, project))}
    if args.command == "media":
        path = Path(project.video.path)
        if not path.is_file():
            raise CLIError("The original video has moved. Import it again from its new location.")
        return {"path": str(path), "size": path.stat().st_size}
    if args.command == "asset":
        path = store.asset(project.id, args.path)
        return {"path": str(path), "relative": str(path.relative_to(store.directory(project.id))), "size": path.stat().st_size}
    if args.command == "assets":
        directory = store.directory(project.id)
        files = []
        for candidate in sorted(directory.rglob("*")):
            relative = candidate.relative_to(directory)
            if any(part.startswith(".") for part in relative.parts) or not candidate.is_file():
                continue
            try:
                path = store.asset(project.id, str(relative))
            except FileNotFoundError:
                continue
            files.append({"path": str(path), "relative": str(relative), "size": path.stat().st_size})
        return {"project_id": project.id, "video": project.video.path, "assets": files}
    raise CLIError("Unsupported command.")


def main(argv: list[str] | None = None):
    try:
        args = build_parser().parse_args(argv)
        if args.command == "speech-key" and args.action == "set" and args.session and args.server is None:
            raise CLIError("--session requires --server so the key remains in a running Clarity server session.")
        # Help, capability discovery and querying server-owned jobs need no disk writes.
        if args.command == "capabilities":
            from .capabilities import capabilities
            result = capabilities()
        elif args.command in ("job", "job-wait"):
            result = read_job(args)
        elif getattr(args, "server", None) is not None:
            result = execute_server(args)
        else:
            try:
                store = Store(args.projects_dir)
                speech = SpeechService(store)
            except Exception:
                raise CLIError("Could not initialize local project storage or settings. Check the projects directory and its permissions.") from None
            result = execute(args, store, speech)
        if result is not None:
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except ValidationError as error:
        known_fields = {"id", "start", "end", "text", "cues", "title", "revision", "video", "duration", "width", "height", "path", "name", "has_audio", "schema_version", "created_at", "updated_at"}
        details = [{"location": [part if isinstance(part, int) or part in known_fields else "[field]" for part in item["loc"]], "type": item["type"]} for item in error.errors(include_input=False, include_context=False)]
        print(json.dumps({"error": "Validation failed. Check caption timing, text, and field types.", "details": details}), file=sys.stderr)
        raise SystemExit(1)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input."}), file=sys.stderr)
        raise SystemExit(1)
    except UnicodeError:
        print(json.dumps({"error": "Input files must contain valid UTF-8 text."}), file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, OSError, KeyError, TypeError) as error:
        if isinstance(error, (CLIError, ConflictError)):
            message = str(error)
        elif isinstance(error, PermissionError):
            message = "File access was denied. Check local directory permissions."
        elif isinstance(error, FileNotFoundError):
            message = "File or project not found. Check the project ID and local file paths."
        elif isinstance(error, (KeyError, TypeError)):
            message = "Invalid input structure. Check the command help and supplied JSON fields."
        elif isinstance(error, OSError):
            message = "A local file operation failed. Check the input files and available disk space."
        else:
            message = str(error)
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print(json.dumps({"error": "Cancelled. No task was retried."}), file=sys.stderr)
        raise SystemExit(130)
    except Exception:
        print(json.dumps({"error": "The operation failed unexpectedly. Check local configuration and required tools."}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
