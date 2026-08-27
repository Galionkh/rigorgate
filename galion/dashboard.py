from __future__ import annotations

import html
from typing import Any


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def render_dashboard(report: dict[str, Any]) -> str:
    candidates = report.get("candidates") or []
    breadth = report.get("market_breadth") or {}
    universe = report.get("universe") or {}
    cache = report.get("cache") or {}
    performance = report.get("signal_performance") or {}
    provider_mix = universe.get("deep_data_provider_mix") or {}
    provider_mix_text = " · ".join(
        f"{name}: {count}" for name, count in sorted(provider_mix.items())
    ) or "—"
    rows = []
    for rank, candidate in enumerate(candidates, start=1):
        technical = candidate.get("technical") or {}
        sector = candidate.get("sector_context") or {}
        forensic = candidate.get("forensic_screen") or {}
        flags = ", ".join(
            (candidate.get("event_risk_flags") or [])
            + (forensic.get("flags") or [])
            + (candidate.get("long_eligibility_blockers") or [])
        ) or "—"
        rows.append(
            "<tr>"
            f"<td>{rank}</td><td><b>{_escape(candidate.get('symbol'))}</b><br><small>{_escape(candidate.get('company'))}</small></td>"
            f"<td>{_escape(candidate.get('primary_archetype'))}</td><td>{_escape(candidate.get('composite_screen_score'))}</td>"
            f"<td>Stage {_escape(technical.get('stage'))}<br><small>{_escape(technical.get('stage_name'))}</small></td>"
            f"<td>{_escape(candidate.get('sector'))}<br><small>{_escape(sector.get('etf'))} · rank {_escape(sector.get('rank'))}</small></td>"
            f"<td>{_escape(forensic.get('quality_score'))}<br><small>{_escape(forensic.get('label'))}</small></td>"
            f"<td>{_escape(flags)}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="8">No signal passed the screen in this session.</td></tr>')

    horizon_cards = []
    for horizon, values in (performance.get("horizons") or {}).items():
        claim_ready = values.get("performance_claim_ready") is True
        headline = (
            f'{_escape(values.get("win_rate_vs_spy_pct"))}%'
            if claim_ready
            else "Validating"
        )
        horizon_cards.append(
            f'<div class="metric"><span>{_escape(horizon)}</span><strong>{headline}</strong>'
            f'<small>{_escape(values.get("observations"))} of {_escape(values.get("minimum_observations_for_claim"))} matured observations'
            f' · net excess {_escape(values.get("average_excess_return_net_pct"))}%</small></div>'
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GALION SignalForge Dashboard</title><style>
:root{{--bg:#08111f;--panel:#111d31;--line:#243653;--text:#edf4ff;--muted:#9eb0ca;--accent:#42d8a8;--warn:#ffcc66}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(140deg,#07101c,#0c1830);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1440px;margin:auto;padding:28px}} header{{display:flex;justify-content:space-between;gap:20px;align-items:end;flex-wrap:wrap}}
h1{{margin:0;font-size:clamp(28px,5vw,52px)}} h2{{margin-top:34px}} .sub,small{{color:var(--muted)}} .badge{{border:1px solid var(--accent);color:var(--accent);padding:8px 12px;border-radius:999px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px}} .metric{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:6px}}
.metric span{{color:var(--muted)}} .metric strong{{font-size:28px}} .table{{overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}} table{{width:100%;border-collapse:collapse;min-width:980px}} th,td{{padding:13px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:var(--accent)}}
.notice{{border-left:4px solid var(--warn);padding:14px;background:#2b2416;margin:24px 0;border-radius:8px}} footer{{color:var(--muted);margin:32px 0}}
</style></head><body><main>
<header><div><div class="sub">GALION SignalForge · {_escape(report.get('as_of_session'))}</div><h1>U.S. Equity Discovery Dashboard</h1></div><div class="badge">{_escape(report.get('run_status'))}</div></header>
<div class="notice"><b>Not a buy recommendation.</b> These are screen-grade research priorities. The user owns every investment and execution decision.</div>
<section class="grid">
<div class="metric"><span>Market regime</span><strong>{_escape(report.get('market_regime'))}</strong><small>{_escape(breadth.get('posture'))}</small></div>
<div class="metric"><span>Above 50-day average</span><strong>{_escape(breadth.get('above_sma50_pct'))}%</strong><small>{_escape(breadth.get('stocks_evaluated'))} stocks</small></div>
<div class="metric"><span>Stage 2</span><strong>{_escape(breadth.get('stage2_pct'))}%</strong><small>confirmed or early uptrends</small></div>
<div class="metric"><span>Research candidates</span><strong>{_escape(universe.get('screen_grade_candidates'))}</strong><small>from {_escape(universe.get('eligible_common_stock_candidates'))} eligible assets</small></div>
<div class="metric"><span>Deep-data coverage</span><strong>{_escape(universe.get('deep_data_successful'))}</strong><small>{_escape(provider_mix_text)}</small></div>
<div class="metric"><span>Fundamental cache</span><strong>{_escape(cache.get('hits'))}</strong><small>hits · {_escape(cache.get('misses'))} misses</small></div>
</section>
<h2>Research shortlist</h2><div class="table"><table><thead><tr><th>#</th><th>Security</th><th>Archetype</th><th>Score</th><th>Stage</th><th>Sector</th><th>Accounting quality</th><th>Risk flags</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Shadow portfolio vs. SPY</h2><section class="grid">{''.join(horizon_cards) or '<div class="metric"><span>No matured observations yet</span><small>Entries are measured at the next session open with estimated transaction costs.</small></div>'}</section>
<footer>Sources: Alpaca, SEC EDGAR/XBRL, Alpha Vantage, FRED, and optional FMP fallback. No order is created or transmitted.</footer>
</main></body></html>"""
