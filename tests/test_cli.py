"""Behavioral CLI tests: isolated projects, mocked Keychain, no live services."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from clarity import __main__ as cli
from clarity.models import Cue, Video
from clarity.speech import Credentials, SpeechService
from clarity.store import Store


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    class Keychain:
        values = {}

        def get_password(self, service, account):
            return self.values.get((service, account))

        def set_password(self, service, account, value):
            self.values[service, account] = value

        def delete_password(self, service, account):
            del self.values[service, account]

    monkeypatch.setattr(Credentials, "keychain", staticmethod(lambda: Keychain()))
    for name in ("OPENROUTER_API_KEY", "CLARITY_LOCAL_API_KEY", "CLARITY_LOCAL_BASE_URL", "OPENROUTER_VOICE"):
        monkeypatch.delenv(name, raising=False)
    return Keychain.values


@pytest.fixture
def run(tmp_path, capsys):
    def invoke(*args, code=0):
        if code:
            with pytest.raises(SystemExit) as raised:
                cli.main(["--projects-dir", str(tmp_path / "projects"), *args])
            assert raised.value.code == code
        else:
            cli.main(["--projects-dir", str(tmp_path / "projects"), *args])
        captured = capsys.readouterr()
        assert not (captured.out if code else captured.err)
        return json.loads(captured.err if code else captured.out)
    return invoke


@pytest.fixture
def project(tmp_path):
    video = tmp_path / "screen.mp4"
    video.write_bytes(b"fake video; media functions are mocked")
    store = Store(tmp_path / "projects")
    project = store.create(Video(path=str(video), name=video.name, duration=20, width=1280, height=720), "Original recording")
    return store.update(project.id, [Cue(id="first", start=0, end=4, text="Open the recording."), Cue(id="second", start=5, end=9, text="Review the caption.")], 0)


def test_preferences_patch_is_partial_persistent_and_separate_from_speech(run, tmp_path):
    original = run("preferences", "show")
    assert original["appearance"] == "dark"
    changed = run("preferences", "set", "--json", '{"appearance":"light","sidebar_width":288,"last_project":"demo"}')
    assert changed["sidebar_width"] == 288
    patch = tmp_path / "patch.json"
    patch.write_text('{"caption_size":28,"last_project":null}')
    changed = run("preferences", "set", "--file", str(patch))
    assert changed["appearance"] == "light" and changed["caption_size"] == 28
    assert changed["last_project"] is None
    restarted = run("preferences", "show")
    assert restarted["sidebar_width"] == 288 and restarted["caption_size"] == 28
    assert run("speech-config", "show")["provider"] == "openrouter"


def test_speech_config_preserves_active_provider_and_other_choices(run):
    run("speech-config", "set", "--json", '{"local_base_url":"http://127.0.0.1:9999/v1","local":{"model":"kokoro","voice":"af_heart"}}')
    current = run("speech-config", "set", "--json", '{"local":{"instructions":"Speak slowly."}}')
    assert current["provider"] == "openrouter"
    assert current["local"] == {"model": "kokoro", "voice": "af_heart", "instructions": "Speak slowly."}
    assert run("speech-config", "set", "--json", '{"provider":"local"}')["provider"] == "local"
    assert run("speech-settings") == run("speech-config", "show")


@pytest.mark.parametrize("command,patch", [("preferences", '{"api_key":"private-sentinel"}'), ("speech-config", '{"openrouter":{"api_key":"private-sentinel"}}'), ("speech-config", '{"local_base_url":"http://user:private-sentinel@localhost/v1"}'), ("preferences", '{"appearance":"private-sentinel"}'), ("speech-config", '{"local":{"model":"private-sentinel"}'), ("preferences", '[]')])
def test_invalid_preference_input_is_json_and_does_not_echo_values(run, tmp_path, command, patch):
    error = run(command, "set", "--json", patch, code=1)
    assert "private-sentinel" not in json.dumps(error)
    assert "error" in error
    database = tmp_path / "projects" / ".local" / "settings.sqlite3"
    assert b"private-sentinel" not in database.read_bytes()


def test_keys_use_stdin_and_persist_in_mock_keychain_only(run, monkeypatch, credentials, tmp_path):
    key = "private-key-sentinel"
    monkeypatch.setattr(sys, "stdin", io.StringIO(key + "\n"))
    result = run("speech-key", "set", "--provider", "openrouter", "--stdin")
    assert result["keys"]["openrouter"] == {"configured": True, "source": "keychain"}
    assert credentials["Clarity Studio Speech", "openrouter"] == key
    assert key not in json.dumps(result)
    assert run("speech-config", "show")["keys"]["openrouter"]["configured"]
    assert key.encode() not in (tmp_path / "projects" / ".local" / "settings.sqlite3").read_bytes()
    assert not run("speech-key", "remove", "--provider", "openrouter")["keys"]["openrouter"]["configured"]
    assert not credentials


def test_key_prompt_uses_getpass_and_refuses_plain_argv(run, monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    prompts = []
    with monkeypatch.context() as context:
        context.setattr(sys, "stdin", Terminal())
        context.setattr(sys, "stderr", Terminal())
        context.setattr(cli.getpass, "getpass", lambda prompt: prompts.append(prompt) or "hidden-sentinel")
        assert cli.read_key(False) == "hidden-sentinel"
    assert prompts and "hidden" in prompts[0]
    error = run("speech-key", "set", "--provider", "openrouter", "private-argv-sentinel", code=1)
    assert "private-argv-sentinel" not in json.dumps(error)


def test_nonterminal_and_bad_stdin_keys_fail_without_echo(run, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert "hidden terminal" in run("speech-key", "set", "--provider", "local", code=1)["error"]
    monkeypatch.setattr(sys, "stdin", io.StringIO("private-sentinel\nanother-line"))
    result = run("speech-key", "set", "--provider", "local", "--stdin", code=1)
    assert "private-sentinel" not in json.dumps(result)


def test_rename_and_single_caption_edits_preserve_history_and_reject_conflicts(run, project, tmp_path):
    renamed = run("rename", project.id, "--title", "A clearer title", "--revision", "1")
    assert renamed["revision"] == 2 and renamed["cues"] == [cue.model_dump() for cue in project.cues]
    edited = run("edit", project.id, "first", "--text", "Choose a recording.", "--end", "4.5", "--revision", "2")
    assert edited["cues"][0] == {"id": "first", "start": 0, "end": 4.5, "text": "Choose a recording."}
    conflict = run("delete-cue", project.id, "second", "--revision", "2", code=1)
    assert "current revision 3" in conflict["error"]
    current = run("show", project.id)
    assert len(current["cues"]) == 2 and current["revision"] == 3
    result = run("delete-cue", project.id, "second", "--revision", "3")
    assert len(result["cues"]) == 1 and result["revision"] == 4
    assert (tmp_path / "projects" / project.id / "history" / "000003.json").is_file()


def test_edit_validation_and_missing_revision_do_not_mutate(run, project):
    assert run("edit", project.id, "first", "--start", "6", "--revision", "1", code=1)["error"]
    assert run("edit", project.id, "first", "--revision", "1", code=1)["error"]
    assert run("delete-cue", project.id, "first", code=1)["error"]
    assert run("rename", project.id, "--title", "Changed", code=1)["error"]
    assert run("show", project.id)["revision"] == 1


def test_validation_locations_do_not_echo_untrusted_field_names(run, project, tmp_path):
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps([{"start": 0, "end": 3, "text": "A caption.", "private-field-sentinel": "private-value-sentinel"}]))
    error = run("cues", project.id, "--file", str(cues), "--revision", "1", code=1)
    assert "private-field-sentinel" not in json.dumps(error)
    assert "private-value-sentinel" not in json.dumps(error)
    assert error["details"][0]["location"] == ["[field]"]
    assert run("show", project.id)["revision"] == 1


def test_add_supports_revision_and_list_search(run, project):
    added = run("add", project.id, "--start", "10", "--end", "13", "--text", "Export your captions.", "--revision", "1")
    assert added["revision"] == 2 and len(added["cues"]) == 3
    run("add", project.id, "--start", "14", "--end", "17", "--text", "Stale edit.", "--revision", "1", code=1)
    assert len(run("list", "--search", "  ORIGINAL ")) == 1
    assert run("list", "--search", "missing") == []


def test_reference_and_copy_imports_leave_original_untouched(run, tmp_path, monkeypatch):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"unchanged original content")
    monkeypatch.setattr(cli, "probe", lambda path: Video(path=str(path.resolve()), name=path.name, duration=20, width=640, height=480))
    referenced = run("import", str(source))
    assert referenced["video"]["path"] == str(source)
    copied = run("import", str(source), "--copy", "--title", "Copied recording")
    target = Path(copied["video"]["path"])
    assert target != source and target.is_relative_to(tmp_path / "projects" / "_uploads")
    assert target.read_bytes() == source.read_bytes() == b"unchanged original content"
    assert copied["title"] == "Copied recording"


def test_failed_copied_import_removes_incomplete_upload(run, tmp_path, monkeypatch):
    source = tmp_path / "broken.mov"
    source.write_bytes(b"not a video")
    def fail(path):
        raise ValueError("No usable video stream.")
    monkeypatch.setattr(cli, "probe", fail)
    assert "No usable video stream" in run("import", str(source), "--copy", code=1)["error"]
    assert source.read_bytes() == b"not a video"
    assert not list((tmp_path / "projects" / "_uploads").iterdir())


def test_media_assets_and_preview_preserve_file_boundary(run, tmp_path, project, monkeypatch):
    directory = tmp_path / "projects" / project.id
    asset = directory / "captions.srt"
    asset.write_text("captions")
    outside = tmp_path / "secret.txt"
    outside.write_text("do not expose")
    (directory / "escaped.txt").symlink_to(outside)
    (directory / ".private").write_text("hidden")
    assert run("media", project.id)["path"] == project.video.path
    manifest = run("assets", project.id)
    assert "captions.srt" in {item["relative"] for item in manifest["assets"]}
    assert not {"escaped.txt", ".private"} & {item["relative"] for item in manifest["assets"]}
    assert run("asset", project.id, "--path", "captions.srt")["size"] == len("captions")
    run("asset", project.id, "--path", "../../secret.txt", code=1)
    run("asset", project.id, "--path", "escaped.txt", code=1)
    monkeypatch.setattr(cli, "browser_preview", lambda store, value: store.directory(value.id) / "preview.mp4")
    assert run("preview", project.id)["path"] == str(directory / "preview.mp4")


def test_discovery_and_connection_test_use_saved_settings_without_audio(run, monkeypatch):
    calls = []
    monkeypatch.setattr(SpeechService, "test_connection", lambda self, provider: calls.append(("test", provider)) or {"connected": True, "message": "No audio generated."})
    monkeypatch.setattr(SpeechService, "discover", lambda self, provider, base_url, model: calls.append(("discover", provider, base_url, model)) or {"models": [], "voices": []})
    assert run("speech-test", "--provider", "local")["connected"]
    run("speech-models", "--provider", "local", "--base-url", "http://localhost:9999/v1", "--model", "kokoro")
    assert calls == [("test", "local"), ("discover", "local", "http://localhost:9999/v1", "kokoro")]
    run("speech-models", "--base-url", "http://localhost:9999/v1", code=1)
    assert len(calls) == 2


def test_narrate_endpoint_override_is_transient_and_forwards_selected_cues(run, project, monkeypatch):
    run("speech-config", "set", "--json", '{"local":{"model":"kokoro","voice":"af_heart"}}')
    calls = []
    def fake_narrate(store, value, voice, model, instructions, **kwargs):
        calls.append((kwargs["connection"].base_url, voice, model, kwargs["cue_ids"]))
        return {"generated": 1}
    monkeypatch.setattr(cli, "narrate", fake_narrate)
    assert run("narrate", project.id, "--provider", "local", "--base-url", "http://localhost:9999/v1", "--cue", "first")["generated"] == 1
    assert calls == [("http://localhost:9999/v1", "af_heart", "kokoro", ["first"])]
    settings = run("speech-config", "show")
    assert settings["provider"] == "openrouter" and settings["local_base_url"] == "http://127.0.0.1:8880/v1"
    run("narrate", project.id, "--provider", "openrouter", "--base-url", "http://localhost:9999/v1", code=1)
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["https://example.com", "http://localhost.evil", "http://10.0.0.2:8765", "file:///tmp/job", "http://user:private-sentinel@localhost:8765", "http://localhost:8765/api", "http://localhost:8765?key=private-sentinel", "http://localhost:99999"])
def test_job_requests_reject_nonlocal_or_credential_urls_without_requests(run, monkeypatch, url):
    monkeypatch.setattr(cli, "get_server_json", lambda *args: pytest.fail("invalid server URL was requested"))
    result = run("job", "task", "--server", url, code=1)
    assert "private-sentinel" not in json.dumps(result)


def test_job_wait_polls_only_until_complete_and_reports_failure_timeout(run, monkeypatch):
    statuses = iter(["running", "done"])
    calls = []
    def read(url, path):
        calls.append((url, path))
        return {"id": "task", "status": next(statuses)}
    monkeypatch.setattr(cli, "get_server_json", read)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    assert run("job-wait", "task", "--interval", "0.05")["status"] == "done"
    assert calls == [("http://localhost:8765", "/api/jobs/task")] * 2
    monkeypatch.setattr(cli, "get_server_json", lambda *args: {"id": "task", "status": "error", "message": "Failed"})
    assert run("job", "task")["status"] == "error"
    assert "failed" in run("job-wait", "task", code=1)["error"]
    monkeypatch.setattr(cli, "get_server_json", lambda *args: {"id": "task", "status": "running"})
    assert "Timed out" in run("job-wait", "task", "--timeout", "0", code=1)["error"]
    assert "interval" in run("job-wait", "task", "--interval", "nan", code=1)["error"]


def test_server_http_transport_disables_redirects_and_redacts_error_bodies():
    calls = []
    def response(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com"}, text="private-sentinel")
    with httpx.Client(transport=httpx.MockTransport(response), follow_redirects=False) as client:
        with pytest.raises(cli.CLIError) as raised:
            cli.get_server_json("http://localhost:8765", "/api/jobs/task", client)
    assert calls == ["http://localhost:8765/api/jobs/task"]
    assert "private-sentinel" not in str(raised.value)


def test_help_and_capabilities_do_not_initialize_storage(tmp_path, monkeypatch, capsys):
    def fail(*args):
        pytest.fail("Store initialized for help/capabilities")
    monkeypatch.setattr(cli, "Store", fail)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--projects-dir", str(tmp_path / "unused"), "--help"])
    assert raised.value.code == 0
    assert "speech-key" in capsys.readouterr().out
    cli.main(["--projects-dir", str(tmp_path / "unused"), "capabilities"])
    assert isinstance(json.loads(capsys.readouterr().out), dict)
    assert not (tmp_path / "unused").exists()


def test_startup_and_argument_errors_are_json_without_sensitive_values(tmp_path, capsys, monkeypatch):
    for args in (["frame", "private-sentinel", "--time", "private-sentinel"], ["private-sentinel"]):
        with pytest.raises(SystemExit) as raised:
            cli.main(args)
        assert raised.value.code == 1
        captured = capsys.readouterr()
        assert not captured.out and "private-sentinel" not in captured.err
        assert json.loads(captured.err)["error"]
    def fail(*args):
        raise OSError("private-sentinel")
    monkeypatch.setattr(cli, "Store", fail)
    with pytest.raises(SystemExit):
        cli.main(["list"])
    captured = capsys.readouterr()
    assert "private-sentinel" not in captured.err and json.loads(captured.err)["error"]


def test_serve_reuses_only_matching_workspace_and_projects_directory(tmp_path, monkeypatch):
    import uvicorn
    store = Store(tmp_path / "projects")
    speech = SpeechService(store)
    args = cli.build_parser().parse_args(["serve"])
    matching = {"app": "clarity-studio", "workspace": str(cli.ROOT), "projects_directory": str(store.root)}
    monkeypatch.setattr(cli, "get_server_json", lambda *args: matching)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("Started a duplicate server"))
    assert cli.execute(args, store, speech) == {"url": "http://localhost:8765", "status": "already running"}
    for patch in ({"projects_directory": str(tmp_path / "other")}, {"workspace": str(tmp_path / "other")}, {"app": "another-app"}):
        monkeypatch.setattr(cli, "get_server_json", lambda *args, patch=patch: {**matching, **patch})
        with pytest.raises(cli.CLIError, match="already using"):
            cli.execute(args, store, speech)


def test_server_bind_failure_is_json(run, monkeypatch):
    import uvicorn
    def missing(*args):
        raise cli.CLIError("Not running")
    def fail(*args, **kwargs):
        assert kwargs["log_level"] == "critical"
        raise SystemExit(1)
    monkeypatch.setattr(cli, "get_server_json", missing)
    monkeypatch.setattr(uvicorn, "run", fail)
    assert "Could not start" in run("serve", code=1)["error"]


def test_projects_dir_overrides_environment_in_subprocess(tmp_path):
    env = {**os.environ, "CLARITY_PROJECTS_DIR": str(tmp_path / "environment-projects")}
    selected = tmp_path / "selected-projects"
    command = [sys.executable, "-m", "clarity", "--projects-dir", str(selected)]
    result = subprocess.run([*command, "preferences", "set", "--json", '{"appearance":"light"}'], capture_output=True, text=True, env=env, check=True)
    assert json.loads(result.stdout)["storage"]["projects"] == str(selected)
    result = subprocess.run([*command, "preferences", "show"], capture_output=True, text=True, env=env, check=True)
    assert json.loads(result.stdout)["appearance"] == "light"
    assert not (tmp_path / "environment-projects").exists()


@pytest.fixture
def server_transport(monkeypatch):
    """A session-aware local API fake, with no network or credential backend."""
    original_client = httpx.Client
    settings = {"provider": "local", "local_base_url": "http://127.0.0.1:9999/v1", "openrouter": {"model": "fish-audio/drama-3", "voice": "voice", "instructions": "Explain clearly."}, "local": {"model": "kokoro", "voice": "af_heart", "instructions": "Speak naturally."}}
    keys = {provider: {"configured": False, "source": "none"} for provider in ("openrouter", "local")}
    calls = []

    def respond(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"app": "clarity-studio", "workspace": "/server/workspace", "projects_directory": "/server/projects", "narration_configured": keys["openrouter"]["configured"]})
        if request.url.path == "/api/speech/settings":
            if request.method == "PUT":
                assert "settings" not in body
                provider = body["credential_provider"]
                if body.get("clear_key"):
                    keys[provider] = {"configured": False, "source": "none"}
                elif body.get("remember_key"):
                    assert body.get("api_key") or keys[provider]["configured"]
                    keys[provider] = {"configured": True, "source": "keychain"}
                else:
                    assert body["api_key"]
                    keys[provider] = {"configured": True, "source": "session"}
            return httpx.Response(200, json={**settings, "keys": keys})
        if request.url.path == "/api/speech/test":
            assert request.method == "POST" and body == {"provider": "openrouter"}
            return httpx.Response(200, json={"connected": keys["openrouter"]["configured"], "message": "Server session checked. No audio generated."})
        if request.url.path == "/api/speech/discover":
            assert request.method == "POST"
            return httpx.Response(200, json={"models": [{"id": "server-model"}], "voices": [{"id": "server-voice"}], "warnings": []})
        if request.url.path == "/api/projects/demo/narrate":
            assert request.method == "POST"
            return httpx.Response(200, json={"job_id": "queued-task"})
        pytest.fail("Unexpected mocked server request")

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(cli.httpx, "Client", client)
    return {"calls": calls, "keys": keys}


def test_server_session_key_set_inspect_test_remember_remove(run, server_transport, monkeypatch, tmp_path, credentials):
    endpoint = "http://localhost:8765"
    monkeypatch.setattr(sys, "stdin", io.StringIO("private-server-sentinel\n"))
    saved = run("speech-key", "set", "--provider", "openrouter", "--server", endpoint, "--session", "--stdin")
    assert saved["keys"]["openrouter"] == {"configured": True, "source": "session"}
    assert saved["provider"] == "local"
    assert "private-server-sentinel" not in json.dumps(saved)
    assert server_transport["calls"] == [
        ("GET", "/api/health", None),
        ("PUT", "/api/speech/settings", {"credential_provider": "openrouter", "api_key": "private-server-sentinel", "remember_key": False}),
    ]
    assert run("health", "--server", endpoint)["narration_configured"]
    assert run("speech-config", "show", "--server", endpoint)["keys"]["openrouter"]["source"] == "session"
    assert run("speech-test", "--provider", "openrouter", "--server", endpoint)["connected"]
    monkeypatch.setattr(cli, "read_key", lambda *args, **kwargs: pytest.fail("Remember/remove prompted for a key"))
    remembered = run("speech-key", "remember", "--provider", "openrouter", "--server", endpoint)
    assert remembered["keys"]["openrouter"]["source"] == "keychain"
    assert "api_key" not in server_transport["calls"][-1][2]
    cleared = run("speech-key", "remove", "--provider", "openrouter", "--server", endpoint)
    assert not cleared["keys"]["openrouter"]["configured"]
    assert server_transport["calls"][-1][2]["clear_key"] is True
    assert not (tmp_path / "projects").exists() and not credentials


def test_server_key_set_defaults_to_remembered_without_changing_active_provider(run, server_transport, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdin", io.StringIO("private-server-sentinel\n"))
    saved = run("speech-key", "set", "--provider", "openrouter", "--server", "http://localhost:8765", "--stdin")
    assert saved["provider"] == "local"
    assert saved["keys"]["openrouter"]["source"] == "keychain"
    assert server_transport["calls"][-1][2]["remember_key"] is True
    assert not (tmp_path / "projects").exists()


def test_server_session_flags_require_a_real_server_before_storage_or_input(run, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "Store", lambda *args: pytest.fail("Created local storage for server-only flags"))
    monkeypatch.setattr(cli, "read_key", lambda *args, **kwargs: pytest.fail("Prompted for a key before validating flags"))
    assert "requires --server" in run("speech-key", "set", "--provider", "openrouter", "--session", code=1)["error"]
    assert run("speech-key", "remember", "--provider", "openrouter", code=1)["error"]
    assert not (tmp_path / "projects").exists()


@pytest.mark.parametrize("args", [
    ("health", "--server", "https://example.com"),
    ("speech-config", "show", "--server", "http://user:private-sentinel@localhost"),
    ("speech-test", "--provider", "openrouter", "--server", "http://10.0.0.2:8765"),
    ("speech-key", "set", "--provider", "openrouter", "--server", "https://example.com", "--stdin"),
    ("speech-key", "remove", "--provider", "local", "--server", "http://localhost:8765/path"),
    ("speech-key", "remember", "--provider", "local", "--server", "http://localhost:8765?key=private-sentinel"),
])
def test_server_actions_reject_unsafe_urls_without_requests_or_storage(run, monkeypatch, args):
    monkeypatch.setattr(cli, "Store", lambda *args: pytest.fail("Created local storage for server action"))
    monkeypatch.setattr(cli, "get_server_json", lambda *args, **kwargs: pytest.fail("Requested an unsafe URL"))
    error = run(*args, code=1)
    assert "private-sentinel" not in json.dumps(error)


def test_server_identity_is_checked_before_reading_or_sending_key(run, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "Store", lambda *args: pytest.fail("Created local storage"))
    monkeypatch.setattr(cli, "read_key", lambda *args, **kwargs: pytest.fail("Read a key before validating server"))
    def read(url, path, **kwargs):
        calls.append(path)
        return {"app": "another-app", "detail": "private-sentinel"}
    monkeypatch.setattr(cli, "get_server_json", read)
    error = run("speech-key", "set", "--provider", "openrouter", "--server", "http://localhost:8765", "--stdin", code=1)
    assert calls == ["/api/health"]
    assert "private-sentinel" not in json.dumps(error)


def test_server_key_error_never_echoes_key_or_response_body(run, monkeypatch, tmp_path):
    original_client = httpx.Client
    def respond(request):
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"app": "clarity-studio"})
        if request.method == "GET":
            return httpx.Response(200, json={"provider": "openrouter", "openrouter": {}, "local": {}, "local_base_url": "http://localhost:8880/v1", "keys": {}})
        return httpx.Response(400, json={"detail": "private-server-sentinel"})
    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(sys, "stdin", io.StringIO("private-server-sentinel"))
    error = run("speech-key", "set", "--provider", "openrouter", "--server", "http://localhost:8765", "--session", "--stdin", code=1)
    assert "HTTP 400" in error["error"] and "private-server-sentinel" not in json.dumps(error)
    assert not (tmp_path / "projects").exists()


def test_server_discovery_preserves_provider_model_and_transient_url_without_local_store(run, server_transport, tmp_path):
    result = run("speech-models", "--provider", "local", "--model", "kokoro", "--base-url", "http://localhost:9998/v1", "--server", "http://localhost:8765")
    assert result["models"] == [{"id": "server-model"}]
    assert server_transport["calls"] == [
        ("GET", "/api/health", None),
        ("POST", "/api/speech/discover", {"provider": "local", "model": "kokoro", "base_url": "http://localhost:9998/v1"}),
    ]
    assert not (tmp_path / "projects").exists()
    server_transport["calls"].clear()
    run("speech-models", "--server", "http://localhost:8765")
    assert server_transport["calls"][-1] == ("POST", "/api/speech/discover", {"provider": "openrouter"})


def test_server_narration_dispatches_once_and_returns_job_without_wait_or_local_store(run, server_transport, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "read_job", lambda *args: pytest.fail("Automatically waited for narration"))
    monkeypatch.setattr(cli, "narrate", lambda *args, **kwargs: pytest.fail("Generated narration in the CLI process"))
    result = run("narrate", "demo", "--server", "http://localhost:8765", "--provider", "openrouter", "--model", "fish-audio/drama-3", "--voice", "server-voice", "--instructions", "Explain clearly.", "--cue", "first", "--cue", "second")
    assert result == {"job_id": "queued-task"}
    assert server_transport["calls"] == [
        ("GET", "/api/health", None),
        ("POST", "/api/projects/demo/narrate", {"provider": "openrouter", "model": "fish-audio/drama-3", "voice": "server-voice", "instructions": "Explain clearly.", "cue_ids": ["first", "second"]}),
    ]
    assert not (tmp_path / "projects").exists()
    server_transport["calls"].clear()
    assert run("narrate", "demo", "--server", "http://localhost:8765") == {"job_id": "queued-task"}
    assert server_transport["calls"][-1] == ("POST", "/api/projects/demo/narrate", {})


@pytest.mark.parametrize("args", [
    ("narrate", "demo", "--base-url", "http://localhost:9998/v1", "--server", "http://localhost:8765"),
    ("narrate", "../private-sentinel", "--server", "http://localhost:8765"),
    ("speech-models", "--provider", "openrouter", "--base-url", "http://localhost:9998/v1", "--server", "http://localhost:8765"),
    ("speech-models", "--server", "http://user:private-sentinel@localhost:8765"),
    ("narrate", "demo", "--server", "https://example.com"),
])
def test_invalid_server_discovery_and_narration_do_not_make_requests_or_initialize_store(run, monkeypatch, args):
    monkeypatch.setattr(cli, "Store", lambda *args: pytest.fail("Created a local store"))
    monkeypatch.setattr(cli, "get_server_json", lambda *args, **kwargs: pytest.fail("Made a request with invalid arguments"))
    error = run(*args, code=1)
    assert "private-sentinel" not in json.dumps(error)


@pytest.mark.parametrize("args", [("speech-models",), ("narrate", "demo")])
def test_server_discovery_and_narration_verify_app_identity_before_dispatch(run, monkeypatch, args):
    requests = []
    def wrong_app(url, path, **kwargs):
        requests.append(path)
        return {"app": "another-app"}
    monkeypatch.setattr(cli, "get_server_json", wrong_app)
    monkeypatch.setattr(cli, "Store", lambda *args: pytest.fail("Created a local store"))
    assert "not Clarity" in run(*args, "--server", "http://localhost:8765", code=1)["error"]
    assert requests == ["/api/health"]
