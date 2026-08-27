# Data Sources

SignalForge keeps providers modular because no free source is complete, equally timely, and suitable for every research layer.

| Source | Role | Credential | Important limitation |
|---|---|---|---|
| SEC EDGAR/XBRL | Official filings and company facts | None; descriptive user agent required | Automated cloud traffic may be throttled or blocked |
| Alpaca | Assets and historical market data | API key | Free feed coverage and consolidated-volume behavior vary by plan |
| FRED | Macro observations | API key | Macro series are revised and have publication lags |
| Alpha Vantage | Financial statement fallback | API key | Free request limits and coverage constraints |
| Financial Modeling Prep | Optional financial fallback | API key | Free endpoints and quotas may change |

## Provider policy

1. Prefer authoritative primary sources for company claims.
2. Validate payload content, not only response status.
3. Record the source and retrieval time for every material input.
4. Expose fallback use and missing coverage in the report.
5. Cache responsibly and honor provider terms and rate limits.
6. Never ship credentials, copied proprietary datasets, or data that cannot be redistributed.

## SEC user agent

SEC requests must identify the application and include a monitored contact address. Set a descriptive value such as:

```bash
export SEC_USER_AGENT="SignalForge Research your-email@example.com"
```

Do not copy the placeholder unchanged. Review the SEC fair-access guidance before running large jobs.

## Free versus professional coverage

Free sources are useful for reproducible discovery, but fragmented coverage changes what the engine can prove. A missing field should lower data quality or block advancement; it should not be converted into a favorable assumption. Users who add licensed data remain responsible for its terms and must keep redistributable fixtures separate from proprietary payloads.
