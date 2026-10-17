# Privacy and data flow

Clarity Studio runs a local FastAPI server and a browser editor on your Mac.
It has no built-in telemetry, account system, or automatic cloud backup.

| Action | Data used | Destination |
| --- | --- | --- |
| Import by path | Original video path | Local project JSON; video remains in place |
| Upload a recording | Video file | Managed copy under the local project root |
| Prepare for AI | Extracted frames, contact sheets, task brief | Local project directory |
| Ask an external AI agent to inspect | Frames/context selected by the agent | That agent's configured model service; outside Clarity's control |
| Refresh OpenRouter models | Model metadata request | OpenRouter API |
| Test OpenRouter connection | Authentication request | OpenRouter API; no generated speech |
| Generate OpenRouter narration | Caption text, delivery instructions, model/voice IDs, authentication | OpenRouter and its speech provider |
| Use a local speech connection | Connection metadata or caption text for generation | The configured loopback/private-network server |
| Export | Captions, video, or existing narration | Local export directory |

The app does not send the video to speech providers. Provider retention, billing,
and model behavior are governed by their own policies. Local-server credentials
and text go to your configured endpoint; use a trusted server and network.

## Local files and credentials

The default root is `projects/`. `CLARITY_PROJECTS_DIR` or the CLI's
`--projects-dir PATH` selects another root. The editor and CLI must use the same
root to see the same projects.

- `PROJECT_ID/project.json`: caption text, times, revision, and absolute video path.
- `PROJECT_ID/history/`: previous project revisions.
- `frames/`, `inspection/`, `preview.mp4`: visual evidence and preview copies.
- `narration/`, `exports/`: generated audio, subtitles, and rendered video.
- `.local/settings.sqlite3`: nonsecret preferences.
- `_speech-catalog.json`: cached model/voice catalog metadata under the data root.

The configuration directory uses owner-only permissions (`0700`) and its SQLite
database uses `0600`. Preferences are stored transactionally. A legacy
`_speech-settings.json` may remain as an ignored migration/recovery file.
Local projects and exports are ordinary files, not encrypted storage.

Remembered speech credentials use macOS Keychain. Session-only credentials stay
in the server process, and environment variables can supply credentials to the
process that inherits them. Credentials are not returned in API responses,
written into project JSON/settings SQLite, or saved in browser local storage.
An environment key must be removed at its source; deleting a Keychain entry
does not erase another process's environment or session override.

The app does not load `.env` files automatically. Do not put credentials in
caption text, delivery instructions, source files, URLs, or command arguments.
The credential guarantees apply to the app's credential fields, not arbitrary
text entered elsewhere.

## Sharing and backups

SRT/VTT/text exports include your caption wording. JSON exports additionally
include absolute media paths and project metadata. Audio and video may contain
private content visible or audible in the recording. Review each artifact before
sharing it. Redact screenshots and diagnostics before filing an issue.

Back up the chosen project root and any videos imported by reference. A project
JSON file does not include the referenced recording. Project-root backups do not
include credentials kept in Keychain.

`.gitignore` excludes local media, projects, databases, credentials, AI skills and
memory, app bundles, environments, caches, and temporary artifacts. It cannot
remove files already tracked or secrets already in Git history. Keep alternative
data roots outside the checkout or add a local exclusion before using them.
See the [public-source check](development.md#before-publishing-source).

## Local server boundary

The editor binds to `127.0.0.1`, checks Host headers, and rejects cross-origin
requests. It has no multi-user authentication. Do not expose it through a public
tunnel or reverse proxy. It is not a sandbox against other local processes or
users with access to your files.
