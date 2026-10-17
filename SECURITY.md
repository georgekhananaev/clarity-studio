# Security policy

Clarity Studio is an early macOS-first local application. Security fixes target
the current `main` branch; there is no maintained release/LTS support schedule.

## Report a vulnerability privately

Do not include vulnerabilities, credentials or private recordings in a public
issue. On the repository's **Security → Advisories** page, use **Report a
vulnerability** if private vulnerability reporting is enabled. Describe affected
code, impact, reproduction steps and a synthetic example. Do not include live
API keys or other people's data.

If the private-report option is unavailable, open a minimal issue requesting a
private reporting channel, without vulnerability details or sensitive material.
Do not assume this repository has a private reporting address or response SLA.
Maintainers should enable [GitHub private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)
when the public repository is created.

## Intended boundary

The HTTP service is for one local user on loopback, without multi-user login.
Do not expose it through public tunnels or a reverse proxy. Project files are
ordinary local files. Keychain protects remembered credentials, but the app is
not a sandbox against programs running as the same user.

Generation can send caption text to OpenRouter or a configured private-network
speech server and can spend credits. Read [privacy and data flow](docs/privacy.md)
for the complete storage and sharing behavior. Use only media and voice inputs
you have permission to use.

## If a credential is exposed

Revoke or rotate it with the provider first. Removing a file or changing
`.gitignore` does not invalidate a leaked key or erase existing Git history.
Report the affected location without copying the credential into another issue
or log. Review any public history cleanup separately with the maintainer.
