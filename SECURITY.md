# Security Policy

## Supported versions

Security fixes are applied to the current `main` branch and the latest tagged release.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting when it is available for this repository. Do not open a public issue for a vulnerability that could expose secrets, enable code execution, or compromise user data.

Include the affected version, reproduction steps, impact, and any suggested mitigation. You should receive an acknowledgement within seven days. Please allow reasonable time for investigation and a coordinated fix before public disclosure.

## Credential safety

- Never commit `.env`, API keys, tokens, cookies, brokerage credentials, or private reports.
- Use local environment variables or GitHub Actions secrets.
- Grant provider keys the minimum available permissions.
- SignalForge does not need trading permission and should never receive it.
- Rotate any credential that appears in a log, report, issue, or pull request.

## Data safety

Only submit synthetic, public-domain, or legally redistributable test fixtures. Remove account identifiers and personal portfolio information from reports before sharing them.

This policy covers the SignalForge codebase. Provider outages, data errors, investment losses, and unsupported private deployments are outside the vulnerability program.
