"""
data/loader.py

Downloads and locally caches daily OHLCV (Open/High/Low/Close/Volume)
price data for NSE (India) listed stocks using yfinance.

Verified against yfinance 1.6.0 (see requirements.txt) on 2026-09-02:
- multi_level_index=False makes yf.download() return flat columns
  (Open, High, Low, Close, Volume) even for a single ticker -- no
  manual MultiIndex flattening needed.
- An invalid/delisted symbol does NOT raise an error -- it returns an
  EMPTY DataFrame. This is the main failure mode we guard against below.
- Rate limiting raises yfinance.exceptions.YFRateLimitError (HTTP 429).
"""

import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# An optional second source for the LATEST sessions only (see set_tail_source). None means yfinance alone, which is
# what every backtest and every test uses; only the daily forward run switches it on.
_TAIL_SOURCE = [None]

MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2

# Circuit breaker. When Yahoo is unreachable (found 2026-10-22, right after the laptop woke), yfinance does not raise: it prints
# "possibly delisted" and returns an empty frame, after about 15 seconds of its own retrying PER SYMBOL, so a run over 450 symbols
# could take two hours to learn nothing. A download that spans more than a year is never legitimately empty, so
# BREAKER_AFTER of them in a row mean the source is down: stop asking for BREAKER_COOLDOWN_SECONDS and serve the cache, then probe again.
# The cache is served as it is (the health check's price-data age shows the lag); nothing is invented.
BREAKER_AFTER = 5
BREAKER_COOLDOWN_SECONDS = 300
LONG_RANGE_DAYS = 365
_BREAKER = {"failures": 0, "open_until": 0.0}
_EMPTY = ["Open", "High", "Low", "Close", "Volume"]
COLUMNS = ["open", "high", "low", "close", "volume"]


def _normalize_symbol(symbol: str) -> str:
    """
    Append the NSE '.NS' suffix if the caller didn't already include it.
    Index tickers (Yahoo's fixed, permanent "^" prefix convention, e.g.
    "^NSEI" for Nifty 50) are passed through unchanged -- this is a
    stable ticker-syntax rule, not a maintained per-symbol mapping, so
    it doesn't reintroduce the alias-database problem from Stage 1.
    """
    symbol = symbol.strip().upper()
    if symbol.startswith("^") or symbol.endswith(".NS"):
        return symbol
    return symbol + ".NS"


def set_tail_source(source) -> None:
    """
    Register (or, with None, remove) a function `source(symbol, start, end) -> DataFrame` that supplies the newest sessions
    yfinance has not priced yet. Used only by the daily forward run, with the read-only Upstox client (data/upstox_tail.py),
    so that a day Yahoo publishes late does not hold the forward tests back. Rows it returns go through the same
    cleaning as Yahoo's, are saved to the cache, and are replaced by Yahoo's own value as soon as Yahoo prices that day.
    """
    _TAIL_SOURCE[0] = source


def _tail_rows(symbol: str, combined: pd.DataFrame, end_ts: pd.Timestamp) -> pd.DataFrame:
    """Rows after the newest priced Yahoo day, from the registered tail source; empty when there is none, or on any failure."""
    source = _TAIL_SOURCE[0]
    if source is None or combined.empty or end_ts <= combined.index.max():
        return combined.iloc[0:0]
    try:
        rows = source(symbol, combined.index.max() + pd.Timedelta(days=1), end_ts)
    except Exception as e:                       # the second source is an extra: its failure must never break the primary load
        print(f"[loader] tail source failed for {symbol}: {str(e)[:80]}")
        return combined.iloc[0:0]
    if rows is None or rows.empty:
        return combined.iloc[0:0]
    rows = _drop_phantom_rows(rows[COLUMNS].astype(float))
    rows = rows[(rows[["open", "high", "low", "close"]] > 0).all(axis=1) & (rows["high"] >= rows["low"])]      # a priceless or impossible bar is never kept
    rows = rows[(rows.index > combined.index.max()) & (rows.index <= end_ts)]
    rows.index.name = "date"
    return rows


