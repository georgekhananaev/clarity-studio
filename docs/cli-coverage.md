# Application operation coverage

The CLI covers the app's **25 application API operations**. The machine-readable
map is `./clarity-cli capabilities`; `tests/test_capabilities.py` compares it with
the actual FastAPI routes and parses the mapped CLI forms. Behavioral CLI tests
check dispatch, revisions, validation, private credentials and error handling.

This means operation parity, not an assertion that every possible input or
external provider has been tested. Live speech generation remains a separate,
explicitly approved operation. The [AI guide](ai-cli.md) gives the workflow and
credential rules.

| App/API operation | CLI equivalent |
| --- | --- |
| `GET /api/health` | `health` (or `--server URL` for that server) |
| `GET /api/preferences` | `preferences show` |
| `PUT /api/preferences` | `preferences set --json …` or `--file …` |
| `GET /api/speech/settings` | `speech-config show` (optional `--server URL`) or direct `speech-settings` |
| `PUT /api/speech/settings` | `speech-config set`, `speech-key set/remove`, `speech-key remember --server URL` |
| `PATCH /api/speech/preferences` | `speech-config set --json …` |
| `POST /api/speech/discover` | `speech-models` (optional `--server URL`) |
| `POST /api/speech/test` | `speech-test --provider …` (optional `--server URL`) |
| `GET /api/doctor` | `doctor` |
| `GET /api/projects` | `list` (plus `--search`) |
| `POST /api/projects` | `import VIDEO` |
| `POST /api/upload` | `import VIDEO --copy` |
| `GET /api/projects/{project_id}` | `show PROJECT_ID` |
| `PUT /api/projects/{project_id}/cues` | `cues`, `add`, `edit`, `delete-cue`, `rename` |
| `GET /api/projects/{project_id}/media` | `media PROJECT_ID` |
| `GET /api/projects/{project_id}/frame` | `frame PROJECT_ID --time …` |
| `GET /api/projects/{project_id}/subtitles.vtt` | `export PROJECT_ID --format vtt` |
| `GET /api/projects/{project_id}/export/{format}` | `export PROJECT_ID --format …` |
| `GET /api/projects/{project_id}/files/{relative:path}` | `assets PROJECT_ID`, `asset PROJECT_ID --path …` |
| `POST /api/projects/{project_id}/inspect` | `inspect PROJECT_ID` |
| `POST /api/projects/{project_id}/render` | `render PROJECT_ID` (optional `--narrated`) |
| `POST /api/projects/{project_id}/narrate` | `narrate PROJECT_ID` (optional `--server URL`) — requires generation approval |
| `POST /api/projects/{project_id}/audio` | `audio PROJECT_ID --format …` |
| `POST /api/projects/{project_id}/preview` | `preview PROJECT_ID` |
| `GET /api/jobs/{job_id}` | `job JOB_ID`, `job-wait JOB_ID` |

The static website, icons and framework OpenAPI metadata are presentation or
discovery resources, not additional persisted application operations. The CLI
has 31 top-level commands, including aliases, capability discovery and server
startup. Run individual `--help` pages for their arguments.

## Differences an AI must understand

- API media tasks return a job ID; direct CLI media commands finish synchronously.
  `narrate --server URL` queues with that server's session credentials and returns
  a job ID. `job`/`job-wait` query tasks that were started on the HTTP server.
- API media/file responses stream bytes; CLI media/file commands return paths.
- Browser upload copies a chosen file; CLI import references it unless `--copy`
  is supplied. Both workflows keep the original recording intact.
- Browser playback, selected widgets, dialogs, clipboard and unsaved edits are
  tab-local presentation. Headless visual inspection uses frames/contact sheets;
  persisted playback/layout preferences have CLI equivalents.
- Keys saved in Keychain work across processes; environment/session overrides
  belong to their processes. `speech-key set --server URL --session` keeps a key
  in the running server; `remember --server URL` persists it in Keychain.
  Server modes use that server's workspace, not the CLI's `--projects-dir`.
  Direct CLI key removal cannot erase another process's environment or a
  deliberate session override; `remove --server URL` clears the target server.
- A passing mocked speech test verifies integration behavior. It does not prove
  the user's chosen live voice/model works. Generation requires separate approval.
