# Multi-Asset Trend Trading: Design Frozen Before Any Result Was Looked At

Written 2026-10-20, before `research/multiasset_trend.py` was ever run. Nothing below was tuned on a result; the one
number that could be tuned (the trend length) was set from convention and is not swept.

## Why this exists

Until now the project's trading strategies were all equity-only, while the advisory spans seven asset classes. The
project's topic is *multi-asset algorithmic trading and risk-managed advisory*, so the trading side needs to span the same
assets. This adds one family of rules over the advisory's six priced assets (Nifty 50 ETF, Nifty Midcap 150 ETF,
Nasdaq-100 fund, gold ETF, long government-bond ETF, Bitcoin in rupees) with cash as the alternative. It uses the same
data, cleaning, costs (0.10% of the amount traded, each way), 6% cash rate, one-day execution lag and in-sample / out-of-sample
windows (2022-12-31 / 2023-01-01) as `ADVISORY.md`, so the results can be read side by side.

## The rule: a trend filter

Every 21 trading days (the advisory's rebalance rhythm), look at each asset's close. An asset is **in an uptrend** if its close
is above its own average close over the last **210 trading days** (about ten months, the usual convention, not tuned). The decision is made at the close of
day *t* and carried out at the close of day *t* + 1. Nothing sees the future. An asset in a downtrend is replaced by cash.
The first trade can happen once 210 days of history exist.

Two hypotheses are registered:

1. **`trend_equal_weight`**: each of the six assets has an equal one-sixth slot. A slot holds its asset in an uptrend and cash otherwise.
2. **`trend_risk_managed`**: only assets in an uptrend are eligible. They are weighted by inverse 63-day volatility within the
   advisory's *moderate* caps, then volatility-targeted to 10% a year (never leveraged), with the drawdown guard
   (halve the risky part after a 12% fall from the peak, until half is recovered): exactly the advisory's risk machinery, applied only to the assets the trend
   filter allows. If nothing is in an uptrend the portfolio is entirely cash.

These two are the only new hypotheses (ledger 208 becomes 210). Both are judged by the same harness, Bonferroni at the
cumulative count, in-sample and out-of-sample.

## The benchmarks (not hypotheses)

* **`static_equal_weight`**: the same six assets, equal weights, re-set every 21 days, same costs, no timing. This is the right
  null for a timing rule: it answers whether *timing* added anything beyond simply being in these assets.
* The Nifty 50 ETF, buy and hold (as on the Advisory page).

## How it will be reported

Both hypotheses with their harness status as of the cumulative count, risk measures (volatility, maximum drawdown, Value at Risk,
Expected Shortfall, Calmar) for both windows next to both benchmarks, the four stress stretches of `ADVISORY.md`, and today's
signals (which assets are above their trend). Whatever the result is, it is reported as found.

## Limits stated in advance

Seven years of history including one crash and a very strong stretch for gold, the Nasdaq-100 and Bitcoin; free-source prices;
no taxes or exact spreads; one trend length only, so this says nothing about other lengths; and a rule that is in cash
for a while will look good in a falling market and poor in a rising one by construction.

## What was found (registered 2026-10-20, ledger 208 became 210)

Both rules are `VALIDATED_FAILED` at 210 hypotheses (the bar is 0.05/210 = 0.000238).

| Rule | Sharpe in-sample | Sharpe out-of-sample | Out-of-sample p | Worst fall out-of-sample |
|---|---|---|---|---|
| Trend filter, equal weight | 0.94 | 1.61 | 0.00098 | -8.9% |
| Trend filter, risk-managed | 0.31 | 1.19 | 0.0111 | -6.0% |
| Same six assets, no timing (benchmark) | 0.99 | 1.74 | n/a | -10.6% |
| Nifty 50 ETF, buy and hold | 0.53 | 0.18 | n/a | -15.2% |

* **Timing did not add return per unit of risk.** Neither rule's Sharpe ratio is above the no-timing benchmark in either window
  (out-of-sample 1.61 and 1.19 against 1.74). The filter's value was in the worst falls: out-of-sample -8.9% and -6.0% against -10.6% with no timing.
* **It lowered the damage in every named bad stretch.** COVID crash: -18.2% and -12.7% against -21.9% with no timing and -35.1% for the
  Nifty 50 ETF. 2021-22 bear: -12.0% and -6.7% against -22.0%. 2022 rate-hike year: -3.5% and -0.9% against -12.9% (the Nifty 50 ETF itself ended +5.5%).
  Crypto winter: -12.8% and -7.1% against -22.8%.
* **The equal-weight rule came closest to the bar** (out-of-sample p = 0.00098, about four times the bar), and that is the window in which
  gold, the Nasdaq-100 and Bitcoin were all unusually strong, which flatters any rule that holds them.
* So the honest reading is that a trend filter acted as a risk reducer over these assets, not as a source of excess return; and one trend length
  (210 days) was tested, so nothing is claimed about others.

## Forward tracking

The rules were frozen on 2026-10-20 before any result existed, so they are run forward from the 2026-10-19 close (base 100); the
first session that counts is 2026-10-20 (`research/advisory_forward.py`, shown on the Paper trading page). Nothing is judged and no Sharpe
is shown before 252 forward sessions. Registered once; no further hypothesis is added by tracking.
