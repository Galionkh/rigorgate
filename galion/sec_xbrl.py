from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any, Iterable


FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}

INCOME_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "InterestAndDividendIncomeOperating",
    ),
    "grossProfit": ("GrossProfit",),
    "operatingIncome": ("OperatingIncomeLoss",),
    "netIncome": (
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "weightedAverageShsOut": (
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
    "weightedAverageShsOutDil": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
}

BALANCE_TAGS: dict[str, tuple[str, ...]] = {
    "totalAssets": ("Assets",),
    "totalCurrentAssets": ("AssetsCurrent",),
    "cashAndCashEquivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "totalCurrentLiabilities": ("LiabilitiesCurrent",),
    "totalStockholdersEquity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
}

TOTAL_DEBT_TAGS = (
    "LongTermDebtAndFinanceLeaseObligations",
    "DebtAndFinanceLeaseObligations",
    "LongTermDebt",
)
CURRENT_DEBT_TAGS = (
    "DebtCurrent",
    "LongTermDebtAndFinanceLeaseObligationsCurrent",
    "LongTermDebtCurrent",
)
NONCURRENT_DEBT_TAGS = (
    "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    "LongTermDebtNoncurrent",
)

CASHFLOW_TAGS: dict[str, tuple[str, ...]] = {
    "operatingCashFlow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capitalExpenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _facts(payload: dict[str, Any], taxonomy: str = "us-gaap") -> dict[str, Any]:
    facts = (payload.get("facts") or {}).get(taxonomy) or {}
    return facts if isinstance(facts, dict) else {}


def _records(
    payload: dict[str, Any],
    tags: Iterable[str],
    units: tuple[str, ...],
    *,
    taxonomy: str = "us-gaap",
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    concepts = _facts(payload, taxonomy)
    for priority, tag in enumerate(tags):
        concept = concepts.get(tag) or {}
        unit_map = concept.get("units") or {}
        if not isinstance(unit_map, dict):
            continue
        rows: list[dict[str, Any]] = []
        for unit in units:
            value = unit_map.get(unit)
            if isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))
        for row in rows:
            form = str(row.get("form") or "").upper()
            value = _number(row.get("val"))
            end = _as_date(row.get("end"))
            if form not in FORMS or value is None or end is None:
                continue
            output.append(
                {
                    **row,
                    "val": value,
                    "end_date": end,
                    "start_date": _as_date(row.get("start")),
                    "tag": tag,
                    "priority": priority,
                }
            )
    return output


def _prefer(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    if int(candidate["priority"]) != int(current["priority"]):
        return int(candidate["priority"]) < int(current["priority"])
    return str(candidate.get("filed") or "") > str(current.get("filed") or "")


def _quarter_label(days: int, fallback: Any = None) -> str | None:
    if 60 <= days <= 130:
        return str(fallback) if str(fallback or "").startswith("Q") else None
    if 130 < days <= 220:
        return "Q2"
    if 220 < days <= 310:
        return "Q3"
    if 310 < days <= 390:
        return "Q4"
    return None


def duration_quarters(
    payload: dict[str, Any],
    tags: Iterable[str],
    units: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Return discrete quarters, deriving Q2/Q3/Q4 from cumulative SEC facts."""
    records = _records(payload, tags, units)
    periods: dict[tuple[date, date], dict[str, Any]] = {}
    for record in records:
        start = record.get("start_date")
        end = record.get("end_date")
        if start is None or end is None:
            continue
        days = (end - start).days + 1
        if days < 60 or days > 390:
            continue
        key = (start, end)
        if _prefer(record, periods.get(key)):
            periods[key] = record

    candidates: dict[str, dict[str, Any]] = {}

    def add(record: dict[str, Any], value: float, source: str, days: int) -> None:
        end = str(record["end_date"])
        candidate = {
            "value": value,
            "end": end,
            "filed": record.get("filed"),
            "form": record.get("form"),
            "accn": record.get("accn"),
            "fy": record.get("fy"),
            "fp": _quarter_label(days, record.get("fp")),
            "tag": record.get("tag"),
            "priority": record.get("priority", 999),
            "source": source,
        }
        current = candidates.get(end)
        candidate_rank = (
            0 if source == "reported-discrete" else 1,
            int(candidate["priority"]),
            -int(str(candidate.get("filed") or "0000-00-00").replace("-", "") or 0),
        )
        current_rank = (
            0 if current and current.get("source") == "reported-discrete" else 1,
            int((current or {}).get("priority", 999)),
            -int(str((current or {}).get("filed") or "0000-00-00").replace("-", "") or 0),
        )
        if current is None or candidate_rank < current_rank:
            candidates[end] = candidate

    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for (start, end), record in periods.items():
        days = (end - start).days + 1
        if 60 <= days <= 130:
            add(record, float(record["val"]), "reported-discrete", days)
        grouped[start].append(record)

    for group in grouped.values():
        ordered = sorted(group, key=lambda item: item["end_date"])
        for later_index, later in enumerate(ordered):
            later_days = (later["end_date"] - later["start_date"]).days + 1
            eligible = []
            for earlier in ordered[:later_index]:
                interval_days = (later["end_date"] - earlier["end_date"]).days
                if 60 <= interval_days <= 130:
                    eligible.append(earlier)
            if not eligible:
                continue
            earlier = max(eligible, key=lambda item: item["end_date"])
            value = float(later["val"]) - float(earlier["val"])
            add(later, value, "derived-from-cumulative", later_days)
    return candidates


def instant_values(
    payload: dict[str, Any],
    tags: Iterable[str],
    units: tuple[str, ...],
    *,
    taxonomy: str = "us-gaap",
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for record in _records(payload, tags, units, taxonomy=taxonomy):
        if record.get("start_date") is not None:
            continue
        end = str(record["end_date"])
        if _prefer(record, output.get(end)):
            output[end] = {
                "value": float(record["val"]),
                "end": end,
                "filed": record.get("filed"),
                "form": record.get("form"),
                "accn": record.get("accn"),
                "fy": record.get("fy"),
                "fp": record.get("fp"),
                "tag": record.get("tag"),
                "priority": record.get("priority", 999),
                "source": "reported-instant",
            }
    return output


def _latest_meta(maps: Iterable[dict[str, dict[str, Any]]], end: str) -> dict[str, Any]:
    rows = [values[end] for values in maps if end in values]
    if not rows:
        return {}
    return max(rows, key=lambda row: str(row.get("filed") or ""))


def _field(values: dict[str, dict[str, Any]], end: str) -> float | None:
    row = values.get(end)
    return float(row["value"]) if row else None


def _filing_index_url(cik: str, accession: Any) -> str | None:
    accn = str(accession or "").strip()
    if not accn:
        return None
    accession_plain = accn.replace("-", "")
    try:
        cik_plain = str(int(cik))
    except ValueError:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{accession_plain}/"
        f"{accn}-index.html"
    )


def latest_filings_from_companyfacts(
    companyfacts: dict[str, Any], cik: str, limit: int = 12
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for taxonomy in ("us-gaap", "dei"):
        for concept in _facts(companyfacts, taxonomy).values():
            units = (concept or {}).get("units") or {}
            if not isinstance(units, dict):
                continue
            for facts in units.values():
                if not isinstance(facts, list):
                    continue
                for fact in facts:
                    if not isinstance(fact, dict):
                        continue
                    form = str(fact.get("form") or "").upper()
                    accn = str(fact.get("accn") or "")
                    if form not in FORMS or not accn:
                        continue
                    existing = rows.get(accn)
                    candidate = {
                        "accessionNumber": accn,
                        "filingDate": fact.get("filed"),
                        "reportDate": fact.get("end"),
                        "formType": form.replace("/A", ""),
                        "finalLink": _filing_index_url(cik, accn),
                    }
                    if existing is None or str(candidate.get("filingDate") or "") > str(
                        existing.get("filingDate") or ""
                    ):
                        rows[accn] = candidate
    return sorted(
        rows.values(), key=lambda row: str(row.get("filingDate") or ""), reverse=True
    )[:limit]


def _sector_from_sic(value: Any) -> str | None:
    try:
        sic = int(value)
    except (TypeError, ValueError):
        return None
    if 100 <= sic <= 999 or 4900 <= sic <= 4999:
        return "Utilities"
    if 2000 <= sic <= 2149 or 5400 <= sic <= 5499:
        return "Consumer Defensive"
    if 2200 <= sic <= 2399 or 3700 <= sic <= 3719 or 5200 <= sic <= 5999:
        return "Consumer Cyclical"
    if 2830 <= sic <= 2839 or 3840 <= sic <= 3859 or 8000 <= sic <= 8099:
        return "Healthcare"
    if 2900 <= sic <= 2999:
        return "Energy"
    if 3570 <= sic <= 3579 or 3660 <= sic <= 3699 or 7370 <= sic <= 7379:
        return "Technology"
    if 4810 <= sic <= 4899 or 7310 <= sic <= 7319 or 7800 <= sic <= 7899:
        return "Communication Services"
    if 6000 <= sic <= 6499 or 6700 <= sic <= 6797:
        return "Financial Services"
    if 6500 <= sic <= 6699 or sic == 6798:
        return "Real Estate"
    if 1000 <= sic <= 1499 or 2400 <= sic <= 3299:
        return "Basic Materials"
    if 1500 <= sic <= 1999 or 3300 <= sic <= 4799 or 5000 <= sic <= 5199:
        return "Industrials"
    return None


def normalize_companyfacts(
    companyfacts: dict[str, Any],
    *,
    cik: str,
    symbol: str,
    submissions: dict[str, Any] | None = None,
    provider: str,
) -> dict[str, Any]:
    income_maps = {
        field: duration_quarters(
            companyfacts,
            tags,
            ("shares",) if "Shs" in field else ("USD",),
        )
        for field, tags in INCOME_TAGS.items()
    }
    balance_maps = {
        field: instant_values(companyfacts, tags, ("USD",))
        for field, tags in BALANCE_TAGS.items()
    }
    total_debt = instant_values(companyfacts, TOTAL_DEBT_TAGS, ("USD",))
    current_debt = instant_values(companyfacts, CURRENT_DEBT_TAGS, ("USD",))
    noncurrent_debt = instant_values(companyfacts, NONCURRENT_DEBT_TAGS, ("USD",))
    for end in sorted(set(current_debt) | set(noncurrent_debt)):
        if end in total_debt:
            continue
        current = _field(current_debt, end)
        noncurrent = _field(noncurrent_debt, end)
        if current is None and noncurrent is None:
            continue
        meta = _latest_meta((current_debt, noncurrent_debt), end)
        total_debt[end] = {**meta, "value": (current or 0.0) + (noncurrent or 0.0), "source": "derived-debt-components"}
    balance_maps["totalDebt"] = total_debt

    cash_maps = {
        field: duration_quarters(companyfacts, tags, ("USD",))
        for field, tags in CASHFLOW_TAGS.items()
    }

    all_duration_maps = [*income_maps.values(), *cash_maps.values()]
    all_instant_maps = list(balance_maps.values())
    income_ends = sorted(
        set().union(*(values.keys() for values in income_maps.values())), reverse=True
    )
    balance_ends = sorted(
        set().union(*(values.keys() for values in balance_maps.values())), reverse=True
    )
    cash_ends = sorted(
        set().union(*(values.keys() for values in cash_maps.values())), reverse=True
    )

    income: list[dict[str, Any]] = []
    for end in income_ends[:12]:
        meta = _latest_meta(all_duration_maps, end)
        row = {
            "date": end,
            "fillingDate": meta.get("filed"),
            "period": meta.get("fp"),
            "fiscalYear": meta.get("fy"),
            **{field: _field(values, end) for field, values in income_maps.items()},
        }
        if row.get("revenue") is not None or row.get("netIncome") is not None:
            income.append(row)

    balance: list[dict[str, Any]] = []
    for end in balance_ends[:12]:
        meta = _latest_meta(all_instant_maps, end)
        row = {
            "date": end,
            "fillingDate": meta.get("filed"),
            "period": meta.get("fp"),
            "fiscalYear": meta.get("fy"),
            **{field: _field(values, end) for field, values in balance_maps.items()},
        }
        if row.get("totalAssets") is not None:
            balance.append(row)

    cashflow: list[dict[str, Any]] = []
    for end in cash_ends[:12]:
        meta = _latest_meta(all_duration_maps, end)
        operating = _field(cash_maps["operatingCashFlow"], end)
        capex = _field(cash_maps["capitalExpenditure"], end)
        row = {
            "date": end,
            "fillingDate": meta.get("filed"),
            "period": meta.get("fp"),
            "fiscalYear": meta.get("fy"),
            "operatingCashFlow": operating,
            "capitalExpenditure": capex,
            "freeCashFlow": operating - capex if operating is not None and capex is not None else None,
        }
        if operating is not None:
            cashflow.append(row)

    submissions = submissions if isinstance(submissions, dict) else {}
    tickers = submissions.get("tickers") if isinstance(submissions.get("tickers"), list) else []
    exchanges = submissions.get("exchanges") if isinstance(submissions.get("exchanges"), list) else []
    try:
        symbol_index = [str(value).upper() for value in tickers].index(symbol.upper())
    except ValueError:
        symbol_index = -1
    exchange = exchanges[symbol_index] if 0 <= symbol_index < len(exchanges) else None
    shares_maps = [
        instant_values(
            companyfacts,
            ("EntityCommonStockSharesOutstanding",),
            ("shares",),
            taxonomy="dei",
        ),
        instant_values(
            companyfacts,
            ("CommonStockSharesOutstanding",),
            ("shares",),
        ),
    ]
    outstanding = None
    share_dates = sorted(set().union(*(values.keys() for values in shares_maps)), reverse=True)
    for end in share_dates:
        outstanding = next((_field(values, end) for values in shares_maps if end in values), None)
        if outstanding is not None:
            break

    sic = submissions.get("sic")
    profile = {
        "companyName": submissions.get("name") or companyfacts.get("entityName"),
        "symbol": symbol.upper(),
        "cik": cik,
        "exchangeShortName": exchange,
        "sector": _sector_from_sic(sic),
        "industry": submissions.get("sicDescription"),
        "sic": sic,
        "sharesOutstanding": outstanding,
        "fiscalYearEnd": submissions.get("fiscalYearEnd"),
        "normalization": "SEC XBRL reported facts; cumulative duration facts converted to discrete quarters",
    }
    latest_filings = latest_filings_from_companyfacts(companyfacts, cik)
    coverage = {
        "income_quarters": len(income),
        "balance_quarters": len(balance),
        "cashflow_quarters": len(cashflow),
        "latest_income_period": income[0]["date"] if income else None,
        "latest_balance_period": balance[0]["date"] if balance else None,
        "latest_cashflow_period": cashflow[0]["date"] if cashflow else None,
        "minimum_five_quarters_complete": min(len(income), len(balance), len(cashflow)) >= 5,
    }
    return {
        "provider": provider,
        "cik": cik,
        "company": profile["companyName"],
        "profile": profile,
        "statements": {
            "income": income,
            "balance": balance,
            "cashflow": cashflow,
        },
        "latest_filings": latest_filings,
        "filing_evidence_status": "linked" if latest_filings else "companyfacts-only",
        "filing_evidence_method": "SEC XBRL accession metadata linked to EDGAR filing index",
        "statement_coverage": coverage,
    }
