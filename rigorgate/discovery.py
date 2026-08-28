from __future__ import annotations

from dataclasses import asdict
from .indicators import TechnicalSnapshot


ARCHETYPES = ("momentum", "pullback", "reversal", "breakout", "event_shock")
MIN_ARCHETYPE_SCORE = {
    "momentum": 50.0,
    "pullback": 50.0,
    "reversal": 50.0,
    "breakout": 50.0,
    "event_shock": 20.0,
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def archetype_scores(snapshot: TechnicalSnapshot, spy: TechnicalSnapshot) -> dict[str, float]:
    relative_63d = snapshot.return_63d - spy.return_63d
    relative = clamp(50.0 + relative_63d * 250.0)
    distance_sma50 = snapshot.close / snapshot.sma50 - 1.0

    momentum = snapshot.technical_score * 0.65 + relative * 0.25
    momentum += 10.0 if snapshot.stage == 2 else (-20.0 if snapshot.stage == 4 else 0.0)
    pullback = 0.0
    if snapshot.stage == 2 and snapshot.sma50 > snapshot.sma200 and snapshot.close > snapshot.sma200:
        pullback = 45.0
        pullback += clamp((0.10 - abs(distance_sma50)) / 0.10 * 25.0, 0.0, 25.0)
        pullback += 20.0 if 38 <= snapshot.rsi14 <= 58 else 5.0
        pullback += 10.0 if -0.25 <= snapshot.distance_from_52w_high <= -0.04 else 0.0

    reversal = 20.0
    reversal += 25.0 if snapshot.return_21d > 0 else 0.0
    reversal += 20.0 if snapshot.return_126d < 0 else 0.0
    reversal += 20.0 if snapshot.close > snapshot.sma20 else 0.0
    reversal += 15.0 if 35 <= snapshot.rsi14 <= 62 else 0.0
    reversal += 10.0 if snapshot.stage == 1 else 0.0

    breakout = 20.0
    breakout += 30.0 if -0.03 <= snapshot.breakout_distance_pct <= 0.05 else 0.0
    breakout += clamp((snapshot.volume_ratio_20d - 0.8) / 2.2 * 25.0, 0.0, 25.0)
    breakout += 15.0 if snapshot.stage == 2 and snapshot.close > snapshot.sma20 > snapshot.sma50 else 0.0
    breakout += 10.0 if relative >= 60 else 0.0

    event_shock = 0.0
    event_shock += clamp(abs(snapshot.return_1d) / 0.20 * 45.0, 0.0, 45.0)
    event_shock += clamp(abs(snapshot.gap_pct) / 0.15 * 30.0, 0.0, 30.0)
    event_shock += clamp((snapshot.volume_ratio_20d - 1.5) / 5.0 * 25.0, 0.0, 25.0)

    return {
        "momentum": round(clamp(momentum), 2),
        "pullback": round(clamp(pullback), 2),
        "reversal": round(clamp(reversal), 2),
        "breakout": round(clamp(breakout), 2),
        "event_shock": round(clamp(event_shock), 2),
    }


def build_research_queue(
    snapshots: dict[str, TechnicalSnapshot],
    spy: TechnicalSnapshot,
    *,
    per_archetype: int = 6,
    limit: int = 30,
) -> list[dict]:
    rows = []
    for symbol, snapshot in snapshots.items():
        scores = archetype_scores(snapshot, spy)
        rows.append(
            {
                "symbol": symbol,
                "archetype_scores": scores,
                "discovery_rank": round(max(scores.values()), 2),
                "primary_archetype": max(scores, key=scores.get),
                "technical": asdict(snapshot),
            }
        )

    selected: dict[str, dict] = {}
    for archetype in ARCHETYPES:
        ranked = sorted(rows, key=lambda row: row["archetype_scores"][archetype], reverse=True)
        qualified = [
            row for row in ranked if row["archetype_scores"][archetype] >= MIN_ARCHETYPE_SCORE[archetype]
        ]
        for row in qualified[:per_archetype]:
            selected[row["symbol"]] = row
    return sorted(selected.values(), key=lambda row: row["discovery_rank"], reverse=True)[:limit]


def diversified_shortlist(queue: list[dict], *, per_archetype: int = 2, limit: int = 10) -> list[dict]:
    """Reserve research capacity for each archetype before filling by overall rank."""
    selected: dict[str, dict] = {}
    for archetype in ARCHETYPES:
        ranked = sorted(
            queue,
            key=lambda row: row.get("archetype_scores", {}).get(archetype, 0.0),
            reverse=True,
        )
        qualified = [
            row
            for row in ranked
            if row.get("archetype_scores", {}).get(archetype, 0.0) >= MIN_ARCHETYPE_SCORE[archetype]
        ]
        for row in qualified[:per_archetype]:
            if len(selected) >= limit:
                break
            selected[row["symbol"]] = row
    for row in sorted(queue, key=lambda item: item["discovery_rank"], reverse=True):
        if len(selected) >= limit:
            break
        selected[row["symbol"]] = row
    return list(selected.values())


def event_risk_flags(snapshot: TechnicalSnapshot) -> list[str]:
    flags = []
    if abs(snapshot.return_1d) >= 0.15:
        flags.append("extreme_one_day_move")
    if abs(snapshot.gap_pct) >= 0.10:
        flags.append("large_opening_gap")
    if snapshot.volume_ratio_20d >= 4.0:
        flags.append("extreme_relative_volume")
    return flags
