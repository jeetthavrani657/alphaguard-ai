# Finding: Cross-Sectional Momentum on Nifty 50 — Does Not Beat Random Selection

**Status: complete, corrected once. Last updated 2026-09-21.**
**Pre-registered in `MOMENTUM_METHODOLOGY.md` before any result existed —
nothing below was tuned after seeing a number.**

## Correction notice (read this first)

The first version of this document (2026-09-06) reported that momentum
**beat** its zero-skill benchmark in-sample (97th percentile) and was
**inconclusive** out-of-sample (92nd). **Both statements were wrong.**
They were produced by two bugs in this project's own momentum code,
found on 2026-09-21 while adding momentum to the web app:

1. **Blocked symbols silently became cash.** Momentum ranked all 50
   symbols, and the engine then dropped any symbol the discontinuity
   gate blocks for that window. When a blocked symbol ranked in the top
   10, its 10% slot did not pass to the 11th-ranked name — it became
   cash. ADANIENT (blocked in-sample by its 2015 bad print) was in the
   top 10 on **28 of 54** in-sample rebalances; the portfolio was on
   average only ~95% invested, while exposure was reported as ~98–100%.
   Fixed: `build_window_inputs()` in `research/run_momentum_strategy.py`
   now ranks only symbols the gate allows for the window, so a blocked
   symbol can never be selected.
   Regression test: `tests/test_momentum_pipeline.py`.
2. **The random-selection benchmark started a month late
   out-of-sample.** It used only rebalance dates after the window
   start, so it sat in cash for the first month while momentum was
   already invested — a small bias in momentum's favour. Fixed: the
   benchmark now uses exactly the same rebalance dates as the strategy.

Both are integration-level bugs of the kind described in `FINDINGS.md`
Section 6 — no formula was wrong, and both produced a plausible,
slightly flattering number. Corrected results follow; the hypothesis
was re-registered in place (same hypothesis, so the cumulative count is
unchanged at 165).

## Headline

**Momentum does not beat the zero-skill benchmark in either window.**
Its Sharpe sits at the **88.0th** percentile (in-sample) and **87.5th**
(out-of-sample) of 200 random-selection portfolios drawn from the same
stocks with the same costs and the same monthly rebalancing — both below
the 90th-percentile line set in advance for "does not beat" (95th to
count as a win). With 200 simulations a percentile is itself uncertain
by roughly ±2–3 points, so the fair reading is "not distinguishable
from picking the same number of stocks at random", not "proven worse
than random". Harness verdict, by an independent test: `VALIDATED_FAILED`.

## Why this needed new machinery

Every prior strategy ranks a stock against its OWN history. Momentum
ranks stocks against EACH OTHER and holds one shared portfolio, which
`engine/backtest.py`'s independent-books model cannot express. Built per
`MOMENTUM_METHODOLOGY.md` Section 2: `strategies/cross_sectional_
momentum.py` (ranking) and `engine/portfolio_backtest.py` (a second,
weight-target engine), both with ground-truth tests.

Two bugs were found and fixed on the engine's first real run, before
the correction above:

1. A held stock with no price row on some date (e.g. 2025-03-18, a
   known market-wide data artifact already stripped from each symbol's
   own frame by `data/loader.py`) was marked to **0.0** via
   `.get(date, 0.0)`, fabricating a ~99.8% one-day "crash". Fixed by
   forward-filling closes onto the window calendar.
2. Forward-fill cannot fill dates before a symbol's first real row (a
   late listing), and `shares * NaN` is NaN even when `shares == 0`,
   which turned the whole in-sample equity curve to NaN. Fixed with
   `fillna(0.0)` after the forward-fill, which is safe because a symbol
   can only be held once it has real data.

## Frozen configuration (unchanged from `MOMENTUM_METHODOLOGY.md`)

Nifty 50, 12-1 momentum (252-day lookback skipping the most recent 21
days), top 10 held equal-weight, monthly full rebalance, long-only, same
cost model as every other Nifty 50 result in this project.

## Results (corrected)

| | In-sample (2015–2020-06) | Out-of-sample (2020-07–2025) |
|---|---|---|
| CAGR | 11.18% | 35.73% |
| Sharpe | 0.361 | 1.405 |
| Max Drawdown | −41.01% | −21.41% |
| Time invested | 98.4% | 100.0% |
| Rebalances | 65 | 66 |

In-sample and out-of-sample date ranges were verified to have zero
overlapping dates and non-identical equity curves before any result was
trusted (asserted directly in `research/run_momentum_strategy.py`).

