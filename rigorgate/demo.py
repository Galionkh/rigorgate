from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .discovery import build_research_queue
from .indicators import build_snapshot, combine_regime, market_breadth, market_regime


def synthetic_bars(
    *,
    count: int = 260,
    start: float = 100.0,
    daily_step: float = 0.20,
    volume: int = 2_000_000,
) -> list[dict[str, Any]]:
    """Generate deterministic, fictional bars for the zero-credential demo."""
    first = date(2025, 1, 2)
    rows = []
    for index in range(count):
        cycle = 1.8 * math.sin(index / 5.5) + 0.55 * math.sin(index / 2.3)
        close = start + daily_step * index + cycle
        rows.append(
            {
                "t": (first + timedelta(days=index)).isoformat(),
                "o": round(close - 0.15, 4),
                "h": round(close + 0.80, 4),
                "l": round(close - 0.75, 4),
                "c": round(close, 4),
                "v": volume + index * 1_000,
            }
        )
    return rows


def build_demo_report() -> dict[str, Any]:
    """Run the real deterministic technical engine on synthetic securities."""
    spy = build_snapshot(synthetic_bars(start=100, daily_step=0.18))
    qqq = build_snapshot(synthetic_bars(start=120, daily_step=0.24))
    iwm = build_snapshot(synthetic_bars(start=90, daily_step=0.10))
    stocks = {
        "DEMOA": build_snapshot(synthetic_bars(start=45, daily_step=0.22)),
        "DEMOB": build_snapshot(synthetic_bars(start=80, daily_step=0.08)),
        "DEMOC": build_snapshot(synthetic_bars(start=180, daily_step=-0.12)),
    }
    breadth = market_breadth(stocks)
    regime = combine_regime(market_regime(spy, qqq, iwm), breadth)
    queue = build_research_queue(stocks, spy, per_archetype=2, limit=3)
    return {
        "run_status": "DEMO COMPLETE",
        "source_posture": "synthetic-demo-only",
        "decision_status": "NOT A BUY RECOMMENDATION",
        "market_regime": regime,
        "market_breadth": breadth,
        "benchmarks": {"SPY": asdict(spy), "QQQ": asdict(qqq), "IWM": asdict(iwm)},
        "research_queue": queue,
        "disclaimer": (
            "All securities and prices in this demo are fictional. "
            "No order was created or transmitted."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run RigorGate with deterministic synthetic data"
    )
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args(argv)
    report = build_demo_report()
    rendered = json.dumps(report, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
