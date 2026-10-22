# Findings: Systematic Strategy Research on NSE Equities, 2015–2025

**Status: complete, corrected, consolidated; one forward test running. Last updated 2026-10-16.**

Six strategies. Three universes (Nifty 50, Nifty Midcap 150, Nifty
Smallcap 250). 204 pre-registered/tracked hypotheses. **Not one produced
a validated edge over buy-and-hold.** Four of the results that looked
positive along the way turned out to be bugs in this project's own
measurement code, not in the market — see Section 6, which documents
that in detail because it is arguably the most useful thing this project
produced.

> **Data note (2026-10-16): a loader bug was found and fixed; figures below are the values as first computed.**
> yfinance's `end` is exclusive, so the last day of the window was never downloaded (Midcap/Smallcap ended
> 2025-12-30), and the Nifty 50 cache had a fake one-day move on 2025-12-31 for four stocks where a tail was
> spliced on at a different dividend-adjustment basis. The loader is fixed, the cache re-downloaded on one
> basis, and all three universes now run through 2025-12-31. **No status and no conclusion changed.** The
> figures printed in this document move by about 0.01 Sharpe at most; current values for the headline results,
> out-of-sample: MA crossover Nifty 50 **0.984** (printed 0.974), Midcap **1.450** (1.440), Smallcap **1.508**
> (1.505); momentum **1.414** (1.405); RSI reversion **-1.326** (printed -1.331). The one result near its bar: Smallcap
> MA crossover's out-of-sample p = 0.000231 against 0.05/204 = 0.000245, which would fail at 217 hypotheses
> (it is `OOS_ONLY_SIGNIFICANT` regardless). Full before/after table and method:
> `data/known_issues.md`, "The last day of the research window is never downloaded".

> **Ledger update (2026-10-16): 204 became 205.** The quality + value forward book
> (`FUNDAMENTALS_PREREG.md`) was registered and counted. No backtest was run for it, so none of the
> results in this document changed; Bonferroni bar is now 0.05/205 = 0.000244.
>
> **Second ledger update (2026-10-19): 205 became 208.** The three risk profiles of the multi-asset advisory tool
> (`ADVISORY.md`, `research/advisory.py`) were registered and judged once; all three are `VALIDATED_FAILED`.
> Bonferroni bar is now 0.05/208 = 0.000240. No result in this document changed (Smallcap MA, p = 0.000231, still clears it).
>
> **Third ledger update (2026-10-20): 208 became 210.** Two multi-asset trend-trading rules
> (`MULTIASSET_TREND.md`, `research/multiasset_trend.py`) were registered and judged once; both are `VALIDATED_FAILED`.
> Bonferroni bar is now 0.05/210 = 0.000238. No result in this document changed (Smallcap MA, p = 0.000231, still clears it).
>
> **Fourth ledger update (2026-10-20): 210 became 212.** Two multi-asset dual-momentum rules
> (`MULTIASSET_MOMENTUM.md`, `research/multiasset_momentum.py`) were registered and judged once; both are `VALIDATED_FAILED`
> (profitable in the backtest, about fifty times short of the bar). Bonferroni bar is now 0.05/212 = 0.000236. No result in this
> document changed (Smallcap MA, p = 0.000231, still clears it).
>
> **Fifth ledger update (2026-10-22): 212 became 215.** Three stock-selection ideas (`FACTOR_IDEAS.md`,
> `research/factor_ideas.py`) were registered and judged once: low volatility on the Nifty 50 (`VALIDATED_FAILED`), one-month
> reversal on the Nifty 50 and 12-1 momentum on the Midcap 150 (both `OOS_ONLY_SIGNIFICANT`: they clear the bar in the later window
> and not in the earlier one, so neither is validated). Bonferroni bar is now 0.05/215 = 0.0002326. Smallcap MA (p = 0.000231) still
> clears it, by a hair. Full results and the survivorship check of the mid-cap idea are in `FACTOR_IDEAS.md`.

This document is the complete, current research record. It supersedes
every number previously reported for the strategies below — where a
number changed from an earlier version of this file, the reason is in
Section 6 and Appendix A, not hidden. `MIDCAP_SMALLCAP_FINDINGS.md`
carries the full construction detail for the Midcap/Smallcap universes
(ticker resolution, cost re-estimation, survivorship measurement
methodology), and `MOMENTUM_FINDINGS.md` carries the full detail for
cross-sectional momentum (a mechanically distinct strategy family
needing its own backtest engine) — neither is duplicated here; this
document has the numbers that matter for the conclusion. The forward
test in Section 3g is specified in `FORWARD_TEST.md`.

---

## 1. The question

Do simple, mechanically-applied trading rules — a trend-following moving-
average crossover, a mean-reversion RSI threshold rule, and a
statistical-arbitrage pairs screen — produce risk-adjusted returns better
than simply buying and holding the same stocks, after realistic Indian
equity costs? And does the answer depend on which segment of the market
you test it on? A later question was added at the owner's request:
**can a strategy reach a 90% win rate, and what does it cost to get
there?** (Section 3f.)

Tested in stages, each raising the bar on what would count as a real
answer rather than an anecdote:

1. One stock, one strategy, the default parameterization.
2. A 48-symbol universe, pooling trades so sample size stops being the
   limiting factor.
3. A 109-point grid over the strategy's own parameters, to check whether
   *any* variant works and whether an apparent winner is distinguishable
   from noise.
4. A second, entirely different strategy family (RSI mean-reversion) and
   a third (cointegration-based pairs), so the answer isn't "one rule
   happens not to work."
5. The same first rule, unchanged, on two segments the large-cap universe
   doesn't cover (Midcap 150, Smallcap 250) — a control comparison asking
   whether Nifty 50 specifically (the most heavily arbitraged segment)
   was the reason nothing worked.
6. A purpose-built statistical test (Section 4) asking whether any
   apparent improvement anywhere in the above is genuine skill or a
   mechanical artifact of how much time a strategy spends out of the
   market.
7. A dip-buying rule built specifically to maximize win rate, followed
   by a bounded 36-variant search for a 90% win rate after costs, to
   find out what a high win rate actually buys (Section 3f).
8. A frozen forward test on data that does not exist yet — the only
   test left once every historical window has been looked at
   (Section 3g).

## 2. Methodology

**Universes:**
- **Nifty 50** — current constituent list (50 symbols), minus Yes Bank
  and Vodafone Idea (run separately as stress cases — both went through
  a near-collapse during the window and aren't representative of a
  normal constituent).
