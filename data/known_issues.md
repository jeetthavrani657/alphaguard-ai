# Known data issues

Confirmed data-quality findings in NSE price history from yfinance, logged
so they aren't rediscovered from scratch. Each entry was checked against
evidence -- external sources, or the price/volume data itself -- not assumed.

**This file is the human-readable log. `data/discontinuity_registry.py` is
the machine-readable counterpart that `assert_backtest_safe()` actually
reads** -- when you review a new flagged date, update both together.

Every entry below has an explicit **Status**, the **evidence** behind it,
and a **Reviewed** date. Nothing is silently assumed clean.

## Resolution status

Every discontinuity gets one of three statuses:

- **GENUINE** — a real price move that actually happened (a crash, a rally,
  a crisis). Backtesting across it is correct. The gate does not block it.
- **ARTIFACT** — a price change that did NOT happen economically (e.g. an
  unadjusted demerger moving value to a different ticker). Backtesting
  across it is wrong. The gate blocks it.
- **UNREVIEWED** — nobody has looked at it yet. The gate blocks it by
  default, on purpose: an unreviewed move might be an artifact, so silence
  must never be read as "safe."

A separate small set of entries below aren't price-jump discontinuities at
all (a missing-day heuristic bug, a data-vendor artifact) -- those use
**FIXED** or **RESOLVED** instead, since ARTIFACT/GENUINE/UNREVIEWED don't
apply to them.

---

## OPEN ITEMS (unresolved -- read these first)

### ADANIENT.NS 2015-06-03 — OHLC plausibility gap in the validator

- **Status: OPEN** (validator gap, not yet fixed)
- **Reviewed:** 2026-09-02
- **Evidence:** the raw row is `open=294.19, high=294.19, low=54.57,
  close=56.32`, sitting between a prior close of 91.95 and a next close of
  59.81. A price range from 54 to 294 in one day that snaps straight back
  the next is not a real trade -- it's a corrupted print in Yahoo's feed
  (classified ARTIFACT in the registry; see the Stage 5 table below).
