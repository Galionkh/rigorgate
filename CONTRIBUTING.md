# Contributing to GALION SignalForge

Thank you for helping build transparent, evidence-aware equity research software.

## Before you start

- Search existing issues and discussions.
- Open an issue before large architectural changes.
- Do not submit secrets, brokerage credentials, proprietary datasets, or personal portfolio data.
- Do not describe a score as a win probability unless the calibration method and sample are documented.
- Keep order execution outside the project boundary.

## Development setup

```bash
git clone https://github.com/Galionkh/galion-signal-forge.git
cd galion-signal-forge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

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