- **Nifty Midcap 150** — 145/150 constituents resolved to NSE tickers.
- **Nifty Smallcap 250** — 246/250 constituents resolved.
- All three are **current** constituent lists, not point-in-time —
  survivorship bias is real and measured, not just disclosed. See
  Section 5.

**Period:** 2015-01-01 to 2025-12-31 (~11 years, ~2,714 trading days),
split at 2020-06-30 into in-sample (discovery) and out-of-sample
(confirmation) halves for every strategy tested at universe scale.

**Costs (India, equity delivery):** 0% brokerage (discount-broker
standard), 0.1% STT both legs, 0.00307% exchange transaction charge,
₹10/crore SEBI fee, 18% GST on (brokerage + SEBI + exchange charges),
0.015% stamp duty (buy leg only), and slippage — 0.05% per side for
Nifty 50 (verified against Zerodha's published rates), re-estimated
per-symbol for Midcap/Smallcap as a square-root function of each stock's
own average daily traded value (median 0.088%/0.136%, 1.8-2.7x the flat
large-cap rate, up to 10x at the thinnest names — see
`MIDCAP_SMALLCAP_FINDINGS.md` Section 3 for the derivation).

**Look-ahead handling:** a signal computed from day T's close cannot
affect day T's position — `position = signal.shift(1)`, one line, with
an independent runtime assertion that re-derives the same invariant a
different way and fails loudly if it's ever violated. Verified by
hand-tracing a real trade against raw data (Stage 3) and by deliberately
breaking the lag in a test and confirming the assertion fires
(`tests/test_backtest_lookahead.py`). Fills happen at the next bar's
open, never the same bar's close.

**Benchmarks:** buy-and-hold of the same symbol/universe, run through the
*identical* backtest engine as the strategy (same lag mechanism, same
cost model, same starting capital) — never computed separately, so the
comparison is never apples-to-oranges by construction.

**Pre-registration:** the pairs cointegration work is fully pre-
registered — `METHODOLOGY.md`, frozen 2026-09-03, before any pair was
tested for performance, fixes the selection criteria, statistical test,
significance threshold, entry/exit rules, stop rules, and holdout
period in writing. The MA crossover and RSI work predates a formal
pre-registration discipline; the multiple-testing correction and
out-of-sample check (below) are what stand in for it retroactively.

**Multiple-testing correction:** every hypothesis this project has ever
tested is tracked in a persistent, cumulative ledger
(`research/hypothesis_ledger.json`) — **204 total** (109 MA-crossover
sweep cells + 51 pairs + 2 MA-vs-RSI + 2 Midcap/Smallcap + 1
cross-sectional momentum + 2 dip-buying A/B + 1 dip-in-uptrend + 36
win-rate grid variants). Bonferroni (family-wise) correction is
applied against this TRUE cumulative count (a real bug, not always the
case — see Section 6, Bug 3); Benjamini-Hochberg FDR is applied within
each run's own batch only, disclosed as such rather than presented as
more rigorous than it is. A result is never reported as "significant"
against the wrong, smaller denominator.

## 3. Results

### 3a. MA crossover — Nifty 50

**Single stock (RELIANCE.NS), default params (fast=50, slow=200):**

| | Strategy | RELIANCE Buy & Hold | Nifty 50 Buy & Hold |
|---|---|---|---|
| Total Return | 193.34% | **710.03%** | 206.70% |
| CAGR | 10.28% | **20.96%** | 10.73% |
| Max Drawdown | −45.82% | −45.11% | −38.28% |
| Sharpe | 0.30 | **0.64** | 0.37 |
| Trades | 6 | — | — |

One trade (2015-11-26 to 2019-09-09, a multi-year uptrend) produced
93.8% of the strategy's total realized profit; excluding it, compounded
return across the other 5 trades was +4.1% against +169.3% including it.
Six trades is not a sample on its own — this is why every result below
pools across a universe.

**Universe (48 symbols), full period:**

| | Strategy (pooled) | Universe Buy & Hold |
|---|---|---|
| CAGR | 10.33% | **18.10%** |
| Max Drawdown | −30.32% | −38.82% |
| Sharpe | 0.43 | **0.75** |
| Total Trades | 320 | — |
| Win Rate | 48.1% | — |
| Profit Factor | 3.72 | — |

**Genuine in-sample / out-of-sample split** (corrected — see Section 6):

| | Strategy IS | Strategy OOS | Buy&Hold IS | Buy&Hold OOS |
|---|---|---|---|---|
| CAGR | 3.06% | 18.63% | 10.29% | **29.95%** |
| Sharpe | **−0.19** | 0.97 | 0.32 | **1.32** |
| Max Drawdown | −31.96% | −16.10% | −40.07% | −19.46% |

The strategy loses to buy-and-hold on both CAGR and Sharpe in **both**
genuinely-separated halves. 2020-07 to 2025 was an exceptional bull run
(buy-and-hold Sharpe 1.32) — the strategy's own absolute numbers look
strong in isolation there (Sharpe 0.97), but so did everything else, more
so. Harness status: **VALIDATED_FAILED** (out-of-sample p=0.0118 does
not clear the TRUE cumulative Bonferroni bar of 0.05/162≈0.00031 —
against just this run's own batch size of 2 it would have cleared 0.025
and shown as OOS_ONLY_SIGNIFICANT, which is what this document reported
before a THIRD harness gap was found and fixed; see Section 6).

**Parameter sweep (109 cells, fast∈[10,100], slow∈[100,300]):**

| | CAGR | Sharpe |
|---|---|---|
| Min | 9.36% | 0.35 |
| Median | 10.97% | 0.49 |
| Max (best cell: fast=100, slow=280) | 13.27% | 0.63 |
| Universe buy-and-hold | 18.10% | 0.75 |

**Zero of 109 combinations beat buy-and-hold on CAGR or Sharpe.** The
grid's own noise floor (Lo 2002 asymptotic SE, n≈2,713 days, grid-mean
Sharpe 0.49) is ≈0.30 — larger than the entire observed spread across
all 109 cells (0.28). An extreme-value ceiling for the maximum of 109
independent draws from that noise floor is ≈1.22; the actual observed
maximum (0.627) sits comfortably below it. The best-looking cell in the
grid is unremarkable relative to pure sampling noise, not a discovery.

**Stress cases (not blended into the universe above):** Yes Bank +11.98%
total return / 1.03% CAGR / Sharpe −0.05 (essentially flat); Vodafone
Idea −34.97% / −3.84% CAGR / Sharpe −0.11 (a loser). Neither would have
rescued the strategy's case.

