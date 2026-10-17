# Clarity Studio: guide for AI agents

Use `./clarity-cli` from the project root. It edits the same persisted projects
as the browser editor. The caption workflow needs neither a browser nor the
Clarity web server. You supply the visual understanding and caption wording.

## Discover the contract

```sh
./clarity-cli capabilities
./clarity-cli --help
./clarity-cli cues --help
./clarity-cli doctor
./clarity-cli list
```

`capabilities` returns a JSON inventory of commands, application API equivalents,
server requirements and speech-generation boundaries. The
[coverage map](cli-coverage.md) explains the equivalents. Help and capabilities
work without initializing a workspace. Every command has `--help`.

Successful commands write JSON to stdout. Failures write a JSON error to stderr
and exit nonzero; inspect the exit status before using stdout. Help is plain text.
Validation failures omit input values and redact unrecognized field names.
Do not parse pretty-printed JSON with line-based text tools. Read it as JSON.
`serve` is a long-running server process, not a one-response command.

### Select a workspace

The default data root is `projects/`. Use an absolute path with the global option
**before the subcommand** to isolate an experiment:

```sh
./clarity-cli --projects-dir /absolute/path/to/demo-projects list
```

`CLARITY_PROJECTS_DIR` supplies the default when the option is absent. That root
contains projects, generated files and `.local/settings.sqlite3`; it never
contains API keys written by Clarity. Keep alternative roots outside version
control too. Use the same root consistently throughout a workflow.

## Create explanatory subtitles

Replace `PROJECT_ID`, `REVISION` and paths below with values returned by commands.
Do not literally pass those placeholders, assume the revision is zero, or infer
the recording's contents from its filename.

1. Import a supplied recording, then read the returned project:

   ```sh
   ./clarity-cli import /absolute/path/recording.mp4 --title "Feature walkthrough"
   ./clarity-cli show PROJECT_ID
   ```

   The default import references the original in place. Add `--copy` to keep a
   managed copy, equivalent to a browser upload. Keep referenced originals at
   their recorded locations. `list --search "walkthrough"` filters titles.

2. Extract visual evidence:

   ```sh
   ./clarity-cli inspect PROJECT_ID --every 5 --max-frames 48
   ./clarity-cli frame PROJECT_ID --time 12.5 --width 0
   ```

   Read the returned brief and manifest. **Open every returned contact sheet
   with an image tool.** Inspect individual frames near actions and transitions;
   use `--width 0` for native-resolution UI text. Frame times must be less than
   the video's duration. Sampling is incomplete evidence. A contact sheet has
   no audio, so do not claim that visual inspection transcribed speech.

3. Write caption JSON under the ignored project directory. For a new project:

   ```json
   [
     {"start": 0.5, "end": 4.0, "text": "Open the recording to begin editing."},
     {"start": 4.2, "end": 8.0, "text": "Adjust the caption text and its timing."}
   ]
   ```

   Ground wording in visible evidence and user context. Do not invent unseen
   clicks, outcomes or intent. Use seconds with millisecond precision, nonempty
   text, `end > start`, no overlaps and times within the video. Aim for at most
   22 characters per second. Split long explanations into readable captions.
   When editing, preserve existing caption `id` values and include every caption
   to retain: `cues` replaces the entire list. Omit IDs only for new captions.

4. Re-read the project, merge any intervening edits, and apply the revision just
   read:

   ```sh
   ./clarity-cli show PROJECT_ID
   ./clarity-cli cues PROJECT_ID --file /absolute/path/captions.json --revision REVISION
   ./clarity-cli validate PROJECT_ID
   ./clarity-cli export PROJECT_ID --format srt
   ./clarity-cli export PROJECT_ID --format vtt
   ```

   A revision conflict is a stop-and-merge condition. Re-read, understand changes
   and merge the intended edits; never blindly retry with a newer revision.
   Validation returns warnings separately from structural validity. Fix useful
   pacing/timing warnings before presenting the result. Exports return file paths.

**For a subtitles-only request, stop after validation and subtitle export.**
Present the recording and subtitle paths for review. Do not call `narrate` just
because an API key is available. Audio generation requires the user's approval.

## Edit individual items

Read `show` before each group of changes, and use its current revision:

