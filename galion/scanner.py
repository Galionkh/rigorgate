from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import JsonFundamentalCache
from .dashboard import render_dashboard
from .forensics import analyze_statements
from .http import ProviderError
from .discovery import build_research_queue, diversified_shortlist, event_risk_flags
from .indicators import (
    TechnicalSnapshot,
    build_snapshot,
    combine_regime,
    market_breadth,
    market_regime,
)
from .providers import (
    AlpacaProvider,
    AlphaVantageProvider,
    Credentials,
    FmpProvider,
    FredProvider,
    SecProvider,
    completed_market_data_cutoff,
    default_history_window,
)
from .scoring import fundamental_score, market_cap, revision_score, valuation_score
from .tracking import SignalLedger


INDEX_BENCHMARKS = ["SPY", "QQQ", "IWM"]
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financial": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
BENCHMARKS = INDEX_BENCHMARKS + sorted(set(SECTOR_ETFS.values()))
MIN_PRICE = 5.0
MIN_MARKET_CAP = 500_000_000.0
MIN_ADV20 = 20_000_000.0
RESEARCH_QUEUE_LIMIT = 30
DEEP_DATA_LIMIT = 10
MIN_DEEP_DATA_SUCCESSES = 3


def quote_spread_bps(snapshot: dict[str, Any]) -> float | None:
    quote = snapshot.get("latestQuote") or snapshot.get("latest_quote")
    if not isinstance(quote, dict):
        return None
    bid = quote.get("bp") if "bp" in quote else quote.get("bid_price")
    ask = quote.get("ap") if "ap" in quote else quote.get("ask_price")
    try:
        bid_value, ask_value = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    midpoint = (bid_value + ask_value) / 2
    if bid_value <= 0 or ask_value <= bid_value or midpoint <= 0:
        return None
    return round((ask_value - bid_value) / midpoint * 10000, 2)


def latest_session_date(bars: dict[str, list[dict[str, Any]]], symbol: str = "SPY") -> str | None:
    symbol_bars = bars.get(symbol) or []
    if not symbol_bars:
        return None
    return str(sorted(symbol_bars, key=lambda item: str(item["t"]))[-1]["t"])[:10]


