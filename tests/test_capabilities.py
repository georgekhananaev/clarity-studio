import argparse

from clarity.__main__ import build_parser
from clarity.capabilities import API_OPERATIONS, COMMANDS, capabilities
from clarity.server import create_app
from clarity.store import Store


def test_application_api_operations_have_real_cli_equivalents(tmp_path):
    app = create_app(Store(tmp_path / "projects"))
    actual = {(method, route.path) for route in app.routes
              if getattr(route, "path", "").startswith("/api/")
              for method in route.methods}
    mapped = {(method, path) for method, path, _ in API_OPERATIONS}
    assert actual == mapped
    assert len(mapped) == len(API_OPERATIONS), "Duplicate operation in coverage map"
    parser = build_parser()
    actions = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    assert set(actions.choices) == set(COMMANDS)
    # Parse actual mapped command forms, rather than accepting a prose map whose
    # command names or flags no longer exist. Required operands get dummy values.
    for _, _, equivalents in API_OPERATIONS:
        for equivalent in equivalents.split("; "):
            words = equivalent.split()
            if words[0] in {"show", "cues", "add", "edit", "delete-cue", "rename", "frame", "export", "render", "narrate", "audio", "preview", "assets", "asset", "media", "inspect"}:
                words.insert(1, "project-id")
            if words[0] in {"edit", "delete-cue"}:
                words.insert(2, "cue-id")
            if words[0] in {"cues", "add", "edit", "delete-cue", "rename"}:
                words.extend(["--revision", "0"])
            if words[0] == "cues":
                words.extend(["--file", "captions.json"])
            if words[0] == "add":
                words.extend(["--start", "0", "--end", "2", "--text", "Example"])
            if words[0] == "edit":
                words.extend(["--text", "Example"])
            if words[0] == "rename":
                words.extend(["--title", "Example"])
            if words[0] == "frame":
                words.extend(["--time", "0"])
            if words[0] == "asset":
                words.extend(["--path", "exports/captions.srt"])
            if words[0] == "import":
                words.append("video.mp4")
            if words[:2] in (["preferences", "set"], ["speech-config", "set"]):
                words.extend(["--json", "{}"])
            if words[0] in {"speech-key", "speech-test"}:
                words.extend(["--provider", "local"])
            if words[0] in {"job", "job-wait"}:
                words.append("job-id")
            parser.parse_args(words)


def test_capability_discovery_identifies_live_speech_and_server_boundaries():
    inventory = capabilities()
    commands = {item["name"]: item for item in inventory["commands"]}
    assert {name for name, item in commands.items() if item["generates_speech"]} == {"narrate"}
    assert {name for name, item in commands.items() if item["server_required"]} == {"job", "job-wait"}
    assert {name for name, item in commands.items() if item["server_modes"]} == {"health", "speech-config", "speech-key", "speech-models", "speech-test", "narrate"}
    assert inventory["documentation"] == "docs/ai-cli.md"
