# Cross-Sectional Momentum Methodology — Frozen Before Any Result

**Status: PRE-REGISTERED. Written 2026-09-06, before any signal was
computed, any backtest run, or any result of any kind.** Nothing in this
document may be changed after results are seen. If a rule here turns out
to be wrong or impractical, that's a finding to report, not a line to
quietly edit — same discipline as `METHODOLOGY.md`'s pairs work.

This is a new strategy FAMILY, not a new parameterization of something
already tested. Every prior strategy in this project (MA crossover, RSI
reversion) ranks a stock against **its own history** — the signal for
RELIANCE never looks at TCS. Cross-sectional momentum ranks stocks
**against each other** at each point in time and holds whichever ones
rank highest. That's a different mechanism, a different claim about why
it should work, and — as it turns out below — a different backtest
engine, because the existing one assumes every symbol trades as an
independent, separately-capitalized book.

---

## 0. Rationale (written before any result exists)

**Claim:** stocks that have outperformed their peers over the trailing
9-12 months tend to keep outperforming for the next several months,
because the market **underreacts** to information. Analysts revise
earnings estimates in stages rather than all at once; institutional
capital reallocates slowly (mandates, liquidity constraints, career risk
in front-running a trend before it's confirmed); and the disposition
effect (investors sell winners too early and hold losers too long)
means good news gets priced in gradually rather than immediately. A
stock's recent relative strength is therefore a real, if temporary,
signal about information the market hasn't fully absorbed yet — not
noise.

This is not "it has worked in backtests" — it's the standard behavioral-
finance explanation for a well-documented academic finding (Jegadeesh &
Titman, 1993, "Returns to Buying Winners and Selling Losers," one of the
most replicated results in empirical asset pricing), and it is
mechanically distinct from every rationale already used in this project:
MA crossover's rationale is about a **single stock's own trend**
persisting; RSI reversion's is about a single stock's own short-term
**overreaction** fading. This rationale is about **relative**
mispricing across stocks, which is why it has to be computed
cross-sectionally rather than per-symbol.

**Stated up front, not discovered after a bad result:** the version
tested here is **long-only** (no shorting — infeasible at this
project's capital scale, same constraint that killed the pairs
execution layer in `METHODOLOGY.md` Section 0). The academic momentum
premium is measured long-short (long winners, short losers), and the
long leg alone is mechanically expected to capture roughly half of it
at best, while still carrying full market beta. A long-only
implementation is a real test of whether ranking adds value on top of
being invested — not a fair test of "the momentum premium" as the
literature defines it. Any negative result below should be read as "the
long-only, single-market, single-decade version of this doesn't clear
the bar," not as "momentum doesn't exist."

## 1. Frozen parameters

**Universe: Nifty 50 (`config.UNIVERSE`).** Chosen, not defaulted to:
(a) it's the only universe in this project with a COMPLETE discontinuity
review (GENUINE/ARTIFACT/UNREVIEWED) — Midcap/Smallcap still carry an
unreviewed backlog (see `README.md`'s Technical Debt); testing a brand
new strategy mechanism on a not-fully-reviewed universe would confound
two open questions at once. (b) It's the same universe already used for
MA crossover and RSI reversion, so this is a clean three-way comparison
of strategy FAMILIES on fixed ground, before any cross-universe
extension — which would be a separate, later, separately-registered
hypothesis, not folded into this one.

**Ranking lookback: trailing 252 trading days, skipping the most recent
21 trading days** — the standard "12-1" momentum formation period
(Jegadeesh & Titman's original design and the most-replicated choice in
the literature: 252 trading days ≈ 12 months, 21 trading days ≈ 1
month). Momentum score at formation date T for symbol S:

```
score(S, T) = close(S, T-21) / close(S, T-252) - 1
```

**Skip-month convention: YES, included, for the standard reason.** The
most recent month is excluded from the ranking window because 1-month
reversal is a separate, well-documented, OPPOSITE-signed effect
(short-term overreaction that mean-reverts, not momentum) — including it
would contaminate the momentum signal with a reversal signal pointing
the other way. This is not a free parameter tuned for this data; it is
the reason "12-1," not "12," is the standard name for this formation
period.

**Holdings: top 10 of 50 (a quintile), equal-weighted.** A true decile
of a 50-symbol universe is 5 stocks — too concentrated for a first test
of a brand-new mechanism (idiosyncratic single-stock risk would dominate
the result, and 5 names is not a pooled sample by this project's own
established standard). Quintile portfolios are a standard, literature-
recognized alternative to deciles specifically for smaller universes.
Long-only: hold the top 10, nothing else — the bottom-ranked stocks are
simply not held, never shorted (Section 0).

**Rebalance frequency: monthly, full equal-weight rebalance of the
entire portfolio** — not just membership changes. Monthly is the
standard cadence in the momentum literature (matches the 12-1 formation
period's own natural time unit). Full rebalancing (resetting every held
position back to exactly 1/10 of current portfolio value every month,
not just trading the names that enter or exit the top 10) is the more
commonly replicated convention AND the more conservative one for this
test's own purposes — it maximizes turnover, which is exactly the thing
Section on costs below is checking might kill the strategy. Using the
lower-turnover alternative (trade only membership changes) would make
any negative result about costs less credible, since it would look
chosen to minimize the very cost this document is designed to test
honestly.

**Formation and execution timing:** formation date = the last trading
day of calendar month T-1, using data through that day's close (no
look-ahead — this is the same day the MA crossover signal is computed
through). Rebalance trades execute at the OPEN of the first trading day
of month T — the same next-bar-open convention already used everywhere
else in this engine.

**Position sizing / capital model:** ONE shared portfolio of
`config.INITIAL_CAPITAL`, not `N` independent per-symbol books. This is
a structural difference from every strategy tested before it (see
Section 2) — "top 10 of the universe" is a claim about a single
portfolio's composition, not about running 50 independent parallel
books and summing them.

**Costs:** `engine/costs.py`'s existing India equity-delivery cost model
(brokerage, STT, exchange charge, SEBI fee, GST, stamp duty, 0.05%
slippage), applied to every buy and sell leg of every monthly rebalance
trade — the same cost stack already verified for Nifty 50, not the
Midcap/Smallcap liquidity-adjusted model (this universe is Nifty 50).

**Missing/insufficient data handling:** a symbol with fewer than 273
trading days of history (252 + 21) as of a given formation date is
excluded from that period's ranking only — not force-included with an
undefined score. If a held stock's data ends entirely before the next
rebalance (delisting mid-holding-period), it is force-exited at its last
available price on that date, logged, not silently dropped or crashed
on.

## 2. Why this needs a new backtest engine, not `engine/backtest.py`

`engine/backtest.py`/`engine/universe.py` model every symbol as an
independent book: `generate_signals(df)` sees ONE symbol's price history
and returns ONE symbol's long/cash signal, and `run_strategy_on_universe()`
runs and sums `N` separately-capitalized backtests. That model cannot
express "hold whichever 10 stocks rank highest this month, sized as
fractions of ONE shared portfolio" — ranking is inherently a function of
the WHOLE universe at once, and position sizing depends on how many
names are held this period, which changes over time.

New code, reusing everything reusable from the existing engine:
- `strategies/cross_sectional_momentum.py` — pure function: universe of
  `{ticker: df}` in, a DataFrame of target portfolio weights (one row
  per formation date, one column per symbol) out. No knowledge of money
  or execution, same boundary rule as every other strategy in this
  project.
- `engine/portfolio_backtest.py` — a new, second backtest loop for
  weight-target (not binary long/cash) strategies: walks forward day by
  day, holds whatever weights were set at the last rebalance, executes
  rebalance trades at each formation date's next-open, and reuses
  `engine/costs.py` and `engine/metrics.py` unchanged. Does NOT touch or
  modify `engine/backtest.py` — that engine is correct and tested for
  what it does; this is an addition for a genuinely different kind of
  strategy, not a replacement.

## 3. Mandatory checks (per `README.md`'s standing workflow)

1. **Zero-skill benchmark: same-count random selection from the same
   universe**, not the cash-dilution benchmark used for MA
   crossover/RSI. Those strategies vary how much time they spend
   invested — Sharpe-vs-cash-dilution is the right null for them
   (`FINDINGS.md` Section 4). Momentum is (almost) always fully
   invested in SOME 10 stocks; the question isn't "does timing add
   value," it's "does picking BY RANK add value over picking the same
   number of names at random." Implementation: Monte Carlo — simulate
   many independent portfolios that hold 10 randomly-chosen (not
   ranked) names, rebalanced monthly with the same costs, and compare
   momentum's actual Sharpe against the resulting distribution (mean and
   percentile rank), not a single random draw (too noisy to mean
   anything on its own).