- **Why the current validator misses it:** `data/validator.py`'s OHLC
  logic check only flags `open > high` or `open < low`. Here
  `open == high == 294.19` exactly -- technically valid ("open is within
  the high/low range"), even though 294 next to a 54-56 trading range on
  the same day is absurd. The check verifies internal OHLC consistency,
  not plausibility against the stock's own recent range, so an extreme
  but internally-"consistent" bad print slips through untouched.
- **What a fix would involve:** a new check comparing each day's
  open/high/low against, e.g., a rolling multiple (3-5x?) of the recent
  (20-30 day) closing-price range, flagging anything wildly outside it.
- **False-positive tradeoff:** real stocks legitimately move fast --
  a genuine upper/lower circuit day, a post-results gap, or an early day
  of extreme volatility (like Yes Bank's March 2020 week, already reviewed
  as GENUINE below) could trip a naive multiple-of-range check even
  though nothing is wrong with the data. Getting the threshold right
  needs deliberate tuning against more known-good extreme days, not a
  reactive patch for one bad print. Left open rather than quietly
  "fixed" with an untuned threshold.

---

## Corporate action discontinuities

### TMPV.NS (formerly TATAMOTORS.NS) — 2025-10-14 — -40.2%

- **Status: ARTIFACT**
- **Reviewed:** 2026-09-02
- **Cause:** Tata Motors demerger. The original "Tata Motors Limited"
  listing was renamed "Tata Motors Passenger Vehicles Limited"
  (`TMPV.NS`), and a new "Tata Motors Limited" commercial-vehicles entity
  was listed separately as `TMCV.NS` (history starts 2025-11-12 -- no
  pre-demerger data). The value of the spun-off CV business was removed
  from the passenger-vehicle share price on 2025-10-14: a clean,
  single-day -40.2% drop with no trading-day gap.
- **Evidence:**
  - `yf.Ticker('TMPV.NS').actions` has no split/dividend entry near
    2025-10-14 -- confirms this is NOT an ordinary adjusted action.
  - `yf.Search('Tata Motors')` confirms the entity rename
    (`nameChangeDate: 2026-09-01`) and the TMCV listing start date.
  - Volume was only ~3.3x the 30-day average (52.3M vs 15.9M) -- much
    lower than any of the 18 GENUINE moves reviewed below, all of which
    ran 2x-14x.
  - Price instantly stabilized in a flat 387-398 range for the following
    week instead of continuing to move as news was digested -- a clean
    step-change to a new level, not organic price discovery. This
    flat-after-step signature is the actual tell, more than the volume
    number alone.
- **The `TATAMOTORS.NS` ticker itself now 404s** ("possibly delisted") --
  fully retired in favor of `TMPV.NS` / `TMCV.NS`.
- **How to handle:** `assert_backtest_safe()` refuses to run a backtest
  spanning 2025-10-14 for `TMPV.NS` unless called with `override=True`.
  Decide how to treat the value transfer before overriding (e.g. truncate
  the series at the demerger date, or manually splice in `TMCV.NS`'s value).

---

## Reviewed large moves — YES BANK (YESBANK.NS)

All 10 dates flagged by the >25% threshold. **All Status: GENUINE.**
**Reviewed: 2026-09-02.** Method: checked `yf.Ticker().actions` (none
matched, which is why they were flagged in the first place), checked
volume vs. the trailing 30-day average, checked whether price direction
persisted or snapped back, and cross-checked the busiest/least-certain
dates against independent news sources.

| Date | Move | Status | Volume vs 30d avg | Evidence |
|---|---|---|---|---|
| 2018-09-21 | -29.0% | GENUINE | 10x | RBI cut CEO Rana Kapoor's tenure extension to Jan 2019 (governance concerns). Confirmed externally (Business Standard, BusinessToday, same-day). Decline persisted for a week after. |
| 2019-02-14 | +28.1% | GENUINE | 4.3x | RBI found no asset-quality divergence in 2017-18 reporting. Confirmed externally (BusinessToday, dated 2019-02-14, reports the same +28.96% figure). |
| 2019-04-30 | -29.2% | GENUINE | 6.6x | Q4 FY19 results period, large NPA/provisioning miss. Decline continued for a full week after (no reversion). |
| 2019-10-03 | +32.8% | GENUINE | 2.3x (of an already-elevated avg) | Relief bounce after a severe capitulation crash the prior 4 sessions (53.70 -> 32.00) on NPA-divergence/PCA fears. |
| 2020-03-05 | +25.6% | GENUINE | 5.3x | Day RBI placed Yes Bank under moratorium, capped withdrawals at Rs 50,000. Confirmed externally (Outlook India, Business Standard). Highest-volume day in the window. |
| 2020-03-06 | -56.1% | GENUINE | — | RBI released the draft reconstruction plan with SBI as anchor investor (confirmed externally) -- panic selling as terms became concrete. |
| 2020-03-09 | +31.6% | GENUINE | 4x | Continued moratorium-week volatility, compounded by the broader COVID market crash the same week. |
| 2020-03-11 | +35.5% | GENUINE | 2x | Between the RBI draft plan (03-06) and the Cabinet's final scheme approval (03-13, confirmed externally). |
| 2020-03-16 | +45.2% | GENUINE | — | Relief rally after Cabinet approved the final reconstruction scheme (2020-03-13, confirmed externally); moratorium lifted 2020-03-18. |
| 2020-03-17 | +58.1% | GENUINE | — | Continuation of the rescue-completion relief rally, one day before the moratorium was formally lifted. |

Full reasoning per date is in `data/discontinuity_registry.py`.

## Reviewed large moves — VODAFONE IDEA (IDEA.NS)

All 8 dates flagged. **All Status: GENUINE. Reviewed: 2026-09-02.**

| Date | Move | Status | Volume vs 30d avg | Evidence |
|---|---|---|---|---|
| 2017-01-30 | +25.3% | GENUINE | 14x | Vodafone confirmed merger talks with Idea Cellular. Confirmed externally (Business Standard, CNN Money, same-day). Rally continued the next day too. |
| 2019-07-29 | -27.0% | GENUINE | 12x | Q1 FY20 results window -- record quarterly loss reported ~2019-07-26. Decline continued for a week after. |
| 2019-11-19 | +36.0% | GENUINE | ~3x (of an elevated avg) | Relief-rally leg of the AGR crisis (SC's adverse verdict was 2019-10-24; the crash preceding this date matches that timeline exactly). Not independently re-searched, but every structural signal (volume, timing, persistence) is consistent. |
| 2020-02-19 | +40.0% | GENUINE | 4x | Continuation of the AGR crisis saga -- SC hearings in Feb 2020 swung between contempt threats and relief signals. Not independently re-searched; consistent with the surrounding AGR-driven dates. |
| 2020-03-13 | +33.3% | GENUINE | 0.7x (below its own elevated avg) | Matches the globally-documented COVID-crash relief rally of 2020-03-13 (Indian equities broadly rallied hard that day). The one date here with below-average volume, but still 347M shares -- a market-wide event, not stock-specific. |
| 2020-03-18 | -35.1% | GENUINE | 2x | Trough of the March 2020 global COVID crash. Highest-volume day in the window. |
| 2020-09-03 | +26.8% | GENUINE | 1.6x | SC's 2020-09-01 AGR ruling gave telcos 10 years to pay dues instead of immediate payment -- landmark relief verdict, rally lands 2 trading days later. |
| 2021-09-16 | +25.7% | GENUINE | volume was only 1,277 shares (see note) | Union Cabinet announced a major telecom relief package (~2021-09-15); stock "more than doubled" 2021-09-01 to 09-17, repeatedly hitting the upper circuit (confirmed externally, Business Standard/Angel One). The near-zero volume initially looked suspicious, but matches the known mechanism for a stock locked at its upper circuit: almost no one sells at the locked price, so traded volume collapses even though the price move is real. |

Full reasoning per date is in `data/discontinuity_registry.py`.

**Contrast with the TMPV artifact:** every one of these 18 moves shows
either a large volume spike or (in the one upper-circuit case) a specific,
externally-confirmed mechanism explaining low volume -- and every one shows
price continuing to move or hold at the new level as real news was
digested. None show TMPV's signature: a clean step-change followed by
immediate, flat stability. That contrast is what separates GENUINE from
ARTIFACT here, more than any single number.

## Reviewed large moves — found running the Stage 5 universe

Running the discontinuity gate across 50 Nifty 50 symbols for the first
time surfaced 4 more dates (5 including TMPV, already reviewed above).
**Reviewed: 2026-09-02.** Same method as above; the two least-certain
external claims (Hindenburg crash dates, SBI recapitalization rally) were
independently re-confirmed via web search this session.

| Symbol | Date | Move | Status | Evidence |
|---|---|---|---|---|
| ADANIENT.NS | 2015-06-03 | −38.7% | **ARTIFACT** | Not a real move -- a corrupted data point. See the OPEN ITEMS section above for the full writeup. |
| ADANIENT.NS | 2019-05-20 | +27.4% | GENUINE | 2019 exit-poll rally (Modi 2nd term predicted); market-wide +3.7-3.8%, Adani's high-beta reaction to it confirmed externally. |
| ADANIENT.NS | 2023-02-01 | −28.2% | GENUINE | Hindenburg Research report crash (day 1 of 2); confirmed externally, ~54% total decline by 02-02. |
| ADANIENT.NS | 2023-02-02 | −26.7% | GENUINE | Hindenburg crash, day 2. |
| AXISBANK.NS | 2020-03-23 | −27.9% | GENUINE | Trough of the global COVID crash -- same date already established via the IDEA.NS review. |
| BAJAJFINSV.NS | 2020-03-23 | −25.9% | GENUINE | Same COVID-crash trough date. |
| SBIN.NS | 2017-10-25 | +27.7% | GENUINE | ₹2.11 lakh crore ($32.4B) PSU bank recapitalization plan approved; confirmed externally ("SBI... rose more than 20 percent" same-day). |

Full reasoning per date is in `data/discontinuity_registry.py`.

---

## Market-wide data artifacts

### 2025-03-18 — zero volume, flat OHLC, across every symbol checked

- **Status: FIXED** (in `data/loader.py`)
- **Reviewed:** 2026-09-02
- **Symptom:** `RELIANCE.NS`, `TMPV.NS`, `YESBANK.NS`, `IDEA.NS` all had a
  row for 2025-03-18 with `open == high == low == close == prior day's
  close` and `volume == 0`.
- **Evidence:** confirmed via multiple independent 2025 NSE holiday
  lists that 2025-03-18 (a Tuesday) is **not** an NSE holiday (nearest
  holidays: 2025-03-14 Holi, 2025-03-31 Id-Ul-Fitr). No NSE-wide outage
  reported for that date either. A real closure produces a *missing* row,
  not a present one with the prior close carried forward at zero volume --
  so this is a **Yahoo Finance data artifact**, not a market event.
- **Fix:** `data/loader.py` now drops any row matching this exact
  fingerprint (zero volume + flat OHLC + OHLC equal to the prior close)
  as part of cleaning, for every symbol -- not just a hardcoded date for
  these four. Pattern-based, not a growing list of one-off exceptions.
  Verified: after a `force_refresh`, none of the four test symbols show
  this row anymore (2715 rows -> 2714).

### 2016-10-12 — missing across every symbol checked

- **Status: RESOLVED** (was a validator heuristic bug, not a data problem)
- **Reviewed:** 2026-09-02
- **What happened:** the validator's old (isolated-single-day) holiday
  heuristic mis-flagged this as a "possible genuine gap." It's actually a
  real back-to-back NSE holiday pair: 2016-10-11 (Dussehra) and
  2016-10-12 (Moharram), confirmed against a 2016 NSE holiday list.
- **Fix:** classify missing days by *run length* (consecutive missing
  business days) instead of single-day isolation -- now correctly
  classifies this as likely-holiday. Logged here as the reason for that
  fix, not as an ongoing data problem.

### OHLC logic check flagged 8 symbols for floating-point noise, not real violations

- **Status: RESOLVED** (validator bug, not a data problem)
- **Reviewed:** 2026-09-06
- **What happened:** running the validator across the new Midcap 150 /
  Smallcap 250 universes, 8 symbols (NHPC, FSL, GRAPHITE, HEG, TRIDENT,
  CHENNPETRO, TECHNOE, BSOFT) failed "OHLC logic violations." Every
  single flagged row turned out to be floating-point rounding noise
  from yfinance's split/dividend adjustment arithmetic -- e.g. NHPC's
  2020-06-09 "close < low" violation was close=15.593150138854982 vs
  low=15.593150138854980, a difference of 1.8e-15 (economically zero).
  FSL alone had 527 such rows. The strict `<`/`>` comparison in
  `_check_ohlc_logic` treated this machine-precision noise as a real
  violation.
- **Fix:** added a Rs 1e-6 absolute tolerance to the four OHLC
  comparisons -- large enough to absorb ~1e-14/1e-15 float noise,
  many orders of magnitude too small to hide a genuine violation (which
  in practice run from a few paise to several rupees). Verified: all 8
  symbols now pass; `tests/test_validator_ohlc_tolerance.py` locks in
  both that noise-level differences pass AND that a genuine (Rs 5+)
  violation still fails.

### Current-day bar arrives with a volume but NaN prices

- **Status: RESOLVED** (loader fix, tested)
- **Reviewed:** 2026-10-16
- **What happened:** when the cache was first extended to the present,
  Yahoo returned the still-forming session (e.g. 2026-10-15) as a row
  with a nonzero volume but NaN open/high/low/close. The validator
  flagged NaN prices as a hard failure, but nothing downstream acted on
  that: the engine would have marked the portfolio's last day to NaN and
  corrupted that window's CAGR/Sharpe.
- **Fix:** `data/loader.py`'s `_drop_phantom_rows()` now also drops any
  row with a NaN price (a priceless bar can never be traded or marked).
  `tests/test_loader_artifact_rows.py` covers it, and confirms the
  original 2025-03-18 zero-volume artifact is still dropped and an
  ordinary zero-volume day with a price move is kept.

### The last day of the research window is never downloaded (yfinance `end` is exclusive)

- **Status: RESOLVED 2026-10-16** (loader fix + cache repair; see "Resolution" at the end of this entry)
- **Reviewed:** 2026-10-16
- **What happened:** `config.END_DATE` is `2025-12-31` and `data/loader.py` passed it
  straight to `yfinance` as `end=`. Yahoo treats `end` as **exclusive**, so a fresh
  download stops at 2025-12-30. On every later load the cache check
  (`cache.max >= end`) fails, the loader asks for the "missing" tail
  `2025-12-31 -> 2025-12-31`, Yahoo returns nothing for a zero-width range, and
  that failure is swallowed (one `possibly delisted; no price data found` line per
  stock in the console).
- **Evidence (cache last-bar dates):** Nifty 50: all 50 stocks end 2026-10-15
  (their cache was extended to the present for the forward test, which contains
  the 2025-12-31 bar). Midcap 150: all 145 end **2025-12-30**. Smallcap 250: all
  246 end **2025-12-30**.
- **Effect on results:** the three universes are not on exactly the same window.
  Nifty 50 includes 2025-12-31, Midcap/Smallcap do not. One extra trading day
  moves a Sharpe by about 0.01: Nifty 50 MA crossover out-of-sample is 0.9745
  when ended 2025-12-30 (the figure FINDINGS.md Section 4 prints, 0.974) and
  0.9831 with the 2025-12-31 bar (what the cache produces today). Momentum
  1.4051 vs 1.4135 likewise. No conclusion changes: every strategy's status and
  every strategy-vs-benchmark ordering is the same either way.
- **Related defect found while fixing it (adjustment-basis splice):** extending
  a cache by appending a downloaded tail joined two adjustment bases. Yahoo
  re-scales adjusted history whenever a dividend goes ex, so the join showed a
  fake one-day move. In the Nifty 50 cache the 2025-12-30 -> 2025-12-31 move was
  wrong for four stocks: COALINDIA -1.25 pts, TCS -0.53, POWERGRID -0.46,
  ONGC -0.42. Midcap would have had the same had the missing day simply been
  appended.

#### Resolution (2026-10-16)

- **Loader (`data/loader.py`):**
  1. `end` is now inclusive: Yahoo is asked for `end + 1 day` and the result is
     clipped to the window.
  2. A cache that does not reach the requested window is no longer patched.
     The whole range (the union of the request and what is held) is
     re-downloaded and replaces the cache, so one series = one adjustment
     basis. The cache never shrinks.
  3. Vendor-truncation guard: if the cache holds data at the start of the
     requested range and the download no longer does, the cache is kept and a
     warning printed. Found live: **HEG.NS is now served by Yahoo only from
     2026-07-17**; a plain refresh would have discarded 2,714 rows of
     2015-2025. HEG's cache (through 2025-12-30) is therefore intact but has no
     2025-12-31 bar; every other symbol has one. An empty download also keeps
     the cache.
  - Tests: `tests/test_loader_end_date.py` (13 tests, 7 of the first 11 fail on
    the old loader).
- **Cache repair:** `python data/refresh_cache.py` re-downloaded all 441
  symbols in one pass (399 s, 0 failures). Measured against the backup taken
  first: Midcap +145 rows (one 2025-12-31 bar each) and 18 stock-days whose
  return moved by at most 0.00014 pt; Smallcap +1 day for 245 of 246 stocks and
  39 stock-days moved by at most 0.0075 pt; Nifty 50 12 stock-days moved, the
  largest being the COALINDIA seam (1.25 pt). A fresh download compared with
  the repaired cache at the 12-30/12-31 seam: no scale mismatch in the Nifty 50
  or in 40 sampled Midcap stocks.
- **Effect on results** (web app snapshot regenerated; no hypothesis was
  registered, the ledger is unchanged at 204). Every strategy now runs through
  2025-12-31, in all three universes. **No status changed.**

  | Strategy (out-of-sample) | Sharpe before | Sharpe after | Strategy return before -> after |
  |---|---|---|---|
  | MA crossover, Nifty 50 | 0.983 | 0.984 | 157.4% -> 157.6% |
  | MA crossover, Midcap 150 | 1.440 | 1.450 | 270.7% -> 273.7% |
  | MA crossover, Smallcap 250 | 1.505 | 1.508 | 346.3% -> 347.7% |
  | RSI reversion, Nifty 50 | -1.326 | -1.326 | 12.1% -> 12.1% |
  | Momentum, Nifty 50 | 1.413 | 1.414 | 441.7% -> 441.7% |
  | Dip A / Dip B / Dip uptrend | 0.477 / -1.873 / -6.920 | 0.479 / -1.872 / -6.920 | (within 0.1 pt) |

  In-sample Sharpe ratios are unchanged to three decimals for all eight
  strategies. The largest move anywhere is +0.010 (Midcap out-of-sample).
  "Before" is the cache as it stood when the issue was found, which for Nifty 50
  already included 2025-12-31 (with the fake seam moves) and for Midcap/Smallcap
  ended 2025-12-30.
- **One result is close to its bar and worth knowing:** the Smallcap 250 MA
  crossover's out-of-sample p-value is 0.000231 against the Bonferroni bar
  0.05/204 = 0.000245, a pass by a hair. It stays `OOS_ONLY_SIGNIFICANT`, and
  it would fail once the ledger reaches **217** hypotheses (it was 210 before
  the repair). It is "OOS only" in any case: the in-sample leg (p = 0.47) never
  replicated.
- **Not changed:** the narrative figures printed in FINDINGS.md,
  MIDCAP_SMALLCAP_FINDINGS.md and MOMENTUM_FINDINGS.md (for example 0.974 /
  1.324 for the Nifty 50, 1.4397 / 1.5048 hard-coded in
  `research/run_survivorship_and_exposure_check.py`). They are the values as
  computed at the time and the table above gives the current ones. Re-running
  the research scripts would register new hypotheses and change the ledger
  count, so it is deliberately not done; none of the differences affect a
  conclusion.
- **Going forward:** `python data/refresh_cache.py` is the supported way to
  refresh the cache. Cost of the new policy: a window whose last day has no bar
  (weekend/holiday), or a stock that listed after `start`, re-downloads that
  symbol on every load (one request per symbol, as before, larger payload).

---

## Upstox daily data vs the yfinance cache (checked 2026-10-19, 8 stocks, 2015-2025)

Source: `research/compare_upstox_yfinance.py`, via the read-only client `data/upstox_client.py` (free
Upstox API, daily candles back to 2000). Stocks with splits/bonuses in the window: RELIANCE, HDFCBANK,
INFY, TATASTEEL, TCS, ITC, MARUTI, ASIANPAINT. **This is a sample of 8, not the universe.**

- **Same trading calendar.** About 2,720 days each; the two sources differ by only 2 days one way
  (Diwali muhurat sessions 2017-10-19 and 2018-11-07 are in yfinance) and 8-11 days the other way
  (Saturday/Sunday special sessions, plus 2025-03-18). Volumes match to about 0.01%.
- **Split and bonus adjusted, both.** No source shows a -50%-style day; daily-return correlation is
  0.992-0.9996.
- **Dividends differ, on purpose of each source.** Upstox prices are NOT dividend-adjusted, yfinance's are.
  The price ratio Upstox/yfinance is 1.10-1.56 in 2015 and about 1.0-1.05 in 2025. So the same backtest on
  Upstox prices would show LOWER returns for dividend payers (roughly 1-4% a year for the ones tested):
  **Upstox is not a drop-in replacement for the cache.** A dividend history would have to be added back.
- **Two days differ by more than 5% in return:** ITC 2025-01-06 (the hotels demerger: Upstox -8.09%,
  yfinance -4.55%, i.e. the two treat the demerger differently) and TATASTEEL 2018-01-31 (Upstox -9.15%,
  yfinance -4.62%; cause not established).
- **2025-03-18 was a real trading day.** Upstox has normal prices and volume for it; yfinance's row for that
  date is the flat zero-volume artifact documented above, which the loader rightly strips. Upstox could fill
  the gap if it ever matters.
- **Not tested:** delisted/removed stocks (the instrument list covers listed ones), minute data, the live
  feed, and the other ~440 stocks.

- **Upstox's daily endpoint does not return the current day.** `fetch_daily` stops at the last COMPLETED day
  (asking for 2026-10-19 on the evening of 2026-10-19 returned nothing). Today's candle comes from the intraday
  endpoint, `upstox_client.fetch_today_daily`. Found while verifying the first forward day (below).

## First forward day, verified independently (2026-10-19)

The quality + value book reported -0.480% for its first counted day. Recomputed by hand, outside the engine: the
ten frozen picks' opens and closes from **Upstox** and from the **yfinance cache** agree exactly (10 of 10, equal-
weight gross return -0.319% from both); with whole-share rounding (99.0% of capital invested) and the engine's
buy-side costs (STT 0.1%, stamp 0.015%, exchange and SEBI charges, GST, 0.05% slippage) the net is -0.480%. The
forward machinery, the data and the cost model reproduce a real day to three decimals.

## yfinance publishes the latest day late, and a plain refresh deleted it (found 2026-10-20)

For the advisory's ETF prices, yfinance returned a row for 2026-10-19 with a volume but an empty close in the hours
after the session (on the evening of the 19th it had returned a provisional close). The advisory loader overwrote its
cache with each re-download and dropped empty closes, so the forward tracker slid back from "1 forward day" to "not
started". Fix: `advisory.merge_fresh` keeps a cached day the source does not have yet, and lets fresh values win where
it does, so a provisional close is corrected once the final one appears. Three cache rows lost that morning were
restored from the previous output file (261.20, 311.42, 119.83: the provisional closes of 2026-10-19). Re-downloading
also re-adjusts history slightly (the moderate profile's first forward day moved from -0.632% to -0.641%); that is the
kind of vendor revision `advisory_forward.csv` keeps one row per run to expose.

**The paper books were affected too (corrected the same morning; an earlier version of this note wrongly said they
were not).** The stock price cache in `data/loader.py` follows the same replace-on-refresh rule, and a manual run at
about 01:00 on 2026-10-20 deleted the 2026-10-19 row of ~440 cached stocks and sent all three books back to "not
started" until it was repaired. The loader now keeps cached rows later than the newest priced row of a fresh download
(tested). The 292 missing rows were restored from Upstox's read-only historical candles (all but HFCL, which Upstox
does not list; it fills in at the next normal run).

**Fixed the same day: the books now have a second source for the newest sessions.** `data/upstox_tail.py` is registered as the
loader's tail source by the daily books run (`data.loader.set_tail_source`). It supplies only sessions after Yahoo's last priced
day, only when such a session should exist (a weekday after 16:00 India time), so on a normal evening it makes no request at
all. Rows pass the loader's usual cleaning (no priceless or impossible bar), are saved with the cache, are logged in
`data/cache/upstox_tail_log.csv`, and are replaced by Yahoo's own value as soon as Yahoo prices the day. It uses only the read-only
historical-candle endpoints through the client's gate (CLAUDE.md rule 5). The Upstox token expires daily and is regenerated by
hand; a rejected token costs one request and the run carries on with Yahoo alone. Basis caveat: Upstox is split/bonus adjusted but
not dividend adjusted, which matters only if a dividend goes ex inside the few days it fills.

## The advisory forward clock started a day too early (found and corrected 2026-10-20)

`research/advisory_forward.py` first copied the paper books' dates (base 2026-10-16, first counted day 2026-10-19). But the
advisory rule was committed at 21:26 on 2026-10-19, after that day's close, so its results had already seen 2026-10-19 and that
day is not out-of-time. The clock now starts from the 2026-10-19 close and counts from 2026-10-20 (the trend rules, frozen on 2026-10-20,
use the same dates). The "day 1" figures shown earlier (about -0.6% for the profiles) were therefore not forward evidence and were
removed from `advisory_forward.csv`. The paper books were frozen on 2026-10-16, before 2026-10-19, so their dates stand.

## A catch-up run in market hours counted a half-finished day (found and corrected 2026-10-22)

The laptop slept from the evening of 2026-10-20 to the late morning of 2026-10-22, so the 19:00 run of 2026-10-21 was missed and
Windows ran it as a catch-up at about noon on 2026-10-22. Yahoo serves a live, half-finished bar for the current day while the
session is open (ITC showed 7M shares against a normal 12-20M), the loader cached it, and one row dated 2026-10-22 reached
`forward_books.csv` and `forward_snapshots.csv` as if it were a close. Both rows were removed. `data/loader.py` now drops today's
bar, from a download and from the cache, until 16:00 India time (test: `tests/test_loader_incomplete_today.py`). The same run was
also killed by the task's 30-minute limit, because Yahoo failed many downloads for the first minutes after the wake-up; the numbers
are recomputed from the full price history on every run, so the next evening run catches up with no gap in the results.

The same incident had a second effect, found the same evening. The noon run had already saved 2026-10-22's half-finished bar to the
cache files of about 295 stocks, and the guard above only stops new partial bars, so the 19:00 run found those files "complete"
(cache reaches the requested day: no download) and logged the day's numbers from noon prices (ITC cached at 257.25 with 7.1M shares;
Yahoo's close was 258.90 with 15.3M). The 22 October rows were removed from those cache files, the forward steps were re-run, and the
three logs now hold the full-day figures (the Nifty 50 benchmark for the day moved from -2.16% to -1.75% over the books' three days).
Lesson: a bar saved by an earlier, unguarded run cannot be recognised afterwards, so after any run during market hours, strip that
day's last cache row before the evening run (the new guard keeps this from happening again).

## When Yahoo is unreachable the downloads came back empty and slowly (found 2026-10-22, breaker added the same day)

Right after the laptop woke, yfinance did not raise: it printed "possibly delisted" and returned an empty frame for every symbol, after
about 15 seconds of its own retrying each, so one step of the daily run could spend 15 minutes (a run over 450 symbols could spend two
hours) learning nothing. `data/loader.py` now counts long-range downloads (more than a year, which are never legitimately empty) that
come back empty; after five in a row it asks for the Nifty 50 index. If the index answers, the failures were bad tickers and the run carries on;
if not, it stops asking for five minutes and serves the cache as it is, then probes again. The prices are then older, which the health check's
price-data age and the web app's status strip show; nothing is invented, and the next run catches up. The daily task also now wakes the laptop
(on mains power) and may run for two hours. Tests: `tests/test_loader_breaker.py`.
