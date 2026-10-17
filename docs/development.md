# Development

Follow the [Mac quick start](../README.md#quick-start). Python dependencies are in
`pyproject.toml` and `uv.lock`; use the lockfile rather than upgrading incidentally.
Node.js 18 or newer is needed for the JavaScript tests. There is no frontend
package installation or application build step.

```sh
./setup.command
./clarity-cli doctor
./clarity-cli serve --open
```

Setup uses prebuilt FFmpeg bottles and Python wheels. It fails rather than
building a dependency from source. `CLARITY_FFMPEG` and `CLARITY_FFPROBE` can point
to alternative executables; subtitle rendering requires FFmpeg with libass.
`uv lock --check` checks lock consistency without changing it. Intentional
dependency changes should update both `pyproject.toml` and `uv.lock` for review.

## Architecture

| Location | Responsibility |
| --- | --- |
| `clarity/__main__.py` | JSON CLI and server startup |
| `clarity/capabilities.py` | Machine-readable CLI/API operation map |
| `clarity/models.py`, `clarity/store.py` | Validated captions, revisions, project storage |
| `clarity/config.py`, `clarity/settings.py` | Transactional SQLite preferences |
| `clarity/speech.py` | Provider connections, model discovery, Keychain credentials |
| `clarity/media.py`, `clarity/output.py` | FFmpeg evidence, exports, narration and timing |
| `clarity/server.py` | Local FastAPI endpoints and background jobs |
| `web/` | Static HTML, CSS, JavaScript and SVG assets |
| `tests/` | Python/media tests and JavaScript state regressions |

The OpenAPI schema is served at `/openapi.json`. See the
[coverage map](cli-coverage.md) for CLI equivalents. Restart a running server
after Python changes; static frontend changes can be refreshed in the browser.

## Tests

```sh
.venv/bin/python -m pytest -q
node --check web/app.js
node --check web/speech.js
node --check web/preferences.js
node --test tests/speech-state.test.cjs
zsh -n setup.command clarity-cli 'Launch Clarity.command'
python3 scripts/check_public_repo.py
```

The tests use temporary data and mocked speech responses/credentials. They do
not require API keys or spend speech credits. Media tests use real FFmpeg and
FFprobe. Keep meaningful tests for behavior, validation, concurrency and
credential handling. Avoid using a real project or live speech service as a test
fixture. CI runs these checks on macOS; other platforms are not claimed as tested.

For manual experiments, isolate local data:

```sh
./clarity-cli --projects-dir /absolute/path/to/private-demo list
```

The optional sample generator also honors `CLARITY_PROJECTS_DIR`. It creates a
labeled practice video locally and makes no speech or network calls.

## Before publishing source

```sh
python3 scripts/check_public_repo.py
python3 scripts/check_public_repo.py --archive dist/clarity-studio-public.zip
```

The check inspects tracked files and eligible untracked files, checks sensitive
paths/ignore rules, scans recognizable secret signatures and home-directory
paths, and inspects reachable Git-history blobs. It reports locations and rule
names without printing matching values. It is a focused publication check, not
a guarantee that arbitrary secrets or private prose can be detected. Files with
NUL bytes, symlinks and files over 4 MiB are rejected for separate review. Review
the diff and archive inventory as well.

The archive is made only after a passing check. It contains the reviewed source
set under `clarity-studio/`, without `.git`, local projects, environments, keys,
media, AI files, or audit output. It is a source snapshot, not a built app. The
command also writes a manifest with file hashes beside the ZIP. It does not
stage files, initialize a repository, commit, change history, or upload anything.

Git commit names/emails are public metadata if you publish existing history;
`.gitignore` does not hide them. A source-only snapshot avoids carrying local
history into a first upload. Choose your public Git identity separately. Never
upload the whole working folder or attach local audit reports to a public issue.

Before enabling a public repository, configure private vulnerability reporting
and GitHub secret scanning/push protection where available. These are repository
settings and cannot be enabled by source files. The included workflow has
read-only repository permissions and makes no live speech calls.
