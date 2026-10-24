# Three Intraday Rules on the Nifty 50: Design Frozen Before Any Return Was Looked At

Written 2026-10-24, after the 15-minute candles were downloaded and checked for quality (`research/intraday_quality.py`) but before any intraday rule was ever run or any intraday return computed.
Nothing below was tuned on a result. Every number (the 30-minute range, the 1% thresholds, the Rs 10,00,000 account, the costs) is set once here and is not swept.

## Why this exists, and the warning that goes with it

The owner asked for what other platforms offer, and intraday is one of them. `INTRADAY_COSTS.md` already states the arithmetic: a same-day round trip costs about 0.14% to 0.3% of its value, so a rule has to
gain about 0.2% per trade before it earns anything, and a rule that turns its whole capital over every day pays roughly 36% to 71% of the capital a year in costs. SEBI's own study found about 91% of
individual F&O traders lost money in FY25; intraday cash traders do no better in most studies. **The prior for every rule below is that it fails the cost bar.** This note exists to test three specific, well-known
ideas under the project's usual discipline (a frozen design, a count in the ledger, realistic costs, a result reported as found), not to find a reason to trade intraday.

`INTRADAY_COSTS.md` said a rule that cannot clear the bar "is not worth the ledger entry". That is overridden on purpose: leaving out the rules that fail would hide the number of ideas tried, which is the very thing the ledger
exists to count. All three are registered together before any result is seen (ledger 217 becomes 220, bar 0.05/220 = 0.000227).

## The data, and what is known about it

15-minute candles for the 50 stocks in `config.UNIVERSE`, from the read-only Upstox client, January 2022 to the last complete session, cached in `data/intraday/` (git-ignored). Checked against Yahoo's daily bars:
volume agrees (median ratio 1.00), the day's high and low agree (99%), the last 15-minute candle's close sits a median 0.12% from the exchange's official close (the official close is a volume-weighted price of the last 30 minutes), the weekend
special sessions are only in the candles, and the Diwali Muhurat evenings are dropped by the loader. Sessions with fewer than 90% of the 25 candles are excluded. Survivorship: the universe is today's Nifty 50 (the same disclosed bias as the
daily research: stocks that did well enough to be in the index today); for a same-day rule it matters less than for a rule that holds for months, but it is not zero.

## Common to all three rules

* Universe: the 50 stocks above. One trade per stock per day at most. Always flat overnight.
* A day has 25 candles, starting 09:15, 09:30, ... 15:15. Every entry is at the OPEN of a candle, after the signal candle has closed (never the same candle: one-candle lag, as everywhere in this project). Every exit is at the CLOSE of the 15:15 candle (the last trade of the session).
* Longs and shorts are both allowed (same-day shorts are possible in the cash segment).
* "Prior close" means the close of the previous session's 15:15 candle in this same data set (one source, one basis).
* Costs: `research/intraday_costs.py`, default slippage 0.05% a side. The account is Rs 10,00,000, split equally over the day's trades (no leverage), so each trade's cost percentage depends on its size (the flat brokerage matters for small trades). Days with no trade earn nothing (cash interest is ignored: stricter than the other rules).
* The strategy's daily return is the equal-weighted net return of that day's trades; the equity curve compounds it; the Sharpe ratio is annualised from daily returns (252 days).
* Windows: in-sample 2022-01-03 to 2024-06-30, out-of-sample 2024-07-01 to the last data day. Both are short (about 2.5 and 2.3 years), so the harness's bar is hard to pass; the out-of-sample window carries the weight.

## The three hypotheses

**`orb_30`: opening-range breakout.** The opening range is the highest high and lowest low of the 09:15 and 09:30 candles (the first 30 minutes). From the close of the 09:45 candle through the close of the 14:30 candle, at the first candle that closes above
the range high, buy at the next candle's open; at the first that closes below the range low, sell short at the next candle's open. At most one trade per stock per day; exit at the close of the 15:15 candle. Reason: an early move out of the opening range is said to
signal that one side has won the day, and the move tends to continue.

**`gap_fade`: fade a large overnight gap.** The gap is the 09:15 candle's open divided by the prior close, minus one. If the gap is +1% or more, sell short; if it is -1% or less, buy. Entry at the open of the 09:30 candle (not the opening auction), exit at the close of
the 15:15 candle. Reason: overnight gaps in liquid stocks are said to be partly overreaction that fills during the day.

**`late_momentum`: the first half-hour predicts the last half-hour.** The first-half-hour return is the close of the 09:30 candle divided by the prior close, minus one (so it includes the gap). If it is +1% or more, buy; if -1% or less, sell short. Entry at the open of the
15:00 candle, exit at the close of the 15:15 candle (a 30-minute hold). Reason: the published "intraday momentum" finding (Gao, Han, Li and Zhou, 2018, on index ETFs), here at single-stock level and with a threshold so that it trades only on large moves.