2. **Exposure reported alongside every Sharpe** — expected to be near
   100% by construction (always holding 10 names), but measured, not
   assumed; a formation date with fewer than 10 eligible-history symbols
   would show through as reduced exposure.
3. **In-sample and out-of-sample verified separately, and the windows'
   disjointness confirmed directly** — not assumed from the date-window
   fix being in place. Concretely: assert the two windows' resulting
   equity curves have non-overlapping date ranges and produce different
   values, the same check `tests/test_backtest_date_window.py` already
   locks in for the existing engine, applied here too before trusting
   any IS/OOS comparison.
4. **Survivorship, quantified for momentum specifically, not inherited
   from `FINDINGS.md` Section 5's MA crossover number.** A ranking
   strategy that selects on trailing return has a channel MA crossover
   does not: a stock that later collapsed or delisted is missing from
   today's constituent list, so it can never be RANKED, let alone
   selected — even in the years before its collapse, when it might well
   have ranked in the top 10 on trailing momentum. This is a
   structurally worse form of the same bias, and needs its own measured
   estimate, not an assumption that Section 5's 12.0% figure carries
   over unchanged.
5. **Turnover and its cost, reported explicitly.** Full monthly
   rebalancing of a 10-name portfolio is high-turnover by construction
   compared to MA crossover's ~300-day average holding period. Report
   annualized turnover (fraction of portfolio value traded per year) and
   the resulting annual cost drag in percentage points — stated as its
   own number, not folded silently into the net Sharpe.
