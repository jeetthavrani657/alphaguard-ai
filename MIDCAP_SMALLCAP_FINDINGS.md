# Finding: MA Crossover Behaves Differently on Midcap/Smallcap Than on Nifty 50

**Status: control comparison complete, amended after a date-window engine
fix. Last updated 2026-09-06.**

**AMENDMENT (2026-09-06):** the numbers originally reported below in
Sections 5 and 6 were computed with a bug: `engine/backtest.py`'s
`start`/`end` parameters were used only by the discontinuity gate, not
to actually restrict which dates got backtested -- every "in-sample"
and "out-of-sample" call silently ran the SAME full 2015-2025 backtest.
Confirmed by hand-tracing a symbol (HAVELLS.NS): the two
"different-period" equity curves were byte-identical. Fixed in
`engine/backtest.py` (regression tests in
`tests/test_backtest_date_window.py`) and every affected result below
has been re-run with a genuine split. **Two real conclusions change as
a result — not just the numbers:**

1. The original claim "Smallcap 250's Sharpe edge over buy-and-hold
   represents genuine timing" is **retracted**. With a real OOS window,
   Smallcap's strategy Sharpe (1.505) is statistically indistinguishable
   from a synthetic "same average exposure, zero timing skill" benchmark
   (1.506) -- see the new Section 8. There is no evidence of timing skill
   in either universe; Midcap's timing was actively *negative* (below
   what no-skill dilution would have given for free).
2. The universe-dependence pattern from Section 6 is not overturned,
   but its true shape is different and more precise than originally
   described -- see the corrected Section 6 below.

**AMENDMENT 2 (2026-09-06):** fixing the above surfaced a second, separate
bug in `research/harness.py` itself -- VALIDATED_CONFIRMED status was
granted from out-of-sample significance alone, with no requirement that
in-sample show anything, which is exactly the shape both results below
have (flat-to-negative in-sample, strongly positive out-of-sample).
Fixed: see "Through the research harness" in Section 5. Both Midcap 150
and Smallcap 250 were, at that point, correctly `OOS_ONLY_SIGNIFICANT`,
not `VALIDATED_CONFIRMED` -- but see Amendment 3.

**AMENDMENT 3 (2026-09-06):** a THIRD bug, in the same statistical
machinery: `run_harness()`'s Bonferroni correction divided by this run's
own batch size (2), never by the ledger's true cumulative hypothesis
count (164 at the time), despite the ledger existing specifically to
track that cumulative burden. Fixed -- see `FINDINGS.md` Section 6, Bug
3. Recomputed against the correct bar (0.05/164≈0.00030, not 0.05/2=
0.025): **Midcap 150's out-of-sample p=0.0004 no longer clears it --
status is `VALIDATED_FAILED`, not `OOS_ONLY_SIGNIFICANT`.** Smallcap
250's p=0.0002 still clears it, narrowly -- it remains
`OOS_ONLY_SIGNIFICANT`, the only one of the three MA-crossover universes
(including Nifty 50, see `FINDINGS.md`) that does once corrected
properly. No strategy in this project's history has ever achieved
genuine VALIDATED_CONFIRMED status.

Section 5's tables, Section 6's conclusion, and the harness registration
are corrected below. Sections 1-4 (universe construction, Stage 1
validation, cost re-estimation, survivorship-bias measurement) are
UNCHANGED -- none of that work depended on `run_backtest`'s date
handling. Two new sections (7 and 8) answer the follow-up questions this
amendment made necessary: how big is survivorship bias in absolute
Sharpe/CAGR terms (not just membership-churn percentages), and is the
Smallcap Sharpe number mechanical or real.

`FINDINGS.md` established that MA crossover (fast=50, slow=200) does not
beat buy-and-hold on Nifty 50 large caps, at any tested parameter. Three
strategies tested there, three negative results — all on the most
heavily arbitraged segment of the Indian market. This document asks the
control-comparison question that follows directly from that pattern:
**does the same rule, unchanged, behave differently in less
institutionally-covered segments?** Same rule, same parameters
(`config.MA_CROSSOVER_PARAMS`, never retuned), same methodology — only
the universe changes.

## 1. Building the universes