IST = timezone(timedelta(hours=5, minutes=30))     # NSE sessions are dated in Indian time
SESSION_COMPLETE_IST = dtime(16, 0)                # the session ends 15:30; give the vendors until 16:00 to settle the day


def _now_utc() -> datetime:
    """The current time. A separate function so a test can pretend it is a different hour."""
    return datetime.now(timezone.utc)


def _drop_incomplete_today(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove today's bar while the session is still running (before 16:00 IST). Yahoo serves a live, half-finished bar for
    today during market hours; kept, it would be cached and logged as if it were the day's close (found 2026-10-22, when
    a catch-up run at noon counted a partial day in the forward books). Applied to downloads AND to the cache.
    """
    if df is None or df.empty:
        return df
    ist_now = _now_utc().astimezone(IST)
    if ist_now.time() >= SESSION_COMPLETE_IST:
        return df
    return df[df.index < pd.Timestamp(ist_now.date())]     # keep only days strictly before today's IST date


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}.csv"


def _load_cache(symbol: str) -> pd.DataFrame | None:
    """Read the cached CSV for a symbol, or None if nothing is cached yet."""
    path = _cache_path(symbol)
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col="date", parse_dates=True)
    df.index.name = "date"
    return df


def _save_cache(symbol: str, df: pd.DataFrame) -> None:
    df.to_csv(_cache_path(symbol), index_label="date")


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case column names and keep only the OHLCV columns we care about."""
    # Defensive check: multi_level_index=False should already prevent this,
    # but flatten anyway in case a future yfinance version changes behaviour.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    df.columns.name = None
    df.index.name = "date"
    return df[COLUMNS]