def latest_filings(bundle: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    if bundle.get("latest_filings"):
        output = []
        for filing in bundle.get("latest_filings", [])[:limit]:
            output.append(
                {
                    "accessionNumber": filing.get("accessionNumber") or filing.get("accession_number"),
                    "filingDate": filing.get("filingDate") or filing.get("acceptedDate"),
                    "reportDate": filing.get("reportDate"),
                    "form": filing.get("formType") or filing.get("form"),
                    "primaryDocument": filing.get("finalLink") or filing.get("link"),
                    "filing_url": filing.get("finalLink") or filing.get("link"),
                }
            )
        return output
    recent = (bundle.get("submissions") or {}).get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    keys = ["accessionNumber", "filingDate", "reportDate", "form", "primaryDocument"]
    length = max((len(recent.get(key, [])) for key in keys), default=0)
    rows = []
    for index in range(min(length, limit)):
        row = {key: (recent.get(key, [None] * length) + [None] * length)[index] for key in keys}
        accession = str(row.get("accessionNumber") or "").replace("-", "")
        document = row.get("primaryDocument")
        if accession and document:
            cik_plain = str(int(bundle["cik"]))
            row["filing_url"] = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{accession}/{document}"
        rows.append(row)
    return rows


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def screen_risk_score(snapshot: TechnicalSnapshot, flags: list[str]) -> float:
    score = 82.0
    score -= clamp((snapshot.atr14_pct - 0.025) * 800.0, 0.0, 30.0)
    score -= 20.0 if snapshot.close < snapshot.sma200 else 0.0
    score -= 25.0 if flags else 0.0
    score -= 10.0 if snapshot.distance_from_52w_high > -0.01 else 0.0
    return round(clamp(score), 2)


def screen_catalyst_score(filings: list[dict[str, Any]], flags: list[str]) -> float:
    forms = {str(row.get("form") or "").upper() for row in filings}
    if flags:
        return 60.0
    if "8-K" in forms:
        return 58.0
    return 40.0


def screen_data_quality(
    overview: dict[str, Any],
    statements: dict[str, Any],
    filings: list[dict[str, Any]],
    revision_evidence: dict[str, Any],
) -> float:
    score = 30.0
    score += 15.0 if overview else 0.0
    score += 20.0 if all(statements.get(name) for name in ("income", "balance", "cashflow")) else 0.0
    score += 20.0 if filings else 0.0
    score += 15.0 if revision_evidence.get("available") else 0.0
    return round(clamp(score), 2)


def concise_provider_error(symbol: str, exc: Exception) -> str:
    message = " ".join(str(exc).split())
    return f"{symbol}: {message[:240]}"


def provider_quota_exhausted(exc: Exception) -> bool:
    """Recognize provider allowance errors so a free key is not retried wastefully."""
    message = " ".join(str(exc).lower().split())
    markers = (
        "rate limit",
        "call frequency",
        "daily limit",
        "api limit",
        "quota",
        "standard api rate limit",
        "premium endpoint",
        "budget exhausted",
    )
    return any(marker in message for marker in markers)


def reported_overview_from_bundle(
    bundle: dict[str, Any], latest_price: float | None = None
) -> dict[str, Any]:
    """Build reported/derivable fields from either SEC XBRL or FMP statements."""
    profile = bundle.get("profile") or {}
    statements = bundle.get("statements") or {}
    income = statements.get("income") or []
    if not isinstance(profile, dict) or not isinstance(income, list) or not income:
        raise ProviderError("reported statements cannot build a company overview")

    def value(row: dict[str, Any], key: str) -> float | None:
        try:
            parsed = float(row.get(key))
        except (TypeError, ValueError):
            return None
        return parsed

    def total(rows: list[dict[str, Any]], key: str, count: int = 4) -> float | None:
        values = [value(row, key) for row in rows[:count]]
        return sum(item for item in values if item is not None) if values and all(item is not None for item in values) else None

    latest = income[0]
    prior_year = income[4] if len(income) >= 5 else None
    revenue_ttm = total(income, "revenue")
    net_income_ttm = total(income, "netIncome")
    operating_income_ttm = total(income, "operatingIncome")
    cap = value(profile, "marketCap") or value(profile, "mktCap")
    shares_outstanding = value(profile, "sharesOutstanding")
    if cap is None and shares_outstanding is not None and latest_price is not None:
        cap = shares_outstanding * latest_price
    balance = statements.get("balance") or []
    equity = value(balance[0], "totalStockholdersEquity") if balance else None

    def ratio(numerator: float | None, denominator: float | None) -> float | None:
        return numerator / denominator if numerator is not None and denominator not in {None, 0} else None

    latest_revenue = value(latest, "revenue")
    latest_income = value(latest, "netIncome")
    prior_revenue = value(prior_year, "revenue") if prior_year else None
    prior_income = value(prior_year, "netIncome") if prior_year else None
    trailing_pe = ratio(cap, net_income_ttm) if net_income_ttm and net_income_ttm > 0 else None
    return {
        "Name": profile.get("companyName") or bundle.get("company"),
        "Exchange": profile.get("exchangeShortName") or profile.get("exchange"),
        "Sector": profile.get("sector"),
        "Industry": profile.get("industry"),
        "CIK": bundle.get("cik") or profile.get("cik"),
        "MarketCapitalization": cap,
        "ProfitMargin": ratio(net_income_ttm, revenue_ttm),
        "OperatingMarginTTM": ratio(operating_income_ttm, revenue_ttm),
        "ReturnOnEquityTTM": ratio(net_income_ttm, equity),
        "QuarterlyRevenueGrowthYOY": ratio(latest_revenue, prior_revenue) - 1.0 if ratio(latest_revenue, prior_revenue) is not None else None,
        "QuarterlyEarningsGrowthYOY": ratio(latest_income, prior_income) - 1.0 if ratio(latest_income, prior_income) is not None else None,
        "PriceToSalesRatioTTM": ratio(cap, revenue_ttm),
        "TrailingPE": trailing_pe,
        "PriceToBookRatio": ratio(cap, equity),
        "ReportedDataProvider": bundle.get("provider"),
    }


def fmp_overview_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible wrapper for tests and older integrations."""
    return reported_overview_from_bundle(bundle)


def sector_leadership(
    snapshots: dict[str, TechnicalSnapshot],
    spy: TechnicalSnapshot,
) -> dict[str, dict[str, Any]]:
    """Rank sector ETFs using absolute trend and 3-month strength versus SPY."""
    rows: list[tuple[str, float, TechnicalSnapshot]] = []
    for etf in sorted(set(SECTOR_ETFS.values())):
        snapshot = snapshots.get(etf)
        if snapshot is None:
            continue
        relative_63d = snapshot.return_63d - spy.return_63d
        score = 50.0 + relative_63d * 250.0
        score += 20.0 if snapshot.stage == 2 else (-20.0 if snapshot.stage == 4 else 0.0)
        score += 10.0 if snapshot.close > snapshot.sma50 else -10.0
        rows.append((etf, clamp(score), snapshot))
    ranked = sorted(rows, key=lambda row: row[1], reverse=True)
    total = len(ranked)
    return {
        etf: {
            "etf": etf,
            "rank": rank,
            "rank_out_of": total,
            "leadership_score": round(score, 2),
            "return_63d": snapshot.return_63d,
            "relative_to_spy_63d": round(snapshot.return_63d - spy.return_63d, 5),
            "stage": snapshot.stage,
            "posture": "leading" if rank <= max(3, total // 3) else ("lagging" if rank > total * 2 / 3 else "neutral"),
        }
        for rank, (etf, score, snapshot) in enumerate(ranked, start=1)
    }


def sector_etf_for_name(sector: Any) -> str | None:
    normalized = " ".join(str(sector or "").split()).casefold()
    for name, etf in SECTOR_ETFS.items():
        if name.casefold() == normalized:
            return etf
    return None


def long_eligibility(
    snapshot: TechnicalSnapshot,
    event_flags: list[str],
    forensic: dict[str, Any],
) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if snapshot.stage == 4:
        blockers.append("stage_4_downtrend_for_long")
    if event_flags:
        blockers.append("unresolved_event_gap_risk")
    if forensic.get("flags"):
        blockers.append("unresolved_forensic_accounting_flags")
    return not blockers, blockers


def compact_regulatory_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Keep auditable normalized evidence while excluding bulky SEC response bodies."""
    keys = (
        "provider",
        "cik",
        "company",
        "profile",
        "statements",
        "latest_filings",
        "filing_evidence_status",
        "filing_evidence_method",
        "submissions_url",
        "companyfacts_url",
        "source_urls",
        "statement_coverage",
        "provider_warning",
    )
    return {key: bundle.get(key) for key in keys if bundle.get(key) is not None}


def require_deep_data_coverage(
    attempt_count: int,
    success_count: int,
    warnings: list[str],
    *,
    minimum_successes: int = MIN_DEEP_DATA_SUCCESSES,
) -> None:
    if attempt_count and success_count == 0:
        summary = "; ".join(warnings[:3])
        raise ProviderError(
            "Mandatory deep-data retrieval failed for every shortlisted symbol"
            + (f": {summary}" if summary else "")
        )
    required = min(minimum_successes, attempt_count)
    if attempt_count and success_count < required:
        raise ProviderError(
            f"Mandatory deep-data coverage was insufficient: {success_count}/{attempt_count} "
            f"attempted symbols; minimum {required}"
        )


def company_bundle_with_fallback(
    symbol: str,
    cik_hint: Any,
    sec: SecProvider,
    fmp: FmpProvider | None,
    *,
    alpha: AlphaVantageProvider | None = None,
    alpha_profile: dict[str, Any] | None = None,
    try_sec: bool = True,
) -> tuple[dict[str, Any], str | None, bool]:
    """Prefer normalized SEC XBRL; use FMP only when the SEC path cannot cover a name."""
    if try_sec:
        try:
            sec_bundle = sec.company_bundle(symbol, cik_hint=cik_hint)
        except ProviderError as sec_exc:
            warning = " ".join(str(sec_exc).split())[:240]
            lowered = warning.lower()
            sec_working = not any(
                marker in lowered
                for marker in (
                    "sec infrastructure unavailable",
                    "http 403",
                    "http 429",
                    "timed out",
                    "connection refused",
                )
            )
            alpha_error: str | None = None
            if alpha is not None:
                try:
                    bundle = alpha.company_bundle(
                        symbol,
                        profile=alpha_profile,
                        cik_hint=cik_hint,
                    )
                    return (
                        bundle,
                        f"{warning}; free Alpha Vantage fundamentals fallback used",
                        sec_working,
                    )
                except ProviderError as exc:
                    alpha_error = " ".join(str(exc).split())[:200]
            if fmp is not None:
                bundle = fmp.company_bundle(symbol, cik_hint=cik_hint)
                suffix = (
                    f"; Alpha Vantage fallback failed ({alpha_error})"
                    if alpha_error
                    else ""
                )
                return bundle, f"{warning}{suffix}; optional FMP fallback used", sec_working
            detail = f"; Alpha Vantage fallback failed ({alpha_error})" if alpha_error else ""
            raise ProviderError(f"{warning}{detail}; no operational free fundamentals fallback")
        return sec_bundle, sec_bundle.get("provider_warning"), True
    if fmp is None:
        raise ProviderError("SEC unavailable and optional FMP fallback is not configured")
    return fmp.company_bundle(symbol, cik_hint=cik_hint), "SEC skipped after infrastructure failure; optional FMP fallback used", False


def build_report(smoke: bool = False) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    credentials = Credentials.from_environment()
    alpaca = AlpacaProvider(
        credentials.alpaca_key_id,
        credentials.alpaca_secret_key,
        historical_feed=os.getenv("GALION_ALPACA_HISTORICAL_FEED", "sip"),
        realtime_feed=os.getenv("GALION_ALPACA_REALTIME_FEED", "iex"),
        historical_fallback_feed=os.getenv(
            "GALION_ALPACA_HISTORICAL_FALLBACK_FEED", "iex"
        ),
    )
    alpha = (
        AlphaVantageProvider(
            credentials.alpha_vantage_key,
            min_interval_seconds=float(os.getenv("AV_MIN_INTERVAL_SECONDS", "13")),
            call_budget=int(os.getenv("AV_CALL_BUDGET", "25")),
        )
        if credentials.alpha_vantage_key
        else None
    )
    fred = FredProvider(credentials.fred_key) if credentials.fred_key else None
    fmp = FmpProvider(credentials.fmp_key) if credentials.fmp_key else None
    sec_user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not sec_user_agent:
        raise ProviderError(
            "SEC_USER_AGENT is required for live scans; use an application name and contact email"
        )
    sec = SecProvider(sec_user_agent)
    cache = JsonFundamentalCache.from_environment()
    cache.prune()
    cache_hits = 0
    cache_misses = 0

    raw_assets = alpaca.assets()
    assets = alpaca.eligible_assets(raw_assets)
    if smoke:
        smoke_symbols = {"AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "JPM", "XOM"}
        assets = [asset for asset in assets if asset["symbol"] in smoke_symbols]
    symbols = [str(asset["symbol"]) for asset in assets]
    all_symbols = sorted(set(symbols + BENCHMARKS))
    start, _ = default_history_window()
    market_data_end = completed_market_data_cutoff()
    bars = alpaca.daily_bars(all_symbols, start=start, end=market_data_end)
    session_date = latest_session_date(bars)
    if not session_date:
        raise ProviderError("No completed SPY session was returned by Alpaca")

    snapshots: dict[str, TechnicalSnapshot] = {}
    rejected = {"insufficient_history": 0, "price": 0, "liquidity": 0, "invalid": 0}
    for symbol in all_symbols:
        try:
            snapshot = build_snapshot(bars.get(symbol, []))
        except (ValueError, KeyError, TypeError):
            rejected["insufficient_history"] += 1
            continue
        if symbol not in BENCHMARKS:
            if snapshot.close < MIN_PRICE:
                rejected["price"] += 1
                continue
            if snapshot.avg_dollar_volume_20d < MIN_ADV20:
                rejected["liquidity"] += 1
                continue
        snapshots[symbol] = snapshot
    if any(symbol not in snapshots for symbol in INDEX_BENCHMARKS):
        raise ProviderError("Index benchmark history is incomplete")
    index_regime = market_regime(snapshots["SPY"], snapshots["QQQ"], snapshots["IWM"])

    stock_snapshots = {
        symbol: snapshot for symbol, snapshot in snapshots.items() if symbol not in BENCHMARKS
    }
    breadth = market_breadth(stock_snapshots)
    regime = combine_regime(index_regime, breadth)
    sector_ranks = sector_leadership(snapshots, snapshots["SPY"])
    ranked = build_research_queue(
        stock_snapshots,
        snapshots["SPY"],
        per_archetype=6,
        limit=(len(stock_snapshots) if smoke else RESEARCH_QUEUE_LIMIT),
    )
    # Free providers do not cover every valid listing, so keep a diversified
    # reserve and skip unsupported symbols until the deep-data target is met.
    research_targets = diversified_shortlist(
        ranked,
        per_archetype=6,
        limit=(len(ranked) if smoke else RESEARCH_QUEUE_LIMIT),
    )
    quote_data = alpaca.snapshots([item["symbol"] for item in research_targets])
    asset_map = {str(asset["symbol"]): asset for asset in assets}

    candidates: list[dict[str, Any]] = []
    provider_warnings: list[str] = list(alpaca.provider_warnings)
    deep_data_successes = 0
    deep_data_attempts = 0
    try_sec = True
    try_alpha = alpha is not None
    provider_mix: dict[str, int] = {}
    for item in research_targets:
        if deep_data_successes >= DEEP_DATA_LIMIT:
            break
        deep_data_attempts += 1
        symbol = item["symbol"]
        overview: dict[str, Any] = {}
        estimates: dict[str, Any] = {}
        regulatory_bundle: dict[str, Any] = {}
        alpha_warnings: list[str] = []
        cached = cache.get(symbol)
        cached_statements = ((cached or {}).get("regulatory_bundle") or {}).get("statements") or {}
        if cached and not all(cached_statements.get(name) for name in ("income", "balance", "cashflow")):
            cached = None
        if cached:
            cache_hits += 1
            overview = cached.get("overview") or {}
            regulatory_bundle = cached.get("regulatory_bundle") or {}
        else:
            cache_misses += 1
        if try_alpha:
            if not cached:
                try:
                    overview = alpha.overview(symbol) if alpha else {}
                except ProviderError as exc:
                    alpha_warnings.append(concise_provider_error(symbol, exc))
                    if provider_quota_exhausted(exc):
                        try_alpha = False
                        alpha_warnings.append(
                            "Alpha Vantage allowance unavailable; disabled for the remainder of this run"
                        )
            if try_alpha:
                try:
                    estimates = alpha.earnings_estimates(symbol) if alpha else {}
                except ProviderError as exc:
                    alpha_warnings.append(concise_provider_error(symbol, exc))
                    if provider_quota_exhausted(exc):
                        try_alpha = False
                        alpha_warnings.append(
                            "Alpha Vantage allowance unavailable; disabled for the remainder of this run"
                        )
        if not cached:
            try:
                regulatory_bundle, fallback_warning, sec_working = company_bundle_with_fallback(
                    symbol,
                    overview.get("CIK"),
                    sec,
                    fmp,
                    alpha=alpha,
                    alpha_profile=overview,
                    try_sec=try_sec,
                )
                try_sec = try_sec and sec_working
                if fallback_warning:
                    provider_warnings.append(f"{symbol}: {fallback_warning}")
            except ProviderError as exc:
                provider_warnings.append(concise_provider_error(symbol, exc))
                continue
        try:
            reported_overview = reported_overview_from_bundle(
                regulatory_bundle,
                latest_price=float(item["technical"]["close"]),
            )
        except ProviderError as exc:
            provider_warnings.append(concise_provider_error(symbol, exc))
            continue
        if overview:
            overview = {
                **reported_overview,
                **{
                    key: value
                    for key, value in overview.items()
                    if value is not None and value not in ("", "None", "-")
                },
            }
        else:
            overview = reported_overview
            alpha_warnings.append(
                f"{symbol}: reported {regulatory_bundle.get('provider')} fundamentals used because Alpha Vantage overview was unavailable"
            )
        if not cached:
            cache.set(
                symbol,
                {
                    "overview": overview,
                    "regulatory_bundle": compact_regulatory_bundle(regulatory_bundle),
                },
            )
        provider_warnings.extend(alpha_warnings)
        deep_data_successes += 1
        provider_name = str(regulatory_bundle.get("provider") or "unknown")
        provider_mix[provider_name] = provider_mix.get(provider_name, 0) + 1
        cap = market_cap(overview)
        if cap is None or cap < MIN_MARKET_CAP:
            continue
        filings = latest_filings(regulatory_bundle)
        if "fmp" in str(regulatory_bundle.get("provider") or "") and not filings:
            provider_warnings.append(
                f"{symbol}: FMP free statements returned without filing links; primary filing review remains a final-underwriting blocker"
            )
        statements = regulatory_bundle.get("statements") or {}
        forensic = analyze_statements(statements)
        f_score = fundamental_score(overview)
        v_score = valuation_score(overview)
        rev_score, revision_evidence = revision_score(estimates)
        t_score = float(item["technical"]["technical_score"])
        snapshot = snapshots[symbol]
        risk_flags = event_risk_flags(snapshot)
        risk_score = screen_risk_score(snapshot, risk_flags)
        catalyst_score = screen_catalyst_score(filings, risk_flags)
        data_quality_score = screen_data_quality(overview, statements, filings, revision_evidence)
        sector_name = str(overview.get("Sector") or "")
        sector_etf = sector_etf_for_name(sector_name)
        sector_context = sector_ranks.get(sector_etf or "", {
            "etf": sector_etf,
            "rank": None,
            "rank_out_of": len(sector_ranks),
            "leadership_score": 50.0,
            "posture": "unmapped",
        })
        sector_score = float(sector_context.get("leadership_score") or 50.0)
        forensic_score = float(forensic.get("quality_score") or 50.0)
        raw_composite = (
            f_score * 0.22
            + v_score * 0.13
            + rev_score * 0.12
            + catalyst_score * 0.08
            + t_score * 0.18
            + sector_score * 0.08
            + risk_score * 0.10
            + data_quality_score * 0.05
            + forensic_score * 0.04
        )
        composite = round(clamp(raw_composite - float(forensic.get("penalty") or 0.0)), 2)
        eligible_for_long, long_blockers = long_eligibility(snapshot, risk_flags, forensic)
        statement_periods = {
            name: [
                {
                    "date": row.get("date"),
                    "filing_date": row.get("fillingDate") or row.get("filingDate"),
                    "period": row.get("period"),
                    "fiscal_year": row.get("fiscalYear") or row.get("calendarYear"),
                }
                for row in rows[:5]
            ]
            for name, rows in statements.items()
            if isinstance(rows, list)
        }
        candidate = {
            **item,
            "company": overview.get("Name") or asset_map.get(symbol, {}).get("name"),
            "exchange": overview.get("Exchange") or asset_map.get(symbol, {}).get("exchange"),
            "sector": overview.get("Sector"),
            "industry": overview.get("Industry"),
            "sector_context": sector_context,
            "market_cap": cap,
            "spread_bps_latest_quote": quote_spread_bps(quote_data.get(symbol, {})),
            "fundamental_score_screen": f_score,
            "valuation_score_screen": v_score,
            "revisions_score_screen": rev_score,
            "catalyst_score_screen": catalyst_score,
            "risk_reward_proxy_score_screen": risk_score,
            "data_quality_score_screen": data_quality_score,
            "forensic_screen": forensic,
            "revision_evidence": revision_evidence,
            "composite_screen_score": composite,
            "long_eligible_screen": eligible_for_long,
            "long_eligibility_blockers": long_blockers,
            "event_risk_flags": risk_flags,
            "regulatory_evidence": {
                "provider": regulatory_bundle.get("provider"),
                "cik": regulatory_bundle.get("cik"),
                "submissions_url": regulatory_bundle.get("submissions_url"),
                "companyfacts_url": regulatory_bundle.get("companyfacts_url"),
                "source_urls": regulatory_bundle.get("source_urls", {}),
                "latest_filings": filings,
                "filing_evidence_status": regulatory_bundle.get("filing_evidence_status"),
                "statement_coverage": regulatory_bundle.get("statement_coverage"),
                "statement_periods": statement_periods,
            },
            "market_sources": [
                "https://docs.alpaca.markets/us/reference/stockbars",
                "https://www.alphavantage.co/documentation/",
                "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
            ],
            "status": (
                "EVENT REVIEW — DO NOT CHASE"
                if risk_flags
                else "WATCHLIST — STAGE 4 LONG VETO"
                if snapshot.stage == 4
                else "FORENSIC REVIEW — ACCOUNTING FLAGS"
                if forensic.get("flags")
                else "SCREEN-GRADE — REQUIRES GALION DEEP UNDERWRITING"
            ),
            "qualification_blockers": [
                "latest filing content not yet reviewed",
                "earnings release/transcript and management guidance not yet reviewed",
                "peer valuation and industry-specific KPI review not yet applied",
                "bear/base/bull scenarios not yet supported",
                "catalyst, hard-veto and red-team checks not yet completed",
            ]
            + (["extreme price/volume event requires gap-risk underwriting"] if risk_flags else [])
            + (["Stage 4 downtrend blocks long qualification until technical repair"] if snapshot.stage == 4 else [])
            + (["forensic flags require filing-level accounting verification"] if forensic.get("flags") else []),
        }
        candidates.append(candidate)

    require_deep_data_coverage(deep_data_attempts, deep_data_successes, provider_warnings)

    candidates.sort(key=lambda item: item["composite_screen_score"], reverse=True)
    macro = fred.macro_snapshot() if fred else {"status": "FRED_API_KEY not configured"}
    ledger = SignalLedger(
        Path(os.getenv("GALION_SIGNAL_LEDGER", "data/signal_ledger.json")),
        round_trip_cost_bps=float(
            os.getenv("GALION_SHADOW_ROUND_TRIP_COST_BPS", "10")
        ),
    )
    signal_performance = ledger.update(
        session_date,
        candidates,
        bars,
        market_regime=regime,
        market_data_feed=alpaca.bars_feed_used,
    )
    completed = datetime.now(timezone.utc)
    return {
        "run_status": "SCREEN-GRADE COMPLETE" if candidates else "NO SCREEN-GRADE CANDIDATE",
        "decision_status": "NOT A BUY RECOMMENDATION",
        "source_posture": "screen-grade",
        "as_of_session": session_date,
        "started_at_utc": started.isoformat(),
        "completed_at_utc": completed.isoformat(),
        "index_regime": index_regime,
        "market_regime": regime,
        "market_breadth": breadth,
        "sector_leadership": sector_ranks,
        "universe": {
            "active_assets_received": len(raw_assets),
            "eligible_common_stock_candidates": len(assets),
            "passed_price_liquidity_history": len(stock_snapshots),
            "research_queue_size": len(ranked),
            "deep_data_target": min(DEEP_DATA_LIMIT, len(research_targets)),
            "deep_data_requested": deep_data_attempts,
            "deep_data_successful": deep_data_successes,
            "deep_data_provider_mix": provider_mix,
            "screen_grade_candidates": len(candidates),
            "rejections": rejected,
            "gates": {
                "price_min": MIN_PRICE,
                "market_cap_min": MIN_MARKET_CAP,
                "avg_dollar_volume_20d_min": MIN_ADV20,
            },
        },
        "benchmarks": {symbol: asdict(snapshots[symbol]) for symbol in BENCHMARKS if symbol in snapshots},
        "macro": macro,
        "cache": {
            "hits": cache_hits,
            "misses": cache_misses,
            "ttl_days": int(os.getenv("GALION_CACHE_TTL_DAYS", "14")),
            "credentials_stored": False,
        },
        "source_stack": {
            "market_data": (
                f"Alpaca delayed {str(alpaca.bars_feed_used or 'unknown').upper()} adjusted daily bars"
            ),
            "historical_feed_requested": alpaca.historical_feed,
            "historical_feed_used": alpaca.bars_feed_used,
            "historical_end_utc": market_data_end.isoformat(),
            "latest_quote_feed": alpaca.snapshot_feed_used,
            "reported_fundamentals_primary": "SEC EDGAR XBRL direct or official nightly bulk archive",
            "reported_fundamentals_fallback": "FMP optional" if fmp else "not configured",
            "estimates": "Alpha Vantage free allowance" if alpha else "not configured",
            "alpha_vantage_calls_used": alpha.call_count if alpha else 0,
            "alpha_vantage_call_ceiling": alpha.call_budget if alpha else 0,
            "macro": "FRED" if fred else "not configured",
            "liquidity_limitation": (
                "Historical SIP volume is consolidated and delayed; latest spread remains an IEX screen-grade proxy"
                if alpaca.bars_feed_used == "sip"
                else "IEX volume can understate consolidated U.S. market volume; liquidity remains a screen-grade proxy"
            ),
        },
        "signal_performance": signal_performance,
        "candidates": candidates,
        "provider_warnings": provider_warnings,
        "next_step": "Complete cited filing, IR, catalyst, scenario and red-team review before any investment decision.",
        "disclaimer": "Research support only. No order was created or transmitted; the user makes every investment decision.",
    }


def failure_report(exc: Exception) -> dict[str, Any]:
    return {
        "run_status": "RUN NOT OPERATIONAL",
        "decision_status": "NO ANALYTICAL CONCLUSION",
        "source_posture": "not-operational",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "missing_dependency_or_error": str(exc),
        "candidates": [],
        "disclaimer": "No order was created or transmitted.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GALION SignalForge — Latest Discovery Run",
        "",
        f"- **Run status:** `{report['run_status']}`",
        f"- **Decision status:** `{report['decision_status']}`",
        f"- **Source posture:** `{report['source_posture']}`",
        f"- **Session:** `{report.get('as_of_session', 'not evaluated')}`",
        f"- **Market regime:** `{report.get('market_regime', 'not evaluated')}`",
        f"- **Breadth posture:** `{(report.get('market_breadth') or {}).get('posture', 'not evaluated')}`",
        "",
    ]
    if report["run_status"] == "RUN NOT OPERATIONAL":
        lines += ["## Blocking error", "", str(report.get("missing_dependency_or_error")), ""]
        return "\n".join(lines)
    lines += [
        "## Screen-grade shortlist",
        "",
        "These names are **research priorities, not buy recommendations**. GALION must review filings, IR, catalysts, valuation scenarios, hard vetoes and the bear case before any final status.",
        "",
        f"Universe: {report['universe']['eligible_common_stock_candidates']} eligible listings; "
        f"{report['universe']['passed_price_liquidity_history']} passed price/liquidity/history; "
        f"{report['universe']['research_queue_size']} entered the diversified research queue; "
        f"{report['universe']['deep_data_requested']} received deep-data requests and "
        f"{report['universe']['deep_data_successful']} produced complete screen-grade bundles.",
        "",
        "| Rank | Ticker | Archetype | Stage | Sector rank | Screen | Technical | Fundamental | Valuation | Forensic | Risk | Data |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, candidate in enumerate(report.get("candidates", []), start=1):
        lines.append(
            f"| {index} | {candidate['symbol']} | {candidate.get('primary_archetype') or ''} | "
            f"{candidate['technical'].get('stage', '')} | {candidate.get('sector_context', {}).get('rank') or '—'} | "
            f"{candidate['composite_screen_score']:.2f} | {candidate['technical']['technical_score']:.2f} | "
            f"{candidate['fundamental_score_screen']:.2f} | {candidate['valuation_score_screen']:.2f} | "
            f"{(candidate.get('forensic_screen', {}).get('quality_score') or 0):.2f} | "
            f"{candidate['risk_reward_proxy_score_screen']:.2f} | {candidate['data_quality_score_screen']:.2f} |"
        )
    lines += ["", "## Required next step", "", str(report.get("next_step")), "", "---", report["disclaimer"], ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "latest.md").write_text(render_markdown(report), encoding="utf-8")
    (output_dir / "dashboard.html").write_text(render_dashboard(report), encoding="utf-8")
    session = report.get("as_of_session")
    if session:
        history = output_dir / "history"
        history.mkdir(parents=True, exist_ok=True)
        (history / f"{session}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GALION free-data discovery scan")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--smoke", action="store_true", help="Use a small universe for initial validation")
    args = parser.parse_args(argv)
    try:
        report = build_report(smoke=args.smoke)
        code = 0
    except Exception as exc:  # Fail closed and preserve an auditable failure report.
        report = failure_report(exc)
        code = 2
    write_report(report, Path(args.output_dir))
    print(json.dumps({"run_status": report["run_status"], "source_posture": report["source_posture"]}))
    return code


if __name__ == "__main__":
    sys.exit(main())
