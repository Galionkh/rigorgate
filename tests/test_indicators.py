from __future__ import annotations

import unittest
import json
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rigorgate.cache import JsonFundamentalCache
from rigorgate.dashboard import render_dashboard
from rigorgate.forensics import analyze_statements
from rigorgate.indicators import build_snapshot, combine_regime, market_breadth, market_regime
from rigorgate.discovery import build_research_queue, diversified_shortlist, event_risk_flags
from rigorgate.events import materiality_score, normalize_news
from rigorgate.http import ProviderError
from rigorgate.providers import (
    AlpacaProvider,
    AlphaVantageProvider,
    FmpProvider,
    SecProvider,
    completed_market_data_cutoff,
)
from rigorgate.remote_zip import RemoteZipJsonArchive
from rigorgate.sec_xbrl import normalize_companyfacts
from rigorgate.scanner import (
    company_bundle_with_fallback,
    concise_provider_error,
    fmp_overview_from_bundle,
    latest_filings,
    provider_quota_exhausted,
    quote_spread_bps,
    require_deep_data_coverage,
    sector_leadership,
    sector_etf_for_name,
    long_eligibility,
)
from rigorgate.scoring import fundamental_score, revision_score, valuation_score
from rigorgate.tracking import SignalLedger


def bars(count: int = 260, start: float = 100.0, step: float = 0.25) -> list[dict]:
    first = date(2025, 1, 1)
    output = []
    for index in range(count):
        close = start + step * index
        output.append(
            {
                "t": (first + timedelta(days=index)).isoformat(),
                "o": close - 0.2,
                "h": close + 1.0,
                "l": close - 1.0,
                "c": close,
                "v": 1_000_000 + index * 1_000,
            }
        )
    return output