Nifty Midcap 150 and Smallcap 250 constituent names were scraped from
smart-investing.in's weightage tables (2026-09-05) and each resolved to
an NSE ticker via yfinance's own search index, not guessed. That
automated resolution was then checked by hand against
`yf.Ticker().info`'s `longName` — which caught **8 real mismatches**
(4 per universe) where the top search hit was a similarly-named but
different company: a demerged subsidiary, a spinoff, an associate
entity, or an ETF instead of the actual index constituent. Examples:
"ATUL LTD" auto-resolved to `ATULAUTO.NS` (Atul Auto, an unrelated
three-wheeler maker) instead of `ATUL.NS`; "NMDC LTD" resolved to
`NSLNISP.NS` (NMDC Steel, a separately-listed spinoff) instead of
`NMDC.NS`. All 8 corrected and individually re-verified before use.
Final coverage: 145/150 Midcap and 246/250 Smallcap constituents (the
weightage source cut off a handful of the smallest-weight names, plus
one Midcap constituent — a recent ABB demerger entity — that yfinance's
search couldn't resolve at all). See `config.py`'s `MIDCAP150_UNIVERSE`
/ `SMALLCAP250_UNIVERSE` for the exact lists and this reasoning in full.

## 2. Stage 1 validation, before any strategy ran

Running the existing Stage 1 validator surfaced a real bug, not just
data problems: 8 symbols (NHPC, FSL, GRAPHITE, HEG, TRIDENT, CHENNPETRO,
TECHNOE, BSOFT) failed "OHLC logic violations." Every flagged row
turned out to be floating-point rounding noise from yfinance's
split/dividend adjustment arithmetic — e.g. NHPC's flagged
2020-06-09 row had `close` and `low` differing by 1.8e-15, economically
identical values that a strict `<` comparison treated as a violation.
FSL alone had 527 such rows. Fixed with a Rs 1e-6 absolute tolerance in
`data/validator.py`'s OHLC check (large enough to absorb ~1e-14/1e-15
noise, far too small to hide a genuine violation, which in practice run
from paise to several rupees) — see `data/known_issues.md` and
`tests/test_validator_ohlc_tolerance.py`, which locks in both that
noise-level differences pass and a genuine violation still fails.

**After the fix: 145/145 (100%) Midcap and 246/246 (100%) Smallcap
resolved symbols pass hard validation.** Zero failed to download, zero
failed validation. This is a materially different answer than the
pre-fix numbers (99.3% / 97.2%) would have suggested, and the difference
is entirely the validator bug, not the data.

Separately, 12 Midcap and 33 Smallcap symbols have fewer than 500 rows
of history (recent listings) — usable for validation purposes but too
short for a 200-day moving average to ever produce a signal. Three of
these (GROWW, LENSKART, ANTHEM — all genuinely recent IPOs with 34, 36,
and 111 trading days respectively) crashed the first strategy run
outright: `generate_signals()` correctly returned an all-NaN series
(nowhere in their short history does a 200-day MA exist), and
`validate_signals()` correctly raised rather than fake a signal. That
exposed a real gap in `engine/universe.py`: there was no graceful way
to exclude a symbol that's fundamentally incompatible with a given
strategy's warm-up requirement — it just crashed the batch. Fixed by
catching this the same way a discontinuity-gate block is already
handled: excluded from the aggregate, logged with a reason, batch
continues. See `tests/` (existing suite re-passes) and the `blocked`
lists in the results below.

## 3. Costs, re-estimated not inherited

The Nifty 50 work used a flat 0.05% slippage assumption for every
symbol — defensible for large caps, wrong for thinner names. Replaced
with a per-symbol estimate: `research/liquidity_costs.py` computes each
stock's own average daily traded value (ADV) and applies a square-root
market-impact model, `slippage_pct = 0.05% * sqrt(reference_ADV / ADV)`,
clipped to [0.05%, 2%].

**What this is based on:**
- The square-root form is the standard shape used in market-microstructure
  impact models (Almgren-Chriss and its practitioner variants), not
  invented for this project.
- `reference_ADV` (Rs 254.5 crore/day) is the median ADV of the actual
  Nifty 50 universe, computed directly from this project's own cached
  data — not assumed. This calibrates the model so a Nifty-50-liquid
  stock gets exactly the same 0.05% used throughout the prior work.