### 3b. MA crossover — Midcap 150 and Smallcap 250 (control comparison)

Same rule, same parameters (`config.MA_CROSSOVER_PARAMS`, fast=50/
slow=200, never retuned), liquidity-adjusted costs, genuine IS/OOS split.
Full universe-construction and cost-derivation detail in
`MIDCAP_SMALLCAP_FINDINGS.md`.

**Nifty Midcap 150:**

| | Strategy IS | Strategy OOS | Buy&Hold IS | Buy&Hold OOS |
|---|---|---|---|---|
| CAGR | 3.25% | 26.91% | 10.94% | **36.28%** |
| Sharpe | **−0.219** | 1.440 | 0.375 | **1.564** |
| Max Drawdown | −27.40% | −14.76% | −37.66% | −22.59% |

**Nifty Smallcap 250:**

| | Strategy IS | Strategy OOS | Buy&Hold IS | Buy&Hold OOS |
|---|---|---|---|---|
| CAGR | 5.55% | 31.27% | 8.34% | **40.00%** |
| Sharpe | +0.030 | 1.505 | 0.221 | **1.506** |
| Max Drawdown | −35.17% | −18.05% | −58.27% | −28.43% |

The strategy loses to buy-and-hold on CAGR in every cell, both
universes, both windows — often by a wide margin (Smallcap OOS: 31.27%
vs 40.00%). On Sharpe, Smallcap's OOS number (1.505) is nearly identical
to its own buy-and-hold's (1.506) — Section 4 shows precisely why that
near-tie is not evidence the strategy adds value.

