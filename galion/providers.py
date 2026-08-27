from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .http import ProviderError, get_json
from .remote_zip import RemoteZipJsonArchive
from .sec_xbrl import normalize_companyfacts


ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks"
ALPACA_PAPER_URL = "https://paper-api.alpaca.markets/v2"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
FRED_URL = "https://api.stlouisfed.org/fred"
FMP_URL = "https://financialmodelingprep.com/stable"
SEC_DATA_URL = "https://data.sec.gov"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_BULK_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
)


@dataclass(frozen=True)
class Credentials:
    alpaca_key_id: str
    alpaca_secret_key: str
    alpha_vantage_key: str | None
    fred_key: str | None
    fmp_key: str | None

    @classmethod
    def from_environment(cls) -> "Credentials":
        names = {
            "alpaca_key_id": "APCA_API_KEY_ID",
            "alpaca_secret_key": "APCA_API_SECRET_KEY",
            "alpha_vantage_key": "ALPHA_VANTAGE_API_KEY",
            "fred_key": "FRED_API_KEY",
            "fmp_key": "FMP_API_KEY",
        }
        raw_values = {field: os.getenv(name, "").strip() for field, name in names.items()}
        missing = [
            names[field]
            for field in ("alpaca_key_id", "alpaca_secret_key")
            if not raw_values[field]
        ]
        if missing:
            raise ProviderError("Missing required secrets: " + ", ".join(missing))
        values = {
            field: value if value else None for field, value in raw_values.items()
        }
        return cls(**values)


def chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


