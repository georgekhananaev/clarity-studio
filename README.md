<p align="center"><img src="web/logo.svg" width="260" alt="Clarity Studio"></p>

# Clarity Studio

Turn screen recordings into clear, timed explanations. Clarity Studio combines
a local browser editor with a JSON CLI that AI agents can use to inspect frames,
write captions, and export subtitles without browser automation.

Built for macOS. Your recordings and projects stay on your machine. Optional
speech generation connects to OpenRouter or a local speech server.

- **Edit and review:** video preview, caption editor, timeline, timing shortcuts,
  resizable panels, and saved appearance/playback preferences.
- **Work with AI:** timestamped frames, contact sheets, a task brief, revision
  checks, and machine-readable command discovery.
- **Export:** SRT, WebVTT, text, project JSON, and video with captions burned in.
- **Add narration:** per-caption speech, cached audio, MP3/WAV tracks, and
  narrated video with timing validation.

Clarity prepares the evidence and manages captions; your AI agent supplies the
visual understanding and explanations. It does not automatically transcribe
speech or generate explanations on its own.

## Example video and tutorial

This narrated example shows what you can create with Clarity Studio and walks
through importing recordings, editing and timing captions, playback, exports,
preferences, and narration setup.

[![Watch the Clarity Studio example video and tutorial](https://i.ytimg.com/vi/TamkPEVWvXA/hqdefault.jpg)](https://www.youtube.com/watch?v=TamkPEVWvXA)

[Watch the full video on YouTube](https://www.youtube.com/watch?v=TamkPEVWvXA)
with English narration, captions, and chapter timestamps.

## Quick start

You need **macOS**, **Python 3.12 or newer**, [Homebrew](https://brew.sh), and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Git is needed for
the development/publication checks. Node.js is needed only for JavaScript tests.

Download or clone this repository, open its folder in Terminal, then run:

```sh
./setup.command
./clarity-cli serve --open
```

Setup installs the locked Python dependencies and the prebuilt Homebrew
`ffmpeg-full` package when needed. It does not compile the application. The
editor opens at **http://localhost:8765**. You can also double-click
**Launch Clarity.command** after setup. Keep that terminal open; Ctrl+C stops
the server.

The library starts empty. Choose **New recording** to upload a managed copy or
reference an existing video by its full path. No API key is needed to edit,
inspect, or export captions. To create a labeled 12-second practice recording:

```sh
.venv/bin/python scripts/create_sample.py
```

If a codec will not play, choose **Create preview** to make a local H.264 copy.
See [troubleshooting](docs/troubleshooting.md) for setup and playback issues.

## A caption workflow for AI agents

Start with the [AI CLI guide](docs/ai-cli.md) and the
[operation coverage map](docs/cli-coverage.md). Discover commands with:

```sh
./clarity-cli capabilities
./clarity-cli doctor
./clarity-cli import /absolute/path/recording.mp4 --title "Feature walkthrough"
./clarity-cli show PROJECT_ID
./clarity-cli inspect PROJECT_ID --every 5 --max-frames 48
```

Replace `PROJECT_ID` with the returned ID. View the extracted contact sheets and
inspect additional frames around transitions. Write a JSON caption array:

```json
[
  {"start": 0.5, "end": 4.0, "text": "Open Settings to choose a language."},
  {"start": 4.2, "end": 7.8, "text": "Select the language you want to use."}
]
```

Save it under the ignored project directory. Re-read the project, preserve
existing cue IDs when editing, and apply the current revision:

```sh
./clarity-cli cues PROJECT_ID --file /absolute/path/cues.json --revision REVISION
./clarity-cli validate PROJECT_ID
./clarity-cli export PROJECT_ID --format srt
```

`cues` replaces the full caption list. Revision conflicts require reviewing and
merging changes. The CLI works directly on local files; no web server is needed
for this workflow. Operation results are JSON; failures exit nonzero with a JSON
error on stderr.

## Narration

Configure connections in **Preferences → Integrations**, then open **Add AI
narration** to select a speech model and a supported voice. OpenRouter's catalog
includes Drama 3 when available; some models require a voice ID from the
provider's own library. Kokoro-FastAPI, Speaches, and other local servers must
implement an OpenAI-compatible `/audio/speech` endpoint. Clarity does not install
the models or run their inference servers.

Generating speech sends caption text to the selected provider. **OpenRouter
generation uses your credits.** Model discovery and connection tests generate
no speech. The AI workflow requires explicit approval before generating audio.
Existing matching audio is reused, and paid requests are not retried
automatically. Listen to the result: a valid audio response can still misread
symbols or add unwanted words. Spell out button names such as “left bracket”
when needed.

Exports require current audio that fits every caption. Adjust wording or timing
for overlong clips. Narrated video replaces the original audio; ordinary
captioned video preserves it. See the [full guide](docs/user-guide.md#speech-models-openrouter-and-local-servers).

## Privacy and storage

Projects, revision history, generated media, and nonsecret preferences live under
`projects/` by default. Remembered API keys use **macOS Keychain**; session-only
keys stay in the running server. The settings database does not store API keys.
An optional `CLARITY_PROJECTS_DIR` changes the data root.

The editor binds to loopback and is intended for one local user. It is not a
multi-user or internet-hosted service. Contact sheets are created locally; an
external AI agent may send those images to its own model service. Project JSON
exports contain local media paths. Read [privacy and data flow](docs/privacy.md)
before sharing projects, logs, or recordings.

## Documentation and contributing

- [User guide](docs/user-guide.md): UI, shortcuts, exports, speech setup, storage, API.
- [AI CLI guide](docs/ai-cli.md): safe, browser-free caption and narration workflows.
- [CLI coverage](docs/cli-coverage.md): application operations and CLI equivalents.
- [Development](docs/development.md): setup, tests, architecture, and public-source checks.
- [Troubleshooting](docs/troubleshooting.md): common problems and fixes.
- [Contributing](CONTRIBUTING.md): issues, changes, and pull requests.
- [Security](SECURITY.md): vulnerability reporting and supported scope.

Created by **George Khananaev**. See [LICENSE](LICENSE) for the source license.
Model services, dependencies, and user-supplied media have their own terms.
