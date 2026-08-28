from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HORIZONS = (5, 20, 60, 120)
MIN_MATURED_OBSERVATIONS = 50
DEFAULT_ROUND_TRIP_COST_BPS = 10.0


def _ordered(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: str(item.get("t") or ""))


def _price(row: dict[str, Any], key: str, fallback: str = "c") -> float:
    value = row.get(key)
    if value is None:
        value = row[fallback]
    return float(value)


class SignalLedger:
    """Track screen signals using a realistic next-session-open shadow portfolio."""

    def __init__(
        self,
        path: Path,
        *,
        round_trip_cost_bps: float = DEFAULT_ROUND_TRIP_COST_BPS,
    ) -> None:
        if round_trip_cost_bps < 0:
            raise ValueError("round_trip_cost_bps cannot be negative")
        self.path = path
        self.round_trip_cost_bps = float(round_trip_cost_bps)

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": 2, "signals": []}

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(payload, dict) or not isinstance(payload.get("signals"), list):
            return self._empty()
        return payload

    @staticmethod
    def _dates(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {str(row.get("t") or "")[:10]: index for index, row in enumerate(rows)}

    def _update_legacy_signal(
        self,
        signal: dict[str, Any],
        symbol_rows: list[dict[str, Any]],
        spy_rows: list[dict[str, Any]],
    ) -> None:
        """Preserve pre-v2 measurements without mixing them into the v2 headline."""
        signal["entry_policy"] = "same_session_close_legacy"
        symbol_index = self._dates(symbol_rows).get(str(signal.get("session") or ""))
        spy_index = self._dates(spy_rows).get(str(signal.get("session") or ""))
        if symbol_index is None or spy_index is None:
            return
        outcomes = signal.setdefault("outcomes", {})
        for horizon in HORIZONS:
            key = f"{horizon}d"
            if key in outcomes:
                continue
            if symbol_index + horizon >= len(symbol_rows) or spy_index + horizon >= len(spy_rows):
                continue
            entry = _price(symbol_rows[symbol_index], "c")
            exit_price = _price(symbol_rows[symbol_index + horizon], "c")
            spy_entry = _price(spy_rows[spy_index], "c")
            spy_exit = _price(spy_rows[spy_index + horizon], "c")
            raw_return = exit_price / entry - 1.0
            benchmark_return = spy_exit / spy_entry - 1.0
            window = symbol_rows[symbol_index + 1 : symbol_index + horizon + 1]
            outcomes[key] = {
                "return": round(raw_return, 5),
                "spy_return": round(benchmark_return, 5),
                "excess_return": round(raw_return - benchmark_return, 5),
                "max_favorable_excursion": round(
                    max(_price(row, "h") for row in window) / entry - 1.0, 5
                ),
                "max_adverse_excursion": round(
                    min(_price(row, "l") for row in window) / entry - 1.0, 5
                ),
                "measurement_policy": "same_session_close_legacy",
            }

    def _update_shadow_signal(
        self,
        signal: dict[str, Any],
        symbol_rows: list[dict[str, Any]],
        spy_rows: list[dict[str, Any]],
    ) -> None:
        symbol_dates = self._dates(symbol_rows)
        spy_dates = self._dates(spy_rows)
        signal_date = str(signal.get("session") or "")
        symbol_signal_index = symbol_dates.get(signal_date)
        spy_signal_index = spy_dates.get(signal_date)
        if symbol_signal_index is None or spy_signal_index is None:
            return

        symbol_entry_index = symbol_signal_index + 1
        spy_entry_index = spy_signal_index + 1
        if symbol_entry_index >= len(symbol_rows) or spy_entry_index >= len(spy_rows):
            signal["shadow_status"] = "awaiting_next_session_open"
            return

        entry_row = symbol_rows[symbol_entry_index]
        spy_entry_row = spy_rows[spy_entry_index]
        entry = _price(entry_row, "o")
        spy_entry = _price(spy_entry_row, "o")
        signal.update(
            {
                "entry_session": str(entry_row.get("t") or "")[:10],
                "entry_open": round(entry, 6),
                "benchmark_entry_open": round(spy_entry, 6),
                "shadow_status": "open_or_maturing",
            }
        )

        outcomes = signal.setdefault("outcomes", {})
        cost = self.round_trip_cost_bps / 10_000.0
        for horizon in HORIZONS:
            key = f"{horizon}d"
            if key in outcomes:
                continue
            exit_index = symbol_entry_index + horizon - 1
            spy_exit_index = spy_entry_index + horizon - 1
            if exit_index >= len(symbol_rows) or spy_exit_index >= len(spy_rows):
                continue
            exit_row = symbol_rows[exit_index]
            spy_exit_row = spy_rows[spy_exit_index]
            exit_price = _price(exit_row, "c")
            spy_exit = _price(spy_exit_row, "c")
            gross_return = exit_price / entry - 1.0
            net_return = gross_return - cost
            benchmark_return = spy_exit / spy_entry - 1.0
            window = symbol_rows[symbol_entry_index : exit_index + 1]
            outcomes[key] = {
                "exit_session": str(exit_row.get("t") or "")[:10],
                "gross_return": round(gross_return, 5),
                "net_return": round(net_return, 5),
                "round_trip_cost_bps": self.round_trip_cost_bps,
                "spy_return": round(benchmark_return, 5),
                "excess_return_net": round(net_return - benchmark_return, 5),
                "max_favorable_excursion": round(
                    max(_price(row, "h") for row in window) / entry - 1.0, 5
                ),
                "max_adverse_excursion": round(
                    min(_price(row, "l") for row in window) / entry - 1.0, 5
                ),
                "measurement_policy": "next_session_open_to_horizon_close",
            }
        if len(outcomes) == len(HORIZONS):
            signal["shadow_status"] = "fully_matured"

    def update(
        self,
        session: str,
        candidates: list[dict[str, Any]],
        bars: dict[str, list[dict[str, Any]]],
        *,
        market_regime: str,
        market_data_feed: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        payload = self.load()
        signals = payload["signals"]
        spy_rows = _ordered(bars.get("SPY", []))

        for signal in signals:
            symbol_rows = _ordered(bars.get(str(signal.get("symbol")), []))
            if not symbol_rows or not spy_rows:
                continue
            if signal.get("entry_policy") in {None, "same_session_close_legacy"}:
                self._update_legacy_signal(signal, symbol_rows, spy_rows)
            else:
                self._update_shadow_signal(signal, symbol_rows, spy_rows)

        existing = {(str(item.get("session")), str(item.get("symbol"))) for item in signals}
        for rank, candidate in enumerate(candidates[:limit], start=1):
            key = (session, str(candidate["symbol"]))
            if key in existing:
                continue
            technical = candidate.get("technical") or {}
            signals.append(
                {
                    "signal_type": "screen_grade",
                    "session": session,
                    "symbol": candidate["symbol"],
                    "rank": rank,
                    "signal_close": technical.get("close"),
                    "entry_policy": "next_session_open",
                    "round_trip_cost_bps": self.round_trip_cost_bps,
                    "screen_score": candidate.get("composite_screen_score"),
                    "component_scores": {
                        "technical": technical.get("technical_score"),
                        "fundamental": candidate.get("fundamental_score_screen"),
                        "valuation": candidate.get("valuation_score_screen"),
                        "revisions": candidate.get("revisions_score_screen"),
                        "data_quality": candidate.get("data_quality_score_screen"),
                    },
                    "archetype": candidate.get("primary_archetype"),
                    "stage": technical.get("stage"),
                    "long_eligible_screen": candidate.get("long_eligible_screen"),
                    "long_eligibility_blockers": candidate.get("long_eligibility_blockers") or [],
                    "market_regime": market_regime,
                    "market_data_feed": market_data_feed,
                    "shadow_status": "awaiting_next_session_open",
                    "outcomes": {},
                }
            )
            existing.add(key)

        payload["schema_version"] = 2
        payload["measurement_policy"] = "next_session_open_to_horizon_close"
        payload["round_trip_cost_bps"] = self.round_trip_cost_bps
        payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        payload["signals"] = signals[-2000:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return self.summary(payload)

    @staticmethod
    def summary(payload: dict[str, Any]) -> dict[str, Any]:
        signals = payload.get("signals") or []
        shadow_signals = [
            item for item in signals if item.get("entry_policy") == "next_session_open"
        ]
        legacy_signals = [
            item for item in signals if item.get("entry_policy") == "same_session_close_legacy"
        ]
        horizons: dict[str, Any] = {}
        for horizon in HORIZONS:
            key = f"{horizon}d"
            values = [
                item["outcomes"][key]["excess_return_net"]
                for item in shadow_signals
                if isinstance(item.get("outcomes"), dict)
                and key in item["outcomes"]
                and item["outcomes"][key].get("excess_return_net") is not None
            ]
            observed_win_rate = (
                round(sum(value > 0 for value in values) / len(values) * 100.0, 2)
                if values
                else None
            )
            publishable = len(values) >= MIN_MATURED_OBSERVATIONS
            horizons[key] = {
                "observations": len(values),
                "minimum_observations_for_claim": MIN_MATURED_OBSERVATIONS,
                "performance_claim_ready": publishable,
                "win_rate_vs_spy_pct": observed_win_rate if publishable else None,
                "observed_win_rate_vs_spy_pct": observed_win_rate,
                "average_excess_return_net_pct": (
                    round(sum(values) / len(values) * 100.0, 2) if values else None
                ),
            }
        return {
            "signal_type": "screen_grade_shadow_portfolio",
            "entry_policy": "next_session_open",
            "round_trip_cost_bps": payload.get(
                "round_trip_cost_bps", DEFAULT_ROUND_TRIP_COST_BPS
            ),
            "total_shadow_signals": len(shadow_signals),
            "legacy_signals_excluded": len(legacy_signals),
            "horizons": horizons,
            "warning": (
                "Performance is withheld as a claim until each horizon has at least "
                f"{MIN_MATURED_OBSERVATIONS} matured next-session-open observations. "
                "Legacy same-session-close outcomes are excluded."
            ),
        }
