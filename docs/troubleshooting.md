# Troubleshooting

## Setup or launch fails

Run `./setup.command` from the repository folder. It requires macOS, Python 3.12+
available as `python3`, Homebrew and uv. `python3 --version`, `brew --version`
and `uv --version` help identify missing prerequisites. Follow their official
installation instructions linked in the [README](../README.md#quick-start).

If a downloaded source archive lost executable permissions, run:

```sh
chmod +x setup.command clarity-cli 'Launch Clarity.command'
./setup.command
```

The source is not a signed macOS application bundle. If Finder refuses to open a
launcher, use the Terminal commands above. Do not disable system-wide security
settings. A missing prebuilt dependency stops setup rather than compiling it.

## FFmpeg or subtitle rendering is unavailable

Run `./clarity-cli doctor`. Check that FFmpeg and FFprobe are found and subtitle
rendering is available. Setup uses Homebrew's `ffmpeg-full` keg. A custom FFmpeg
must include libass; `CLARITY_FFMPEG` and `CLARITY_FFPROBE` can select executable
paths without changing your shell configuration.

## The editor is empty or opens the wrong workspace

A new installation has no recordings. Import a video or generate the optional
sample with `.venv/bin/python scripts/create_sample.py`.
Check `./clarity-cli health` for the direct CLI's workspace. To inspect a running
server, use `./clarity-cli health --server http://localhost:8765`. A process keeps
its original data root and environment until it restarts.

If port 8765 is in use by another workspace, stop that server in its terminal or
start a separate instance with `./clarity-cli serve --port 8766 --open`.
Avoid killing an unrelated process. Restart after Python source changes.

## Video will not play or cannot be found

Path imports reference the original file; keep it in place. File uploads make a
managed copy. For unsupported browser codecs, choose **Create preview** or run
`./clarity-cli preview PROJECT_ID`. This does not modify the original recording.

If exported video shows two caption layers in a player, disable the player's
external subtitle track: the MP4 already has captions burned in. Keep separately
exported SRT/VTT files in another folder if the player auto-loads them.

## Saving reports a revision conflict

Another client saved the project. Re-read its current revision, review what
changed, and merge your edits. Do not blindly retry with the newer revision.
Previous project versions are retained in `history/`. Resolve unsaved browser
drafts before applying CLI edits.

## Speech connection or generation fails

Configure connections under **Preferences → Integrations**. A session-only key
belongs to its server; direct CLI processes cannot inherit it. Use `--server`
on supported commands or remember the key in Keychain. Never paste keys into
issues, chat, preference JSON or command arguments.

Model discovery/connection tests do not generate audio. A local server must
implement `/audio/speech`, not just text chat. If model/voice discovery is absent,
enter supported IDs manually. Providers change availability; use current catalog
data and their documentation rather than an invented voice ID.

Inspect failed jobs before retrying generation: completed clips are kept, and a
repeated paid request can be charged again. Listen for misread symbols or extra
speech. Spell out UI symbols when necessary and regenerate only the affected
caption. Missing, stale or overlong clips block timed exports; shorten wording
or extend timing into available space. Speech is not silently truncated.

For an issue report, include the command without credentials, OS/Python versions,
sanitized `doctor` output, expected behavior and reproduction steps. Use a
synthetic recording, and review paths, caption text and logs before attaching.
