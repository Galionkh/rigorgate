# Live Scan Guide

The public repository is safe to evaluate with the offline demo. A live scan requires your own provider accounts and responsible operating practices.

## Local setup

```bash
git clone https://github.com/Galionkh/galion-signal-forge.git
cd galion-signal-forge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Load credentials from `.env` using your preferred shell or secret manager. The project intentionally does not parse or upload your secret file.

## Verify before going live

```bash
python -m compileall -q galion run_scan.py run_events.py
python -m unittest discover -s tests -v
python -m galion.demo
```

## Run modes

```bash
python run_scan.py --mode smoke
python run_scan.py --mode full
python run_events.py
```

Use `smoke` to verify provider credentials, schema compatibility, and report generation with a narrow workload. Use `full` only after smoke mode succeeds and you understand the provider quotas.

## GitHub Actions deployment

The public workflow runs tests only and needs no secrets. If you create a private live-deployment workflow:

1. store credentials in repository or environment secrets;
2. use least-privilege workflow permissions;
3. pin third-party actions to trusted versions or commit SHAs;
4. set concurrency limits and provider request caps;
5. keep generated reports free of credentials and proprietary payloads;
6. review the first runs manually before adding a schedule.

## How to use an output

A scan result is a research queue. Before acting on a candidate, verify current price and liquidity, read the latest primary filings and company release, inspect earnings quality and guidance, compare valuation with appropriate peers, define invalidation and position risk, and perform a red-team review. SignalForge does not complete these steps on your behalf and does not place trades.

## Troubleshooting

- **No financial coverage:** inspect provider status, quotas, ticker mapping, and the recorded fallback chain.
- **SEC access failure:** confirm the user agent and request rate; use cached public facts or a permitted fallback.
- **Unexpectedly low volume:** determine whether the selected feed represents IEX or consolidated SIP volume.
- **Stale report:** compare the report cutoff with the latest completed market session.
- **No research candidates:** this is a valid result. Do not weaken hard gates merely to produce a name.
