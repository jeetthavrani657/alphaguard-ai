# Forward Paper Books: Frozen 2026-10-16, Before Any Forward Data Exists

**Status: PRE-REGISTERED.** Written before a single forward day has been
recorded. Nothing below may be edited after results arrive. If a book turns out
to be wrong, that is the finding: changing it restarts the clock and counts as
a new hypothesis in the ledger.

Research only. This logs what a book WOULD have done. It places no orders,
connects to no broker, and is not trading advice.

## Why this exists

After 204 tracked hypotheses nothing is validated (`FINDINGS.md` Section 7).
Two configurations came closest to interesting, and both were judged on a
window that is now spent: the 2020 to 2025 bull run. The only evidence that can
still change their status is data that does not exist yet. This document sets
up that test so it cannot be argued with afterwards. It is the paper-trading
step that any future live system would have to pass first.

**This creates no new hypothesis.** Both books were registered and counted
before (the ledger stays at 204). A forward run of an already-counted, frozen
configuration collects out-of-time evidence for it; it is not another try.

## The frozen books

| | Book 1 | Book 2 |
|---|---|---|
| Id | `momentum_nifty50` | `ma_crossover_smallcap250` |
| Strategy | Cross-sectional momentum, 12-1, top 10, monthly, long-only | MA crossover 50/200, long when fast > slow |
| Universe | Nifty 50 (`config.UNIVERSE`), data gate applied as everywhere | Nifty Smallcap 250 (`config.SMALLCAP250_UNIVERSE`) |
| Parameters | lookback 252, skip 21, top 10 (`cross_sectional_momentum.py`) | `config.MA_CROSSOVER_PARAMS` (fast 50, slow 200) |
| Sizing | One account of Rs 10 lakh, equal-weight, full monthly rebalance | Each stock is its own Rs 10 lakh book (as in every backtest here) |
| Costs | `engine/costs.py`, unchanged | `engine/costs.py` plus the per-stock liquidity slippage (`research/liquidity_costs.py`), estimated on the frozen 2015-2025 window so it cannot drift |
| Fills | Next session's open after the signal (same engine) | same |
| Benchmark | Buy-and-hold of the same stocks, same days | same |

Why these two, stated before the data: **Momentum** beat buy-and-hold in its
one out-of-sample window (Sharpe 1.41 vs 1.34) but missed its own correction
bar (p 0.00051 vs 0.000245) and sat below the pre-set 90th percentile of random
stock selection. **Smallcap MA crossover** is the only configuration to clear
the cumulative bar out-of-sample, by a hair (p 0.000231 vs 0.000245), only
out-of-sample, and its Sharpe is explained by partial exposure rather than
timing (`FINDINGS.md` Section 4). Neither is believed to be an edge. They are
the best candidates available, which is a low bar.

## What counts

Forward window starts at the freeze, **2026-10-16**; the first countable
session is **2026-10-19** (the first after the freeze-day close). Everything is
recomputed from raw prices on every run with the same engine as the backtests,
so a result cannot depend on when it was run.

## When it is judged

- **No verdict of any kind before 252 forward trading days**, and for the
  momentum book not before 12 monthly rebalances have executed. Sharpe is not
  even displayed before 252 days; until then the numbers are monitoring, not
  evidence.
- **A book passes only if ALL of these hold:**
  1. its forward Sharpe exceeds buy-and-hold's over the same days and stocks;
  2. a one-sided significance test of its forward Sharpe
     (`harness.sharpe_p_value`) gives **p < 0.025** (0.05 shared across the
     two books);
  3. momentum only: its forward Sharpe is at or above the **90th percentile**
     of the existing zero-skill random-selection distribution
     (`random_selection_sharpes`) over the same forward window. For the MA
     book, criterion 1 is already the zero-skill test (`FINDINGS.md`
     Section 4 shows the same-exposure untimed benchmark equals buy-and-hold's
     Sharpe).
- **What a pass would justify:** a small, capped live trial through a broker,
  with the separate work that needs (`FINDINGS.md` and the audit). Not scaling.
- **What a failure means:** the candidacy ends. No re-tuning; a variant is a
  new hypothesis and is counted.
- Always reported, never hidden: return and maximum drawdown against the
  benchmark, exposure, open positions, and pending signals.

## Honest expectation, stated before the data

**The most likely outcome is that both books fail**, mainly by trailing
buy-and-hold. Both were measured in a market where holding stocks returned a
Sharpe of 1.3 to 1.6; the forward period will not necessarily repeat that, and
a rule that is mostly out of the market (the MA book) or concentrated in 10
names (momentum) has real ways to lag it. The test exists to find out by how
much and whether either book earns its risk, not to confirm anything.

## What this does NOT establish

One market, one to two years, whatever regime occurs. Survivorship bias in
today's constituent lists persists (smaller for a forward window). Paper fills
at the next open ignore real-world slippage beyond the modelled costs, partial
fills, and circuit locks, especially in small caps.

## Running it

```
python research/forward_books.py
```

Any day after the close; idempotent. It rewrites
`reports/output/forward_books_latest.json` (the current picture, read by the
web app's **Paper trading** page) and adds or replaces one row per (book, data
date) in `reports/output/forward_books.csv` (the history of the numbers, so a
vendor re-adjustment would show). It also runs from `run_forward_log.bat`, the
scheduled task NSE-ForwardTest-Daily, after the dip-rule forward test.

The Smallcap book needs the whole Smallcap 250 price history refreshed each
day, so the scheduled run is slower than before (several minutes).