```sh
./clarity-cli rename PROJECT_ID --title "Clearer walkthrough" --revision REVISION
./clarity-cli add PROJECT_ID --start 8.2 --end 11.8 --text "Preview the result." --revision REVISION
./clarity-cli edit PROJECT_ID CAPTION_ID --text "Review the captions." --revision REVISION
./clarity-cli delete-cue PROJECT_ID CAPTION_ID --revision REVISION
```

`edit` accepts any combination of `--start`, `--end`, `--text`; it preserves the
caption ID and validates the whole project. Each successful mutation increments
the revision, including renaming. Read the returned revision for the next edit.
Legacy `add` accepts omission of `--revision`, but AI callers should supply it.
There is no destructive project-delete operation in the app or CLI.

## Configure the app without opening it

```sh
./clarity-cli preferences show
./clarity-cli preferences set --json '{"appearance":"dark","sidebar_width":240}'
./clarity-cli preferences set --json '{"playback_speed":1,"muted":false,"caption_size":22}'
./clarity-cli speech-config show
./clarity-cli speech-config set --json '{"local_base_url":"http://127.0.0.1:8880/v1","local":{"model":"kokoro","voice":"af_heart"}}'
```

`set --file /path/nonsecret-settings.json` is an alternative to `--json`.
Patches preserve unspecified fields, including nested provider choices. Changing
the local endpoint/model does not select local narration. To select it explicitly:

```sh
./clarity-cli speech-config set --json '{"provider":"local"}'
./clarity-cli speech-config set --json '{"provider":"openrouter","openrouter":{"model":"fish-audio/drama-3"}}'
```

Send a patch rather than resubmitting the whole `show` response: `storage` and
`keys` in responses are read-only metadata and are not accepted settings fields.

Speech settings allow `provider`, `local_base_url`, and the `openrouter`/`local`
objects (`model`, `voice`, `instructions`). Local URLs must use localhost or a
private IP address and contain no user credentials, query or fragment. Clarity
connects to a speech server; it does not install or start a model runtime.

Editor preferences allow `appearance` (`light`, `dark`, `system`),
`playback_speed` (0.5, 0.75, 1, 1.5, 2), `muted`, `caption_size` (18, 22, 28),
`sidebar_collapsed`, `sidebar_width` (168–360 pixels), `preview_share` (0.5–0.75),
`preferences_pane` (`general`, `integrations`) and `last_project` (project ID or
null to clear). Caption size affects the browser preview, not rendered subtitles.
Never include a token/key/password in these patches.

### Credentials and connections

```sh
./clarity-cli speech-key set --provider openrouter
./clarity-cli speech-key remove --provider openrouter
./clarity-cli speech-test --provider openrouter
./clarity-cli speech-models --provider openrouter
./clarity-cli speech-models --provider local --model kokoro
./clarity-cli speech-test --provider local
```

`speech-key set` reads a hidden terminal prompt and remembers the key in macOS
Keychain. For automation, `--stdin` accepts a secure input stream. **Never place
the key in argv, shell history, JSON preference files, chat or logs.** Do not
invent a fake live credential merely to exercise this command. Tests use a
mocked Keychain. Removal affects the remembered key for the selected provider
and, for local speech, its current endpoint.

`OPENROUTER_API_KEY` and `CLARITY_LOCAL_API_KEY` can instead supply keys to the
CLI process. Precedence is an explicit process session override, then the
environment, then Keychain. Direct CLI commands cannot use a browser server's
session-only key; use the explicit server modes below. Removing a remembered key
cannot erase another process's environment or session override; clear those at
their source or restart that process. Keychain reads pick up changed remembered credentials.
Commands return key **status/source**, never key values.

To manage the credentials of an already running Clarity server:

```sh
./clarity-cli health --server http://localhost:8765
./clarity-cli speech-config show --server http://localhost:8765
./clarity-cli speech-key set --provider openrouter --server http://localhost:8765 --session
./clarity-cli speech-key remember --provider openrouter --server http://localhost:8765
./clarity-cli speech-key remove --provider openrouter --server http://localhost:8765
./clarity-cli speech-models --provider openrouter --server http://localhost:8765
./clarity-cli speech-test --provider openrouter --server http://localhost:8765
```