def _drop_phantom_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop rows matching the exact fingerprint of a Yahoo data artifact seen
    on 2025-03-18 (RELIANCE.NS, TMPV.NS, YESBANK.NS, IDEA.NS all affected
    identically that day -- confirmed NOT an NSE holiday, see
    data/known_issues.md): zero volume, with open/high/low/close all equal
    to each other AND equal to the prior day's close. A real NSE holiday
    produces a MISSING row, not a present one -- so this only ever removes
    rows where literally nothing happened, never a real (if quiet) trading
    day. Applied generically (by pattern, not by hardcoded date) so it
    also catches the same artifact on other symbols/dates without needing
    a maintained list.
    """
    prior_close = df["close"].shift()
    flat_ohlc = (df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])
    carried_forward = df["close"] == prior_close
    is_phantom = (df["volume"] == 0) & flat_ohlc & carried_forward

    # Second artifact class, found 2026-10-16 when the cache was first
    # extended to the present: Yahoo returns the CURRENT, still-forming
    # session as a row with a volume but NaN open/high/low/close. A
    # priceless row can never be traded or marked, and left in it turns
    # the last day's portfolio equity into NaN -- so it is dropped here,
    # like the phantom row above. (The validator separately flags NaN
    # prices as a hard failure, but nothing downstream acted on that.)
    has_nan_price = df[["open", "high", "low", "close"]].isna().any(axis=1)

    return df[~(is_phantom | has_nan_price)]


CANARY_SYMBOL = "^NSEI"                      # the Nifty 50 index: always listed, so an empty answer means the source is down


def _yahoo_answers() -> bool:
    """One small request for the canary. Any failure counts as 'not answering'."""
    try:
        return not yf.download(CANARY_SYMBOL, period="5d", progress=False, multi_level_index=False).empty
    except Exception:
        return False


def _record_download(failed: bool) -> None:
    """Count a failed long-range download, open the breaker after BREAKER_AFTER in a row, and reset the count on any success."""
    if not failed:
        _BREAKER["failures"] = 0
        return
    _BREAKER["failures"] += 1
    if _BREAKER["failures"] >= BREAKER_AFTER:
        _BREAKER["failures"] = 0
        if _yahoo_answers():                    # the index came back: these were bad tickers, not a dead source
            print(f"[loader] {BREAKER_AFTER} downloads in a row came back empty, but Yahoo answers for the index: carrying on.")
            return
        _BREAKER["open_until"] = time.monotonic() + BREAKER_COOLDOWN_SECONDS
        print(f"[loader] {BREAKER_AFTER} downloads in a row came back empty: Yahoo looks unreachable. "
              f"No more requests for {BREAKER_COOLDOWN_SECONDS // 60} minutes; cached prices are served as they are.")


def _download_with_retry(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Call yfinance with retry + exponential backoff on rate limiting or
    other transient errors. Raises loudly if all retries are exhausted --
    it never fails silently.

    `end` is passed straight to yfinance, which treats it as EXCLUSIVE. Callers
    that mean "up to and including day D" must pass D + 1 day
    (load_price_data does).
    """
    if time.monotonic() < _BREAKER["open_until"]:
        print(f"[loader] Yahoo looks unreachable: not asking for {symbol} (the cache is served as it is).")
        return pd.DataFrame(columns=_EMPTY)

    long_range = (pd.Timestamp(end) - pd.Timestamp(start)).days > LONG_RANGE_DAYS
    backoff = INITIAL_BACKOFF_SECONDS
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            frame = yf.download(
                symbol,
                start=start,
                end=end,
                auto_adjust=True,        # split & dividend adjusted prices
                progress=False,
                multi_level_index=False,  # flat columns, even for one ticker
            )
            _record_download(failed=long_range and frame.empty)
            return frame
        except YFRateLimitError as e:
            last_error = e
            print(f"[loader] Rate limited fetching {symbol} "
                  f"(attempt {attempt}/{MAX_RETRIES}). Waiting {backoff}s...")
        except Exception as e:
            last_error = e
            print(f"[loader] Error fetching {symbol} "
                  f"(attempt {attempt}/{MAX_RETRIES}): {e}. Waiting {backoff}s...")

        if attempt < MAX_RETRIES:
            time.sleep(backoff)
            backoff *= 2

    _record_download(failed=True)
    raise RuntimeError(
        f"Failed to download data for {symbol} after {MAX_RETRIES} attempts. "
        f"This may mean Yahoo Finance is rate-limiting or unreachable. "
        f"Last error: {last_error}"
    )


