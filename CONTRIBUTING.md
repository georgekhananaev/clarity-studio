# Contributing to Clarity Studio

Bug reports, documentation improvements, accessibility fixes and focused code
changes are welcome. Start with the [README](README.md) and
[development guide](docs/development.md).

## Issues

Use the bug or feature template. Describe what you tried, what you expected and
what happened. Include macOS/Python versions and a small, synthetic reproduction.
Remove keys, private URLs, home-directory paths, personal captions and recording
content from screenshots or logs. For vulnerabilities, follow [SECURITY.md](SECURITY.md)
instead of posting the details publicly.

## Pull requests

Keep changes focused and explain the user-visible problem. For larger behavior
changes, discuss the intended approach in an issue first. Follow the existing
Python and plain JavaScript style; the frontend has no build step.

Run the checks relevant to the change and report their actual results. Add tests
for meaningful behavior or regressions; mocked speech tests must never call a
paid provider. Keep lockfile changes intentional. See the development guide for
the complete test commands and the public-source audit.

Preserve original recordings, project revisions and cached work. Use temporary
or isolated data roots. Do not contribute recordings, generated media, local
databases, credentials, app bundles, AI memory/skills or personal tool settings.
Check the staged diff even when `.gitignore` covers those paths.

Treat people respectfully, give concrete feedback, and keep discussions focused
on the work. Explain tradeoffs and welcome corrections. There is no promised
response time or release schedule.

By submitting a contribution, you confirm you have the right to share it under
the project's [license](LICENSE). Third-party assets need compatible permission
and any required notices; do not add bundled fonts or models casually.
