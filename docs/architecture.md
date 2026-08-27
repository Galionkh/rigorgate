# Architecture

GALION SignalForge is a staged research pipeline. Each stage may reject a security, enrich its evidence record, or pass it to a more expensive stage. The design favors traceability over opaque model complexity.

## Core flow

1. **Universe formation** — accepts eligible, active U.S.-listed common stocks and excludes unsupported instruments.
2. **Market regime** — estimates breadth, trend participation, and macro context before interpreting single-stock signals.
3. **Technical discovery** — measures stage, relative strength, momentum, volatility, liquidity, and breakout structure.
4. **Financial normalization** — maps provider-specific statements into comparable quarterly histories.
5. **Accounting checks** — tests cash conversion, accruals, leverage, dilution, and earnings quality.
6. **Valuation and risk** — evaluates observable multiples, downside structure, and reward-to-risk constraints.
7. **Evidence ledger** — stores provenance, timestamps, provider fallbacks, missing fields, and rejection reasons.
8. **Shadow validation** — records the original snapshot and evaluates outcomes only after their horizons mature.

## Trust boundaries

- Provider payloads are untrusted input.
- A successful HTTP response is not proof that the requested dataset is complete.
- Missing critical data is visible in the candidate posture and quality score.
- Provider fallbacks are recorded, not silently blended.
- Generated reports are research artifacts and never order instructions.
- Brokerage execution is outside the project boundary.

## Repository layout

| Path | Purpose |
|---|---|
| `galion/` | Research engine, provider adapters, scoring, reports, and validation |
| `tests/` | Unit and invariant tests |
| `docs/` | Architecture, methodology, provider, and operations documentation |
| `run_scan.py` | Live discovery entry point |
| `run_events.py` | Event-monitor entry point |
| `.github/workflows/ci.yml` | Secret-free public verification |

## Extension rules

A new provider adapter should expose an explicit contract, validate payload shape, attach observation time and source metadata, and fail with a typed provider error. A new score component should include unit tests, declare how missing values are handled, and avoid turning an ordinal score into a probability without calibration evidence.
