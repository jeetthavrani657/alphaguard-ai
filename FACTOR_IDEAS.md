# Three Stock-Selection Ideas: Design Frozen Before Any Result Was Looked At

Written 2026-10-22, before `research/factor_ideas.py` was ever run. Nothing below was tuned on a result. Every number
(252 days, 21 days, the top 10, the top 30, monthly) is set once here and is not swept.

## Why this exists

The owner asked for new research ideas. The honest way to add one is to state it with its reason in advance, run it once,
count it in the ledger, and report whatever it does. Three ideas are registered together (ledger 212 becomes 215, so the bar
moves from 0.05/212 = 0.000236 to 0.05/215 = 0.000233), no more. A fourth idea needs its own frozen note and its own count.

## The three ideas and their reasons

All three are long-only, equal-weighted, rebalanced on the last trading day of each month, executed at the next session's open
with the engine's ordinary Indian cost model, exactly like the momentum strategy already in the ledger
(`MOMENTUM_METHODOLOGY.md`). Only the score used to rank the stocks differs.

1. **`lowvol_nifty50`: low volatility.** Rank the Nifty 50 stocks by the standard deviation of their daily returns over the last
   **252 trading days**; hold the **10** with the lowest value. Reason: stocks that swing less have tended to earn at least as much
   as the wild ones, because many investors reach for volatile "lottery" stocks and are limited in leverage (the low-volatility
   anomaly, Frazzini and Pedersen on betting against beta, Ang et al. on idiosyncratic volatility). It is a different claim from
   momentum (past winners keep winning) and from the two moving-average and RSI ideas (a stock's own trend or overreaction).
2. **`reversal1m_nifty50`: one-month reversal.** Rank the Nifty 50 stocks by their return over the last **21 trading days**
   (the most recent month is NOT skipped here); hold the **10** with the lowest return, the month's biggest losers. Reason:
   a month of heavy selling often pushes a price past what the news justifies, and liquidity providers are paid for absorbing it,
   so the loser tends to bounce next month (Jegadeesh 1990; Lehmann 1990). It is the mirror of the 12-1 momentum rule, which skips
   this very month for the same reason.
3. **`momentum_midcap150`: the existing 12-1 momentum rule on the Midcap 150.** Same score (return from 252 to 21 trading days
   ago), applied to the Midcap 150 and holding the top **30**, the top fifth, as 10 of 50 was a fifth in the Nifty 50. Reason:
   momentum is said to be stronger where information travels slowly and fewer analysts look, which describes mid caps better than
   the Nifty 50 (the Nifty 50 result is already in the ledger). The rule is unchanged; only the universe and the fifth differ.

## What is used, and what is not

* Prices: the project's own validated loader and the discontinuity gate, as for every equity strategy. A stock the gate blocks is
  removed BEFORE ranking, so it can never be chosen (`FINDINGS.md`, Bug 4).
* Windows: in-sample 2015-01-01 to 2020-06-30 and out-of-sample 2020-07-01 to 2025-12-31 (`config.py`), verified disjoint.
* Each idea is judged by the same harness as every other strategy, at the cumulative count, with the zero-skill benchmark
  (200 random selections of the same size from the same eligible stocks, same costs and turnover rule; seed 20261022, fixed here),
  exposure and turnover reported beside every Sharpe ratio.
* Not done, on purpose: no other lookback, no other fraction, no "best of" across the three, no change after seeing a number.

## How it will be reported

All three with their harness status at 215, in-sample and out-of-sample Sharpe, return, worst fall, exposure, turnover and the
zero-skill percentile, beside buy and hold of the same universe. A failure to beat the benchmark is reported as found.

## Limits stated in advance

Today's index membership is used for the whole history, so every result here is flattered by survivorship (`FINDINGS.md`
Section 5 measured this for the Nifty 50; it is larger for the Midcap 150, where more names have left the index). Free-source
prices; no taxes; the engine's cost model, not actual fills; long-only, so the full academic long-short premium cannot be captured.
Passing a bar set by 215 ideas is hard: a rule can make money and still fail it, which is what most results in this project did.

## What was found (registered 2026-10-22, ledger 212 became 215)

