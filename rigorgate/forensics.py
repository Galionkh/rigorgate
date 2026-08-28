from __future__ import annotations

import math
from typing import Any


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _value(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _number(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _sum(rows: list[dict[str, Any]], keys: tuple[str, ...], count: int = 4) -> float | None:
    if len(rows) < count:
        return None
    values = [_value(row, *keys) for row in rows[:count]]
    return sum(values) if all(value is not None for value in values) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def _signal(name: str, passed: bool | None, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def analyze_statements(statements: dict[str, Any]) -> dict[str, Any]:
    """Run conservative, explainable accounting checks over reported quarterly data.

    This is a Piotroski-style screening layer, not the official F-Score. Missing
    fields stay unknown instead of being silently treated as passes or failures.
    """
    income = statements.get("income") or []
    balance = statements.get("balance") or []
    cashflow = statements.get("cashflow") or []
    if not all(isinstance(rows, list) and rows for rows in (income, balance, cashflow)):
        return {
            "available": False,
            "label": "Piotroski-style screen",
            "reason": "complete income, balance and cash-flow statements were not available",
            "score": None,
            "quality_score": None,
            "penalty": 0.0,
            "flags": ["forensic_data_unavailable"],
            "signals": [],
        }

    current_income = income[:4]
    current_cash = cashflow[:4]
    latest_balance = balance[0]
    prior_balance = balance[4] if len(balance) >= 5 else None

    net_income = _sum(current_income, ("netIncome",))
    operating_cash = _sum(
        current_cash,
        ("operatingCashFlow", "netCashProvidedByOperatingActivities"),
    )
    assets = _value(latest_balance, "totalAssets")
    prior_assets = _value(prior_balance or {}, "totalAssets")
    debt = _value(latest_balance, "totalDebt", "longTermDebt")
    prior_debt = _value(prior_balance or {}, "totalDebt", "longTermDebt")
    current_assets = _value(latest_balance, "totalCurrentAssets")
    current_liabilities = _value(latest_balance, "totalCurrentLiabilities")
    prior_current_assets = _value(prior_balance or {}, "totalCurrentAssets")
    prior_current_liabilities = _value(prior_balance or {}, "totalCurrentLiabilities")
    shares = _value(income[0], "weightedAverageShsOut", "weightedAverageShsOutDil")
    prior_shares = _value(income[4], "weightedAverageShsOut", "weightedAverageShsOutDil") if len(income) >= 5 else None
    free_cash_flow = _sum(current_cash, ("freeCashFlow",))

    # Free normalized sources provide at least five quarters. Trend comparisons
    # therefore use the latest quarter versus the year-ago quarter; TTM
    # cash-quality tests still use the latest four quarters.
    latest_income = income[0]
    year_ago_income = income[4] if len(income) >= 5 else None
    latest_net_income = _value(latest_income, "netIncome")
    prior_net_income = _value(year_ago_income or {}, "netIncome")
    latest_revenue = _value(latest_income, "revenue")
    prior_revenue = _value(year_ago_income or {}, "revenue")
    latest_gross_profit = _value(latest_income, "grossProfit")
    prior_gross_profit = _value(year_ago_income or {}, "grossProfit")
    roa = _ratio(latest_net_income, assets)
    prior_roa = _ratio(prior_net_income, prior_assets)
    leverage = _ratio(debt, assets)
    prior_leverage = _ratio(prior_debt, prior_assets)
    current_ratio = _ratio(current_assets, current_liabilities)
    prior_current_ratio = _ratio(prior_current_assets, prior_current_liabilities)
    gross_margin = _ratio(latest_gross_profit, latest_revenue)
    prior_gross_margin = _ratio(prior_gross_profit, prior_revenue)
    asset_turnover = _ratio(latest_revenue, assets)
    prior_asset_turnover = _ratio(prior_revenue, prior_assets)
    accrual_ratio = _ratio(
        (net_income - operating_cash) if net_income is not None and operating_cash is not None else None,
        assets,
    )
    fcf_conversion = _ratio(free_cash_flow, net_income)
    dilution = _ratio(shares, prior_shares)
    dilution = dilution - 1.0 if dilution is not None else None

    comparisons = [
        _signal("positive_net_income", net_income > 0 if net_income is not None else None, "TTM net income is positive"),
        _signal("positive_operating_cash_flow", operating_cash > 0 if operating_cash is not None else None, "TTM operating cash flow is positive"),
        _signal("cash_exceeds_earnings", operating_cash > net_income if operating_cash is not None and net_income is not None else None, "operating cash flow exceeds net income"),
        _signal("improving_roa", roa > prior_roa if roa is not None and prior_roa is not None else None, "return on assets improved year over year"),
        _signal("lower_leverage", leverage < prior_leverage if leverage is not None and prior_leverage is not None else None, "debt-to-assets declined year over year"),
        _signal("higher_current_ratio", current_ratio > prior_current_ratio if current_ratio is not None and prior_current_ratio is not None else None, "current ratio improved year over year"),
        _signal("no_material_dilution", dilution <= 0.02 if dilution is not None else None, "share count growth is no more than 2%"),
        _signal("higher_gross_margin", gross_margin > prior_gross_margin if gross_margin is not None and prior_gross_margin is not None else None, "gross margin improved year over year"),
        _signal("higher_asset_turnover", asset_turnover > prior_asset_turnover if asset_turnover is not None and prior_asset_turnover is not None else None, "asset turnover improved year over year"),
    ]
    known = [item for item in comparisons if item["passed"] is not None]
    passes = sum(item["passed"] is True for item in known)
    screen_score = round(passes / len(known) * 9.0, 2) if known else None

    flags: list[str] = []
    penalty = 0.0
    if accrual_ratio is not None and accrual_ratio > 0.10:
        flags.append("high_accruals")
        penalty += 8.0
    if dilution is not None and dilution > 0.10:
        flags.append("material_share_dilution")
        penalty += 12.0
    if operating_cash is not None and operating_cash < 0 and net_income is not None and net_income > 0:
        flags.append("earnings_not_backed_by_cash")
        penalty += 10.0
    if leverage is not None and leverage > 0.80:
        flags.append("very_high_debt_to_assets")
        penalty += 10.0
    if current_ratio is not None and current_ratio < 0.75:
        flags.append("weak_short_term_liquidity")
        penalty += 8.0

    quality = 50.0
    if accrual_ratio is not None:
        quality += max(-25.0, min(20.0, -accrual_ratio * 180.0))
    if fcf_conversion is not None and net_income and net_income > 0:
        quality += max(-15.0, min(15.0, (fcf_conversion - 0.75) * 20.0))
    if screen_score is not None:
        quality += (screen_score - 4.5) * 3.0
    quality = round(max(0.0, min(100.0, quality)), 2)

    return {
        "available": True,
        "label": "Piotroski-style screen",
        "score": screen_score,
        "known_signals": len(known),
        "quality_score": quality,
        "penalty": round(min(penalty, 30.0), 2),
        "flags": flags,
        "metrics": {
            "accrual_ratio": round(accrual_ratio, 5) if accrual_ratio is not None else None,
            "fcf_to_net_income": round(fcf_conversion, 5) if fcf_conversion is not None else None,
            "debt_to_assets": round(leverage, 5) if leverage is not None else None,
            "current_ratio": round(current_ratio, 5) if current_ratio is not None else None,
            "share_count_yoy": round(dilution, 5) if dilution is not None else None,
        },
        "signals": comparisons,
        "limitations": "Uses reported quarterly fields available from the active free provider; unknown tests are excluded, not imputed.",
    }
