# Pairs Trading Methodology — Frozen Before Any Results

**Status: PRE-REGISTERED. Written 2026-09-03, before any pair selection,
any backtest, or any result of any kind.** Nothing in this document may
be changed after results are seen. If a rule here turns out to be wrong
or impractical, that's a finding to report, not a line to quietly edit.

This document exists because of one specific risk: with 48 symbols there
are 1,128 possible pairs. Selecting the best-performing pair after
testing all of them is data snooping, and it will produce a spectacular,
meaningless backtest. That risk is handled structurally below — every
selection rule, threshold, and holdout boundary is fixed here, in
writing, before any pair is tested for performance.

See `FEASIBILITY.md`-equivalent discussion (Part 1 of the chat record)
for why the traded structure is **futures short + cash/delivery long**,
not full-futures-both-legs.

---

## 0. Scope amendment — 2026-09-03, added after Part 1's feasibility check

**This is research, not a strategy.** Part 1's feasibility check settled
the capital question: a single short futures leg requires a SEBI-mandated
minimum ₹15-20 lakh contract, against this project's ₹10 lakh
`INITIAL_CAPITAL`. One leg alone consumes most of the available base, and
Section 6 below requires enough *pairs*, not one, for the results to mean
anything. There is no version of this that is both properly sized and
retail-scale at this capital level. Inflating `INITIAL_CAPITAL` to make
the arithmetic close would be manufacturing an answer, not finding one.

The question this document now answers is **"do stable cointegrated
relationships exist in this universe, and do they persist out-of-sample,"
not "should this be traded."** No tradeable-edge claim will be made from
what follows, regardless of what the analysis finds. Consequences:

- **The entire execution layer is out of scope.** No `pairs_backtest.py`,
  no futures cost model, no margin or rollover mechanics, no
  hedge-ratio position sizing, no trade log, no P&L. That machinery only
  has value in service of a claim this project is not making.
- **Sections 1-7 below are UNCHANGED from the original freeze** — same
  selection criteria, same statistical test, same significance
  threshold, same Z-score thresholds, same stop rules, same holdout
  dates. Freezing them before results existed was the entire point of
  this document, and a change of scope is not a license to relitigate
  them. They now govern a statistical research question instead of a
  trading rule, but they govern it identically.
- **What changes is the deliverable**, not the method: cointegration
  testing across the frozen candidate universe, spread and Z-score
  construction for qualifying pairs, an in-sample-vs-holdout stability
  check (what fraction of pairs that qualify in-sample still qualify
  out-of-sample), mean-reversion half-life for surviving pairs, and a
  multiple-testing correction on the qualifying count — since at 5%
  significance across the size of candidate set Section 1 produces,
  a meaningful number of "cointegrated" pairs are expected by chance
  alone, and the honest question is whether any survive correcting for
  that.

---

## 1. Pair selection criteria (fixed in advance)

**Universe:** the existing `config.UNIVERSE` (48 symbols, current Nifty
50 minus Yes Bank / Vodafone Idea), further restricted to symbols
confirmed to have currently-eligible NSE stock futures (to be verified
at implementation time — not assumed from the equity universe list).

**Economic pre-filter, applied BEFORE any statistical test:** only pairs
within the same sector/industry group are eligible. Sector/industry
mapping does not currently exist anywhere in this codebase and must be
added as new static data (a small per-symbol sector field), not
inferred or fabricated during analysis. This filter exists specifically
to reduce 1,128 candidate pairs down to an economically-justified subset
*before* any statistics are run — a cointegrated relationship between
two economically unrelated firms is more likely a statistical artifact
than a real, persistent linkage.

**Statistical test: Engle-Granger two-step cointegration test**, not
Johansen. Justification: Johansen's extra power is for detecting
cointegrating relationships among 3+ series simultaneously; pairs
trading is strictly 2-asset, where Engle-Granger is the standard,
simpler, more interpretable choice and buys nothing is left on the
table by not using Johansen here. Engle-Granger's known asymmetry
(regressing A-on-B vs. B-on-A can disagree) is handled by running both
directions and requiring **both** to reject the null of no cointegration.

**Significance threshold:** p < 0.05 on the Augmented Dickey-Fuller test
of the regression residuals, both directions.

**Minimum history:** at least 500 trading days (~2 years) of overlapping
price data between the two symbols. This will exclude some
shorter-history universe symbols (e.g. JIOFIN.NS, listed 2023) from
pairing with anything, and is a fixed rule applied uniformly, not
adjusted per pair.

**Hedge ratio:** the slope coefficient from the winning direction's OLS
regression, estimated ONCE on the selection-period data only (see
Section 2), frozen for the life of the pair — not re-estimated on a
rolling basis. A pair's position sizing uses this fixed ratio throughout.

## 2. Selection frequency: once, not rolling

Pairs are selected **exactly once**, using only the pre-registered
selection window below. No re-selection, no dropping/adding pairs based
on how they later perform, no re-estimating the hedge ratio mid-life.

**Selection window:** 2015-01-01 to 2020-06-30 — reusing the exact
`IN_SAMPLE_END_DATE` split already established in `config.py` for the MA
crossover work. This is a deliberate choice: that boundary was set for
an unrelated strategy, before this pairs investigation existed, so
reusing it here is not a boundary chosen to flatter this specific
result.

A rolling re-selection variant (retiring pairs whose relationship
breaks, admitting newly-qualifying ones) is a legitimate methodology for
a *live* strategy, but is explicitly out of scope for this investigation
— it introduces its own walk-forward discipline requirements that
deserve a separate, dedicated methodology sign-off, not a rule bundled
into this one under time pressure.

## 3. Entry and exit thresholds (fixed in advance, not tuned)