## Benchmarks (not hypotheses)

The Nifty 50 ETF, buy and hold, and the account left in cash at 6%. An intraday rule that does not beat cash after costs has no use.

## How it will be reported

Each rule judged by the harness at the cumulative count (220): in-sample and out-of-sample Sharpe ratio, return, worst fall, the number of trades, **the average gross gain per trade against the 0.2% cost bar**, the average net gain per trade, the win rate, the share of the
gross gain eaten by costs, the profit with and without the best 5% of trades, and the cost sensitivity at 0.03% and 0.10% slippage a side. The Deflated Sharpe at the new count is added. Whatever the result is, it is reported as found.

## Limits stated in advance

About 4.7 years of data (see `OVERFIT_CHECKS.md`: with the number of ideas already tried, the best of pure noise would show a Sharpe of about 1.2); entries and exits at candle open and close, not tradable quotes (a real fill in a fast opening minute would be worse than 0.05%); no price impact, which is small for the Nifty 50 at this size;
no margin or leverage model; no circuit-limit or halt handling; taxes on intraday profits (taxed as business income) are not modelled; the universe is today's index members; a single data source. A rule that works here still needs the forward paper test before it means anything.

## What was found (run 2026-10-25; registered once, ledger 217 to 220, bar 0.05/220 = 0.000227)

All 50 symbols, 1,189 sessions (2022-01-03 to 2026-10-23), the three rules exactly as frozen above. A second implementation reproduced all 72,301 of the engine's trades on the real candles before the run
(49,278 `orb_30`, 7,580 `gap_fade`, 15,443 `late_momentum`). The engine was first run without registering, as the options rules were, and then registered unchanged.

| | `orb_30` | `gap_fade` | `late_momentum` |
|---|---|---|---|
| Trades in-sample / out-of-sample | 25,316 / 23,962 | 4,084 / 3,496 | 8,225 / 7,218 |
| Trades per day | 41 | 7 | 13 |
| **Average gross gain per trade, in-sample** | **+0.034%** | **+0.042%** | **-0.021%** |
| **Average gross gain per trade, out-of-sample** | **-0.002%** | **+0.026%** | **-0.019%** |
| The break-even bar of `INTRADAY_COSTS.md` | 0.2% | 0.2% | 0.2% |
| Average cost per trade (default slippage) | 0.207% | 0.186% | 0.196% |
| Average net gain per trade, out-of-sample | -0.209% | -0.160% | -0.215% |
| Net, out-of-sample, without the best 5% of trades | -0.329% | -0.334% | -0.265% |
| Win rate after costs, out-of-sample | 38.7% | 45.1% | 25.1% |
| Sharpe ratio, in-sample / out-of-sample | -9.6 / -12.7 | -0.7 / -1.8 | -16.9 / -19.3 |
| Out-of-sample total return, worst fall | -70.0%, -70.2% | -40.0%, -44.9% | -68.1%, -68.1% |
| Out-of-sample net per trade at 0.03% / 0.10% slippage a side | -0.169% / -0.309% | -0.120% / -0.260% | -0.175% / -0.315% |
| Harness status at 220 | `VALIDATED_FAILED` | `VALIDATED_FAILED` | `VALIDATED_FAILED` |

(The Nifty 50 ETF over the same out-of-sample window: Sharpe -0.57, -1.8% a year, worst fall 15.2%: a poor window for the benchmark, and still far better than any of the three rules.)

**Reading.** The prior written in advance was that each fails the cost bar, and each fails it by a wide margin: the average gross gain is between -0.02% and +0.04% a trade, one fifth of the 0.2% needed or less. This is
arithmetic rather than bad luck: even at 0.03% slippage and with no spread at all the statutory costs alone (brokerage, STT, exchange and SEBI fees, stamp, GST) are about 0.10% of a round trip, more than twice the best gross gain. Nothing in the
results suggests a version of these three rules that is close to working: the gross gain is about zero in the later window for two of them and the best, `gap_fade`, earns 0.026%. `gap_fade` is the least bad for two plain reasons: its gross gain is slightly positive (+0.026%), and it trades 7 times a day instead of 13 or 41, so each trade is larger and the flat brokerage weighs less (0.186% a trade instead of 0.207%). It is still about 0.16% a trade short.

**What this does not show.** Only these three simple rules, with fixed parameters, were tried: not that no intraday rule can work, and not that a rule with a much larger average move per trade could not clear the bar (a rule would need a gross gain per trade of 0.2% or more,
about five times the best of these, on data it was not designed on). Changing the thresholds, the hold times or the stocks of these rules after seeing this result would be new hypotheses, counted in the ledger, and would be tuning on a result.
Any follow-up would start from the cost bar, not from these rules. The universe is today's index members, a survivorship bias that if anything flatters a result; costs are modelled, not observed in a broker contract note.