These are alternative credential actions, not a sequence to run blindly.
`set --session` keeps the prompted/stdin key only in that server process.
Omitting `--session` also remembers it in Keychain. `remember` saves an existing
server credential without asking for it again. `remove --server` clears that
server's override and the selected remembered key. Credential-only actions leave
connection/model preferences intact, even if another client changed them.
`--stdin` can be combined with `--server`; never echo a key into a logged command.

Server modes verify a loopback Clarity endpoint and do not initialize a local
workspace. The server's `projects_directory` returned by `health --server` is
authoritative; `--projects-dir` does not redirect the server. Confirm it before
working on a server project. A server must be restarted to load Python source
changes; a running older version may not support newer CLI server modes.

Model discovery and connection checks generate no audio. Metadata success is
not proof that a local model supports speech generation; it must implement
`POST /audio/speech`. Tests may legitimately report missing metadata routes.

## Audio: only after approval

The following commands are reference material, **not authorization to execute**.
Require explicit generation approval, a selected provider/model and a real voice
ID supported by that provider. Do not substitute an invented voice ID. Existing
saved choices can be read with `speech-config show`.

```sh
./clarity-cli narrate PROJECT_ID --provider openrouter --model fish-audio/drama-3 --voice VOICE_ID
./clarity-cli narrate PROJECT_ID --provider local --model kokoro --voice af_heart --cue CAPTION_ID
./clarity-cli validate PROJECT_ID
./clarity-cli audio PROJECT_ID --format mp3
./clarity-cli audio PROJECT_ID --format wav
./clarity-cli render PROJECT_ID --narrated
```

To generate with the running server's session credential **after approval**:

```sh
./clarity-cli narrate PROJECT_ID --server http://localhost:8765 --provider openrouter --model fish-audio/drama-3 --voice VOICE_ID
./clarity-cli job-wait JOB_ID --server http://localhost:8765 --timeout 120
```

This mode returns a `job_id` immediately; substitute it in `job-wait`.
It queues once and never retries generation. `--base-url` cannot be combined
with server narration; configure that server's saved local connection instead.

`--base-url` on local discovery/narration overrides the endpoint for that command
without changing saved preferences. Narration sends caption text to the selected
provider, not the video. OpenRouter generation spends credits; do not retry paid
calls automatically. Matching caption audio is cached. Missing, stale or overlong
segments block audio/narrated-video export: fix wording/timing rather than truncate
speech. `--narrated` replaces original audio. Audio exports use already generated
segments; they do not generate speech themselves.

## Files, previews and tasks

```sh
./clarity-cli media PROJECT_ID
./clarity-cli assets PROJECT_ID
./clarity-cli asset PROJECT_ID --path inspection/manifest.json
./clarity-cli preview PROJECT_ID
./clarity-cli render PROJECT_ID
./clarity-cli export PROJECT_ID --format json
./clarity-cli export PROJECT_ID --format txt
```

File commands return local paths and sizes rather than HTTP streams. Project
asset paths cannot escape the project directory. JSON exports include local video
paths; avoid sharing them indiscriminately. `preview` transcodes to a browser
compatible video. `render` burns subtitles into an MP4, preserving original audio
unless `--narrated` is supplied. Neither modifies the original recording.
These media operations are synchronous: await the process and read its final JSON.

For people reviewing in the browser, start `./clarity-cli serve --open`; omit
`--open` for an API-only server. Use `--port` for a separate workspace/server.
HTTP media jobs are asynchronous, so CLI commands can inspect an existing task:

```sh
./clarity-cli job JOB_ID --server http://localhost:8765
./clarity-cli job-wait JOB_ID --server http://localhost:8765 --timeout 120 --interval 0.5
```

`job`, `job-wait` and explicitly selected `--server` modes require the Clarity
HTTP server. The direct caption workflow does not. Server URLs must be
loopback addresses. A timeout or failed job is not retried and may still have
saved useful partial work. Job status is server-local and disappears on restart;
project files remain. UI play/pause, dialog focus, clipboard, selected caption
and unsaved drafts belong to a browser tab; use `frame`/`inspect` for headless
visual navigation. Save or resolve browser drafts before switching to CLI edits.

Do not run application builds, install dependencies, commit, push or deploy as
part of a caption request. Keep user projects, settings, media, keys, AI skills
and memory private under the configured ignore rules.
