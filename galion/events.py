from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .providers import AlpacaProvider, Credentials


MATERIAL_PATTERNS: tuple[tuple[str, int, str], ...] = (
    (r"\bphase\s*3\b|\bpivotal trial\b|\bprimary endpoint\b", 35, "clinical_readout"),
    (r"\bfda\b|\bpdufa\b|\badvisory committee\b|\bapproval\b", 30, "regulatory"),
    (r"\bacquir(?:e|es|ed|ing)|\bmerger\b|\btender offer\b", 30, "m_and_a"),
    (r"\braises? guidance\b|\bcuts? guidance\b|\bpreliminary results\b", 25, "guidance"),
    (r"\brestatement\b|\bauditor resign|\bgoing concern\b|\bbankruptcy\b", 40, "integrity_or_distress"),
    (r"\bcontract\b|\baward(?:ed)?\b|\border\b|\bbacklog\b", 15, "commercial"),
    (r"\bearnings\b|\bquarterly results\b", 10, "earnings"),
)


def materiality_score(headline: str, summary: str = "") -> tuple[int, list[str]]:
    text = f"{headline} {summary}".lower()
    score = 0
    tags: list[str] = []
    for pattern, points, tag in MATERIAL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += points
            tags.append(tag)
    return min(score, 100), tags


def normalize_news(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        headline = str(row.get("headline") or "").strip()
        summary = str(row.get("summary") or "").strip()
        score, tags = materiality_score(headline, summary)
        symbols = sorted({str(symbol).upper() for symbol in row.get("symbols", []) if symbol})
        if score < 20 or not symbols:
            continue
        key = (headline.casefold(), ",".join(symbols))
        if key in seen:
            continue
        seen.add(key)
        alerts.append(
            {
                "headline": headline,
                "symbols": symbols,
                "published_at": row.get("created_at") or row.get("updated_at"),
                "materiality_score": score,
                "tags": tags,
                "discovery_source": row.get("source"),
                "url": row.get("url"),
                "status": "EVENT ALERT — REQUIRES PRIMARY-SOURCE VERIFICATION",
            }
        )
    return sorted(alerts, key=lambda item: (item["materiality_score"], item.get("published_at") or ""), reverse=True)


def build_event_report(hours: int = 36) -> dict[str, Any]:
    credentials = Credentials.from_environment()
    alpaca = AlpacaProvider(credentials.alpaca_key_id, credentials.alpaca_secret_key)
    rows = alpaca.market_news(hours=hours)
    alerts = normalize_news(rows)
    return {
        "run_status": "EVENT MONITOR COMPLETE",
        "decision_status": "ALERTS ARE NOT BUY RECOMMENDATIONS",
        "source_posture": "discovery-only",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": hours,
        "news_items_reviewed": len(rows),
        "material_alerts": alerts[:30],
        "next_step": "Verify every material alert against issuer IR and regulatory primary sources before underwriting.",
    }


def failure_report(exc: Exception) -> dict[str, Any]:
    return {
        "run_status": "EVENT MONITOR NOT OPERATIONAL",
        "source_posture": "not-operational",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "error": str(exc),
        "material_alerts": [],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GALION SignalForge — Premarket Event Monitor",
        "",
        f"- **Run status:** `{report['run_status']}`",
        f"- **Source posture:** `{report['source_posture']}`",
        f"- **Completed:** `{report['completed_at_utc']}`",
        "",
    ]
    if report["source_posture"] == "not-operational":
        return "\n".join(lines + ["## Blocking error", "", str(report.get("error")), ""])
    lines += [
        f"Reviewed {report['news_items_reviewed']} recent news items. Alerts below are discovery signals and require issuer/regulatory verification.",
        "",
        "| Score | Symbols | Event | Tags |",
        "|---:|---|---|---|",
    ]
    for alert in report["material_alerts"]:
        headline = alert["headline"].replace("|", "\\|")
        link = f"[{headline}]({alert['url']})" if str(alert.get("url") or "").startswith("https://") else headline
        lines.append(
            f"| {alert['materiality_score']} | {', '.join(alert['symbols'])} | {link} | {', '.join(alert['tags'])} |"
        )
    if not report["material_alerts"]:
        lines += ["| — | — | No material alert met the threshold | — |"]
    lines += ["", "No order was created or transmitted.", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "latest.md").write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run GALION premarket material-event discovery")
    parser.add_argument("--output-dir", default="reports/events")
    parser.add_argument("--hours", type=int, default=36)
    args = parser.parse_args(argv)
    try:
        report = build_event_report(hours=args.hours)
        code = 0
    except Exception as exc:
        report = failure_report(exc)
        code = 2
    write_report(report, Path(args.output_dir))
    print(json.dumps({"run_status": report["run_status"], "source_posture": report["source_posture"]}))
    return code
