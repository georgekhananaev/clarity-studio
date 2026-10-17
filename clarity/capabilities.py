"""Machine-readable CLI discovery and the application-operation coverage map."""
from __future__ import annotations


# Static web assets and HTML are presentation; each application API route is
# represented here, including read-only streaming/file routes by local paths.
API_OPERATIONS = [
    ("GET", "/api/health", "health"),
    ("GET", "/api/preferences", "preferences show"),
    ("PUT", "/api/preferences", "preferences set"),
    ("GET", "/api/speech/settings", "speech-config show"),
    ("PUT", "/api/speech/settings", "speech-config set; speech-key set; speech-key remember --server http://localhost:8765; speech-key remove"),
    ("PATCH", "/api/speech/preferences", "speech-config set"),
    ("POST", "/api/speech/discover", "speech-models"),
    ("POST", "/api/speech/test", "speech-test"),
    ("GET", "/api/doctor", "doctor"),
    ("GET", "/api/projects", "list"),
    ("POST", "/api/projects", "import"),
    ("POST", "/api/upload", "import --copy"),
    ("GET", "/api/projects/{project_id}", "show"),
    ("PUT", "/api/projects/{project_id}/cues", "cues; add; edit; delete-cue; rename"),
    ("GET", "/api/projects/{project_id}/media", "media"),
    ("GET", "/api/projects/{project_id}/frame", "frame"),
    ("GET", "/api/projects/{project_id}/subtitles.vtt", "export --format vtt"),
    ("GET", "/api/projects/{project_id}/export/{format}", "export"),
    ("GET", "/api/projects/{project_id}/files/{relative:path}", "assets; asset"),
    ("POST", "/api/projects/{project_id}/inspect", "inspect"),
    ("POST", "/api/projects/{project_id}/render", "render"),
    ("POST", "/api/projects/{project_id}/narrate", "narrate"),
    ("POST", "/api/projects/{project_id}/audio", "audio"),
    ("POST", "/api/projects/{project_id}/preview", "preview"),
    ("GET", "/api/jobs/{job_id}", "job; job-wait"),
]

COMMANDS = {
    "capabilities": "Discover commands, API equivalents and automation rules; no store initialization.",
    "doctor": "Check media dependencies and local configuration.",
    "health": "Read workspace and credential status without exposing keys.",
    "list": "List recordings; --search filters titles without modifying projects.",
    "import": "Import a video path; --copy keeps a managed local copy.",
    "show": "Read a project, its revision, warnings and narration status.",
    "rename": "Change the project title using an expected --revision.",
    "inspect": "Extract timestamped frames, contact sheets and an AI task brief.",
    "frame": "Extract a frame at --time; --width 0 preserves original pixels.",
    "cues": "Replace captions from JSON using the revision last read.",
    "add": "Add a caption; AI callers should supply --revision.",
    "edit": "Edit one caption by ID using --revision.",
    "delete-cue": "Remove one caption by ID using --revision.",
    "validate": "Check timing and report warnings and narration readiness.",
    "export": "Write subtitles/project/script as srt, vtt, json or txt.",
    "preview": "Create a browser-compatible video without changing the original.",
    "render": "Render captioned video; --narrated uses existing generated narration.",
    "media": "Return the original video path and metadata.",
    "assets": "List available project files without returning file contents.",
    "asset": "Resolve one project-relative file path within the project boundary.",
    "preferences": "Show or patch validated editor preferences.",
    "speech-settings": "Read speech settings and credential-source status; compatibility alias.",
    "speech-config": "Show or patch speech settings and provider choices; no audio generation.",
    "speech-key": "Save a prompted/stdin key in Keychain or a server session; remember or remove a server key.",
    "speech-models": "Discover models/voices; no audio generation.",
    "speech-test": "Test provider connectivity/authentication; no audio generation.",
    "narrate": "Generate speech for captions using an approved provider/model/voice.",
    "audio": "Export an existing complete narration track as mp3 or wav.",
    "job": "Read a job from an already running local HTTP server.",
    "job-wait": "Wait with a deadline for an existing local-server job.",
    "serve": "Start the local browser editor/API; browser opens only with --open.",
}

SERVER_MODES = {
    "health": ["--server URL"],
    "speech-config": ["show --server URL"],
    "speech-key": ["set --server URL [--session]", "remember --server URL", "remove --server URL"],
    "speech-models": ["--server URL"],
    "speech-test": ["--server URL"],
    "narrate": ["--server URL (queues a job; requires generation approval)"],
}


def capabilities() -> dict:
    return {
        "app": "clarity-studio",
        "cli_contract_version": 1,
        "executable": "./clarity-cli",
        "documentation": "docs/ai-cli.md",
        "coverage_documentation": "docs/cli-coverage.md",
        "output": {"success": "JSON on stdout", "error": "JSON on stderr with nonzero exit status", "help": "Text; use --help at any command level"},
        "workspace": "--projects-dir PATH before the command, or CLARITY_PROJECTS_DIR; defaults to projects/",
        "commands": [{"name": name, "description": description, "server_required": name in ("job", "job-wait"), "server_modes": SERVER_MODES.get(name, []), "generates_speech": name == "narrate"} for name, description in COMMANDS.items()],
        "api_operations": [{"method": method, "path": path, "cli": command} for method, path, command in API_OPERATIONS],
        "automation": {
            "caption_updates": "Read revision, edit grounded captions, preserve IDs, apply with expected revision; re-read and merge conflicts.",
            "visual_evidence": "Inspect the returned contact sheets and frames using an image-capable model; extraction alone does not explain or transcribe a video.",
            "secrets": "Use Keychain, environment variables or speech-key set --stdin; --server URL --session keeps a key in that server only. Never put keys in command arguments, JSON settings or logs.",
            "speech_approval": "Ask for explicit audio-generation authorization before narrate. Model discovery and connection tests generate no speech.",
            "execution": "Direct media commands run synchronously without the web server. Explicit --server modes use that server's workspace and credentials; narrate --server returns a job_id for job/job-wait.",
        },
        "presentation": {
            "scope": "The map covers application operations and persisted configuration, not browser widget automation.",
            "playback": "Use frame/inspect for visual navigation; preferences stores speed/mute/caption size. Headless commands do not play, pause or seek an open browser tab.",
            "editor": "CLI saves affect persisted projects. Unsaved browser drafts and dialogs remain browser-local; save or resolve drafts before switching workflows.",
        },
    }