- The floor (never below 0.05%) and the 2% cap are disclosed judgment
  calls, not a specific published NSE Midcap/Smallcap impact-cost
  number — NSE's own methodology PDF timed out on every fetch attempt
  despite several tries. What IS independently verified: general
  bid-ask-spread research puts NSE large-cap spreads at ~15bps or
  tighter and the least liquid small caps at 500bps+ (Stockopedia), and
  NSE's own Nifty 50 eligibility bar allows impact cost up to 50bps for
  a Rs 1 crore basket even for its most liquid large-cap tier — both
  consistent with a model that scales well above 5bps as liquidity
  falls, neither pinning down an exact number for these two indices
  specifically.

**Result:** median slippage came out to 0.088% (Midcap) and 0.136%
(Smallcap) — 1.8x and 2.7x the flat large-cap rate — rising to 0.255%
and 0.511% at the thinnest names. Every single one of these rates is
*higher* than the 0.05% used in the Nifty 50 work, never lower.

## 4. Survivorship bias, measured for these specific universes

Not borrowed from general literature this time. Two complementary,
concrete measurements:

**Direct measurement — how much of today's universe didn't exist (under
its current identity) in 2015:**

| Universe | % of usable constituents lacking near-full 2015-2025 history |
|---|---|
| Nifty 50 | 12.0% (6/50) |
| Midcap 150 | 36.1% (52/144) |
| Smallcap 250 | 48.5% (116/239) |

This measures one real, direct channel of survivorship bias — listing
churn (IPOs, demergers, ticker changes) — computed from this project's
own data, not cited from someone else's study. It is **3-4x higher** for
Midcap/Smallcap than for Nifty 50, in the direction you'd expect. It
does not capture the other channel: a company that's been continuously
listed under the same ticker since 2015 but has fallen out of the index
on market-cap rank, or been suspended/delisted entirely (which shows up
as *absent*, not *short-history*).

**That other channel, with named, verified examples:** Jet Airways
(India) Ltd — trading suspended 2019-06-28 (removed from F&O), fully
suspended 2024-11-08 on liquidation. Reliance Capital, Reliance
Communications, and Reliance Naval and Engineering — all Anil Ambani
Group companies that went through IBC insolvency proceedings (all three
tanked 30%+ in a single stretch in June 2019 alone, per contemporaneous
reporting). DHFL (Dewan Housing Finance) — collapsed 2019, resolved and
delisted after the Piramal acquisition completed. All five were
solidly mid-cap-scale companies in 2015; none exist as ongoing,
independently tradeable entities today. None of the five appear in
`MIDCAP150_UNIVERSE` or `SMALLCAP250_UNIVERSE` — which is exactly the
survivorship-bias mechanism, made concrete rather than asserted.

**Bottom line:** survivorship bias is real, larger than for Nifty 50,
and now has a measured (not just disclosed) magnitude specific to these
two indices. It biases the buy-and-hold benchmarks in this document
*upward* — so if anything, the true gap between the strategy and a
genuinely point-in-time-correct benchmark is understated, not overstated,
by everything below.

## 5. Results (CORRECTED after the date-window engine fix)

MA crossover (fast=50, slow=200, unchanged), pooled across each
universe, liquidity-adjusted costs, genuine in-sample (2015 to
2020-06-30) / out-of-sample (2020-07-01 to 2025) split. Buy & hold is
now shown for EACH window separately (not one full-period number) --
the only way to compare the strategy and its benchmark on the SAME
dates.

### Nifty Midcap 150

| | Strategy IS | Strategy OOS | Buy&Hold IS | Buy&Hold OOS |
|---|---|---|---|---|
| CAGR | 3.25% | 26.91% | 10.94% | **36.28%** |
| Max Drawdown | -27.40% | -14.76% | -37.66% | -22.59% |
| Sharpe | **-0.219** | 1.440 | 0.375 | **1.564** |
| Total Trades | 352 | 429 | — | — |
| Market Exposure | 45.6% | 66.7% | 100% | 100% |
| Symbols included | 113/145 | 139/145 | 113/145 | 142/145 |

### Nifty Smallcap 250

| | Strategy IS | Strategy OOS | Buy&Hold IS | Buy&Hold OOS |
|---|---|---|---|---|
| CAGR | 5.55% | 31.27% | 8.34% | **40.00%** |
| Max Drawdown | -35.17% | -18.05% | -58.27% | -28.43% |
| Sharpe | +0.030 | 1.505 | 0.221 | **1.506** |
| Total Trades | 501 | 665 | — | — |
| Market Exposure | 41.9% | 63.6% | 100% | 100% |
| Symbols included | 156/246 | 222/246 | 156/246 | 237/246 |

