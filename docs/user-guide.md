# Using Clarity Studio

Start with the [installation guide](../README.md#quick-start) on a new Mac.
The library starts empty; the optional sample is generated locally.

## Let an AI create the captions

Tell the AI working in this folder:

> Create explanatory subtitles for my recording at /absolute/path/recording.mov.
> Follow docs/ai-cli.md. Inspect the video frames, write short explanations of the
> visible actions, validate the timings, and export an SRT file.

The tool prepares evidence and manages captions. **It does not generate
explanations by itself**: your AI agent supplies the visual understanding and
wording. No external model key is needed when the agent uses its own image tools.
The **Prepare for AI** button creates timestamped contact sheets and a task brief;
it does not upload your recording or call a model.

The same workflow is available through commands:

```sh
./clarity-cli doctor
./clarity-cli import /absolute/path/recording.mov --title "Settings walkthrough"
./clarity-cli list
./clarity-cli show PROJECT_ID
./clarity-cli inspect PROJECT_ID --every 5 --max-frames 48
./clarity-cli frame PROJECT_ID --time 12.5 --width 0
```

Inspect the returned contact sheets and individual frames with an image viewing
tool. The interval increases automatically to cover the whole recording when
the frame limit is reached. Sampled frames do not show every event; inspect
additional moments near transitions and use the user's context for intent.

Write a JSON file:

```json
[
  {"start": 0.5, "end": 4.0, "text": "Open Settings to choose a language."},
  {"start": 4.2, "end": 7.8, "text": "Select the language you want to use."}
]
```

Then apply it using the revision returned by `show`:

```sh
./clarity-cli cues PROJECT_ID --file /absolute/path/cues.json --revision REVISION
./clarity-cli validate PROJECT_ID
./clarity-cli export PROJECT_ID --format srt
./clarity-cli render PROJECT_ID
```

`cues` replaces the caption list, so include every caption you want to keep.
Retain caption IDs when editing existing entries. Each save validates times and
overlaps, checks the revision to protect concurrent edits, and keeps the previous
project JSON under `history/`. A single addition is also possible:

```sh
./clarity-cli add PROJECT_ID --start 8 --end 11 --text "Save your changes." --revision REVISION
```

Operation commands produce machine-readable JSON. Failures exit nonzero and write
a JSON error to stderr; help is text and `serve` is a long-running process.
Export formats: `srt`, `vtt`, `json`, `txt`.

## Reviewing and editing

The desktop editor keeps the video, captions, and timeline in one window. Filter
recordings by title in the sidebar, or use the chevron beside the logo to collapse
it. Drag the sidebar's right edge to resize it; double-click the edge to reset its
width. With the edge focused, **← / →** changes the width by 16 pixels and
**Home / End** selects the minimum or maximum. **Escape** cancels an active drag.
Your chosen width saves locally and returns when a narrow window is widened.

Drag the divider between the video and caption panels to adjust their widths;
when focused, use **← / →** (or **Home / End**) to resize it with the keyboard.
Panel widths also persist. Narrow windows stack the panes and scroll normally.


- Click a caption or its timeline block to seek to it.
- Press **Space** to play/pause, or **← / →** to move one second.
- Press **N** in a gap to add a caption at the playhead.
- Press **[ / ]** to set the selected caption's start/end to the playhead.
- Press **⌘S / Ctrl+S** to save. Save is explicit; unsaved edits are marked.
- Press **⌘, / Ctrl+,** to open Preferences, at the bottom left.
- Type freely in text fields; playback shortcuts are disabled while typing.
- Changes made through the CLI appear in the editor when it has no unsaved edits.

Caption text appears over the video immediately, including unsaved changes.
SRT and VTT remain separate subtitle files. Exported MP4 captions are burned in.
The JSON export includes local media paths; it is an editable project record,
not a portable copy of the original video.

## Speech models: OpenRouter and local servers

Open **Add AI narration** in the editor. Choose **OpenRouter** or **Local server**,
select a speech model and a voice, and generate audio for all captions or just the
selected caption. Connection setup lives in **Preferences → Integrations**, linked from the
narration panel. Configuring an integration does not change your selected
narration provider. The model picker is searchable. Model, voice, and delivery choices save automatically when edited or when the panel closes; unsaved API key fields are never included in that background save.

OpenRouter's live speech catalog is loaded from its public API. Drama 3 is pinned
first initially. Voice lists are shown when the model publishes them; Drama 3
and some other providers require you to enter a voice ID from their own library.
Custom model and voice IDs remain available if a catalog is incomplete.
**Refresh models** loads current metadata, with a saved cloud catalog available
when OpenRouter cannot be reached.

### Connecting OpenRouter

Open **Preferences → Integrations → OpenRouter** and enter your API key in the
password field. Integrations can be configured before importing a recording.
**Save connection** saves the key securely in macOS Keychain by default, so it is available after restarts. Uncheck **Save this key securely in macOS Keychain** to keep a new key only in the running server's memory. A new
session key can override a previously remembered key for that session. The key
is cleared from the browser field after saving, and when the panel closes.

**Test connection** checks authentication without generating audio. Browsing the
model catalog and testing authentication do not spend speech credits. Generate
narration only when you intend to use your OpenRouter credits.

Keys are never returned by the settings API, written into project JSON, or
stored in browser local storage. **Remove saved key** removes the Keychain copy
and disables the key for this server session. If a terminal environment variable
supplies the key, remove that variable too before restarting the server.

You can still provide `OPENROUTER_API_KEY` in your terminal instead. In zsh:

```sh
read -s 'OPENROUTER_API_KEY?OpenRouter API key: '
export OPENROUTER_API_KEY
./clarity-cli serve --open
```

Restart an already running server to change its inherited environment. The
launcher does not automatically load `.env` files. Session-only browser keys are
available to that running HTTP server. Use `speech-models`, `speech-test`, or
`narrate` with `--server http://localhost:8765` to use its session from the CLI.
Direct CLI processes use their own environment or a remembered Keychain key.
See the [AI guide](ai-cli.md#credentials-and-connections) for CLI session-key
set, remember and remove commands.

### Connecting local speech models

Open **Preferences → Integrations → Local server** and choose a preset, or enter
your own API base URL:

- Kokoro-FastAPI: `http://127.0.0.1:8880/v1`
- Speaches: `http://127.0.0.1:8000/v1`
- Custom: any compatible speech server on loopback or a private LAN IP.

The local server must already be running and implement `POST /audio/speech`
relative to its API base URL. A server that only supports text chat does not
satisfy this interface. Clarity connects to the server; it does not install or
start a local model runtime. An API key is optional for local servers. Local
credentials are scoped to the saved endpoint and are separate from OpenRouter.

**Test connection** and **Refresh models** inspect `/models` and `/audio/voices`.
If a server does not publish those metadata routes, enter its model and voice IDs
manually. A successful metadata check alone does not prove generation works;
only an explicitly requested generation tests that. Delivery instructions are
sent to OpenRouter; local speech requests use the core compatible fields.

For a CLI-only local setup:

```sh
export CLARITY_LOCAL_BASE_URL=http://127.0.0.1:8880/v1
./clarity-cli speech-models --provider local
./clarity-cli narrate PROJECT_ID --provider local --model kokoro --voice af_heart
```

The saved browser connection takes precedence over the default base URL. An
optional local API key can be supplied with `CLARITY_LOCAL_API_KEY`.

### Generate, listen, and export

```sh
./clarity-cli speech-models --provider openrouter
./clarity-cli speech-settings
./clarity-cli narrate PROJECT_ID --provider openrouter --model fish-audio/drama-3 --voice YOUR_VOICE_ID
./clarity-cli narrate PROJECT_ID --provider local --model kokoro --voice af_heart --cue CAPTION_ID
./clarity-cli validate PROJECT_ID
./clarity-cli audio PROJECT_ID --format mp3
./clarity-cli audio PROJECT_ID --format wav
./clarity-cli render PROJECT_ID --narrated
```

Listen to individual generated segments beside each caption. Open the narration
panel to export a standalone MP3 or WAV track with silence between captions to
preserve their timing. A copy is kept in the recording's `exports/` folder.

Generation sends caption text to the selected speech provider, not the video.
OpenRouter generation uses your credits; local generation stays on your configured
local server. Each caption is generated separately and cached by provider, server,
model, voice, delivery, and text. Matching audio is reused, paid requests are not
automatically retried, and completed segments survive interrupted tasks.

Generated audio is measured. If it is too long, shorten the wording or extend the
caption into available space. Text edits mark older audio as stale. Timed audio
and narrated-video exports require every segment to be present, current, and
within its caption's duration. Speech is never silently truncated. Changing the
selected model or voice takes effect when you generate again; existing audio
retains its recorded provider/model identity. Narrated video exports replace the
original audio; ordinary captioned video exports preserve it.

Provider references: [OpenRouter speech API](https://openrouter.ai/docs/guides/overview/multimodal/tts),
[Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI),
[Speaches](https://github.com/speaches-ai/speaches).

## Preferences and private storage

Open **Preferences** at the bottom left of the sidebar, or press
**⌘, / Ctrl+,**. **General** contains appearance, playback speed, and preview
caption size. **Integrations** contains OpenRouter and local-server connections,
API keys, and connection testing. The compact dark style is the default. Playback
mute state, the last recording, and the last Preferences tab also persist. Preview caption size affects the editor only; exported
videos keep their existing subtitle styling. The interface uses the Mac's Avenir
Next font, with system fallbacks and no remote font downloads.

Configuration is stored in **`projects/.local/settings.sqlite3`** by default.
SQLite transactions protect preference writes and concurrent partial updates.
The `.local` directory uses owner-only permissions (`0700`), and the database
uses `0600`. `CLARITY_PROJECTS_DIR` moves both projects and this configuration.
The old `_speech-settings.json` is imported once after validation and remains as
an ignored recovery backup. Subsequent saves use SQLite; the old file cannot
replace newer database preferences.

**The database contains nonsecret preferences. API tokens remain in macOS
Keychain**, or in server memory when session-only storage is chosen. Keeping
secrets in the OS credential vault avoids embedding a decryption key beside the
database. A copied database does not include your API keys. The settings API
returns credential status, never the token. A database backup alone therefore
does not back up your Keychain credentials.

The root `.gitignore` excludes projects, configuration databases and sidecars,
recordings, generated subtitles and audio/video, environment and credential
files, app bundles, caches, logs, screenshots, and temporary artifacts. Source
files, SVG assets, and `uv.lock` remain eligible for version control. Ignoring a
file does not untrack a file previously added to Git. Review the staged files
and history before publishing; do not force-add private files.

## Storage and HTTP API

Each recording lives under `projects/PROJECT_ID/`:

```text
project.json           Saved captions, video reference, revision
history/               Previous saved revisions
frames/                Timestamped evidence frames
inspection/            Contact sheets, manifest.json, AI-BRIEF.md
narration/             Cached voice segments and durations
exports/               Subtitles and rendered MP4 files
preview.mp4            Optional browser-compatible copy
```

Set `CLARITY_PROJECTS_DIR` to use another data directory. Exported SRT/VTT files
can also be reviewed in a compatible external subtitle editor.

The local API has an OpenAPI schema at `/openapi.json`. Useful endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health`, `GET /api/doctor` | Session and dependency checks |
| `GET/PUT /api/preferences` | Editor preferences (partial updates), plus local storage locations |
| `GET/PUT /api/speech/settings` | Preferences, credentials submission, and redacted key status |
| `PATCH /api/speech/preferences` | Save model/voice/delivery choices without changing connection URLs or keys |
| `POST /api/speech/discover` | Model/voice discovery; body `{ "provider": "openrouter" }` or `local` |
| `POST /api/speech/test` | Test the saved connection without generating speech |
| `GET /api/projects` | List recordings |
| `POST /api/projects` | Import `{ "path": "/absolute/video.mov" }` |
| `POST /api/upload` | Multipart video upload, field `file` |
| `GET /api/projects/{id}` | Read project, revision, warnings, narration status |
| `PUT /api/projects/{id}/cues` | Save `{ "revision": N, "cues": [...] }` |
| `GET /api/projects/{id}/frame?time=12.5&width=0` | Inspect a specific frame |
| `GET /api/projects/{id}/export/srt` | Download subtitles |
| `POST /api/projects/{id}/inspect` | Prepare frames; body `{ "every": 5, "max_frames": 48 }` |
| `POST /api/projects/{id}/render?narrated=false` | Render a captioned MP4 |
| `POST /api/projects/{id}/preview` | Generate a compatible browser preview |
| `POST /api/projects/{id}/narrate` | Generate speech using saved preferences, or override `provider`, `model`, `voice`, and `cue_ids` |
| `POST /api/projects/{id}/audio?format=mp3` | Export the generated timed narration track as MP3 or WAV |
| `GET /api/jobs/{job_id}` | Poll task status and artifact paths |

HTTP long tasks return a `job_id`. Direct CLI media tasks run synchronously;
`narrate --server` returns a server job for `job`/`job-wait` to inspect.
The browser uses byte range requests for seeking. The server rejects cross-origin requests and unknown
Host headers; it is intended for local use, not internet hosting.