Harness status, against the TRUE cumulative Bonferroni bar (0.05/164≈
0.00030, not just this run's own batch size of 2 — see Section 6):
Midcap 150's out-of-sample p=0.0004 does **not** clear it —
**VALIDATED_FAILED**. Smallcap 250's out-of-sample p=0.0002 clears it by
a narrow margin — **OOS_ONLY_SIGNIFICANT**, the only one of the three
MA-crossover universes that still does once the correction is computed
correctly. This is closer to noise than this document previously
reported (both had shown as OOS_ONLY_SIGNIFICANT under an
under-correction bug — see Section 6) — the genuinely-corrected picture
is that essentially none of this survives multiple-testing scrutiny,
which strengthens rather than complicates the overall conclusion
(Section 7).

**Does the universe matter?** Yes, in one precise, narrower sense than
originally concluded: the gap between the strategy's OOS Sharpe and its
own universe's OOS buy-and-hold Sharpe shrinks monotonically as the
universe gets smaller — Nifty 50 −0.35, Midcap 150 −0.12, Smallcap 250
≈0.00. Costs and data quality both moved in the direction that should
have made this *harder* to see (higher liquidity-adjusted slippage,
stricter validation), so the pattern is real. But — see Section 4 — it
is not evidence of timing skill anywhere, including Smallcap.

### 3c. RSI mean-reversion — Nifty 50 universe

Period=14 (Wilder's smoothing), oversold=30, exit=50 — the one
configuration tested, never swept (see Section 7).

| | In-sample | Out-of-sample |
|---|---|---|
| CAGR | −0.40% | 2.08% |
| Sharpe | **−0.579** | **−1.331** |
| Max Drawdown | −27.53% | −3.27% |
| Trades | 368 | 283 |
| Market Exposure | 13.0% | 8.8% |

A clean, unambiguous failure — negative Sharpe in both genuinely-
separated halves, unlike every MA crossover variant above. Harness
status: **VALIDATED_FAILED**. Worth noting for what it rules out: the
strategy is invested only 9-13% of the time (RSI rarely drops into
oversold territory and, once it does, exits quickly), so this isn't
"loses because it's out of the market during a bull run" in the way MA
crossover's underperformance partly is — it loses on a risk-adjusted
basis even while holding cash the overwhelming majority of the time.

### 3d. Pairs cointegration screen — Nifty 50 sector-filtered candidates

Pre-registered in full (`METHODOLOGY.md`) before any pair was tested.
Same-sector economic pre-filter (`config.SECTOR_MAP`) → 55 candidate
pairs → 51 with ≥500 days of overlapping history in the selection window
(2015 to 2020-06-30) → Engle-Granger cointegration test, both directions,
required to both reject the null at p<0.05.

| | Count |
|---|---|
| Candidate pairs (same-sector, sufficient history) | 51 |
| Qualify at raw p<0.05 (both directions) | 5 |
| Survive Bonferroni correction | 1 |
| Survive Benjamini-Hochberg FDR | 3 |
| **Still qualify on a fresh out-of-sample retest (2020-07 to 2025-12)** | **0 of 5** |

The 5 raw-qualifying pairs: HDFCLIFE/SBILIFE (Insurance, half-life 10.9
days), HCLTECH/TCS (IT, 21.2 days), INFY/TCS (IT, 23.5 days), HINDALCO/
TATASTEEL (Metals, 31.8 days), ASIANPAINT/TRENT (Consumer Discretionary,
22.9 days) — all with textbook mean-reversion timescales in-sample.
Every one of them re-tested at holdout p-values of 0.10-0.40, nowhere
near the 0.05 bar. A relationship that looked statistically real for five
years did not survive being checked again on data it hadn't seen — the
single cleanest "looked significant, wasn't real" result in this entire
project.

Per `METHODOLOGY.md` Section 0, no execution layer was ever built for
this: a feasibility check found the SEBI-mandated futures margin
(₹15-20 lakh per leg) exceeds this project's ₹10 lakh capital base for
even a single pair, so this was scoped as pure statistical research
("does stable cointegration exist and survive out-of-sample") rather
than a strategy evaluation from the start.

### 3e. Cross-sectional momentum — Nifty 50, long-only, 12-1/top-10/monthly

Full detail in `MOMENTUM_FINDINGS.md`; pre-registered in
`MOMENTUM_METHODOLOGY.md` before any result existed. A mechanically
distinct family from everything above — ranks stocks against EACH
OTHER rather than against their own history, requiring a new backtest
engine (`engine/portfolio_backtest.py`) since the existing one assumes
independent per-symbol books.

**Corrected 2026-09-21.** The first version of this section reported
momentum beating its zero-skill benchmark in-sample (97th percentile)
and being inconclusive out-of-sample (92nd). Both were wrong, caused by
two bugs in this project's own momentum code (a gate-blocked symbol's
slot silently becoming cash, and a random benchmark that started a month
late) — see Section 6, Bug 4, and `MOMENTUM_FINDINGS.md`.

| | In-sample | Out-of-sample |
|---|---|---|
| CAGR | 11.18% | 35.73% |
| Sharpe | 0.361 | 1.405 |
| Max Drawdown | −41.01% | −21.41% |
| Zero-skill benchmark percentile (200 random-selection portfolios) | **88.0th (does not beat)** | **87.5th (does not beat)** |
| Harness status | — | **VALIDATED_FAILED** (OOS p=0.0006 vs. bar 0.000303) |

Momentum does not clearly beat picking the same number of stocks at
random, in either window, by two independent tests (the pre-registered
bar was the 95th percentile to win, 90th or lower to lose). Its
out-of-sample Sharpe (1.405) is not unusual for this project — MA
crossover's was 1.44 on Midcap and 1.51 on Smallcap — because 2020-07 to
2025 was a broad bull run. Turnover (41–49% of the portfolio per month,
roughly 5–6x its value per year) costs 7.0% / 15.9% of starting capital
(IS/OOS); the random arm pays the same, so costs don't explain the miss
by themselves. Survivorship bias is measurably worse than for any other
strategy here: 87.9% of formation dates had fewer than all 48
constituents rankable, and four named casualties from Section 5 would
each have cleared the actual top-10 cutoff on 10–28 separate formation
dates — dates this current-constituent-only backtest cannot see.

### 3f. Dip-buying, built to maximize win rate

Requested by the owner ("I want a 90% win rate"). Entry: RSI(14) below
a threshold. Exit: a small fixed profit target. Everything in this
subsection is reported with the win rate counted two ways, because the
difference between them is the finding: **closed-trade win rate** (what
`engine/metrics.py` reports, and what a broker's closed-positions report
shows) and **all-in win rate** (open positions marked to market, an
underwater open position counting as a loss).

**Variant A — +3% target, no stop-loss (the maximum-win-rate version):**

| Nifty 50, pooled | In-sample | Out-of-sample |
|---|---|---|
| Win rate, closed trades | **98.6%** (284 trades) | **99.6%** (263 trades) |
| Win rate, counting open positions | 89.8% (30 open, 28 underwater) | 97.0% (8 open, 7 underwater) |
| Avg closed win / avg closed loss | +4.28% / −2.23% | +4.20% / −0.60% |
| Worst still-open position | **−73.7%** | −14.8% |
| Realized P&L / unrealized P&L (Rs) | +1.37 cr / **−85 lakh** | +1.49 cr / −7.6 lakh |
| CAGR vs buy & hold | 1.98% vs 10.29% | 7.99% vs 29.95% |
| Sharpe vs buy & hold | −0.29 vs 0.32 | 0.48 vs 1.32 |
| Time invested | 27.8% | 19.8% |

A closed-trade win rate near 100% is what never closing a loser
produces: the losing trades are not losses, they are open positions. The
profit factors (127, 3,252) are meaningless for the same reason.

**Variant B — the same rule with a 10% stop:** win rate falls to 67.4%
in-sample (601 trades) and 82.0% out-of-sample (362 trades); average win
+4.5% against average loss −11.5%; CAGR −1.97% / +1.75%, below the 6%
risk-free rate in both windows. At those payoffs the break-even win rate
is 72%, so the in-sample window loses money despite a "good" win rate.

**Variant U — dip in an uptrend (RSI<30 and above the 200-day average;
+4% / −12% stop / 60-day limit), one pre-registered configuration:**

| Nifty 50, pooled | In-sample | Out-of-sample |
|---|---|---|
| Win rate, all positions | 72.3% (65 trades) | 86.7% (82 closed + 1 open) |
| Break-even win rate for its payoffs | 70.2% | 70.6% |
| Expectancy per trade, before costs | +0.38% | +2.66% |
| CAGR vs buy & hold | 0.11% vs 10.29% | 0.84% vs 29.95% |
| Time invested | 1.6% | 2.5% |

Out-of-sample has a genuine per-trade edge; it fires so rarely (capital
idle 97–98% of the time) that it does not become a portfolio return.

**The bounded 36-variant search.** Grid declared in advance: RSI entry
{30, 40} × take-profit {2%, 3%, 4%} × stop {8%, 12%, 20%} × time limit
{30, 60 days}, all with the 200-day-average filter, all 36 counted in the
ledger. Win condition fixed in advance: ≥90% all-in win rate after
costs, positive net expectancy, ≥150 trades. Searched on 2015–2025;
the selected variant was then run **once** on 2026-01-01 to 2026-10-15,
data that did not exist when any earlier strategy was tested.

| | Search window (2015–2025) | 2026 holdout |
|---|---|---|
| Variants reaching 90% with positive expectancy | **0 of 36** | — |
| Best win rate of all 36 | 88.5% (RSI<30, +2%/−20%/60d; 148 trades — two under the 150-trade minimum, not waived) | — |
| Selected variant (RSI<40, +2%/−20%/60d) win rate, all-in | 85.1% (1,122 trades) | **60.5%** (closed 75.4% of 61; 15 open) |
| Net expectancy per trade | +0.80% | **−0.67%** |
| Break-even win rate for its payoffs | 80.1% | 80.1% (p = 0.86 against it) |
| Strategy CAGR vs buy & hold | 1.5% vs ≈18% (Section 3a) | −4.4% vs −10.2% (a falling market) |

**Forward test of the two configurations that could serve a 90% goal,
run once each on the same 2026 data** (parameters fixed before 2026 data
existed in this project; not tuned; see `research/forward_test_2026.py`):

| 2026-01-01 to 2026-10-15 | A (+3%, no stop) | U (uptrend, +4%/−12%/60d) |
|---|---|---|
| Win rate, closed trades | **93.6%** (47) | 55.6% (9) |
| Win rate, counting open positions | **67.1%** (26 open, 21 underwater) | 41.7% |
| Realized / unrealized P&L (Rs) | +16.5 lakh / **−21.3 lakh** | −1.5 lakh / −1.3 lakh |
| Worst open position | −23.8% | −6.8% |
| Time invested | 35.7% | 3.4% |

In this falling market A lost less than holding the same stocks (CAGR −1.9% against −9.3%), but it was invested only 36% of the time, so that reflects cash, not stock selection. Its unrealized losses exceed its realized gains.

**What this establishes.**

1. **90%+ is achievable on paper and only on paper.** Every configuration
   showing it does so by not realizing its losses; counted honestly, the
   best result on unseen data was 67%.
2. **Win rate and payoff are one trade-off, not two goals.** For win
   rate *w*, average win *a*, average loss *L*, profit requires
   *w* > *L* / (*a* + *L*). Targets of 2–4% against stops of 12–20% need
   75–91% just to break even, before costs of roughly 0.3% per round
   trip. Raising the target lowers the win rate; tightening the stop
   turns open losses into recorded ones.
3. **Searching longer on seen data finds noise.** The variant selected
   at 85% fell to 60% on fresh data. Nothing in 36 variants survived;
   none would survive the 204-hypothesis correction (Bonferroni bar ≈
   0.00025).
4. **Statistical-test caveat, stated for fairness.** The harness's
   Sharpe-based test is the wrong lens for a strategy that is ~97% cash
   (the engine pays cash 0% against a 6% risk-free rate, giving Sharpe
   ratios of −6 or worse for strategies that merely earn little). The
   per-trade statistics above (win rate, expectancy, break-even
   comparison) are the fairer reading; they reach the same conclusion.

Harness status: variants A and B `VALIDATED_FAILED`; U
`VALIDATED_FAILED`; the 36 grid variants `UNVALIDATED` except the
selected one, `VALIDATED_FAILED`.

### 3g. Forward test (running; see `FORWARD_TEST.md`)

Frozen 2026-10-16, before any of its data exists: RSI<40 and above the
200-day average; exit +2% / −12% stop / 60 trading days; Nifty 50. Chosen
mechanically as the grid variant with the highest all-in win rate that
also limits losses (stop ≤12%) and has ≥150 trades — 83.6% over
2015–2025, break-even 79.1%. A win is **your definition**: 90% of ALL
positions, open ones marked to market. Only entries filled from the
2026-10-19 open count; no conclusion before 100 counted positions
(about a year); pass requires ≥90%, positive expectancy, and p < 0.05
against break-even. The stated expectation, written down in advance: a
win rate below 90%. Status: **not started** (first countable fill is
the 2026-10-19 open). Run `python research/forward_log.py` or use the
app's Forward test page.

## 4. The zero-skill Sharpe benchmark, and what it established

A strategy that's out of the market some fraction of the time will
almost always show lower volatility than buy-and-hold. If that alone
were enough to raise its Sharpe ratio, "the strategy adds value" would
be the wrong conclusion to draw from a Sharpe improvement — "the
strategy is diluted with cash, and dilution mechanically changes Sharpe"
would be the right one. Smallcap 250's near-tie with its own
buy-and-hold (Section 3b) made this distinction matter in practice, not
just in principle.

**The test:** Sharpe ratio is invariant to blending a return stream with
cash at the risk-free rate — diluting a stream to weight *w* scales both
its excess return and its volatility by exactly *w*, leaving their ratio
unchanged. So a strategy that holds its OWN realized exposure fraction
on RANDOM, trend-blind days (zero timing skill) has an *expected* Sharpe
identical to 100%-invested buy-and-hold, regardless of what that
exposure fraction is. That gives a clean, parameter-free null: a real
timing edge has to show up as Sharpe measurably ABOVE buy-and-hold's,
not merely close to it.

| Universe (OOS) | Exposure | Buy&Hold Sharpe | Zero-skill benchmark | Actual strategy | Gap |
|---|---|---|---|---|---|
| Nifty 50 | 73.7% | 1.324 | 1.324 | 0.974 | **−0.350** |
| Midcap 150 | 66.7% | 1.564 | 1.564 | 1.440 | **−0.124** |
| Smallcap 250 | 63.6% | 1.506 | 1.506 | 1.505 | **−0.001** |

(The benchmark column equaling buy-and-hold's own Sharpe in every row is
not a coincidence — it's the invariance property above, confirmed
numerically for Midcap and Smallcap by direct simulation.)

**What this established:**

1. **No universe shows genuine timing skill.** Every gap is ≤0. Nifty 50
   and Midcap's timing was actively *negative* — worse than what
   randomly sitting out the same fraction of days would have given for
   free. Smallcap is statistically indistinguishable from zero skill,
   not evidence of some.
2. **A previous conclusion in this project is retracted because of this
   test.** An earlier version of the Midcap/Smallcap analysis read
   Smallcap's near-buy-and-hold Sharpe as a genuine economic mechanism
   (slow-motion crashes giving a 200-day MA time to react rather than
   getting whipsawed). That story does not survive this test — the
   near-tie is exactly what a strategy with no timing ability at all
   would be expected to produce.
3. **A standing rule for future work:** never compare a partially-
   invested strategy's Sharpe against 100%-invested buy-and-hold
   directly and call an improvement "skill." Compare it against this
   strategy's own realized-exposure zero-skill benchmark instead — see
   Section 8.

## 5. Survivorship bias — measured, not just disclosed

All three universes use current constituent lists, not point-in-time
ones. Measured directly from this project's own data (not cited from
outside literature): the fraction of today's usable constituents that
lack near-full 2015-2025 price history (a proxy for "wasn't there, under
this identity, the whole time"):

| Universe | % lacking full 2015 history |
|---|---|
| Nifty 50 | 12.0% (6/50) |
| Midcap 150 | 36.1% (52/144) |
| Smallcap 250 | 48.5% (116/239) |

This captures listing churn but not the other channel — a company
continuously listed since 2015 that fell out of the index or was
suspended/delisted entirely, which shows up as *absent*, not
*short-history*. Five concrete, individually-verified examples: Jet
Airways (suspended 2019, fully delisted 2024), Reliance Capital,
Reliance Communications, and Reliance Naval and Engineering (all IBC
insolvency), and DHFL (collapsed 2019, delisted 2021). None of the five
appear in either constituent list today.

**Magnitude bound, not just direction:** four of these five (DHFL has no
price history left on Yahoo Finance at all — itself a data-source-level
instance of the same bias) were added back into the Midcap 150 aggregate
as an explicitly biased, worst-case sample. Effect: OOS Sharpe moved from
1.440 to 1.421 (−0.018), OOS CAGR from 26.91% to 26.44% (−0.48pp) — small,
because each collapse is one of ~140 equal-sized parallel books (this
system does not market-cap-weight) and the strategy's own trend-following
exit discipline caps, though doesn't eliminate, the damage from a
slow-motion collapse. This bounds the damage from these four specific
named catastrophes; it is not proof survivorship bias is small in
general, only that these examples don't explain the results above.

## 6. The result-breaking bugs

*(Full incident writeups: `engine/backtest.py`'s docstring,
`research/harness.py`'s docstring, `tests/test_backtest_date_window.py`,
`tests/test_harness.py`.)*

Every apparent positive result this project produced during the
Midcap/Smallcap and MA-vs-RSI stages turned out to be an artifact of a
bug in the measurement code, not the market — four of them, found in
sequence, each while verifying the fix for the one before it.
Documenting this is a methodological finding in its own right, not an
aside: a research pipeline that produces four independently-discovered,
independently-fixed false positives from its own tooling, each one
surfaced only by pursuing the previous fix to its conclusion rather than
stopping once the headline number looked right, is telling you something
about how easy this kind of mistake is to make and how hard it is to
catch by inspection.

### Bug 1: the in-sample/out-of-sample split wasn't a split

**What it was.** `engine/backtest.py`'s `run_backtest(df, signal, report,
start, end, ...)` used `start`/`end` for exactly one thing — the
discontinuity gate check. The trading loop iterated the entire `df`
regardless of what window was requested. Every caller that split a
universe into "in-sample" and "out-of-sample" (`run_validation.py`, the
harness demo scripts, the Midcap/Smallcap work) loaded the FULL 2015-2025
history once and reused it for both calls.

**What it made results look like.** Two numbers that looked like genuine
replication because they were, almost, the same computation: Nifty 50's
originally-reported "in-sample vs out-of-sample" CAGR (10.28% vs 10.54%)
and Sharpe (0.42 vs 0.43) were "remarkably stable" only because both
calls silently ran the identical full-history backtest — the tiny
residual difference came entirely from which symbols the discontinuity
gate excluded in each query window, not from any actual difference in
period. For Midcap/Smallcap, the same bug produced an apparently-genuine
"Smallcap 250 beats its own buy-and-hold on Sharpe out-of-sample" result
that later collapsed once real out-of-sample data was used.

**What actually caught it.** Not a code review, and not a test — a
follow-up research question. Building a synthetic zero-skill exposure
benchmark (Section 4) for a specific, isolated 4-stock survivorship
stress test produced an "in-sample" and "out-of-sample" result that were
identical to three decimal places, including the trade count. That's a
statistical impossibility for two genuinely different multi-year
windows, and it was implausible enough to investigate immediately rather
than write up. A hand-trace on a real symbol (HAVELLS.NS) confirmed the
two "different-period" equity curves were byte-identical.

**What would have caught it sooner.** A regression test asserting that
two different `[start, end]` windows on the same signal/data produce
DIFFERENT equity curves. This is now `tests/test_backtest_date_window.py`
— it did not exist from Stage 5 onward, when the in-sample/out-of-sample
split was first introduced, despite that split being the load-bearing
mechanism behind every "does this replicate" claim made since. Every
other piece of this engine that mattered structurally (the look-ahead
lag, the discontinuity gate, the cost model) had a dedicated test from
early on; the date-window behavior did not, because nothing about
calling the same function with different arguments *looked* like it
needed one.

### Bug 2: "confirmed" didn't require anything to replicate

**What it was.** `research/harness.py`'s `run_harness()` granted
`VALIDATED_CONFIRMED` status to any strategy whose out-of-sample Sharpe
alone cleared corrected significance — with no requirement that
in-sample show a significant result too. This gap had no practical
effect while Bug 1 was live (in-sample and out-of-sample were nearly
identical numbers by construction, so they always agreed), which is
partly why it went unnoticed for as long as it did.

**What it made results look like.** The moment Bug 1 was fixed and
out-of-sample became genuinely different, this gap had real teeth: MA
crossover on Nifty 50 (in-sample Sharpe −0.19), Midcap 150 (−0.22), and
Smallcap 250 (+0.03, essentially flat) all cleared out-of-sample
significance during 2020-2025's broad bull run and would have printed
`VALIDATED_CONFIRMED` — indistinguishable in the report from a
genuinely replicated finding, for all three universes simultaneously.

**What actually caught it.** Reading the freshly-corrected MA-vs-RSI
harness output and noticing the label didn't match the numbers: a
strategy with a negative in-sample Sharpe being reported as "confirmed"
read as wrong on inspection, prompting a re-check of `run_harness()`'s
actual status logic against what its own docstring claimed the status
meant.

**What would have caught it sooner.** A test asserting the harness's own
stated design intent — "confirmed on out-of-sample data" should mean a
finding replicated, not that an independent second test happened to
clear a bar. This is now `tests/test_harness.py` (which, notably, did
not exist at all before this — the harness had zero tests of its own
validation logic despite being the single piece of code this entire
project's "is this real" judgment routes through). Fixed:
`VALIDATED_CONFIRMED` now requires in-sample AND out-of-sample to BOTH
independently survive correction; an out-of-sample-only result gets a
distinct, explicitly-flagged status, `OOS_ONLY_SIGNIFICANT`, instead.

### Bug 3: the cumulative hypothesis count was tracked but never used

**What it was.** `research/harness.py`'s own docstring stated, from the
start, that "the multiple-testing burden this project has accumulated
is tracked across sessions, not reset each run." The tracking was real —
`research/hypothesis_ledger.json`'s cumulative count was correctly
maintained. But `run_harness()`'s actual Bonferroni correction was
computed as `alpha / n_tested`, where `n_tested` was only the CURRENT
run's own batch size — a call registering one new strategy always got
`bonferroni_alpha = 0.05/1 = 0.05`, regardless of whether the ledger
already showed 1 prior hypothesis or 163. The cumulative number was
displayed in every report and never once used to compute the bar
anything was actually judged against.

**What it made results look like.** Every status reported earlier in
this document and in `MIDCAP_SMALLCAP_FINDINGS.md` used a Bonferroni bar
of `0.05/2` (each of those runs registered exactly 2 strategies
together), not the true cumulative bar the project's own stated design
called for. Recomputed against the real cumulative count (162 at the
time of the MA-vs-RSI run, 164 at the time of the Midcap/Smallcap run),
the bar tightens from 0.025 to roughly 0.0003 — about 80x stricter.
Two of the three MA-crossover results that had shown as
`OOS_ONLY_SIGNIFICANT` under the under-corrected bar (Nifty 50 and
Midcap 150) do **not** survive the correctly-corrected one; only
Smallcap 250 does, and narrowly (p=0.0002 against a bar of ≈0.0003).
Sections 3a and 3b above report the corrected statuses.

**What actually caught it.** Preparing to register a brand-new strategy
(cross-sectional momentum) and needing to report "the correction
threshold that now applies" made the question concrete enough to check
the actual code, rather than trust the docstring's description of what
it does.

**What would have caught it sooner.** A test asserting that registering
a hypothesis when the ledger already holds N prior ones produces
`bonferroni_alpha = alpha/(N+1)`, not `alpha/1` — now
`tests/test_harness.py`'s cumulative-correction test. The same category
of gap as Bug 2: a mismatch between what the module's docstring claimed
and what the code actually did, sitting in the one place this whole
project's "is this real" judgment routes through, uncaught because
nothing had ever tested it directly. Benjamini-Hochberg FDR is NOT
extended the same way — it needs the full historical p-value vector to
compute correctly, which the ledger never stored (only counts), so it
remains a within-batch statistic, disclosed as such rather than silently
presented as more rigorous than it is (see `research/harness.py`'s
`run_harness()` docstring).

### Bug 4: momentum's blocked symbols became cash, and its benchmark started late

**What it was.** Momentum ranked all 50 symbols, and the engine then
dropped any symbol the discontinuity gate blocks for the window. When a
blocked symbol ranked in the top 10, its slot became cash instead of
passing to the next-ranked name (ADANIENT: top-10 on 28 of 54
in-sample rebalances). Separately, the random-selection benchmark used
only rebalance dates after the window start, so it sat in cash for the
first month out-of-sample while momentum was already invested.

**What it made results look like.** Momentum appeared to *beat* its
zero-skill benchmark in-sample (97th percentile) and be borderline
out-of-sample (92nd) — the most encouraging result of anything tested
here, and exactly the kind of result that would have prompted more
work on it. Corrected: 88th and 87.5th percentile, does not beat.

**What actually caught it.** Adding momentum to the web app meant
wiring the ranking to a window-specific universe for the first time,
which made the question "what happens to a blocked symbol that ranks
first" impossible to skip; a diagnostic then counted the affected
rebalances directly.

**What would have caught it sooner.** A test that a gate-blocked
top-ranked symbol is never selected and that the portfolio is fully
invested — now `tests/test_momentum_pipeline.py`. Reported exposure
(~98–100%) also disagreed with the true invested fraction (~95%); an
exposure figure computed from the holdings, not from "is there any
position", would have exposed it. Same family as Bugs 1–3: a
plausible, slightly flattering number from an integration-level flaw.

### The pattern connecting all four

None of the four bugs was in a formula. Every hand-computable piece of
arithmetic in this codebase (Sharpe, Sortino, CAGR, drawdown, cost
components, the look-ahead lag itself) has a ground-truth test that
catches a sign-flip or an off-by-one immediately. All four bugs that
actually produced a false positive were **integration-level or
semantic** — "does calling this function twice with different arguments
do something different," "does this status mean what its own docstring
says it means," and "does a number that's tracked actually get used" —
the kind of question a component-level unit test, however thorough, does
not ask. All three were only caught by working a real, motivated
question through to a concrete, implausible-looking number (identical
results; a losing strategy called "confirmed"; a correction threshold
that never moved) and refusing to write it up before understanding why.
As a standing practice, not just a lesson: a result that looks slightly
too clean, too stable, or too validated is worth the same suspicion as
one that looks too good — and a number that is DISPLAYED is not the same
as a number that is USED. Check that the two are actually the same
thing before trusting either.

## 7. Overall conclusion

**Across six strategies, three universes, and 204 tracked hypotheses,
no strategy in this project's history has achieved a genuinely validated
edge over buy-and-hold.** Every apparent positive dissolved under
scrutiny built specifically to test it: the parameter sweep's best cell
was statistical noise (Section 3a); Smallcap 250's Sharpe near-buy-and-
hold-tie was a mechanical artifact of partial exposure, not skill
(Section 4); the pairs screen's raw-significant, even BH-FDR-surviving
pairs did not replicate out-of-sample (Section 3d); momentum sits at
only the 88th (in-sample) and 87.5th (out-of-sample) percentile of its
own purpose-built zero-skill benchmark, below the 90th-percentile line
set in advance for "does not beat" (Section 3e); a 90% win rate was
reached only by strategies that do not realize their losses, and the
best honest variant fell from 85% to 60% on data it had not seen
(Section 3f); and four of the project's own "this looks good or
confirmed" moments were bugs in the measurement, not signal in the
market (Section 6) — including, once the third of those was fixed, the
correction threshold itself, which retroactively moved two of the three
MA-crossover universes from `OOS_ONLY_SIGNIFICANT` to `VALIDATED_FAILED`.
Only Smallcap 250 still clears the true cumulative bar, and only
because Section 4 already shows that clearing it is not evidence of
skill.

Stated plainly: mechanically applied trend-following (MA crossover),
mean-reversion (RSI) and dip-buying rules, without discretionary
judgment, do not beat a diversified buy-and-hold position on Indian
large-, mid-, or small-cap equities over 2015-2025, after realistic
costs — at any tested parameterization, on any tested universe, in
either half of the sample. A cointegration-based pairs approach finds
no relationships stable enough to survive a fresh look at unseen data.
A cross-sectional momentum approach does not clearly beat random
selection of the same number of stocks, while carrying the
worst-measured survivorship bias of any strategy in this project. The
one effect that was consistent across every universe and window is a
trade-off, not an edge: MA crossover earns less than buy-and-hold in
return and, in all six comparisons, has the smaller maximum drawdown
(out-of-sample Smallcap 250: −18% against −28%). And a high win rate and
a profitable strategy are close to opposite goals in this data: the
configurations with the highest win rates had the worst profit
outcomes, because the win rate was manufactured by capping wins and
never booking losses. The strategies' structural habit of sitting in
cash is a real handicap during a period dominated by a sustained bull
market — and, per Section 4, is not offset by any measurable timing
skill in choosing when to be out.

## 8. Limitations

- **Survivorship bias** is real and measured (Section 5), not merely
  disclosed: 12.0% / 36.1% / 48.5% of today's Nifty 50 / Midcap 150 /
  Smallcap 250 lack full 2015 history, rising with how far down the
  cap scale you go, in the expected direction. It biases every
  buy-and-hold benchmark in this document *upward* — so if anything,
  the strategy's true gap to a point-in-time-correct benchmark is
  understated, not overstated, throughout.
- **One market, one ~11-year window, dominated by one exceptional bull
  run.** 2020-07 to 2025 produced a buy-and-hold Sharpe of 1.3-1.6 in
  every universe tested — an unusually strong, one-directional regime.
  Every out-of-sample conclusion here is conditioned on that regime
  having occurred; a genuinely different one (a prolonged bear or
  sideways market) is untested and could change every relative
  comparison in this document. This is NSE data only — no claim is made
  about any other market.
- **A narrow strategy family.** Three threshold-based technical rules
  (MA crossover, RSI reversion, dip-buying — the last two are close
  relatives), one statistical-arbitrage screen, and one cross-sectional
  ranking strategy — no discretionary, fundamental, multi-factor,
  options-based, or machine-learning approach has been tested. Nothing here supports a
  conclusion about "systematic trading" broadly, only about this
  specific family.
- **Momentum's survivorship bias is measurably worse than any other
  strategy's here** (Section 3e, `MOMENTUM_FINDINGS.md` Check 4) — a
  structural property of ranking by trailing return against a
  current-constituent-only universe, not a data-quality shortfall that
  more careful sourcing would fix. `engine/portfolio_backtest.py` is
  also new code (this stage), tested against hand-built cases and the
  two bugs its first real run surfaced, without the years of incidental
  exposure `engine/backtest.py` has had.
- **Asymmetric rigor across strategies.** MA crossover got a 109-cell
  parameter sweep and a noise-floor analysis; RSI reversion got exactly
  one configuration, never swept. RSI's failure is real but less
  thoroughly stress-tested than MA crossover's.
- **The pairs work never built or tested an execution layer** (by
  design — see Section 3d). Its conclusion is about statistical
  relationship *stability*, not about whether a correctly-sized,
  properly-costed pairs strategy could work at different capital.
- **The win-rate investigation has thin and partly spent evidence.**
  Forty dip-buying variants were examined on 2015–2025; the only
  genuinely unseen data is 2026 (about 9.5 months, a falling market),
  and three fixed configurations have now been run on it (the
  search's selected variant plus A and U), so it can no longer serve as
  a clean holdout for anything further. Variant U's 2026 sample is nine
  trades. The forward test (Section 3g) is the replacement, and it needs
  about a year to say anything. Closed-position win rate is also what
  the engine's own `win_rate_pct` reports; for rules that can leave
  positions open it should be read next to open-position losses, as
  above.
- **The harness's zero-skill-benchmark and `OOS_ONLY_SIGNIFICANT` logic
  are new** (this stage) and have not yet been exercised against a case
  with a genuinely confirmed edge, since none has occurred in this
  project's history. Whether the current thresholds are well-calibrated
  for that case is untested until one actually appears.

---

## Appendix A: Amendment history

This document has been corrected four times after publication. All
four corrections are described in full in Section 6; this appendix is
a short index, not a duplicate writeup.

- **2026-09-03 (original):** MA crossover investigated on Nifty 50 —
  single symbol, 48-symbol universe, 109-cell parameter sweep, in-
  sample/out-of-sample split. Concluded strategy loses to buy-and-hold;
  in-sample and out-of-sample reported as "remarkably stable."
- **2026-09-06, amendment 1 — the date-window bug (Section 6, Bug 1):**
  the in-sample/out-of-sample split was not a real split.
  `engine/backtest.py` fixed; Nifty 50's true IS/OOS numbers (Sharpe
  −0.19 / +0.97) replace the "remarkably stable" ones. Headline
  conclusion (loses to buy-and-hold) unchanged; strengthened, if
  anything, since genuine out-of-sample buy-and-hold performed even
  better than the pre-fix numbers suggested.
- **2026-09-06, amendment 2 — the harness OOS-only gap (Section 6, Bug
  2):** found while re-registering the corrected numbers through
  `research/harness.py`. Fixed; MA crossover on all three universes
  correctly shows `OOS_ONLY_SIGNIFICANT`, not `VALIDATED_CONFIRMED`. No
  strategy in this project's history has ever achieved genuine
  `VALIDATED_CONFIRMED` status.
- **2026-09-06, consolidation:** restructured into the current single
  document — RSI reversion and pairs cointegration results folded in
  from where they previously lived only in console output and the
  hypothesis ledger; the zero-skill Sharpe benchmark (Section 4) added
  as a named, reusable methodological result; Sections 6-8 added.
- **2026-09-06, amendment 3 — the cumulative-correction gap (Section 6,
  Bug 3):** found while pre-registering a new strategy (cross-sectional
  momentum) and needing to report the correction threshold that
  applies. `run_harness()`'s Bonferroni correction had only ever used
  the current run's own batch size, never the ledger's actual cumulative
  count, despite the ledger existing specifically to track that burden.
  Fixed. Recomputed against the true cumulative bar: Nifty 50 and
  Midcap 150's MA-crossover results move from `OOS_ONLY_SIGNIFICANT` to
  `VALIDATED_FAILED`; only Smallcap 250 still clears it, narrowly.
  Sections 3a, 3b, and 7 updated.
- **2026-09-06, fifth strategy added:** cross-sectional momentum
  (Section 3e, full detail in `MOMENTUM_FINDINGS.md`) — a mechanically
  distinct strategy family needing a new backtest engine
  (`engine/portfolio_backtest.py`), which surfaced two more real bugs on
  its first run (a missing-price-marked-as-zero bug, and a pre-listing
  NaN poisoning the whole equity sum), both fixed and regression-tested
  before any result was reported. Cumulative hypothesis count: 165.
- **2026-09-21, momentum corrected (Section 6, Bug 4):** while adding
  momentum to the web app, two more bugs were found in the momentum code
  (a gate-blocked symbol's slot silently becoming cash; a random
  benchmark starting a month late). The originally reported result —
  beats the benchmark in-sample (97th percentile), inconclusive
  out-of-sample (92nd) — was wrong. Corrected: 88.0th / 87.5th
  percentile, does not beat, `VALIDATED_FAILED`. Sections 3e and 7
  updated; hypothesis re-registered in place (count unchanged, 165).
- **2026-10-16, win-rate investigation, forward test, loader fix:** at
  the owner's request, three dip-buying configurations (A: no stop; B: 10%
  stop; U: uptrend-filtered) and a bounded 36-variant search for a 90%
  win rate were run and registered (ledger 165 → 204), with 2026 data as
  a one-shot holdout. Result: no variant reached 90% honestly (Section
  3f). A forward paper-trade test was frozen in `FORWARD_TEST.md`
  (Section 3g). Extending the data to the present exposed a data
  artifact — Yahoo's still-forming current-day bar arrives with a volume
  but NaN prices, which would have turned the holdout's last equity
  value to NaN — fixed in `data/loader.py` with a test, and logged in
  `data/known_issues.md`, before any result was reported. Sections 1,
  2, 3f, 3g, 7, 8 updated; no earlier result changed.
