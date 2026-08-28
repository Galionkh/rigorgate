# Your first SignalForge contribution

The fastest way to understand SignalForge is to try to break a decision gate.

## Zero-install path

1. Open the repository in [GitHub Codespaces](https://codespaces.new/Galionkh/galion-signal-forge?quickstart=1).
2. Wait for `make verify` to finish.
3. The Replay Lab opens automatically on port 8080.
4. Choose a case, make a blind decision, and inspect the revealed audit trail.

No credentials, market-data subscription, or brokerage account are needed. Every replay is deterministic and fictional.

## Local path

```bash
git clone https://github.com/Galionkh/galion-signal-forge.git
cd galion-signal-forge
python -m pip install -e .
make lab
```

Open `http://localhost:8080`.

## Pick a live contributor quest

Want a concrete task instead of starting from a blank issue? Pick one of these open quests:

- **Break a gate — 30–60 min:** [Add a tempting replay case that must fail closed](https://github.com/Galionkh/galion-signal-forge/issues/1)
- **Improve the lab UX — newcomer friendly:** [Add keyboard shortcuts and visible focus states](https://github.com/Galionkh/galion-signal-forge/issues/2)
- **Test evidence freshness — newcomer friendly:** [Add a stale-evidence edge case](https://github.com/Galionkh/galion-signal-forge/issues/3)
- **Forge a provider — deeper engineering:** [Add deterministic provider contract fixtures](https://github.com/Galionkh/galion-signal-forge/issues/5)
- **Red-team a sector — research challenge:** [Add a sector-specific accounting trap](https://github.com/Galionkh/galion-signal-forge/issues/9)

If one is already claimed, browse all [open issues](https://github.com/Galionkh/galion-signal-forge/issues) and leave a short comment before you start.

## The counterexample challenge

A useful first pull request adds a case where a tempting signal must fail closed:

1. Add or modify a fictional case in `galion/replay_lab.py`.
2. Give it at least one explicit failed gate.
3. State the missing evidence and the strongest red-team objection.
4. Keep `not_a_buy_recommendation` true and `order_created` false.
5. Add a behavioral assertion in `tests/test_replay_lab.py`.
6. Run `make verify`.

The generated `lab/data/replay.json` is committed. `make verify` rebuilds it and fails if generation is not deterministic.

## What makes a strong contribution

- It exposes a false positive, data-quality weakness, or hidden assumption.
- It preserves observation time and avoids look-ahead data.
- It uses synthetic or legally redistributable fixtures.
- It makes uncertainty visible instead of replacing missing evidence with a score.
- It does not add order execution or imply guaranteed performance.

Start with the [good first issues](https://github.com/Galionkh/galion-signal-forge/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) or propose a compact counterexample of your own.
