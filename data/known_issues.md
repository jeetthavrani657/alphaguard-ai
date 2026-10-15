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

- **Status: OPEN** (found by the web app smoke test; deliberately NOT fixed, see below)
- **Reviewed:** 2026-10-16
- **What happens:** `config.END_DATE` is `2025-12-31` and `data/loader.py` passes it
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
- **Proposed fix (needs the owner's decision, because it changes published
  numbers):** request `end + 1 day` from Yahoo in `_download_with_retry` /
  Case 3 of `load_price_data`, then clip to `end` as already done. Then re-run the
  Midcap/Smallcap work and update the affected figures in FINDINGS.md,
  MIDCAP_SMALLCAP_FINDINGS.md and MOMENTUM_FINDINGS.md.
- **Until then:** the web app's status strip shows the conservative
  "data through" date (the earliest across strategies: 2025-12-30), and every
  figure in the app is reproducible from the cache as it stands.