Run once with the frozen 200 random portfolios per window. The bar is 0.05/215 = 0.0002326. In-sample is 2015-01-01 to 2020-06-30,
out-of-sample is 2020-07-01 to 2025-12-31. "Holding all" is every eligible stock in the universe, equal weight, same monthly rebalance and
costs. "Beats random" is where the idea's Sharpe sits among 200 portfolios that pick the same number of stocks by lot.

| Idea | Status at 215 | Sharpe IS / OOS | Holding all, Sharpe IS / OOS | CAGR OOS (holding all) | Worst fall OOS (holding all) | Beats random IS / OOS | p IS / p OOS |
|---|---|---|---|---|---|---|---|
| Low volatility, Nifty 50 | `VALIDATED_FAILED` | 0.49 / 0.99 | 0.33 / 1.55 | 18.3% (30.3%) | -17.8% (-16.2%) | 98.5% / 16.0% | 0.130 / 0.0105 |
| One-month reversal, Nifty 50 | `OOS_ONLY_SIGNIFICANT` | 0.17 / 1.57 | 0.19 / 1.54 | 35.7% (30.2%) | -18.7% (-16.2%) | 82.0% / 98.0% | 0.347 / 0.000132 |
| 12-1 momentum, Midcap 150 (top 30) | `OOS_ONLY_SIGNIFICANT` | 0.54 / 1.98 | 0.33 / 1.66 | 55.2% (35.6%) | -23.2% (-19.0%) | 99.5% / 100% | 0.105 / 0.0000023 |

* **None is validated.** A result needs the bar cleared in both windows; the two that clear it clear it only in the later window, in
  which Indian equities rose strongly. The harness's test asks whether the Sharpe ratio is above zero, which a rising market gives to almost
  any long-only rule, so passing it in the later window alone is weak evidence. The earlier window, which did not have that tailwind, fails for all three.
* **Low volatility did the opposite of what the idea promised in the strong market.** It beat random picks in the earlier window (98.5th
  percentile) and lost to them in the later one (16th), returning 18% a year against 30% for holding all 49 stocks, with a similar worst fall. A
  rule that is calm in a bull market is left behind.
* **One-month reversal is, in the later window, about the same as holding everything** (Sharpe 1.57 against 1.54) and worse in the earlier one
  (0.17 against 0.19), while it replaces most of the portfolio every month (turnover about 150 to 165% of the portfolio each rebalance, costs already included).
  The random-pick percentile (98th in the later window) says it beat random Nifty 50 picks there, but not by enough to pass the bar both times.
* **Mid-cap momentum is the strongest of the three and the most flattered.** It beat random picks and holding all in both windows (Sharpe 0.54 against 0.33,
  and 1.98 against 1.66). Its p-value in the earlier window is 0.105, far above the bar, because that window was weak for equities. See the survivorship check below.
* Equal-weight holding of the Midcap 150 itself returned 35.6% a year in the later window (Sharpe 1.66); a good part of the 55% is the mid-cap rally and today's index list, not selection.

### Survivorship check of the mid-cap idea (`research/midcap_survivorship_check.py`, a diagnostic: registers nothing)

| | CAGR in-sample | CAGR out-of-sample |
|---|---|---|
| Today's list (the registered result) | 14.0% | 55.2% |
| Four verified failures added back (Jet Airways, Reliance Capital, Reliance Communications, Reliance Naval) | 12.8% | 54.7% |
| Without the 50 stocks that were not yet trading when the history starts | 13.5% | 42.0% |

* Adding failed companies back barely moves the result (the rule held them 66 to 69 times), but this is a hand-picked upper bound and the engine holds a
  delisted stock at its last price.
* The stocks that were not yet listed in early 2015 are 35% of the universe and 21% of the later-window picks (7% of the earlier ones); without them the later
  window drops from 55% to 42% a year. That is a sensitivity, not an estimate (a recent listing's momentum can be real), but it shows how much of the number depends on
  which stocks are on today's list. The bias of using today's index membership for the whole history cannot be removed with this data.

So the honest reading: one-month reversal and mid-cap momentum look good in the later window, do not pass in both, and the mid-cap result is
flattered by survivorship. They are not added to the paper tests; if they were, they would need their own frozen note and a forward clock
(`FORWARD_BOOKS.md`) and would count nothing new in the ledger.