**The strategy loses to buy-and-hold on CAGR in every cell, both
universes, both windows, often by a wide margin (e.g. Smallcap OOS:
31.27% vs 40.00%).** On Sharpe, the picture is closer: Smallcap's OOS
Sharpe (1.505) is nearly identical to its own buy-and-hold's (1.506) --
see Section 8 for why that near-tie is NOT the same thing as "the
strategy adds value." Midcap's OOS Sharpe (1.440) still trails its
buy-and-hold (1.564).

Symbols not included were excluded for one of three disclosed, logged
reasons (not silently dropped): insufficient history for a 200-day MA
(GROWW, LENSKART, ANTHEM, others; also now a nontrivial number of
recent listings with literally zero rows inside the IN-SAMPLE window,
correctly excluded from that window only, not from OOS), an unresolved
discontinuity blocking the gate (several bank/NBFC names — e.g.
INDUSINDBK, ICICIPRULI — correctly blocked pending the same
GENUINE/ARTIFACT/UNREVIEWED review process used throughout this
project), or a load/validation failure.

### Through the research harness

**AMENDMENT 2 (2026-09-06):** the harness itself had a second bug,
found while writing the paragraph originally here — `run_harness()`
granted VALIDATED_CONFIRMED whenever out-of-sample alone cleared
corrected significance, with no requirement that in-sample show
anything. Fixed (see `research/harness.py`'s point 7 and
`tests/test_harness.py`): VALIDATED_CONFIRMED now requires in-sample
AND out-of-sample to BOTH independently survive correction; an
out-of-sample-only result gets a new, distinctly-flagged status,
`OOS_ONLY_SIGNIFICANT`, instead.

**AMENDMENT 3 (2026-09-06):** a third bug — `bonferroni_alpha` was
computed against this run's own batch size (2), not the ledger's true
cumulative count (164), despite that count existing specifically to be
used for this. Fixed (see `FINDINGS.md` Section 6, Bug 3). Both results
were re-run under BOTH corrections — the Sharpe/p-values are unchanged,
the status is now correct against the true bar:

| | In-sample Sharpe (p) | OOS Sharpe (p) | Bonferroni bar | Status |
|---|---|---|---|---|
| Midcap 150 | -0.219 (0.696) | **1.440 (0.0004)** | 0.05/164≈0.00030 | **VALIDATED_FAILED** |
| Smallcap 250 | +0.030 (0.472) | **1.505 (0.0002)** | 0.05/164≈0.00030 | **OOS_ONLY_SIGNIFICANT** |

Cumulative hypotheses tested across this project's history: **164**
(109 sweep + 51 pairs + 2 MA-vs-RSI + 2 here — unchanged count; the
date-window fix and both harness fixes were bug-fix re-runs of existing
hypotheses, not new ones).

**Neither result is VALIDATED_CONFIRMED.** Midcap 150's out-of-sample
Sharpe no longer even clears the corrected significance bar on its own;
Smallcap 250's does, narrowly, with a flat-to-negative in-sample Sharpe
behind it — exactly what `OOS_ONLY_SIGNIFICANT` exists to flag: there
was no in-sample finding to replicate, so out-of-sample success alone is
best read as "this window happened to suit a barely-invested strategy"
rather than evidence of skill. The SAME pattern (negative in-sample
Sharpe, positive out-of-sample Sharpe) also appears for Nifty 50's own
MA crossover after the date-window fix (IS Sharpe -0.19, OOS Sharpe
+0.97, now also `VALIDATED_FAILED` against the corrected bar) — see
`FINDINGS.md`'s amendment — so this isn't a Midcap/Smallcap-specific
weakness in the strategy; it's the shared fingerprint of 2020-2025 being
a historic bull run across ALL THREE universes (buy-and-hold Sharpe
1.32-1.56 in every one of them). **No strategy in this document's
history has ever achieved genuine VALIDATED_CONFIRMED status** under the
corrected harness — get_best_strategy() returns None for every run
registered so far.

## 6. Does the result differ meaningfully, and is it explainable by data/costs alone? (CORRECTED)

**It differs, but more narrowly than originally claimed, and the
"genuine timing" interpretation from the original Section 6 does not
survive the fix — see Section 8.**

