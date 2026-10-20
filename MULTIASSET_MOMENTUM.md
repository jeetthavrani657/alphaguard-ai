# Multi-Asset Momentum: Design Frozen Before Any Result Was Looked At

Written 2026-10-20, before `research/multiasset_momentum.py` was ever run. Nothing below was tuned on a result. Every number
(12 months, the top 2 and the top 3, 21 days) is the textbook convention, is set once, and is not swept.

## Why this exists

The owner asked for strategies that make a profit. The honest way to look for one is to state an idea and its reason in advance, run it
once, count it in the ledger and report whatever it does; the dishonest way is to keep adjusting until something passes. This file is the first
way. Two ideas are registered (ledger 210 becomes 212), no more.

## The idea and its reason

**Dual momentum** (relative and absolute momentum across asset classes, in the spirit of Antonacci's "dual momentum" and the time-series momentum
literature of Moskowitz, Ooi and Pedersen). Reason: asset classes that did best over the past year tend to keep doing better for a few months, because
capital reallocates slowly and trends in macro conditions (rates, growth, currency, risk appetite) persist; and an asset that has fallen over the past year is
better left in cash than held (absolute momentum), which is where most of the protection in a bear market is meant to come from. It is a claim about
**relative** strength across assets plus **own** trend, which is different from the existing trend filter (own trend only, equal slots).

## The rules (same six assets, same data, costs, cash rate, lag and windows as `ADVISORY.md`)

Every 21 trading days, at the close of day *t* and carried out at the close of day *t* + 1, measure each asset's total return over the last
**252 trading days (twelve months)**.

1. **`momentum_top2`**: hold the **two** assets with the highest twelve-month return, one half each, **but only an asset whose own twelve-month return is
   positive**; a slot that fails the test is held as cash. Ties are broken by the order of the asset list.
2. **`momentum_top3_risk_managed`**: the **three** assets with the highest twelve-month return and a positive return are the eligible set; they are weighted by inverse
   63-day volatility within the advisory's *moderate* caps, volatility-targeted to 10% a year (never leveraged), with the drawdown guard: the advisory's risk machinery
   applied only to what momentum selects. If none is positive the portfolio is all cash.

The first decision can be taken once 253 days of prices exist, so the simulation starts later than the advisory's (about February 2020). The in-sample / out-of-sample split
is the project's (2022-12-31 / 2023-01-01); the in-sample window is therefore short (under three years), which makes the statistical test hard to pass for ANY rule.

## Benchmarks (not hypotheses)

The same six assets equal-weighted with no selection (the right null for a selection rule), and the Nifty 50 ETF, buy and hold.

## How it will be reported

Both rules with their harness status at the cumulative count, risk measures for both windows beside both benchmarks, the four named stress stretches (those that the
shorter simulation covers) and what each rule holds today. Whatever the result is, it is reported as found, including a failure to beat the benchmark.

## Limits stated in advance

A short history that includes one crash and a very strong run for gold, the Nasdaq-100 and Bitcoin, which flatters any rule that holds them; free-source prices; no taxes or
exact spreads; one lookback only, so nothing is claimed about other lengths; and an in-sample window under three years, in which a Sharpe ratio would have to be very high to
clear a bar set by 212 ideas. Passing that bar is not the same as being profitable: a rule can make money and still fail it, which is exactly what most results here did.

## What was found (registered 2026-10-20, ledger 210 became 212)

Both rules are `VALIDATED_FAILED` at 212 hypotheses (the bar is 0.05/212 = 0.000236). The simulation runs from 2020-02-19; in-sample is 712 days, out-of-sample 936.

| Rule | CAGR in-sample | CAGR out-of-sample | Sharpe in-sample | Sharpe out-of-sample | p in-sample | p out-of-sample | Worst fall out-of-sample |
|---|---|---|---|---|---|---|---|
| Momentum: best two assets | 42.2% | 34.4% | 1.03 | 1.17 | 0.042 | 0.012 | -21.1% |
| Momentum: best three, risk-managed | 9.9% | 14.9% | 0.50 | 1.12 | 0.200 | 0.015 | -10.7% |
| Same six assets, no selection (benchmark) | 19.4% | 27.9% | 0.79 | 1.75 | n/a | n/a | -10.5% |
| Nifty 50 ETF, buy and hold | 16.3% | 7.4% | 0.57 | 0.18 | n/a | n/a | -15.2% |

* **The rules made money, and still failed the bar.** The best-two rule returned about 34% a year out-of-sample against 7% for the Nifty 50 ETF, but its p-values (0.042
  in-sample, 0.012 out-of-sample) are about 180 and 50 times the bar, and an in-sample window under three years cannot clear a bar set by 212 ideas for almost any rule.
* **Selection did not beat simply holding the six assets.** Out-of-sample Sharpe 1.17 and 1.12 against 1.75 for the equal-weight benchmark; the best-two rule's worst fall (-21.1%)
  is twice the benchmark's (-10.5%). It earned more by taking concentrated risk, not more per unit of risk.
* **The risk-managed variant protected best in the crashes** (COVID stretch -7.5% against -21.9% for the benchmark and -35.1% for the Nifty 50 ETF), at the cost of a much lower return.
* **The best-two rule did badly in the stretches where its picks turned.** 2021-22 bear: -27.2% against -21.9% (the Nifty 50 ETF -15.9%); crypto winter -28.2%. Concentration cuts both ways.
* On data through 2026-10-19 the rules would choose the Nasdaq-100 fund and gold (and, for the three-asset rule, government bonds).

So the honest reading: a momentum rule over these assets was profitable in the backtest and carries too much concentrated risk to call validated; the period was kind to gold, the
Nasdaq-100 and Bitcoin, and one twelve-month lookback was tested. The rules are run forward on paper from the 2026-10-19 close.
