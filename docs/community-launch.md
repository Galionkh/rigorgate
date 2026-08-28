# Community launch package

This package turns the public release into a contributor challenge. The product identity remains **an audit-first equity research engine**. **Can you break RigorGate?** is the campaign hook.

## One destination

Send every launch audience to Replay Lab first:

`https://galionkh.github.io/rigorgate/`

The intended path is:

`Try a blind decision → inspect the audit trail → challenge a gate → open an issue or first PR`

Do not optimize the launch around stars alone. Track Replay Lab visits, completed decisions, counterexample issues, first-time issue comments, and outside pull requests.

## Core launch copy

> Can you break RigorGate?
>
> RigorGate is an open-source, audit-first equity research engine. We are not asking you to trust another stock score. We are asking you to find the fictional case, evidence pattern, or engineering edge case that breaks a decision gate.
>
> Try three blind decisions in Replay Lab. Then submit a no-code counterexample, take a bounded first issue, or harden the point-in-time data and validation layers.

## GitHub release

### Title

`RigorGate v0.2.0 — Don't trust the score. Break the gate.`

### Body

RigorGate now has a public contributor challenge built around failure discovery, not performance marketing.

What is ready:

- a deterministic Replay Lab with three blind decisions;
- revealed gates, red-team objections, and downloadable Evidence Passports;
- a no-code path for researchers to submit counterexamples;
- bounded `good first issue` tasks for first pull requests;
- deeper point-in-time, provider, and validation quests;
- 46 deterministic tests and zero required credentials for the public demo.

Start in Replay Lab, make a decision before seeing the engine posture, and tell us where the evidence model fails.

This is research software, not investment advice. All Replay Lab securities and prices are fictional, and no order is created.

## Hacker News style

### Title

`Show HN: RigorGate – an audit-first equity research engine you are invited to break`

### Text

I built RigorGate to explore a different question from most stock screeners: can a research engine make its missing evidence and rejection logic as inspectable as its scores?

The public demo is deterministic, uses fictional securities, needs no API keys, and cannot place orders. Replay Lab gives you three cases while hiding the engine posture. After you choose Research, Wait, or Reject, it reveals the gates, missing evidence, red-team case, and a machine-readable Evidence Passport.

I would value counterexamples more than compliments. Non-coders can submit a research case; new contributors can take a bounded first issue; experienced contributors can work on point-in-time schemas, provider contracts, and walk-forward validation.

Replay Lab: https://galionkh.github.io/rigorgate/

Repository: https://github.com/Galionkh/rigorgate

## Short social post

Can you break RigorGate?

I built an open-source equity research engine that exposes its failed gates, missing evidence, and strongest counterargument.

Your job is not to trust the score. Your job is to find the case that breaks it.

No API keys. Fictional cases. No trading or order execution.

Try the blind Replay Lab, then submit a no-code counterexample or take a first issue.

## Professional network post

Most stock research tools are designed to show what passed. RigorGate is designed to preserve why a candidate failed, what evidence was missing, and what the strongest argument against the decision was.

The project is now open for a different kind of contribution challenge: **Can you break RigorGate?**

Researchers can submit a counterexample without writing code. First-time open-source contributors can take a bounded issue. Data and quant developers can work on point-in-time schemas, provider contracts, evidence diffs, and validation.

The public Replay Lab uses deterministic fictional data, requires no credentials, and cannot create an order. The goal is not to market a score. It is to make the research process harder to fool.

## Launch sequence

1. Publish the GitHub release and verify every link from a signed-out browser.
2. Publish one technical launch post and stay available for replies.
3. Answer every serious question with evidence, scope, and a direct issue link.
4. Publish the short social post only after the first discussion has useful context.
5. Highlight the first outside counterexample or pull request, with contributor permission.

Do not publish the same copy everywhere at once. Adapt the opening to the audience while keeping the challenge, safety boundary, and destination consistent.

## Maintainer response standard

For every new contributor:

- confirm whether the case is reproducible;
- reduce the work to the smallest mergeable next step;
- name the expected file or test when code is needed;
- avoid expanding a first contribution into an architectural rewrite;
- explain rejection with a technical reason and a possible alternative;
- credit useful research cases even when a maintainer writes the fixture.

## First two-week scorecard

| Signal | Healthy early target |
|---|---:|
| Counterexample submissions | 3 |
| First-time issue comments | 5 |
| Outside pull requests opened | 2 |
| Outside pull requests merged | 1 |
| Serious questions answered | 100% |

Targets are directional, not performance claims. The strongest launch outcome is a reproducible failure that improves a gate.