What's still true, unchanged by the fix:

1. **Costs went up, not down** (liquidity-adjusted slippage, 1.8-2.7x
   the flat Nifty 50 rate). **Data quality went up, not down** (100%
   hard-validation pass rate). Neither of these explains anything below
   — both point toward the strategy looking *worse* here, not better,
   so they cannot be the source of any apparent improvement.
2. The RELATIVE gap between the strategy's OOS Sharpe and its own
   universe's OOS buy-and-hold Sharpe genuinely shrinks as the universe
   gets smaller: Nifty 50 gap = 0.974 − 1.324 = **−0.35**; Midcap 150
   gap = 1.440 − 1.564 = **−0.12**; Smallcap 250 gap = 1.505 − 1.506 ≈
   **0.00**. That's a real, monotonic, three-point pattern — not noise
   dressed up as a trend, and not explained by costs or data quality
   (both cut the other way).

What's corrected: the ORIGINAL document read Smallcap's near-zero gap
as "the strategy adding value in this specific segment" (a timing/
economic-mechanism story about slow-motion crashes). **Section 8 below
shows that reading is wrong.** A near-zero gap between a partially-
invested strategy's Sharpe and its own buy-and-hold's Sharpe is exactly
what a mechanical, no-timing-skill strategy would produce if it simply
picked its exposure fraction by lot rather than by trend — because
Sharpe ratio is invariant to diluting a return stream with cash at the
risk-free rate. The correct, narrower conclusion: **the universe genuinely
changes how costly the strategy's cash-drag is, relative to that
universe's own bull-market Sharpe, but nothing in these numbers shows
the strategy is exercising skill at WHEN to be in the market anywhere,
including Smallcap.** Section 8's direct test confirms this precisely.

**Direct answer to the question that mattered most in this stage: no,
small/midcaps do not look better here "only because the data is worse"
— costs and data quality both moved the wrong way for that story.** But
the follow-up question this document didn't originally ask — "is the
improvement real skill or a mechanical artifact of average exposure?" —
turns out to matter more, and the answer is mechanical, not skill, in
both universes (negative-mechanical for Midcap, zero-mechanical for
Smallcap).

## 7. Survivorship magnitude: adding back 5 known casualties (new, addresses a follow-up question)

Section 4 measured survivorship bias by DIRECTION and by membership-churn
PERCENTAGE (36.1%/48.5% of today's constituents lack full 2015 history).
That doesn't say how much it could move the actual Sharpe/CAGR numbers
above. To bound that: took the five named, individually-verified
casualties from Section 4 (Jet Airways, DHFL, Reliance Capital, Reliance
Communications, Reliance Naval and Engineering — all solidly mid-cap-scale
in 2015, none in `MIDCAP150_UNIVERSE` today), fetched their real price
history, ran the SAME unchanged MA crossover on them, and added them into
the Midcap 150 aggregate.

DHFL could not be loaded at all — Yahoo Finance has no historical price
series for `DHFL.NS` any more (`No data returned... symbol is invalid,
delisted, or has no trading history`). That is itself a small, concrete
illustration of survivorship bias operating one level deeper than index
membership: even the data source has stopped carrying a company that
collapsed six years ago. The other four loaded with full, real declines:
Jet Airways -91.9%, Reliance Communications -98.7%, Reliance Capital
-96.9%, Reliance Naval -87.5% (close-to-close over each stock's available
window).

| | Midcap150 baseline | + 4 casualties | Delta |
|---|---|---|---|
| IS Sharpe | -0.219 | -0.246 | -0.027 |
| IS CAGR | 3.25% | 3.01% | -0.24pp |
| OOS Sharpe | 1.440 | 1.421 | -0.018 |
| OOS CAGR | 26.91% | 26.44% | -0.48pp |

The 4 casualties ALONE (their own combined book, no other symbols):
IS Sharpe -0.617 / CAGR -5.03%, OOS Sharpe -0.156 / CAGR ~0.00% — genuinely
bad, as expected for four companies that went to near-zero.

**This is explicitly a biased sample (hand-picked known catastrophic
failures, not a random draw of everyone who could have failed) — an
upper bound on the damage, not an unbiased estimate**, and even under
that deliberately unfavorable framing, the damage is small: roughly
0.02-0.03 Sharpe and a quarter-to-half a CAGR point, out of a baseline
OOS Sharpe of 1.44 and CAGR of 26.9%. Two reasons this is structurally
bounded, not just lucky: (1) `run_strategy_on_universe` gives every
symbol its own equal-sized capital book (parallel books, not
market-cap-weighted), so a handful of total wipeouts among ~117-143
books can only move the pooled average by roughly their own weight,
~3%; (2) the strategy's own trend-following exit discipline caps (does
not eliminate) the damage from a slow-motion collapse — it isn't riding
the stock to zero the way an un-timed buy-and-hold position would.