def load_price_data(symbol: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Load daily OHLCV data for one NSE stock, using a local CSV cache.

    symbol : NSE ticker, with or without the ".NS" suffix, e.g. "RELIANCE"
    start, end : date strings "YYYY-MM-DD"; `end` is INCLUSIVE (the bar dated
        `end` is returned if it exists)
    force_refresh : if True, ignore the cache and re-download from scratch

    Cost note: whenever the cache does not already reach `start`..`end`, the
    whole range is downloaded again (see Case 2 below for why). Two situations
    make that happen on every call: a window ending on a day with no bar
    (weekend or exchange holiday), and a stock that listed after `start`.
    Both cost one request per symbol per call, the same count as before.

    Returns a DataFrame indexed by date (DatetimeIndex) with columns:
    open, high, low, close, volume

    Raises ValueError if the symbol is invalid/delisted or the requested
    range has no data at all (yfinance's own failure mode here is to
    silently return an empty frame -- we catch that and raise instead).
    """
    symbol = _normalize_symbol(symbol)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    if start_ts > end_ts:
        raise ValueError(f"start ({start}) is after end ({end}).")

    existing = _drop_incomplete_today(_load_cache(symbol))   # what is on disk, even when force_refresh ignores it for coverage
    cached = None if force_refresh else existing
    have_cache = cached is not None and not cached.empty

    # Case 1: cache already fully covers the requested window -- no network call.
    if have_cache and cached.index.min() <= start_ts and cached.index.max() >= end_ts:
        return cached.loc[start_ts:end_ts].copy()

    # Case 2: the cache is missing or does not reach the whole window. Download ONE
    # contiguous range and REPLACE the cache with it -- never splice a new piece onto
    # old history.
    #
    # Why not just fetch the missing head/tail (what this function used to do):
    # Yahoo's adjusted prices are re-scaled retroactively every time a dividend or
    # split goes ex. A tail downloaded today is on today's adjustment basis, the
    # history cached last month is on last month's, so the join shows a fake one-day
    # move for every stock that paid a dividend in between (found on the Nifty 50
    # cache: COALINDIA -1.25%, TCS -0.53% on 2025-12-31). One download = one basis.
    #
    # The range requested is the union of what the caller wants and what we already
    # hold, so extending never shrinks the cache.
    if have_cache:
        fetch_start = min(start_ts, cached.index.min())
        fetch_end = max(end_ts, cached.index.max())
    else:
        fetch_start, fetch_end = start_ts, end_ts

    # yfinance's `end` is EXCLUSIVE: end="2025-12-31" returns bars only up to 2025-12-30.
    # Ask for the day after, so the last day the caller named is actually downloaded.
    fresh = _download_with_retry(
        symbol, str(fetch_start.date()), str((fetch_end + pd.Timedelta(days=1)).date())
    )

    if fresh.empty:
        # Nothing came back (e.g. the extension range holds no new trading day). Keep
        # what is cached rather than wiping it, and serve the window from it.
        if have_cache:
            held = cached.loc[start_ts:end_ts]
            if not held.empty:
                return held.copy()
        raise ValueError(
            f"No data returned for '{symbol}' between {start} and {end}. "
            f"This usually means the symbol is invalid, delisted, or has "
            f"no trading history in this range."
        )

    combined = _drop_incomplete_today(_drop_phantom_rows(_clean_columns(fresh)))

    # Yahoo can list the newest session with a volume but no prices for hours after the close, and the line above drops
    # that row. If the cache already held that day (from an earlier download that had provisional prices), replacing
    # the cache would delete a real session and set every forward test back a day (found 2026-10-20). So cached rows
    # LATER than the newest priced row of the fresh download are kept; once Yahoo prices that day, the fresh row wins.
    if existing is not None and not existing.empty and not combined.empty:
        later = existing.loc[existing.index > combined.index.max()]
        if not later.empty:
            combined = pd.concat([combined, later])

    # Vendor-truncation guard. Replacing the cache is only safe if the new download is
    # at least as deep as what we hold. Yahoo sometimes re-lists a ticker and then serves
    # only the history since the re-listing (found: HEG.NS began 2026-07-17 on a refresh,
    # which would have discarded 2,714 rows of 2015-2025). If we held data right at the
    # start of the range we asked for and the download no longer has it, keep the cache.
    if existing is not None and not existing.empty and not combined.empty:
        near_start = fetch_start + pd.Timedelta(days=30)
        if existing.index.min() <= near_start and combined.index.min() > near_start:
            print(f"[loader] WARNING {symbol}: Yahoo returned history starting "
                  f"{combined.index.min().date()}, but the cache starts {existing.index.min().date()}. "
                  f"Treating this as a vendor truncation and KEEPING the cache.")
            held = existing.loc[start_ts:end_ts]
            if held.empty:
                raise ValueError(f"No data available for '{symbol}' between {start} and {end}.")
            return held.copy()

    extra = _tail_rows(symbol, combined, end_ts)
    if not extra.empty:
        combined = pd.concat([combined, extra])

    result = combined.loc[start_ts:end_ts].copy()
    if result.empty:
        raise ValueError(
            f"No data available for '{symbol}' between {start} and {end}, "
            f"even after fetching (e.g. the range may fall entirely on "
            f"non-trading days)."
        )

    _save_cache(symbol, combined)
    return result


if __name__ == "__main__":
    # Quick manual smoke test.
    df = load_price_data("RELIANCE", "2024-01-01", "2024-01-31")
    print(df.head())
    print(f"\nRows: {len(df)}")