For scale: momentum's 1.405 out-of-sample Sharpe is not unusual for this
project — MA crossover's out-of-sample Sharpe was 1.44 on Midcap 150 and
1.51 on Smallcap 250 (`FINDINGS.md` Section 3b), because 2020-07 to 2025
was a broad bull run in which buy-and-hold itself had a Sharpe of 1.3–
1.6. (An earlier version of this document called momentum's number the
project's highest; that was wrong.)

## Check 1: the zero-skill benchmark

Momentum is almost always fully invested, so the cash-dilution test of
`FINDINGS.md` Section 4 does not apply. The right null for a ranking
strategy is: does picking 10 names by momentum rank beat picking 10 at
random from the same date-by-date pool, with the same costs and turnover?
200 Monte Carlo random-selection portfolios per window:

| | Random-selection mean (std) | Momentum Sharpe | Percentile | Verdict |
|---|---|---|---|---|
| In-sample | 0.162 (0.162) | 0.361 | **88.0th** | Does not beat |
| Out-of-sample | 1.188 (0.194) | 1.405 | **87.5th** | Does not beat |

Bar set in advance: ≥95th to beat, ≤90th to not beat, in between
inconclusive. Momentum ends roughly one standard deviation above the
random-pick average in both windows — a modest, consistent tilt, not
enough to separate from chance at the bar this project set.

## Checks 2 & 5: exposure, turnover, and what trading it costs

Exposure is near-100% by construction, so the real cost is turnover:
**41.5% of the portfolio traded per month in-sample, 49.1%
out-of-sample** — roughly 500–600% of portfolio value per year, versus
MA crossover's few trades per symbol over eleven years. Realized costs:
**Rs 70,405 (7.0% of starting capital) in-sample, Rs 158,957 (15.9%)
out-of-sample**. The random-selection arm pays the same cost structure,
so the verdict above is already after costs on both sides; costs are
large, but they don't explain the miss by themselves.

## Check 4: survivorship, quantified for a ranking strategy

**(a) Thin selection pool.** Using today's constituents from day one
means many hadn't listed long enough to be ranked. **116 of 132 monthly
formation dates (87.9%)** had fewer than all 48 gate-eligible
constituents rankable; the thinnest point (2015-01-30) had **zero**.

**(b) The momentum-crash mechanism, tested against the named
casualties.** Each casualty's own trailing 12-1 return was compared with
the ACTUAL top-10 cutoff on the same dates:

| Casualty | Peak 12-1 return | Would have cleared the top-10 cutoff |
|---|---|---|
| Jet Airways | +875.8% (2021-03-31) | **28 of 106** formation dates |
| Reliance Communications | +257.1% (2020-09-30) | **20 of 120** |
| Reliance Capital | +148.7% (2021-07-30) | **15 of 97** |
| Reliance Naval | +175.0% (2021-05-31) | **10 of 119** |
| DHFL | — | no price data available at all |

These are dozens of dates across four names where a point-in-time-correct
universe could have selected a stock during its run-up. This backtest's
current-constituent-only universe is structurally blind to every one of
them — worse than MA crossover's survivorship bias in kind, not just in
degree, since momentum needs a stock to be a CURRENT constituent to be
rankable at all. It is a real reason to treat even the modest tilt above
with suspicion.

## Check 6: the research harness

| | Sharpe | p-value | Survives Bonferroni (0.05/165 ≈ 0.000303) |
|---|---|---|---|
| In-sample | +0.361 | 0.2015 | No |
| Out-of-sample | +1.405 | 0.0006 | No (0.0006 > 0.000303) |

**Status: `VALIDATED_FAILED`.** Cumulative hypotheses: **165** (164
before this run + 1). No sweep was run, per `MOMENTUM_METHODOLOGY.md`.

## Conclusion

Cross-sectional momentum on Nifty 50, long-only, 12-1/top-10/monthly, is
**not a validated strategy** and does not clearly beat random selection
of the same number of stocks. Two independent tests agree. Reasons this
is not the last word on momentum: (1) it is long-only against a premium
the literature measures long-short; (2) turnover-driven costs are large,
though the comparison already includes them; (3) survivorship bias here
is measurably worse than for any other strategy in this project, in a
way this backtest cannot correct for without point-in-time constituent
data this project does not have.

## Limitations

- One parameter configuration, deliberately not swept (a sweep would be
  a separate registered hypothesis). The web app shows the parameters
  but does not let them be edited, for the same reason.
- Nifty 50 only; momentum has not been asked the universe-dependence
  question MA crossover was.
- Same single-market, ~11-year, bull-run-dominated out-of-sample window
  as every other result here (`FINDINGS.md` Section 8).
- `engine/portfolio_backtest.py` is new code. It has already had three
  bugs found in its first real use, which is a reason to expect that
  more edge cases exist, not fewer.