- **Spread:** `price_A - hedge_ratio * price_B`, using the frozen hedge
  ratio from selection.
- **Z-score:** `(spread - rolling_mean) / rolling_std`, both computed
  over a trailing 60-trading-day window (~3 months) — a standard,
  literature-common window chosen for balancing responsiveness against
  noise, not optimized on this data.
- **Entry:** Z-score < -2.0 -> long the spread (long A, short B).
  Z-score > +2.0 -> short the spread (short A, long B). The ±2.0 band is
  the most common convention in the pairs-trading literature (Gatev,
  Goetzmann & Rouwenhorst; Vidyamurthy), chosen for being a
  widely-used, non-cherry-picked default, not for how it performs here.
- **Exit:** Z-score reverts to 0 (spread returns to its rolling mean).

These thresholds are universe-wide and identical for every pair. No
per-pair tuning of entry/exit levels is permitted — that would silently
reopen the exact overfitting risk this document exists to close off.

## 4. Stop-loss for a broken relationship

- **Z-score stop:** |Z-score| exceeds ±4.0 (well outside the entry
  band) -> close immediately regardless of direction. A move this far
  beyond what mean-reversion would statistically predict returning from
  is treated as evidence the relationship itself broke (an M&A, a
  fundamental shock to one leg), not as a deeper entry opportunity. The
  pair is not re-entered until a future re-selection cycle (out of scope
  here — see Section 2) re-validates it.
- **Time stop:** a position open longer than 60 trading days without
  reverting is closed regardless of Z-score. Indefinite exposure waiting
  for a reversion that isn't coming is itself a signal something broke.
- **Discontinuity stop:** if either leg has an unresolved
  ARTIFACT/UNREVIEWED discontinuity (per the existing
  `data/discontinuity_registry.py` / `assert_backtest_safe()`
  machinery) anywhere in the holding window, the position is closed —
  a corrupted price in either leg corrupts the spread for the whole pair,
  independent of the Z-score-based stops above.

## 5. Pre-registered holdout period

**2020-07-01 to 2025-12-31.** Untouched by pair selection, hedge-ratio
estimation, or threshold-setting (all of which use only the 2015-2020-06
selection window above). The holdout is used exactly once, at the end,
to evaluate the pairs and rules already locked in by Sections 1-4 — not
to iterate on them. If the holdout result is bad, the answer is
"reject," not "go back and adjust Section 3's thresholds."

## 6. How many pairs will be traded

**Every pair that passes the Section 1 filters (sector + both-direction
cointegration at p<0.05, ≥500 days history) is traded — no further
discretionary curation, no performance-based selection of a subset.**
The count is an *output* of the pre-registered filtering process, not a
number chosen in advance.

Two pre-committed contingencies:
- **Fewer than 10 pairs pass:** results are treated as exploratory only,
  explicitly not a validated conclusion — the same sample-size honesty
  already applied to 6 single-symbol trades in the MA crossover work.
- **A very large number pass:** all are traded; the practical limit is
  expected to come from Part 1's capital constraint (each futures leg
  needs a ₹15-20 lakh minimum contract), not from an arbitrary pair cap.

## 7. Rejection criteria — written before any result exists

This strategy is **rejected** if, on the pre-registered holdout period:

- The pooled out-of-sample Sharpe ratio is not both positive and
  distinguishable from zero using the same kind of sampling-noise
  standard-error reasoning used to evaluate the MA crossover parameter
  sweep (not just "positive," since a small positive number over a
  short sample proves nothing).
- Performance does not persist in a way consistent with the selection
  period (e.g., win rate collapses, spreads stop reverting) — and if
  this happens, thresholds are NOT retuned to compensate. That would be
  exactly the snooping this document exists to prevent.
- Realistic costs — both legs, including futures-specific STT, margin
  financing, and the recurring monthly rollover cost from Part 1 — 
  consume most or all of the theoretical spread-capture profit. This is
  evaluated as a distinct failure mode from "no statistical edge," the
  same way costs were central to (and separate from) the MA crossover
  conclusion.
- Fewer than 30 pooled closed trades materialize in the holdout period
  — treated as **inconclusive**, a third bucket distinct from both
  accept and reject, not quietly folded into either.

## 8. Residual data-snooping risk — stated plainly, not eliminated

Structural safeguards reduce data snooping. They do not eliminate it.
Specifically, even after everything above:

- Every threshold here (±2.0 entry, 60-day window, ±4.0 stop, 5%
  significance, 500-day minimum) is a *standard literature convention*,
  not tuned on this data — but choosing which standard convention to
  adopt is still a research decision, made by one person, once. A
  different reasonable analyst could defensibly pick ±1.5 or a 90-day
  window. What this document proves is that the choice wasn't
  reverse-engineered from a result, not that no other reasonable choice
  existed.
- The sector/industry classification used for the economic pre-filter
  involves judgment calls (a stock can plausibly belong to more than one
  sector). Applying that judgment before seeing any performance number
  is far better than after, but it is not zero-discretion.
- The universe carries the same survivorship bias already disclosed for
  the MA crossover finding (`FINDINGS.md`) — a cointegrated pair found
  among two *surviving* large caps says nothing about pairs involving a
  stock that later delisted or collapsed.
- Pooling all pairs that pass the filter is a real improvement over
  cherry-picking the best performer after the fact, but it is still a
  form of multiple comparisons if many pairs pass — the pooled result's
  own significance should be assessed with an appropriately conservative
  standard error (as in Section 7), not treated as a single a-priori bet.
- Most fundamentally: the out-of-sample holdout tests whether this holds
  up in *unseen data from the same broad market regime* (2015-2025 NSE
  large caps). It does not test whether it would hold in a structurally
  different regime. This is the same limitation already disclosed for
  the MA crossover conclusion, and it applies here identically.
