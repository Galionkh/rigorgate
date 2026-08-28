# Can you break RigorGate?

RigorGate is an audit-first equity research engine. The challenge is not to trust its score. The challenge is to find the fictional case, public evidence pattern, or engineering edge case that makes a decision gate behave incorrectly.

A useful break can be a false positive, a false rejection, hidden stale evidence, an unsafe fallback, a look-ahead leak, or a sector assumption that does not generalize.

## Choose your path

| Path | Best for | First useful contribution | Typical time |
|---|---|---|---|
| Researcher | Analysts, investors, domain experts | Submit a precise counterexample with decision-time evidence | 5–15 minutes |
| First PR | New open-source contributors | Take a bounded `good first issue` with named files and tests | 30–90 minutes |
| Core engineering | Data, quant, and Python developers | Harden providers, point-in-time data, validation, or evidence diffs | 2–6 hours |

### Researcher: no code required

1. Try all three cases in [Replay Lab](https://galionkh.github.io/rigorgate/).
2. Look for a posture, gate, or missing-evidence rule you disagree with.
3. [Open the challenge form](https://github.com/Galionkh/rigorgate/issues/new?template=counterexample.yml).
4. State what was observable at decision time, what the engine should do, and the strongest argument against your view.

A maintainer or developer can later convert a strong research case into a deterministic fixture. The issue itself is a valid contribution.

### First PR

Pick an open [`good first issue`](https://github.com/Galionkh/rigorgate/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22). Leave a short comment before starting, keep the change scoped to the acceptance criteria, and run:

```bash
make verify
```

The zero-install route is [GitHub Codespaces](https://codespaces.new/Galionkh/rigorgate?quickstart=1).

### Core engineering

Browse the [`help wanted`](https://github.com/Galionkh/rigorgate/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22) queue. The highest-value work protects observation time, source provenance, missing evidence, provider failure behavior, and reproducible validation.

Open an issue before changing a core contract or data model.

## What counts as a valid break?

A strong challenge is:

- reproducible from fictional or legally redistributable evidence;
- explicit about the decision timestamp and what remained unknown;
- tied to one gate, fallback, provider contract, or validation rule;
- capable of becoming a deterministic regression test;
- honest about the strongest red-team objection.

It must not include credentials, paid-provider payloads, personal holdings, target prices, guaranteed-return claims, or order execution.

## The standard for fixing a break

A fix is complete when the failure becomes inspectable, a regression test protects the intended behavior, missing evidence remains visible, and `make verify` passes. A higher score is not proof of a better decision.

Start with [CONTRIBUTOR_START.md](CONTRIBUTOR_START.md), then review [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.
