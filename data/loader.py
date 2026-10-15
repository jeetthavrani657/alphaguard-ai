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
from pathlib import Path

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2
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


def _download_with_retry(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Call yfinance with retry + exponential backoff on rate limiting or
    other transient errors. Raises loudly if all retries are exhausted --
    it never fails silently.
    """
    backoff = INITIAL_BACKOFF_SECONDS
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return yf.download(
                symbol,
                start=start,
                end=end,
                auto_adjust=True,        # split & dividend adjusted prices
                progress=False,
                multi_level_index=False,  # flat columns, even for one ticker
            )
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

    raise RuntimeError(
        f"Failed to download data for {symbol} after {MAX_RETRIES} attempts. "
        f"This may mean Yahoo Finance is rate-limiting or unreachable. "
        f"Last error: {last_error}"
    )


def load_price_data(symbol: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Load daily OHLCV data for one NSE stock, using a local CSV cache.

    symbol : NSE ticker, with or without the ".NS" suffix, e.g. "RELIANCE"
    start, end : date strings "YYYY-MM-DD"
    force_refresh : if True, ignore the cache and re-download from scratch

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

    cached = None if force_refresh else _load_cache(symbol)

    # Case 1: cache already fully covers the requested window -- no network call.
    if cached is not None and not cached.empty:
        if cached.index.min() <= start_ts and cached.index.max() >= end_ts:
            return cached.loc[start_ts:end_ts].copy()

    # Case 2: nothing usable cached (or force_refresh) -- download the full range.
    if cached is None or cached.empty or force_refresh:
        fresh = _download_with_retry(symbol, start, end)
        if fresh.empty:
            raise ValueError(
                f"No data returned for '{symbol}' between {start} and {end}. "
                f"This usually means the symbol is invalid, delisted, or has "
                f"no trading history in this range."
            )
        combined = _clean_columns(fresh)

    # Case 3: cache exists but doesn't fully cover the request -- fetch only
    # the missing head/tail portions instead of re-downloading everything.
    else:
        pieces = [cached]
        if start_ts < cached.index.min():
            head = _download_with_retry(symbol, start, str(cached.index.min().date()))
            if not head.empty:
                pieces.append(_clean_columns(head))
        if end_ts > cached.index.max():
            tail_start = str((cached.index.max() + pd.Timedelta(days=1)).date())
            tail = _download_with_retry(symbol, tail_start, end)
            if not tail.empty:
                pieces.append(_clean_columns(tail))
        combined = pd.concat(pieces)
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()

    combined = _drop_phantom_rows(combined)

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