class IndicatorTests(unittest.TestCase):
    def test_market_data_cutoff_uses_delayed_close_and_excludes_open_session(self) -> None:
        after_close = completed_market_data_cutoff(
            datetime(2026, 8, 27, 21, 0, tzinfo=timezone.utc)
        )
        during_session = completed_market_data_cutoff(
            datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(after_close, datetime(2026, 8, 27, 20, 40, tzinfo=timezone.utc))
        self.assertEqual(during_session, datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc))

    def test_alpaca_prefers_delayed_sip_and_falls_back_only_when_unauthorized(self) -> None:
        requested_feeds = []

        def fake_get_json(url, *, params=None, headers=None, config=None):
            feed = (params or {}).get("feed")
            requested_feeds.append(feed)
            if feed == "sip":
                raise ProviderError("HTTP 403 from Alpaca: subscription does not permit SIP")
            return {"bars": {"AAA": []}, "next_page_token": None}

        provider = AlpacaProvider("key", "secret")
        with patch("rigorgate.providers.get_json", side_effect=fake_get_json):
            result = provider.daily_bars(
                ["AAA"], start=date(2026, 1, 1), end=date(2026, 1, 2)
            )
        self.assertEqual(result, {"AAA": []})
        self.assertEqual(requested_feeds, ["sip", "iex"])
        self.assertEqual(provider.bars_feed_used, "iex")
        self.assertEqual(len(provider.provider_warnings), 1)

    def test_snapshot_is_bounded_and_liquid(self) -> None:
        snapshot = build_snapshot(bars())
        self.assertGreaterEqual(snapshot.technical_score, 0)
        self.assertLessEqual(snapshot.technical_score, 100)
        self.assertGreater(snapshot.avg_dollar_volume_20d, 20_000_000)
        self.assertGreater(snapshot.sma50, snapshot.sma200)

    def test_insufficient_history_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_snapshot(bars(199))

    def test_market_regime(self) -> None:
        snapshot = build_snapshot(bars())
        self.assertEqual(market_regime(snapshot, snapshot, snapshot), "supportive")

    def test_stage_classification_and_breadth(self) -> None:
        rising = build_snapshot(bars(start=100.0, step=0.35))
        falling = build_snapshot(bars(start=300.0, step=-0.35))
        self.assertEqual(rising.stage, 2)
        self.assertEqual(falling.stage, 4)
        breadth = market_breadth({"UP1": rising, "UP2": rising, "UP3": rising, "UP4": rising, "DOWN": falling})
        self.assertGreater(breadth["above_sma50_pct"], 50)
        self.assertEqual(combine_regime("supportive", breadth), "supportive")

    def test_sector_leadership_ranks_relative_strength(self) -> None:
        spy = build_snapshot(bars(step=0.15))
        strong = build_snapshot(bars(step=0.40))
        weak = build_snapshot(bars(start=200.0, step=-0.10))
        ranks = sector_leadership({"XLK": strong, "XLE": weak}, spy)
        self.assertEqual(ranks["XLK"]["rank"], 1)
        self.assertEqual(ranks["XLE"]["rank"], 2)
        self.assertEqual(sector_etf_for_name("TECHNOLOGY"), "XLK")

    def test_stage_four_is_not_long_eligible(self) -> None:
        falling = build_snapshot(bars(start=300.0, step=-0.35))
        eligible, blockers = long_eligibility(falling, [], {"flags": []})
        self.assertFalse(eligible)
        self.assertIn("stage_4_downtrend_for_long", blockers)

    def test_diversified_research_queue(self) -> None:
        spy = build_snapshot(bars())
        snapshots = {
            "AAA": build_snapshot(bars(step=0.30)),
            "BBB": build_snapshot(bars(step=0.05)),
            "CCC": build_snapshot(bars(step=-0.05, start=200.0)),
        }
        queue = build_research_queue(snapshots, spy, per_archetype=1, limit=3)
        self.assertGreaterEqual(len(queue), 1)
        self.assertIn(queue[0]["primary_archetype"], {"momentum", "pullback", "reversal", "breakout", "event_shock"})
        self.assertIn("archetype_scores", queue[0])

    def test_event_shock_flag(self) -> None:
        shocked = bars()
        shocked[-1]["o"] = shocked[-2]["c"] * 1.20
        shocked[-1]["c"] = shocked[-2]["c"] * 1.25
        shocked[-1]["h"] = shocked[-1]["c"] * 1.01
        shocked[-1]["l"] = shocked[-1]["o"] * 0.99
        shocked[-1]["v"] = 20_000_000
        flags = event_risk_flags(build_snapshot(shocked))
        self.assertIn("extreme_one_day_move", flags)
        self.assertIn("large_opening_gap", flags)

    def test_deep_shortlist_reserves_archetypes(self) -> None:
        queue = [
            {
                "symbol": "MOM",
                "discovery_rank": 95,
                "archetype_scores": {"momentum": 95, "pullback": 0, "reversal": 0, "breakout": 60, "event_shock": 0},
            },
            {
                "symbol": "REV",
                "discovery_rank": 70,
                "archetype_scores": {"momentum": 40, "pullback": 0, "reversal": 90, "breakout": 0, "event_shock": 0},
            },
            {
                "symbol": "EVT",
                "discovery_rank": 65,
                "archetype_scores": {"momentum": 30, "pullback": 0, "reversal": 0, "breakout": 0, "event_shock": 95},
            },
        ]
        symbols = {row["symbol"] for row in diversified_shortlist(queue, per_archetype=1, limit=3)}
        self.assertEqual(symbols, {"MOM", "REV", "EVT"})

    def test_spread(self) -> None:
        value = quote_spread_bps({"latestQuote": {"bp": 99.9, "ap": 100.1}})
        self.assertAlmostEqual(value, 20.0)

    def test_sec_cik_normalization(self) -> None:
        self.assertEqual(SecProvider.normalize_cik("320193"), "0000320193")
        self.assertEqual(SecProvider.normalize_cik("CIK0000320193"), "0000320193")
        self.assertIsNone(SecProvider.normalize_cik("not-available"))

    def test_provider_error_is_concise(self) -> None:
        output = concise_provider_error("AAPL", RuntimeError("x" * 1000))
        self.assertLessEqual(len(output), 246)

    def test_zero_deep_data_fails_run_closed(self) -> None:
        with self.assertRaises(ProviderError):
            require_deep_data_coverage(8, 0, ["SEC unavailable"])

    def test_partial_deep_data_can_continue(self) -> None:
        require_deep_data_coverage(8, 4, ["one provider warning"])

    def test_free_data_run_can_continue_with_three_complete_bundles(self) -> None:
        require_deep_data_coverage(10, 3, ["unsupported symbols skipped"])

    def test_two_complete_bundles_are_not_enough(self) -> None:
        with self.assertRaises(ProviderError):
            require_deep_data_coverage(10, 2, ["unsupported symbols skipped"])

    def test_provider_quota_detection(self) -> None:
        self.assertTrue(provider_quota_exhausted(ProviderError("daily API limit reached")))
        self.assertTrue(provider_quota_exhausted(ProviderError("standard API rate limit")))
        self.assertFalse(provider_quota_exhausted(ProviderError("no data for symbol")))

    @patch("rigorgate.providers.get_json")
    def test_fmp_bundle_requires_statements_and_material_filings(self, get_json_mock) -> None:
        get_json_mock.side_effect = [
            [{"symbol": "AAPL", "companyName": "Apple Inc.", "cik": "320193"}],
            [{"date": "2026-06-30", "period": "Q3", "finalLink": "https://example.test/10q"}],
            [{"date": "2026-06-30", "period": "Q3", "finalLink": "https://example.test/10q"}],
            [{"date": "2026-06-30", "period": "Q3", "finalLink": "https://example.test/10q"}],
        ]
        bundle = FmpProvider("secret-not-logged").company_bundle("AAPL")
        self.assertEqual(bundle["provider"], "fmp")
        self.assertEqual(bundle["cik"], "0000320193")
        self.assertEqual(latest_filings(bundle)[0]["form"], "10-Q")
        self.assertNotIn("secret-not-logged", str(bundle))
        self.assertEqual(get_json_mock.call_count, 4)
        self.assertNotIn("sec-filings-search", str(get_json_mock.call_args_list))
        for call in get_json_mock.call_args_list[1:]:
            self.assertEqual(call.kwargs["params"]["limit"], 5)

    @patch("rigorgate.providers.get_json")
    def test_fmp_bundle_marks_missing_free_plan_filing_links(self, get_json_mock) -> None:
        get_json_mock.side_effect = [
            [{"symbol": "AAPL", "companyName": "Apple Inc."}],
            [{"date": "2026-06-30"}],
            [{"date": "2026-06-30"}],
            [{"date": "2026-06-30"}],
        ]
        bundle = FmpProvider("secret-not-logged").company_bundle("AAPL")
        self.assertEqual(bundle["filing_evidence_status"], "links-unavailable-on-free-plan")
        self.assertEqual(bundle["latest_filings"], [])

    @patch("rigorgate.providers.get_json")
    def test_fmp_bundle_fails_closed_without_statements(self, get_json_mock) -> None:
        get_json_mock.side_effect = [
            [{"symbol": "AAPL", "companyName": "Apple Inc."}],
            [{"date": "2026-06-30"}],
            [],
            [{"date": "2026-06-30"}],
        ]
        with self.assertRaises(ProviderError):
            FmpProvider("secret-not-logged").company_bundle("AAPL")

    @patch("rigorgate.providers.get_json")
    def test_alpha_vantage_bundle_normalizes_five_quarters(self, get_json_mock) -> None:
        dates = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
        get_json_mock.side_effect = [
            {"quarterlyReports": [
                {
                    "fiscalDateEnding": value,
                    "totalRevenue": "100",
                    "grossProfit": "50",
                    "operatingIncome": "20",
                    "netIncome": "15",
                }
                for value in dates
            ]},
            {"quarterlyReports": [
                {
                    "fiscalDateEnding": value,
                    "totalAssets": "1000",
                    "totalCurrentAssets": "300",
                    "totalCurrentLiabilities": "150",
                    "totalShareholderEquity": "500",
                    "shortLongTermDebtTotal": "100",
                    "commonStockSharesOutstanding": "10",
                }
                for value in dates
            ]},
            {"quarterlyReports": [
                {
                    "fiscalDateEnding": value,
                    "operatingCashflow": "25",
                    "capitalExpenditures": "-5",
                }
                for value in dates
            ]},
        ]
        provider = AlphaVantageProvider("secret-not-logged", min_interval_seconds=0)
        bundle = provider.company_bundle(
            "TEST",
            profile={"Name": "Test", "Sector": "Technology", "MarketCapitalization": "1000"},
            cik_hint="320193",
        )
        self.assertEqual(bundle["provider"], "alpha-vantage-fundamentals")
        self.assertEqual(bundle["statements"]["cashflow"][0]["freeCashFlow"], 20.0)
        self.assertTrue(bundle["statement_coverage"]["minimum_five_quarters_complete"])
        self.assertEqual(provider.call_count, 3)

    def test_alpha_vantage_local_budget_fails_closed(self) -> None:
        provider = AlphaVantageProvider("secret-not-logged", call_budget=0)
        with self.assertRaises(ProviderError):
            provider.overview("AAPL")

    def test_fmp_fallback_after_sec_block(self) -> None:
        class BlockedSec:
            def company_bundle(self, symbol, cik_hint=None):
                raise ProviderError("HTTP 403")

        class WorkingFmp:
            def company_bundle(self, symbol, cik_hint=None):
                return {"provider": "fmp", "cik": cik_hint}

        bundle, warning, sec_working = company_bundle_with_fallback(
            "AAPL", "0000320193", BlockedSec(), WorkingFmp()
        )
        self.assertEqual(bundle["provider"], "fmp")
        self.assertIn("FMP fallback used", warning)
        self.assertFalse(sec_working)

    def test_fmp_overview_uses_reported_and_derived_fields(self) -> None:
        income = [
            {"revenue": 100 + index * 5, "netIncome": 20 + index, "operatingIncome": 25 + index}
            for index in range(5)
        ]
        bundle = {
            "cik": "0000320193",
            "company": "Apple Inc.",
            "profile": {"companyName": "Apple Inc.", "marketCap": 1000, "sector": "Technology"},
            "statements": {"income": income, "balance": [{"totalStockholdersEquity": 400}]},
        }
        overview = fmp_overview_from_bundle(bundle)
        self.assertEqual(overview["MarketCapitalization"], 1000)
        self.assertGreater(overview["ProfitMargin"], 0)
        self.assertIn("QuarterlyRevenueGrowthYOY", overview)
        self.assertNotIn("ForwardPE", overview)

    def test_remote_zip_reads_only_selected_json_member(self) -> None:
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("CIK0000320193.json", json.dumps({"entityName": "Apple Inc."}))
            archive.writestr("CIK0000789019.json", json.dumps({"entityName": "Microsoft"}))
        payload = memory.getvalue()
        ranges: list[tuple[int, int]] = []

        def reader(start: int, end: int) -> tuple[bytes, int]:
            ranges.append((start, end))
            return payload[start : end + 1], len(payload)

        archive = RemoteZipJsonArchive(
            "https://example.test/companyfacts.zip", range_reader=reader
        )
        output = archive.read_json("CIK0000320193.json")
        self.assertEqual(output["entityName"], "Apple Inc.")
        self.assertLess(sum(end - start + 1 for start, end in ranges), len(payload) * 3)

    def test_sec_companyfacts_normalizes_and_derives_discrete_quarters(self) -> None:
        def duration_rows(values: list[float], unit: str = "USD") -> dict:
            periods = [
                ("2025-01-01", "2025-03-31", "Q1", "10-Q"),
                ("2025-01-01", "2025-06-30", "Q2", "10-Q"),
                ("2025-01-01", "2025-09-30", "Q3", "10-Q"),
                ("2025-01-01", "2025-12-31", "FY", "10-K"),
                ("2026-01-01", "2026-03-31", "Q1", "10-Q"),
            ]
            return {
                "units": {
                    unit: [
                        {
                            "start": start,
                            "end": end,
                            "val": value,
                            "accn": f"0000320193-26-00000{index}",
                            "fy": 2025 if index < 4 else 2026,
                            "fp": fp,
                            "form": form,
                            "filed": "2026-05-01" if index == 4 else "2026-02-01",
                        }
                        for index, ((start, end, fp, form), value) in enumerate(
                            zip(periods, values), start=1
                        )
                    ]
                }
            }

        ends = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]

        def instant_rows(values: list[float]) -> dict:
            return {
                "units": {
                    "USD": [
                        {
                            "end": end,
                            "val": value,
                            "accn": f"0000320193-26-10000{index}",
                            "fy": 2025 if index < 4 else 2026,
                            "fp": "FY" if index == 3 else "Q1",
                            "form": "10-K" if index == 3 else "10-Q",
                            "filed": "2026-05-01" if index == 4 else "2026-02-01",
                        }
                        for index, (end, value) in enumerate(zip(ends, values))
                    ]
                }
            }

        companyfacts = {
            "entityName": "Test Technology Inc.",
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": duration_rows([100, 220, 360, 520, 180]),
                    "GrossProfit": duration_rows([50, 115, 190, 270, 95]),
                    "OperatingIncomeLoss": duration_rows([20, 45, 75, 110, 40]),
                    "NetIncomeLoss": duration_rows([15, 34, 57, 82, 30]),
                    "WeightedAverageNumberOfSharesOutstandingBasic": duration_rows([100, 200, 300, 400, 100], "shares"),
                    "Assets": instant_rows([900, 920, 940, 960, 990]),
                    "AssetsCurrent": instant_rows([300, 310, 320, 330, 340]),
                    "LiabilitiesCurrent": instant_rows([150, 155, 160, 165, 170]),
                    "StockholdersEquity": instant_rows([500, 510, 520, 530, 550]),
                    "LongTermDebt": instant_rows([100, 95, 90, 85, 80]),
                    "NetCashProvidedByUsedInOperatingActivities": duration_rows([20, 45, 75, 110, 40]),
                    "PaymentsToAcquirePropertyPlantAndEquipment": duration_rows([5, 12, 21, 30, 8]),
                },
                "dei": {},
            },
        }
        bundle = normalize_companyfacts(
            companyfacts,
            cik="0000320193",
            symbol="TEST",
            submissions={
                "name": "Test Technology Inc.",
                "tickers": ["TEST"],
                "exchanges": ["Nasdaq"],
                "sic": "3571",
                "sicDescription": "Electronic Computers",
            },
            provider="sec-xbrl-bulk",
        )
        income = bundle["statements"]["income"]
        cashflow = bundle["statements"]["cashflow"]
        self.assertTrue(bundle["statement_coverage"]["minimum_five_quarters_complete"])
        self.assertEqual(bundle["profile"]["sector"], "Technology")
        self.assertEqual(income[1]["revenue"], 160.0)
        self.assertEqual(income[2]["revenue"], 140.0)
        self.assertEqual(cashflow[1]["freeCashFlow"], 26.0)
        self.assertTrue(bundle["latest_filings"][0]["finalLink"].startswith("https://www.sec.gov/Archives/edgar/"))


