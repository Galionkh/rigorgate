from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .demo import build_demo_report, synthetic_bars
from .indicators import build_snapshot


LAB_SCHEMA = "rigorgate-replay-lab/v1"
REPOSITORY_URL = "https://github.com/Galionkh/rigorgate"


def _candidate(
    *,
    symbol: str,
    title: str,
    archetype: str,
    start: float,
    daily_step: float,
    status: str,
    correct_action: str,
    thesis: str,
    red_team: str,
    missing_evidence: list[str],
    gates: list[dict[str, str]],
    evidence_quality: int,
) -> dict[str, Any]:
    bars = synthetic_bars(start=start, daily_step=daily_step)
    snapshot = asdict(build_snapshot(bars))
    prices = [row["c"] for row in bars[-72:]]
    return {
        "symbol": symbol,
        "title": title,
        "archetype": archetype,
        "status": status,
        "correct_action": correct_action,
        "thesis": thesis,
        "red_team": red_team,
        "missing_evidence": missing_evidence,
        "technical_score": snapshot["technical_score"],
        "evidence_quality": evidence_quality,
        "stage": snapshot["stage"],
        "stage_name": snapshot["stage_name"],
        "close": snapshot["close"],
        "rsi14": snapshot["rsi14"],
        "atr14_pct": snapshot["atr14_pct"],
        "return_63d": snapshot["return_63d"],
        "breakout_distance_pct": snapshot["breakout_distance_pct"],
        "invalidation_reference": snapshot["invalidation_reference"],
        "prices": prices,
        "gates": gates,
        "passport": {
            "source_posture": "synthetic-demo-only",
            "observation_id": f"replay-v1-{symbol.lower()}",
            "evidence_quality": evidence_quality,
            "missing_evidence": missing_evidence,
            "decision_status": status,
            "not_a_buy_recommendation": True,
            "order_created": False,
        },
    }


def build_replay_lab_data() -> dict[str, Any]:
    """Build the deterministic, fictional decision challenge used by the public lab."""
    demo = build_demo_report()
    cases = [
        _candidate(
            symbol="DEMOA",
            title="The clean breakout",
            archetype="Momentum / breakout",
            start=45,
            daily_step=0.22,
            status="RESEARCH CANDIDATE",
            correct_action="research",
            thesis="Trend, participation, and invalidation structure align well enough for deeper underwriting.",
            red_team="The chart is strong, but no filing, valuation anchor, or catalyst has been verified in this synthetic replay.",
            missing_evidence=["Primary filings", "Current valuation", "Catalyst evidence"],
            evidence_quality=74,
            gates=[
                {"name": "Instrument and liquidity", "state": "pass", "detail": "Fictional common stock with adequate demo liquidity."},
                {"name": "Trend structure", "state": "pass", "detail": "Confirmed uptrend with positive relative structure."},
                {"name": "Entry timing", "state": "pass", "detail": "Close remains near the breakout reference."},
                {"name": "Primary-source underwriting", "state": "warn", "detail": "Required before any real-world qualification."},
            ],
        ),
        _candidate(
            symbol="DEMOB",
            title="The patient pullback",
            archetype="Pullback / watchlist",
            start=80,
            daily_step=0.08,
            status="WAIT FOR PROOF",
            correct_action="wait",
            thesis="The longer trend is constructive, but the setup needs renewed demand before it earns deeper research time.",
            red_team="A weak rebound can become a distribution phase. Momentum alone does not confirm that sellers are finished.",
            missing_evidence=["Demand confirmation", "Relative-strength turn", "Fundamental refresh"],
            evidence_quality=67,
            gates=[
                {"name": "Instrument and liquidity", "state": "pass", "detail": "Demo liquidity clears the screen."},
                {"name": "Long-term trend", "state": "pass", "detail": "Price remains above the long-term reference."},
                {"name": "Demand confirmation", "state": "warn", "detail": "No decisive volume expansion is present."},
                {"name": "Why now", "state": "fail", "detail": "There is no observable trigger yet."},
            ],
        ),
        _candidate(
            symbol="DEMOC",
            title="The seductive trap",
            archetype="Reversal / false positive",
            start=180,
            daily_step=-0.12,
            status="REJECTED",
            correct_action="reject",
            thesis="A low headline price and occasional bounce cannot repair a deteriorating long-term structure.",
            red_team="Trying to call the bottom would override the stage gate and replace evidence with hope.",
            missing_evidence=["Trend repair", "Stable invalidation", "Verified business inflection"],
            evidence_quality=61,
            gates=[
                {"name": "Instrument and liquidity", "state": "pass", "detail": "The security itself is screenable."},
                {"name": "Stage eligibility", "state": "fail", "detail": "The long-term structure is a confirmed downtrend."},
                {"name": "Risk definition", "state": "fail", "detail": "The setup lacks a stable invalidation reference."},
                {"name": "Variant evidence", "state": "warn", "detail": "No verified inflection offsets the technical damage."},
            ],
        ),
    ]
    return {
        "schema": LAB_SCHEMA,
        "build_id": "rigorgate-replay-v1",
        "run_status": demo["run_status"],
        "source_posture": "synthetic-demo-only",
        "decision_status": "NOT A BUY RECOMMENDATION",
        "market_regime": demo["market_regime"],
        "universe_funnel": [
            {"label": "Synthetic universe", "count": 240},
            {"label": "Liquidity and history", "count": 61},
            {"label": "Technical discovery", "count": 12},
            {"label": "Evidence queue", "count": 3},
        ],
        "cases": cases,
        "contributor_quests": [
            {
                "track": "RESEARCHER",
                "title": "Submit a counterexample",
                "difficulty": "5–15 min",
                "description": "Describe a case that could fool a gate. No code is required; precise decision-time evidence is the contribution.",
                "label": "no code",
                "href": f"{REPOSITORY_URL}/issues/new?template=counterexample.yml&title=%5BChallenge%5D%3A+find+a+false+positive",
            },
            {
                "track": "FIRST PR",
                "title": "Ship a bounded fix",
                "difficulty": "30–90 min",
                "description": "Pick a scoped issue with named files, acceptance checks, and a deterministic verification command.",
                "label": "good first issue",
                "href": f"{REPOSITORY_URL}/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22",
            },
            {
                "track": "CORE ENGINEERING",
                "title": "Harden the evidence layer",
                "difficulty": "2–6 hours",
                "description": "Work on point-in-time schemas, provider contracts, validation, exports, or evidence diffs.",
                "label": "help wanted",
                "href": f"{REPOSITORY_URL}/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22",
            },
        ],
        "repository_url": REPOSITORY_URL,
        "disclaimer": (
            "All securities, prices, evidence, and decisions in Replay Lab are fictional. "
            "Scores are rankings, not probabilities. No order was created or transmitted."
        ),
    }


def build_lab(output_dir: Path) -> Path:
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "replay.json"
    rendered = json.dumps(build_replay_lab_data(), indent=2, sort_keys=True)
    target.write_text(rendered + "\n", encoding="utf-8")
    return target


def serve_lab(directory: Path, port: int) -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"RigorGate Replay Lab: http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or serve RigorGate Replay Lab")
    parser.add_argument("--directory", default="lab", help="Static lab directory")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args(argv)
    directory = Path(args.directory).resolve()
    target = build_lab(directory)
    print(f"Built deterministic replay data: {target}")
    if args.serve or not args.build_only:
        serve_lab(directory, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
