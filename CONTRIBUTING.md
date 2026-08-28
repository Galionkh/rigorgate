# Contributing to GALION SignalForge

Thank you for helping build transparent, evidence-aware equity research software.

## Before you start

- Search existing issues and discussions.
- Open an issue before large architectural changes.
- Do not submit secrets, brokerage credentials, proprietary datasets, or personal portfolio data.
- Do not describe a score as a win probability unless the calibration method and sample are documented.
- Keep order execution outside the project boundary.

## Development setup

The zero-install route is [GitHub Codespaces](https://codespaces.new/Galionkh/galion-signal-forge?quickstart=1). It verifies the repository and opens Replay Lab automatically.

For local development:

```bash
git clone https://github.com/Galionkh/galion-signal-forge.git
cd galion-signal-forge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
make verify
```

Run `make lab` to rebuild and serve the interactive decision challenge at `http://localhost:8080`. For a tightly scoped first pull request, follow the [counterexample challenge](CONTRIBUTOR_START.md).

## Research contributions without code

A precise counterexample is a valid contribution even if you do not implement the fixture. Use the [challenge form](https://github.com/Galionkh/galion-signal-forge/issues/new?template=counterexample.yml) and include:

- the decision-time evidence and its timestamp;
- the gate or posture that appears wrong;
- the expected fail-closed behavior;
- the strongest red-team argument against your conclusion.

Do not paste paid-provider payloads or personal holdings. A maintainer or developer can convert a reproducible research case into a deterministic test later. See [CHALLENGE.md](CHALLENGE.md) for all three contribution paths.

## Pull requests

1. Create a focused branch from `main`.
2. Add tests for behavioral changes and failure cases.
3. Update documentation when contracts, inputs, or interpretation change.
4. Use synthetic or legally redistributable fixtures.
5. Run compile checks, unit tests, and the offline demo.
6. Explain data provenance, missing-value behavior, and look-ahead defenses.

Small, reviewable pull requests are preferred. Maintainers may ask for changes that make evidence gaps more visible or reduce accidental investment-advice framing.

## Commit style

Use short imperative subjects, for example:

- `Add SEC taxonomy fallback tests`
- `Document IEX volume limitations`
- `Harden point-in-time snapshot validation`

## Areas where help is valuable

- free and redistributable provider fixtures;
- point-in-time datasets and validation methodology;
- sector-specific financial normalization;
- bias-resistant research experiments;
- accessibility and dashboard usability;
- documentation, translations, and reproducible examples.

By contributing, you agree that your contribution is licensed under Apache License 2.0 and that you have the right to submit it.