class ScoringTests(unittest.TestCase):
    def test_scores_are_bounded(self) -> None:
        overview = {
            "ProfitMargin": "0.2",
            "OperatingMarginTTM": "0.22",
            "ReturnOnEquityTTM": "0.3",
            "QuarterlyRevenueGrowthYOY": "0.18",
            "QuarterlyEarningsGrowthYOY": "0.25",
            "ForwardPE": "17",
            "PEGRatio": "1.2",
            "EVToEBITDA": "11",
            "PriceToSalesRatioTTM": "2.5",
        }
        self.assertGreaterEqual(fundamental_score(overview), 80)
        self.assertGreaterEqual(valuation_score(overview), 80)

    def test_missing_forward_estimates_are_neutral_not_false_failures(self) -> None:
        score = valuation_score(
            {"TrailingPE": 18, "PriceToSalesRatioTTM": 2.5, "PriceToBookRatio": 2.0}
        )
        self.assertGreaterEqual(score, 80)

    def test_revision_parser(self) -> None:
        score, evidence = revision_score(
            {
                "quarterlyEarningsEstimates": [
                    {"epsEstimateAverage": "2.10", "epsEstimateAverage30DaysAgo": "2.00"}
                ]
            }
        )
        self.assertGreater(score, 50)
        self.assertTrue(evidence["available"])


