from __future__ import annotations

import math
from typing import Any


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _linear(value: float | None, bad: float, good: float, points: float) -> float:
    if value is None:
        return 0.0
    if good == bad:
        return points if value >= good else 0.0
    return clamp((value - bad) / (good - bad), 0.0, 1.0) * points


def fundamental_score(overview: dict[str, Any]) -> float:
    margin = number(overview.get("ProfitMargin"))
    operating_margin = number(overview.get("OperatingMarginTTM"))
    roe = number(overview.get("ReturnOnEquityTTM"))
    revenue_growth = number(overview.get("QuarterlyRevenueGrowthYOY"))
    earnings_growth = number(overview.get("QuarterlyEarningsGrowthYOY"))
    score = 0.0
    score += _linear(margin, -0.05, 0.20, 22)
    score += _linear(operating_margin, -0.05, 0.20, 20)
    score += _linear(roe, 0.0, 0.25, 20)
    score += _linear(revenue_growth, -0.05, 0.20, 20)
    score += _linear(earnings_growth, -0.15, 0.25, 18)
    return round(clamp(score), 2)


def valuation_score(overview: dict[str, Any]) -> float:
    forward_pe = number(overview.get("ForwardPE"))
    trailing_pe = number(overview.get("TrailingPE"))
    peg = number(overview.get("PEGRatio"))
    ev_ebitda = number(overview.get("EVToEBITDA"))
    price_sales = number(overview.get("PriceToSalesRatioTTM"))
    price_book = number(overview.get("PriceToBookRatio"))
    points = 0.0
    available_weight = 0.0

    def add(value: float | None, weight: float, good: float, fair: float) -> None:
        nonlocal points, available_weight
        if value is None:
            return
        available_weight += weight
        if 0 < value <= good:
            points += weight
        elif 0 < value <= fair:
            points += weight * 0.55
        elif value > 0:
            points += weight * 0.15

    if forward_pe is not None:
        add(forward_pe, 30.0, 18.0, 28.0)
    else:
        add(trailing_pe, 25.0, 20.0, 32.0)
    add(peg, 25.0, 1.5, 2.5)
    add(ev_ebitda, 25.0, 12.0, 20.0)
    add(price_sales, 20.0, 3.0, 7.0)
    add(price_book, 15.0, 3.0, 7.0)
    if available_weight == 0:
        return 50.0
    raw = points / available_weight * 100.0
    confidence = min(1.0, available_weight / 50.0)
    return round(clamp(50.0 + (raw - 50.0) * confidence), 2)


def revision_score(payload: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in payload.values():
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    normalized_rows = [{str(key).lower(): value for key, value in row.items()} for row in rows]
    deltas: list[float] = []
    evidence: list[dict[str, Any]] = []
    for row in normalized_rows[:6]:
        current_key = next(
            (key for key in row if "epsestimateaverage" in key and "ago" not in key), None
        )
        prior_key = next(
            (key for key in row if "epsestimateaverage30daysago" in key), None
        ) or next((key for key in row if "epsestimateaverage60daysago" in key), None)
        current = number(row.get(current_key)) if current_key else None
        prior = number(row.get(prior_key)) if prior_key else None
        if current is not None and prior not in {None, 0}:
            delta = current / prior - 1.0
            deltas.append(delta)
            evidence.append({"current": current, "prior": prior, "delta": round(delta, 5)})
    if not deltas:
        return 50.0, {"available": False, "reason": "revision fields not returned"}
    average = sum(deltas) / len(deltas)
    score = clamp(50.0 + average * 500.0)
    return round(score, 2), {"available": True, "average_revision": round(average, 5), "rows": evidence}


def market_cap(overview: dict[str, Any]) -> float | None:
    return number(overview.get("MarketCapitalization"))