**Direct answer: the positive out-of-sample Sharpe survives this stress
test comfortably. It is not plausibly a survivorship artifact** — not
because survivorship bias isn't real (Section 4 shows it clearly is),
but because even a maximally-biased attempt to inject it back in barely
moves the number.

## 8. Is the Smallcap Sharpe number genuine timing, or just lower exposure? (new, corrects Section 6)

A strategy that's out of the market some fraction of the time will
almost always show LOWER volatility than buy-and-hold. If that alone
were enough to explain an improved Sharpe ratio, "the strategy adds
value" would be the wrong conclusion — "the strategy is diluted with
cash, and dilution mechanically changes Sharpe" would be the right one.
These need to be told apart, not assumed.

**The precise test:** Sharpe ratio is invariant to blending a return
stream with cash at the risk-free rate — diluting a stream by weight w
scales both its excess return and its volatility by exactly w, leaving
their ratio unchanged. So a strategy that holds its OWN universe's
exposure fraction w on RANDOM, trend-blind days (zero timing skill) has
an EXPECTED Sharpe identical to 100%-invested buy-and-hold, regardless
of what w is. That gives a clean, parameter-free null: if the real
strategy's Sharpe roughly equals buy-and-hold's, that's the SIGNATURE of
no timing skill, not evidence of it — real timing skill would have to
show up as a Sharpe measurably ABOVE buy-and-hold's, not merely close to
it.

| | Buy&Hold (100% exp.) | Same-exposure, zero-skill benchmark | Actual strategy | Gap (strategy − benchmark) |
|---|---|---|---|---|
| Midcap 150 (66.7% exp.) | 1.564 | 1.564 | 1.440 | **-0.124 (worse than no-skill dilution)** |
| Smallcap 250 (63.6% exp.) | 1.506 | 1.506 | 1.505 | **-0.001 (statistically a tie)** |

(The middle column being identical to buy-and-hold's own Sharpe in both
rows is not a coincidence or a bug — it's the invariance property above,
confirmed numerically.)

**Conclusion: neither universe shows genuine timing skill.** Midcap's
trend-following entries and exits actively hurt it relative to what
randomly sitting out 33% of days would have given for free — a real,
measurable timing COST, not neutral. Smallcap's strategy Sharpe is
statistically indistinguishable from the same-exposure no-skill
benchmark — its near-tie with buy-and-hold in Section 5/6 is exactly
what you'd expect from a strategy with NO timing ability at all, not
evidence that this one has some. The plausible economic mechanism
proposed in the original Section 6 (slow-motion crashes give a 200-day
MA time to react) is not supported by this test and is retracted as a
conclusion, though it remains a reasonable hypothesis someone could test
directly (e.g., comparing crash recovery times by universe) rather than
infer from a Sharpe ratio that turns out to be explainable without it.

## 9. Limitations (in addition to everything in FINDINGS.md Section 6)

- Discontinuity review (GENUINE/ARTIFACT/UNREVIEWED) has not been done
  for the Midcap/Smallcap-specific blocked symbols — several bank/NBFC
  names are excluded pending that review, the same way ADANIENT/TMPV
  were reviewed for Nifty 50. Reviewing them could change which symbols
  are included, though not the aggregate conclusion's direction given
  how few symbols are affected relative to 145/246.
- The liquidity-based slippage model's ceiling (2%) and floor are
  disclosed judgment calls, not a verified NSE-published number for
  these specific indices — a real, stated limitation of Section 3, not
  hidden in the results.
- One parameter set only (fast=50, slow=200) — deliberately unchanged
  for a controlled comparison, but this document makes no claim about
  whether a different (fast, slow) pair would perform differently on
  these universes, the way the Nifty 50 sweep explored that question
  for Nifty 50 specifically.
