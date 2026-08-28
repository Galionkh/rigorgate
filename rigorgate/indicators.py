from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TechnicalSnapshot:
    close: float
    avg_dollar_volume_20d: float
    sma20: float
    sma50: float
    sma150: float
    sma200: float
    sma200_slope_20d: float
    rsi14: float
    atr14_pct: float
    return_1d: float
    return_21d: float
    return_63d: float
    return_126d: float
    distance_from_52w_high: float
    volume_ratio_20d: float
    gap_pct: float
    stage: int
    stage_name: str
    stage_confidence: float
    breakout_level_63d: float
    breakout_distance_pct: float
    invalidation_reference: float
    technical_score: float


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        raise ValueError("previous price must be positive")
    return current / previous - 1.0


def rsi(closes: Sequence[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise ValueError("insufficient closes for RSI")
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    window = changes[-period:]
    gains = sum(max(change, 0.0) for change in window) / period
    losses = sum(max(-change, 0.0) for change in window) / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def atr_percent(bars: Sequence[dict], period: int = 14) -> float:
    if len(bars) < period + 1:
        raise ValueError("insufficient bars for ATR")
    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        high = float(bars[index]["h"])
        low = float(bars[index]["l"])
        prior_close = float(bars[index - 1]["c"])
        true_ranges.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    close = float(bars[-1]["c"])
    return mean(true_ranges[-period:]) / close


def _bounded(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def build_snapshot(bars: Sequence[dict]) -> TechnicalSnapshot:
    if len(bars) < 200:
        raise ValueError("at least 200 adjusted daily bars are required")
    ordered = sorted(bars, key=lambda bar: str(bar["t"]))
    closes = [float(bar["c"]) for bar in ordered]
    volumes = [float(bar["v"]) for bar in ordered]
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError("prices must be finite and positive")
    close = closes[-1]
    avg_dollar_volume = mean(
        [closes[index] * volumes[index] for index in range(len(closes) - 20, len(closes))]
    )
    sma20 = mean(closes[-20:])
    sma50 = mean(closes[-50:])
    sma150 = mean(closes[-150:])
    sma200 = mean(closes[-200:])
    prior_sma200 = mean(closes[-220:-20]) if len(closes) >= 220 else sma200
    sma200_slope = pct_change(sma200, prior_sma200) if prior_sma200 > 0 else 0.0
    rsi14 = rsi(closes)
    atr14 = atr_percent(ordered)
    ret1 = pct_change(close, closes[-2])
    ret21 = pct_change(close, closes[-22])
    ret63 = pct_change(close, closes[-64])
    ret126 = pct_change(close, closes[-127])
    high52 = max(float(bar["h"]) for bar in ordered[-252:])
    distance_high = close / high52 - 1.0
    volume_ratio = volumes[-1] / mean(volumes[-20:]) if mean(volumes[-20:]) else 0.0
    latest_open = float(ordered[-1]["o"])
    gap = latest_open / closes[-2] - 1.0
    breakout_level = max(float(bar["h"]) for bar in ordered[-64:-1])
    breakout_distance = close / breakout_level - 1.0
    swing_low = min(float(bar["l"]) for bar in ordered[-20:]) * 0.98
    atr_stop = close * (1.0 - 2.0 * atr14)
    invalidation_reference = min(close * 0.995, max(swing_low, atr_stop))

    stage2_checks = (
        close > sma50,
        sma50 > sma150,
        sma150 > sma200,
        sma200_slope > 0,
    )
    stage4_checks = (
        close < sma50,
        sma50 < sma150,
        sma150 < sma200,
        sma200_slope < 0,
    )
    if all(stage2_checks):
        stage, stage_name, confidence = 2, "confirmed_uptrend", 100.0
    elif sum(stage2_checks) >= 3 and close > sma200:
        stage, stage_name, confidence = 2, "early_uptrend", 75.0
    elif all(stage4_checks):
        stage, stage_name, confidence = 4, "confirmed_downtrend", 100.0
    elif sum(stage4_checks) >= 3:
        stage, stage_name, confidence = 4, "early_downtrend", 75.0
    elif close < sma50 and close > sma200:
        stage, stage_name, confidence = 3, "distribution", 65.0
    else:
        stage, stage_name, confidence = 1, "base_building", 60.0

    score = 0.0
    score += 18 if close > sma200 else 0
    score += 14 if sma50 > sma200 else 0
    score += 4 if stage == 2 else 0
    score += 12 if close > sma50 else 0
    score += 8 if close > sma20 else 0
    score += _bounded((ret63 + 0.10) / 0.35 * 18, 0, 18)
    score += _bounded((ret126 + 0.15) / 0.60 * 12, 0, 12)
    score += 8 if 45 <= rsi14 <= 70 else (4 if 35 <= rsi14 < 45 else 0)
    score += 5 if -0.18 <= distance_high <= -0.02 else (2 if distance_high > -0.30 else 0)
    score += 5 if 0.8 <= volume_ratio <= 2.5 else 2

    return TechnicalSnapshot(
        close=round(close, 4),
        avg_dollar_volume_20d=round(avg_dollar_volume, 2),
        sma20=round(sma20, 4),
        sma50=round(sma50, 4),
        sma150=round(sma150, 4),
        sma200=round(sma200, 4),
        sma200_slope_20d=round(sma200_slope, 5),
        rsi14=round(rsi14, 2),
        atr14_pct=round(atr14, 5),
        return_1d=round(ret1, 5),
        return_21d=round(ret21, 5),
        return_63d=round(ret63, 5),
        return_126d=round(ret126, 5),
        distance_from_52w_high=round(distance_high, 5),
        volume_ratio_20d=round(volume_ratio, 3),
        gap_pct=round(gap, 5),
        stage=stage,
        stage_name=stage_name,
        stage_confidence=round(confidence, 2),
        breakout_level_63d=round(breakout_level, 4),
        breakout_distance_pct=round(breakout_distance, 5),
        invalidation_reference=round(invalidation_reference, 4),
        technical_score=round(_bounded(score), 2),
    )


def market_regime(spy: TechnicalSnapshot, qqq: TechnicalSnapshot, iwm: TechnicalSnapshot) -> str:
    trend_votes = sum(
        snapshot.close > snapshot.sma50 and snapshot.sma50 > snapshot.sma200
        for snapshot in (spy, qqq, iwm)
    )
    if trend_votes == 3:
        return "supportive"
    if trend_votes >= 1:
        return "mixed"
    return "risk-off"


def market_breadth(snapshots: dict[str, TechnicalSnapshot]) -> dict[str, float | int | str]:
    """Measure participation so index strength cannot hide a weak underlying market."""
    total = len(snapshots)
    if total == 0:
        raise ValueError("market breadth requires at least one stock")
    above_50 = sum(item.close > item.sma50 for item in snapshots.values())
    above_200 = sum(item.close > item.sma200 for item in snapshots.values())
    stage2 = sum(item.stage == 2 for item in snapshots.values())
    stage4 = sum(item.stage == 4 for item in snapshots.values())
    pct_50 = above_50 / total * 100.0
    pct_200 = above_200 / total * 100.0
    pct_stage2 = stage2 / total * 100.0
    pct_stage4 = stage4 / total * 100.0
    if pct_50 >= 55 and pct_stage2 >= 20 and pct_stage4 <= 20:
        posture = "broad_support"
    elif pct_50 < 35 or pct_stage4 >= 40:
        posture = "weak_participation"
    else:
        posture = "mixed_participation"
    return {
        "stocks_evaluated": total,
        "above_sma50_pct": round(pct_50, 2),
        "above_sma200_pct": round(pct_200, 2),
        "stage2_pct": round(pct_stage2, 2),
        "stage4_pct": round(pct_stage4, 2),
        "posture": posture,
    }


def combine_regime(index_regime: str, breadth: dict[str, float | int | str]) -> str:
    posture = breadth.get("posture")
    if index_regime == "supportive" and posture == "broad_support":
        return "supportive"
    if index_regime == "risk-off" or posture == "weak_participation":
        return "risk-off"
    return "mixed"