class AlpacaProvider:
    def __init__(
        self,
        key_id: str,
        secret_key: str,
        *,
        historical_feed: str = "sip",
        realtime_feed: str = "iex",
        historical_fallback_feed: str | None = "iex",
    ) -> None:
        self.headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        self.historical_feed = historical_feed.strip().lower()
        self.realtime_feed = realtime_feed.strip().lower()
        self.historical_fallback_feed = (
            historical_fallback_feed.strip().lower()
            if historical_fallback_feed
            else None
        )
        self.bars_feed_used: str | None = None
        self.snapshot_feed_used: str | None = None
        self.provider_warnings: list[str] = []

    def assets(self) -> list[dict[str, Any]]:
        payload = get_json(
            f"{ALPACA_PAPER_URL}/assets",
            params={"status": "active", "asset_class": "us_equity"},
            headers=self.headers,
        )
        if not isinstance(payload, list):
            raise ProviderError("Alpaca assets response is not a list")
        return payload

    @staticmethod
    def eligible_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        forbidden = re.compile(
            r"\b(ETF|ETN|FUND|WARRANT|RIGHTS?|UNITS?|PREFERRED|DEPOSITARY|ACQUISITION CORP)\b",
            re.IGNORECASE,
        )
        allowed_exchanges = {"NASDAQ", "NYSE", "AMEX"}
        output = []
        for asset in assets:
            symbol = str(asset.get("symbol", "")).strip()
            name = str(asset.get("name", ""))
            if (
                asset.get("status") == "active"
                and asset.get("tradable") is True
                and asset.get("exchange") in allowed_exchanges
                and re.fullmatch(r"[A-Z]{1,5}", symbol)
                and not forbidden.search(name)
            ):
                output.append(asset)
        return sorted(output, key=lambda item: str(item["symbol"]))

    def daily_bars(
        self,
        symbols: list[str],
        *,
        start: date,
        end: date | datetime,
        batch_size: int = 40,
    ) -> dict[str, list[dict[str, Any]]]:
        feeds = [self.historical_feed]
        if (
            self.historical_fallback_feed
            and self.historical_fallback_feed != self.historical_feed
        ):
            feeds.append(self.historical_fallback_feed)
        for index, feed in enumerate(feeds):
            try:
                result = self._daily_bars_for_feed(
                    symbols,
                    start=start,
                    end=end,
                    batch_size=batch_size,
                    feed=feed,
                )
            except ProviderError as exc:
                if index == 0 and len(feeds) > 1 and self._feed_access_denied(exc):
                    self.provider_warnings.append(
                        f"Alpaca delayed {feed.upper()} history was unavailable; "
                        f"fell back to {feeds[1].upper()} ({' '.join(str(exc).split())[:180]})"
                    )
                    continue
                raise
            self.bars_feed_used = feed
            return result
        raise ProviderError("No Alpaca historical feed was operational")

    @staticmethod
    def _feed_access_denied(exc: Exception) -> bool:
        message = " ".join(str(exc).lower().split())
        return any(
            marker in message
            for marker in (
                "http 401",
                "http 403",
                "subscription does not permit",
                "feed is not permitted",
                "not authorized",
            )
        )

    def _daily_bars_for_feed(
        self,
        symbols: list[str],
        *,
        start: date,
        end: date,
        batch_size: int,
        feed: str,
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
        for batch in chunks(symbols, batch_size):
            token: str | None = None
            while True:
                payload = get_json(
                    f"{ALPACA_DATA_URL}/bars",
                    params={
                        "symbols": ",".join(batch),
                        "timeframe": "1Day",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "limit": 10000,
                        "adjustment": "all",
                        "feed": feed,
                        "sort": "asc",
                        "page_token": token,
                    },
                    headers=self.headers,
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
                    raise ProviderError("Alpaca bars response is malformed")
                for symbol, bars in payload["bars"].items():
                    if symbol in result and isinstance(bars, list):
                        result[symbol].extend(bars)
                token = payload.get("next_page_token")
                if not token:
                    break
        return result

    def snapshots(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for batch in chunks(symbols, 100):
            payload = get_json(
                f"{ALPACA_DATA_URL}/snapshots",
                params={"symbols": ",".join(batch), "feed": self.realtime_feed},
                headers=self.headers,
            )
            if isinstance(payload, dict):
                output.update({key: value for key, value in payload.items() if isinstance(value, dict)})
        self.snapshot_feed_used = self.realtime_feed
        return output

    def market_news(self, *, hours: int = 36, limit: int = 200) -> list[dict[str, Any]]:
        """Return recent market-wide news for event discovery, never as primary evidence."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        rows: list[dict[str, Any]] = []
        token: str | None = None
        while len(rows) < limit:
            payload = get_json(
                "https://data.alpaca.markets/v1beta1/news",
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "sort": "desc",
                    "limit": min(50, limit - len(rows)),
                    "include_content": "false",
                    "page_token": token,
                },
                headers=self.headers,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("news"), list):
                raise ProviderError("Alpaca news response is malformed")
            rows.extend(item for item in payload["news"] if isinstance(item, dict))
            token = payload.get("next_page_token")
            if not token:
                break
        return rows[:limit]


class AlphaVantageProvider:
    def __init__(
        self,
        api_key: str,
        min_interval_seconds: float = 13.0,
        call_budget: int = 25,
    ) -> None:
        self.api_key = api_key
        self.min_interval_seconds = min_interval_seconds
        self.call_budget = call_budget
        self.call_count = 0
        self._last_call = 0.0

    def _call(self, function: str, symbol: str) -> dict[str, Any]:
        if self.call_count >= self.call_budget:
            raise ProviderError(
                f"Alpha Vantage daily free-call budget exhausted ({self.call_budget})"
            )
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self.call_count += 1
        payload = get_json(
            ALPHA_VANTAGE_URL,
            params={"function": function, "symbol": symbol, "apikey": self.api_key},
        )
        self._last_call = time.monotonic()
        if not isinstance(payload, dict):
            raise ProviderError(f"Alpha Vantage {function} returned malformed data")
        for key in ("Error Message", "Information", "Note"):
            if key in payload:
                raise ProviderError(f"Alpha Vantage {function}: {payload[key]}")
        if not payload:
            raise ProviderError(f"Alpha Vantage {function} returned no data for {symbol}")
        return payload

    def overview(self, symbol: str) -> dict[str, Any]:
        return self._call("OVERVIEW", symbol)

    def earnings_estimates(self, symbol: str) -> dict[str, Any]:
        return self._call("EARNINGS_ESTIMATES", symbol)

    @staticmethod
    def _quarterly_reports(payload: dict[str, Any], function: str) -> list[dict[str, Any]]:
        rows = payload.get("quarterlyReports")
        if not isinstance(rows, list) or len(rows) < 5:
            raise ProviderError(
                f"Alpha Vantage {function} returned fewer than five quarterly reports"
            )
        return [item for item in rows if isinstance(item, dict)][:8]

    @staticmethod
    def _numeric(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed

    def company_bundle(
        self,
        symbol: str,
        *,
        profile: dict[str, Any] | None = None,
        cik_hint: Any = None,
    ) -> dict[str, Any]:
        income_raw = self._quarterly_reports(
            self._call("INCOME_STATEMENT", symbol), "INCOME_STATEMENT"
        )
        balance_raw = self._quarterly_reports(
            self._call("BALANCE_SHEET", symbol), "BALANCE_SHEET"
        )
        cash_raw = self._quarterly_reports(
            self._call("CASH_FLOW", symbol), "CASH_FLOW"
        )
        balance_by_date = {
            str(row.get("fiscalDateEnding")): row for row in balance_raw
        }
        income = []
        for row in income_raw:
            report_date = str(row.get("fiscalDateEnding") or "")
            balance_row = balance_by_date.get(report_date, {})
            income.append(
                {
                    "date": report_date,
                    "period": "Q",
                    "revenue": row.get("totalRevenue"),
                    "grossProfit": row.get("grossProfit"),
                    "operatingIncome": row.get("operatingIncome"),
                    "netIncome": row.get("netIncome"),
                    "weightedAverageShsOut": balance_row.get("commonStockSharesOutstanding"),
                    "weightedAverageShsOutDil": balance_row.get("commonStockSharesOutstanding"),
                }
            )
        balance = []
        for row in balance_raw:
            current_debt = self._numeric(row.get("currentDebt"))
            noncurrent_debt = self._numeric(
                row.get("longTermDebtNoncurrent") or row.get("longTermDebt")
            )
            debt = self._numeric(row.get("shortLongTermDebtTotal"))
            if debt is None and (current_debt is not None or noncurrent_debt is not None):
                debt = (current_debt or 0.0) + (noncurrent_debt or 0.0)
            balance.append(
                {
                    "date": row.get("fiscalDateEnding"),
                    "period": "Q",
                    "totalAssets": row.get("totalAssets"),
                    "totalCurrentAssets": row.get("totalCurrentAssets"),
                    "totalCurrentLiabilities": row.get("totalCurrentLiabilities"),
                    "totalStockholdersEquity": row.get("totalShareholderEquity"),
                    "totalDebt": debt,
                    "cashAndCashEquivalents": row.get("cashAndCashEquivalentsAtCarryingValue"),
                }
            )
        cashflow = []
        for row in cash_raw:
            operating = self._numeric(row.get("operatingCashflow"))
            capex = self._numeric(row.get("capitalExpenditures"))
            cashflow.append(
                {
                    "date": row.get("fiscalDateEnding"),
                    "period": "Q",
                    "operatingCashFlow": operating,
                    "capitalExpenditure": capex,
                    "freeCashFlow": (
                        operating - abs(capex)
                        if operating is not None and capex is not None
                        else None
                    ),
                }
            )
        profile_row = dict(profile or {})
        cik = SecProvider.normalize_cik(cik_hint or profile_row.get("CIK"))
        return {
            "provider": "alpha-vantage-fundamentals",
            "cik": cik,
            "company": profile_row.get("Name") or symbol,
            "profile": {
                "companyName": profile_row.get("Name") or symbol,
                "exchangeShortName": profile_row.get("Exchange"),
                "sector": profile_row.get("Sector"),
                "industry": profile_row.get("Industry"),
                "cik": cik,
                "marketCap": profile_row.get("MarketCapitalization"),
                "sharesOutstanding": balance_raw[0].get("commonStockSharesOutstanding"),
            },
            "statements": {
                "income": income,
                "balance": balance,
                "cashflow": cashflow,
            },
            "latest_filings": [],
            "filing_evidence_status": "primary-links-require-sec-review",
            "filing_evidence_method": "Alpha Vantage normalized statements; SEC filing must be opened before final underwriting",
            "statement_coverage": {
                "income_quarters": len(income),
                "balance_quarters": len(balance),
                "cashflow_quarters": len(cashflow),
                "minimum_five_quarters_complete": min(len(income), len(balance), len(cashflow)) >= 5,
            },
            "source_urls": {
                "alpha_vantage_documentation": "https://www.alphavantage.co/documentation/",
                "sec_company_search": f"https://www.sec.gov/edgar/browse/?CIK={cik}" if cik else "https://www.sec.gov/edgar/search/",
            },
        }


class FredProvider:
    SERIES = {
        "fed_funds": "DFF",
        "treasury_2y": "DGS2",
        "treasury_10y": "DGS10",
        "unemployment": "UNRATE",
        "cpi": "CPIAUCSL",
        "baa_spread": "BAA10Y",
    }

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def latest(self, series_id: str, limit: int = 24) -> list[dict[str, Any]]:
        payload = get_json(
            f"{FRED_URL}/series/observations",
            params={
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
        )
        observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(observations, list):
            raise ProviderError(f"FRED returned malformed data for {series_id}")
        return [item for item in observations if item.get("value") not in {None, "."}]

    def macro_snapshot(self) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for name, series_id in self.SERIES.items():
            observations = self.latest(series_id)
            latest = observations[0] if observations else None
            output[name] = {
                "series_id": series_id,
                "date": latest.get("date") if latest else None,
                "value": float(latest["value"]) if latest else None,
                "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
            }
        return output


class FmpProvider:
    """Normalized fundamentals and filing metadata used when SEC blocks cloud runners."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _call(self, endpoint: str, **params: Any) -> list[dict[str, Any]]:
        payload = get_json(
            f"{FMP_URL}/{endpoint}",
            params={**params, "apikey": self.api_key},
        )
        if isinstance(payload, dict):
            message = payload.get("Error Message") or payload.get("error") or payload.get("message")
            if message:
                raise ProviderError(f"FMP {endpoint}: {message}")
        if not isinstance(payload, list):
            raise ProviderError(f"FMP {endpoint} returned malformed data")
        return [item for item in payload if isinstance(item, dict)]

    def company_bundle(self, symbol: str, cik_hint: Any = None) -> dict[str, Any]:
        profile = self._call("profile", symbol=symbol)
        income = self._call(
            "income-statement", symbol=symbol, period="quarter", limit=5
        )
        balance = self._call(
            "balance-sheet-statement", symbol=symbol, period="quarter", limit=5
        )
        cashflow = self._call(
            "cash-flow-statement", symbol=symbol, period="quarter", limit=5
        )
        if not profile:
            raise ProviderError(f"FMP profile returned no data for {symbol}")
        missing = [
            name
            for name, rows in (("income", income), ("balance", balance), ("cashflow", cashflow))
            if not rows
        ]
        if missing:
            raise ProviderError(
                f"FMP missing quarterly statements for {symbol}: {', '.join(missing)}"
            )
        material_filings: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for rows in (income, balance, cashflow):
            for row in rows:
                filing_url = str(row.get("finalLink") or row.get("link") or "").strip()
                if not filing_url.startswith("https://") or filing_url in seen_urls:
                    continue
                seen_urls.add(filing_url)
                period = str(row.get("period") or "").upper()
                material_filings.append(
                    {
                        "accessionNumber": row.get("accessionNumber"),
                        "filingDate": row.get("fillingDate") or row.get("filingDate") or row.get("acceptedDate"),
                        "reportDate": row.get("date"),
                        "formType": row.get("formType") or ("10-K" if period == "FY" else "10-Q"),
                        "finalLink": filing_url,
                    }
                )
        profile_row = profile[0]
        cik = SecProvider.normalize_cik(cik_hint or profile_row.get("cik"))
        return {
            "provider": "fmp",
            "cik": cik,
            "company": profile_row.get("companyName") or profile_row.get("companyNameLong"),
            "profile": profile_row,
            "statements": {
                "income": income,
                "balance": balance,
                "cashflow": cashflow,
            },
            "latest_filings": material_filings,
            "filing_evidence_status": (
                "linked" if material_filings else "links-unavailable-on-free-plan"
            ),
            "source_urls": {
                "profile": f"{FMP_URL}/profile?symbol={symbol}",
                "income": f"{FMP_URL}/income-statement?symbol={symbol}&period=quarter",
                "balance": f"{FMP_URL}/balance-sheet-statement?symbol={symbol}&period=quarter",
                "cashflow": f"{FMP_URL}/cash-flow-statement?symbol={symbol}&period=quarter",
            },
            "filing_evidence_method": "links embedded in FMP financial-statement responses",
        }


class SecProvider:
    def __init__(
        self,
        user_agent: str,
        *,
        bulk_archive: RemoteZipJsonArchive | None = None,
    ) -> None:
        self.headers = {"User-Agent": user_agent}
        self._ticker_map: dict[str, dict[str, Any]] | None = None
        self._direct_enabled = True
        self._bulk_archive = bulk_archive

    def ticker_map(self) -> dict[str, dict[str, Any]]:
        if self._ticker_map is None:
            payload = get_json(SEC_TICKERS_URL, headers=self.headers)
            if not isinstance(payload, dict):
                raise ProviderError("SEC ticker map is malformed")
            self._ticker_map = {
                str(item["ticker"]).upper(): item
                for item in payload.values()
                if isinstance(item, dict) and item.get("ticker")
            }
        return self._ticker_map

    @staticmethod
    def normalize_cik(value: Any) -> str | None:
        digits = re.sub(r"\D", "", str(value or ""))
        if not digits or len(digits) > 10:
            return None
        return digits.zfill(10)

    def company_bundle(self, symbol: str, cik_hint: Any = None) -> dict[str, Any]:
        cik = self.normalize_cik(cik_hint)
        entry: dict[str, Any] | None = None
        if cik is None:
            entry = self.ticker_map().get(symbol.upper())
            if not entry:
                raise ProviderError(f"SEC CIK mapping unavailable for {symbol}")
            cik = self.normalize_cik(entry.get("cik_str"))
        if cik is None:
            raise ProviderError(f"SEC CIK is invalid for {symbol}")
        submissions: dict[str, Any] = {}
        companyfacts: dict[str, Any] | None = None
        direct_error: str | None = None
        provider = "sec-xbrl-direct"
        if self._direct_enabled:
            try:
                raw_submissions = get_json(
                    f"{SEC_DATA_URL}/submissions/CIK{cik}.json", headers=self.headers
                )
                if isinstance(raw_submissions, dict):
                    submissions = raw_submissions
                time.sleep(0.15)
                raw_companyfacts = get_json(
                    f"{SEC_DATA_URL}/api/xbrl/companyfacts/CIK{cik}.json",
                    headers=self.headers,
                )
                if not isinstance(raw_companyfacts, dict):
                    raise ProviderError("SEC Company Facts response is malformed")
                companyfacts = raw_companyfacts
            except ProviderError as exc:
                direct_error = " ".join(str(exc).split())[:240]
                self._direct_enabled = False

        if companyfacts is None:
            provider = "sec-xbrl-bulk"
            try:
                if self._bulk_archive is None:
                    self._bulk_archive = RemoteZipJsonArchive(
                        SEC_COMPANYFACTS_BULK_URL,
                        headers=self.headers,
                    )
                companyfacts = self._bulk_archive.read_json(f"CIK{cik}.json")
            except ProviderError as bulk_exc:
                raise ProviderError(
                    "SEC infrastructure unavailable: direct Company Facts failed"
                    + (f" ({direct_error})" if direct_error else "")
                    + f"; bulk Company Facts failed ({bulk_exc})"
                ) from bulk_exc

        try:
            bundle = normalize_companyfacts(
                companyfacts,
                cik=cik,
                symbol=symbol,
                submissions=submissions,
                provider=provider,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"SEC XBRL normalization failed for {symbol}: {exc}") from exc
        coverage = bundle.get("statement_coverage") or {}
        if not coverage.get("minimum_five_quarters_complete"):
            raise ProviderError(
                f"SEC XBRL coverage unavailable for {symbol}: "
                f"income={coverage.get('income_quarters', 0)}, "
                f"balance={coverage.get('balance_quarters', 0)}, "
                f"cashflow={coverage.get('cashflow_quarters', 0)} quarters"
            )
        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        companyfacts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        bundle.update(
            {
                "submissions": submissions,
                "companyfacts": companyfacts,
                "submissions_url": submissions_url,
                "companyfacts_url": companyfacts_url,
                "source_urls": {
                    "sec_submissions": submissions_url,
                    "sec_companyfacts": companyfacts_url,
                    "sec_companyfacts_bulk": SEC_COMPANYFACTS_BULK_URL,
                },
            }
        )
        if provider == "sec-xbrl-bulk" and direct_error:
            bundle["provider_warning"] = (
                f"SEC direct API unavailable ({direct_error}); official nightly "
                "Company Facts bulk archive used"
            )
        return bundle


def default_history_window(today: date | None = None) -> tuple[date, date]:
    current = today or date.today()
    return current - timedelta(days=420), current + timedelta(days=1)


def completed_market_data_cutoff(
    now: datetime | None = None,
    *,
    delay_minutes: int = 20,
) -> datetime:
    """Return an Alpaca SIP-safe end timestamp that excludes an open U.S. session."""
    if delay_minutes < 16:
        raise ValueError("delay_minutes must stay above Alpaca's 15-minute SIP delay")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    eastern_zone = ZoneInfo("America/New_York")
    eastern = current.astimezone(eastern_zone)
    close_plus_delay = eastern.replace(
        hour=16,
        minute=delay_minutes,
        second=0,
        microsecond=0,
    )
    if eastern.weekday() < 5 and eastern >= close_plus_delay:
        cutoff = eastern - timedelta(minutes=delay_minutes)
    else:
        cutoff = eastern.replace(hour=0, minute=0, second=0, microsecond=0)
    return cutoff.astimezone(timezone.utc)