6. **Run through `research/harness.py`.** Report the cumulative
   hypothesis count before and after, and the Bonferroni alpha that
   actually applies — against the TRUE cumulative total, which required
   fixing a second harness bug found while preparing this registration
   (see the accompanying report).

## 4. Rejection / inconclusive criteria (written before any result exists)

- **Rejected** if the strategy's out-of-sample Sharpe does not exceed
  the zero-skill random-selection benchmark's distribution at a level
  that would be surprising under pure chance (not just "positive" —
  the same discipline already applied to the MA crossover sweep and the
  pairs screen).
- **Rejected as a cost-driven failure, a distinct bucket from "no
  ranking value,"** if turnover-adjusted costs consume most of the raw
  (pre-cost) spread between the strategy and the zero-skill benchmark —
  i.e., if the ranking signal shows real pre-cost value but costs erase
  it. This is evaluated separately, the same way `METHODOLOGY.md`
  Section 7 separated "no statistical edge" from "costs consumed the
  edge" for pairs.
- **Inconclusive** if fewer than 24 monthly rebalances occur in either
  the in-sample or out-of-sample window (2 years — unlikely to bind
  given the ~66-month out-of-sample window, but frozen here for the same
  reason `METHODOLOGY.md` froze a minimum trade count for pairs: stated
  before, not adjusted after, seeing how close to the line the actual
  result falls).

## 5. Residual data-snooping risk — stated plainly, not eliminated

- The 12-1 formation period, monthly rebalancing, and quintile-of-10
  sizing are all standard literature conventions, not tuned on this
  data — but choosing to adopt these specific standard conventions
  (rather than, say, a 6-1 formation period or decile sizing) is still a
  research decision made by one person, once, the same caveat
  `METHODOLOGY.md` Section 8 already logged for pairs.
- Survivorship bias (Section 3, check 4) is being measured, not
  corrected for — a genuinely worse figure than MA crossover's is
  expected and will be reported, not adjusted away.
- The out-of-sample window (2020-07 to 2025-12) is the same historic
  bull run already documented in `FINDINGS.md` as dominating every
  other out-of-sample result in this project. A momentum strategy
  tested only against that regime carries the identical limitation
  already disclosed there.
