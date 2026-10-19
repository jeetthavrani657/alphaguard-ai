# Multi-Asset Advisory: Design Frozen Before Any Result Was Looked At

**Status: PRE-REGISTERED, then run once.** Code: `research/advisory.py`. Web page: **Advisory**.
Educational research prototype. **Not investment advice**, not a recommendation to buy or sell,
and it places no orders. Giving investment advice in India is regulated (SEBI).

## What it is

A risk-managed allocation tool across asset classes, the "advisory" part of AlphaGuard AI. For a stated
risk appetite it recommends a split of money and shows what that split would have done in the past
next to buying and holding the Nifty 50 ETF.

| Asset | Instrument (yfinance) |
|---|---|
| Large-cap equity | NIFTYBEES.NS (Nifty 50 ETF) |
| Mid-cap equity | MID150BEES.NS |
| International equity | MON100.NS (Nasdaq-100, in rupees) |
| Gold | GOLDBEES.NS |
| Government bonds | LTGILTBEES.NS (long-term gilt ETF) |
| Crypto | BTC-INR |
| Cash | assumed 6% a year (a liquid ETF's price does not move, so it cannot be used) |

## The rule (frozen, nothing tuned)

1. Every 21 trading days, weight each allowed asset by `1 / its 63-day volatility`, then enforce the
   profile's per-asset caps (an asset with cap 0 is excluded).
2. **Volatility targeting:** if that mix would be more volatile than the profile's target, scale it down and
   hold the rest in cash. Never leverage.
3. **Drawdown guard:** if the portfolio is down more than the profile's limit from its peak, halve the risky
   part until it has recovered half of the way.
4. Weights are decided with data up to the close of day *t* and carried out one day later. Each rebalance
   costs 0.10% of the amount traded, each way.

| Profile | Target volatility | Drawdown guard | Caps (large, mid, intl, gold, debt, crypto) |
|---|---|---|---|
| Conservative | 6% | -8% | 30, 10, 10, 25, 70, 0 |
| Moderate | 10% | -12% | 45, 20, 20, 25, 50, 5 |
| Aggressive | 15% | -20% | 55, 30, 30, 20, 30, 10 |

A five-question questionnaire (0 to 3 points per answer, 15 in total) maps to a profile:
0 to 5 conservative, 6 to 10 moderate, 11 to 15 aggressive.

## How it is judged

The three profiles are **three hypotheses**, registered once in the ledger (205 became **208**) and judged by
the same harness as every strategy. The simulation is split only so the application's two-window convention
applies unchanged: 2019 to 2022 is in-sample and 2023 onwards is out-of-sample; nothing was fitted on
either. Data goes from 2019-05-15 (the first day all assets exist) to the latest close.

## What was found

- **Risk management did its job.** In the out-of-sample window the maximum drawdown was -5.1% to -7.8%
  against -15.2% for the Nifty 50 ETF; in-sample -11.6% to -18.5% against -36.3%. Value at Risk and
  Expected Shortfall were roughly half of the Nifty 50's.
- **Returns depended on the window.** In-sample (an equity bull run) the conservative and moderate mixes
  returned less than the Nifty 50 (7.3% and 10.1% a year against 15.5%). Out-of-sample (a weak Nifty 50 and a
  strong gold, Nasdaq-100 and Bitcoin) all three beat it. That is asset-class hindsight, not skill.
- **No profile passes the corrected significance bar** (0.05 / 208): status `VALIDATED_FAILED` for all three,
  even with out-of-sample Sharpe ratios of 1.26 to 1.60, because the window is only about 3.8 years.
  Diversification lowers risk; this does not show that it earns more.
- **A data problem was found and handled.** The free source returned one-day bad prints (the Nifty 50 and
  gold ETFs at one tenth and one hundredth of their price on 2019-12-19, and the Nasdaq-100 fund on 2021-06-17)
  that came back to normal days later. Left in, they showed as a 90% crash and a 900% rebound and made the
  in-sample results meaningless. The cleaning rule (a one-day move over 50% that is undone within 3 days is a
  bad print, carried forward) is tested and every removed row is listed in the application.

## Added after the design was frozen (display only, no new hypothesis)

These three additions describe or reuse the frozen rule; none changes it, none was back-tested, so the ledger
stays at 208.

- **Why this mix.** For each weight, the asset's role (growth, hedge, stability...), its recent volatility, and its
  share of the portfolio's *risk* (a calm asset can hold much money and little risk). Computed in
  `explain_allocation` from the same 63-day window the rule used.
- **Shopping list.** `GET /api/advisory/basket?profile=...&amount=...` turns the recommended weights into rupees and
  whole units at the last close (Bitcoin in fractions; leftover money stays in cash). It is a unit conversion,
  clearly labelled as the one piece of arithmetic in the API, and it is not an order: the project places none.
- **Trend monitor.** Each risky asset against its own 210-day average: a description of today. It makes no claim
  that the signal predicts anything, so it is shown without performance numbers.

- **Stress test.** Four named bad stretches (COVID crash 2020-02-19 to 2020-03-23; 2021-22 equity bear; the 2022
  rate-hike year; crypto winter), fixed in `STRESS_EPISODES` before any profile was measured on them, read from the
  close before each start. Descriptive, not a test, so the ledger stays at 208. What it found, unflattering parts
  included: in the COVID crash the moderate mix fell 14.1% against 35.1% for the Nifty 50 ETF, but in the 2022
  rate-hike year the ETF ended +5.5% while the moderate mix ended -1.8% (Nasdaq-100 -26% and Bitcoin -60% in rupees
  dragged it; gold +13% helped). Risk management lowered the worst fall in every stretch; it did not always raise the return.

## Forward paper tracking (`research/advisory_forward.py`)

The frozen rule is also run forward on data that did not exist when it was frozen: base of 100 at the 2026-10-19
close, first countable session 2026-10-20. (The advisory was committed on the evening of 2026-10-19, after that day's
close, so that day had already been seen and is not out-of-time. An earlier version copied the paper books' dates
and counted 2026-10-19 as day 1; that was corrected on 2026-10-20.) The two multi-asset trend rules
(`MULTIASSET_TREND.md`) are tracked from the same date. It adds **no** hypothesis (the three
profiles were counted when registered). Everything is recomputed from raw prices with the same `simulate()`, so a
re-run on the same data gives the same answer; `reports/output/advisory_forward.csv` keeps one row per profile and data
date, so a vendor re-adjustment of the free price data would show. Nothing is judged early: no Sharpe is computed or
served before 252 forward sessions. It runs daily from `run_forward_log.bat` (`--refresh` downloads fresh prices) and is
shown on the web app's Paper trading page. Paper only: no orders.

## Limits

Seven years of history including one crash; ETF and coin prices from a free source; no taxes, no real
liquidity or spread costs beyond the flat 0.10%; the cash rate is an assumption; correlations change in
crises; and a simulation is not a forecast.

## Running it

```
python research/advisory.py --register   # ONCE: counts the 3 hypotheses in the ledger
python research/advisory.py              # regenerate the file without touching the ledger
```