class QualityEngineTests(unittest.TestCase):
    def test_fundamental_cache_expires_and_never_needs_credentials(self) -> None:
        with TemporaryDirectory() as directory:
            cache = JsonFundamentalCache(Path(directory), ttl_days=2)
            now = datetime(2026, 8, 20, tzinfo=timezone.utc)
            cache.set("AAPL", {"overview": {"Name": "Apple"}}, now=now)
            self.assertEqual(cache.get("AAPL", now=now)["overview"]["Name"], "Apple")
            self.assertIsNone(cache.get("AAPL", now=now + timedelta(days=3)))
            self.assertNotIn("api", (Path(directory) / "AAPL.json").read_text(encoding="utf-8").lower())

    def test_forensic_layer_flags_accruals_and_dilution(self) -> None:
        income = []
        balance = []
        cashflow = []
        for index in range(8):
            income.append({
                "netIncome": 40 if index < 4 else 20,
                "revenue": 200,
                "grossProfit": 80 if index < 4 else 70,
                "weightedAverageShsOut": 120 if index < 4 else 100,
            })
            balance.append({
                "totalAssets": 1000,
                "totalDebt": 850 if index == 0 else 700,
                "totalCurrentAssets": 60,
                "totalCurrentLiabilities": 100,
            })
            cashflow.append({"operatingCashFlow": -5, "freeCashFlow": -10})
        output = analyze_statements({"income": income, "balance": balance, "cashflow": cashflow})
        self.assertTrue(output["available"])
        self.assertIn("material_share_dilution", output["flags"])
        self.assertIn("earnings_not_backed_by_cash", output["flags"])
        self.assertGreater(output["penalty"], 0)

    def test_signal_ledger_migrates_and_excludes_legacy_close_entries(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = SignalLedger(path)
            stock = bars(count=160, step=0.40)
            spy = bars(count=160, step=0.10)
            session = str(stock[10]["t"])
            path.write_text(json.dumps({
                "schema_version": 1,
                "signals": [{
                    "signal_type": "screen_grade",
                    "session": session,
                    "symbol": "AAA",
                    "outcomes": {},
                }],
            }), encoding="utf-8")
            candidate = {
                "symbol": "AAA",
                "composite_screen_score": 80,
                "primary_archetype": "momentum",
                "technical": {"close": stock[-1]["c"], "stage": 2},
            }
            summary = ledger.update(session, [candidate], {"AAA": stock, "SPY": spy}, market_regime="supportive")
            payload = ledger.load()
            self.assertEqual(len(payload["signals"]), 1)
            self.assertIn("120d", payload["signals"][0]["outcomes"])
            self.assertEqual(payload["signals"][0]["entry_policy"], "same_session_close_legacy")
            self.assertEqual(summary["legacy_signals_excluded"], 1)
            self.assertEqual(summary["horizons"]["20d"]["observations"], 0)

    def test_shadow_ledger_enters_next_session_open_and_applies_costs(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = SignalLedger(path, round_trip_cost_bps=12)
            stock = bars(count=160, step=0.40)
            spy = bars(count=160, step=0.10)
            session = str(stock[10]["t"])
            candidate = {
                "symbol": "AAA",
                "composite_screen_score": 80,
                "primary_archetype": "momentum",
                "long_eligible_screen": True,
                "long_eligibility_blockers": [],
                "technical": {
                    "close": stock[10]["c"],
                    "stage": 2,
                    "technical_score": 85,
                },
            }

            first = ledger.update(
                session,
                [candidate],
                {"AAA": stock[:11], "SPY": spy[:11]},
                market_regime="supportive",
                market_data_feed="sip",
            )
            self.assertEqual(first["horizons"]["5d"]["observations"], 0)
            self.assertEqual(ledger.load()["signals"][0]["shadow_status"], "awaiting_next_session_open")

            summary = ledger.update(
                session,
                [candidate],
                {"AAA": stock, "SPY": spy},
                market_regime="supportive",
                market_data_feed="sip",
            )
            payload = ledger.load()
            signal = payload["signals"][0]
            self.assertEqual(len(payload["signals"]), 1)
            self.assertEqual(signal["entry_session"], str(stock[11]["t"])[:10])
            self.assertEqual(signal["entry_open"], stock[11]["o"])
            self.assertIn("120d", signal["outcomes"])
            self.assertLess(
                signal["outcomes"]["20d"]["net_return"],
                signal["outcomes"]["20d"]["gross_return"],
            )
            self.assertEqual(summary["horizons"]["20d"]["observations"], 1)
            self.assertFalse(summary["horizons"]["20d"]["performance_claim_ready"])
            self.assertIsNone(summary["horizons"]["20d"]["win_rate_vs_spy_pct"])

    def test_dashboard_renders_safety_boundary_and_candidate(self) -> None:
        report = {
            "run_status": "SCREEN-GRADE COMPLETE",
            "as_of_session": "2026-08-21",
            "market_regime": "mixed",
            "market_breadth": {"posture": "mixed_participation", "stocks_evaluated": 100, "above_sma50_pct": 51, "stage2_pct": 20},
            "universe": {"screen_grade_candidates": 1, "eligible_common_stock_candidates": 5000},
            "cache": {"hits": 1, "misses": 0},
            "signal_performance": {"horizons": {}},
            "candidates": [{
                "symbol": "AAPL", "company": "Apple", "primary_archetype": "momentum",
                "composite_screen_score": 82, "technical": {"stage": 2, "stage_name": "confirmed_uptrend"},
                "sector": "Technology", "sector_context": {"etf": "XLK", "rank": 1},
                "forensic_screen": {"quality_score": 75, "label": "Piotroski-style screen", "flags": []},
                "event_risk_flags": [],
            }],
        }
        output = render_dashboard(report)
        self.assertIn("AAPL", output)
        self.assertIn("Not a buy recommendation", output)


class EventMonitorTests(unittest.TestCase):
    def test_material_clinical_event_is_flagged(self) -> None:
        score, tags = materiality_score("Company says Phase 3 trial met primary endpoint")
        self.assertGreaterEqual(score, 35)
        self.assertIn("clinical_readout", tags)

    def test_noise_is_not_promoted(self) -> None:
        alerts = normalize_news(
            [{"headline": "CEO speaks at conference", "symbols": ["AAA"], "url": "https://example.test"}]
        )
        self.assertEqual(alerts, [])

    def test_alert_requires_symbol_and_primary_verification(self) -> None:
        alerts = normalize_news(
            [{
                "headline": "Biotech Phase 3 trial met primary endpoint",
                "summary": "",
                "symbols": ["MRNA"],
                "url": "https://example.test/story",
                "created_at": "2026-08-19T11:00:00Z",
                "source": "wire",
            }]
        )
        self.assertEqual(alerts[0]["symbols"], ["MRNA"])
        self.assertIn("PRIMARY-SOURCE VERIFICATION", alerts[0]["status"])


if __name__ == "__main__":
    unittest.main()
