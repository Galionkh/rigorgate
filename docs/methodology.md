# Methodology

RigorGate is a discovery and underwriting aid for liquid U.S.-listed common stocks. It ranks evidence, not certainty.

## Research sequence

The engine first removes securities that fail instrument, price, history, or liquidity rules. It then measures market regime and sector context, evaluates technical structure, and spends deeper provider calls on a smaller candidate set. Fundamental quality, accounting risk, valuation, and data completeness can reduce or block a candidate regardless of momentum.

## Evidence dimensions

- **Technical structure:** stage, trend alignment, relative strength, breakout behavior, volume, RSI, and ATR.
- **Business quality:** revenue and earnings direction, margins, returns, leverage, and cash generation.
- **Accounting quality:** accruals, cash conversion, share-count changes, working capital, and unusual inconsistencies.
- **Valuation:** observable historical or forward measures when their inputs are available and timestamped.
- **Market context:** breadth, sector participation, volatility, rates, inflation, and other macro observations.
- **Data quality:** source authority, completeness, freshness, provider consistency, and unresolved gaps.

## Hard gates

Hard gates exist to prevent a high aggregate score from hiding a critical defect. Examples include unsupported security types, inadequate liquidity, insufficient price history, stale or incomplete core evidence, accounting flags, unfavorable market-stage conditions, and reward-to-risk below the configured minimum.

## Interpretation

The candidate score is an ordinal ranking within a run. It is not a probability that a stock will rise. The labels communicate workflow state:

- `WATCHLIST`: retain for observation.
- `WAIT FOR PROOF`: advance only if the named missing evidence appears.
- `RESEARCH CANDIDATE`: conduct full primary-source underwriting.
- `REJECTED`: stop and preserve the rejection reasons.

## Validation discipline

Outcome tracking must use the original point-in-time snapshot, including price, evidence availability, thresholds, and posture. Later information must not be backfilled into the original decision record. RigorGate withholds aggregate performance claims until at least 50 observations have matured at the relevant horizon. Even then, results should be reported with sample size, time period, assumptions, and known biases.

## Known limitations

- Free market-data feeds may not represent consolidated U.S. volume.
- Analyst estimate coverage can be partial or absent.
- SEC access may be restricted in some cloud environments.
- Fundamental taxonomies vary by issuer and require normalization.
- Backtests can still suffer from survivorship, selection, and regime bias.
- No research system can guarantee a high success rate or eliminate loss.
