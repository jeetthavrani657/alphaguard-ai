"""
data/intraday.py

Intraday (minute) candles for NSE equities, from the read-only Upstox client (data/upstox_client.py): research data only.

Daily Yahoo prices stay the project's main data. This module exists so that an intraday engine can be built on data that has gone through
the same kind of checks as everything else:

  * a cache per symbol and candle size (data/intraday/, git-ignored);
  * ONE basis per series: Upstox adjusts history for splits and bonuses, so extending the cache must not splice two bases. A tail
    extension re-downloads a few overlapping days and compares them with the cache; if they disagree, the whole range is downloaded again;
    a head extension always re-downloads the whole range;
  * never today's half-finished session: a candle dated after the last COMPLETE session (16:00 India time) is dropped, as in data/loader.py;
  * impossible candles (non-positive price, high below low, a time outside the 09:15 to 15:30 session) are dropped and counted, never kept;
  * a validation report per series: candles per day against a full session, and single-candle jumps that need a look.

History available from Upstox starts around January 2022 for minute data (checked 2026-10-23 back to February 2022).
"""

import os
from datetime import datetime, time as dtime, timedelta, timezone

import pandas as pd

import upstox_client
from upstox_tail import expected_last_session

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intraday")
SESSION_OPEN = dtime(9, 15)
SESSION_CLOSE = dtime(15, 30)                    # the last candle STARTS before this
SESSION_MINUTES = 375                            # 09:15 to 15:30
OVERLAP_DAYS = 4                                 # days re-downloaded on a tail extension, to check the basis has not changed
BASIS_TOLERANCE = 0.005                          # the overlap may differ by this much (0.5%) before the whole range is downloaded again
JUMP_LIMIT = 0.20                                # a single candle moving more than this is flagged for a look
COLUMNS = ["open", "high", "low", "close", "volume"]


def _cache_path(symbol: str, interval_minutes: int) -> str:
    return os.path.join(CACHE_DIR, f"{symbol.removesuffix('.NS').upper()}_{int(interval_minutes)}m.csv")


def _ns(frame: pd.DataFrame) -> pd.DataFrame:
    """The same candles with a nanosecond index, so a frame read from the cache and one just downloaded have the same type."""
    out = frame.copy()
    out.index = pd.DatetimeIndex(out.index).astype("datetime64[ns]")
    out.index.name = "time"
    return out


def _read_cache(path: str) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    frame = pd.read_csv(path, index_col=0, parse_dates=True, float_precision="round_trip")      # exact floats: what was saved is what comes back
    return _ns(frame) if not frame.empty else None


def clean_candles(frame: pd.DataFrame) -> tuple:
    """(clean frame, number of candles dropped). Drops impossible candles; the caller reports the count."""
    if frame.empty:
        return frame, 0
    t = frame.index.time
    in_session = pd.Series([SESSION_OPEN <= x < SESSION_CLOSE for x in t], index=frame.index)
    prices = frame[["open", "high", "low", "close"]]
    possible = ((prices > 0).all(axis=1) & (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
                & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)) & (frame["volume"] >= 0))
    keep = in_session & possible
    return frame[keep], int((~keep).sum())


def validate_intraday(frame: pd.DataFrame, interval_minutes: int) -> dict:
    """Report on a clean series: how many days, which days are short of a full session, and which candles jump more than JUMP_LIMIT."""
    if frame.empty:
        return {"n_candles": 0, "n_days": 0, "short_days": [], "jumps": []}
    per_day = frame.groupby(frame.index.normalize()).size()
    full = SESSION_MINUTES // int(interval_minutes)
    short = per_day[per_day < 0.9 * full]
    change = frame["close"].pct_change().abs()
    same_day = frame.index.normalize().to_series().diff().dt.days.fillna(0).eq(0).to_numpy()     # a gap between sessions is not a candle jump
    jumps = frame.index[(change > JUMP_LIMIT).to_numpy() & same_day]
    return {"n_candles": int(len(frame)), "n_days": int(len(per_day)), "full_session_candles": int(full),
            "short_days": [{"date": d.strftime("%Y-%m-%d"), "candles": int(n)} for d, n in short.items()],
            "jumps": [ts.strftime("%Y-%m-%d %H:%M") for ts in jumps]}


def _overlap_agrees(cached: pd.DataFrame, fresh: pd.DataFrame) -> bool:
    """True if the candles both frames hold agree to within BASIS_TOLERANCE (no adjustment has re-scaled history in between)."""
    both = cached.index.intersection(fresh.index)
    if len(both) == 0:
        return True                                                  # nothing to compare: the safe reading is that the basis is unchanged
    ratio = (fresh.loc[both, "close"] / cached.loc[both, "close"]).abs()
    return bool(((ratio - 1.0).abs() <= BASIS_TOLERANCE).all())


def load_intraday(symbol: str, interval_minutes: int, start: str, end: str, fetch=None, now: datetime | None = None) -> pd.DataFrame:
    """
    Intraday candles for one NSE symbol from `start` to `end` inclusive (YYYY-MM-DD), complete sessions only.
    `fetch(symbol, interval_minutes, start, end) -> DataFrame` defaults to the read-only Upstox client; tests pass a fake.
    """
    fetch = fetch or upstox_client.fetch_symbol_intraday
    now = now or datetime.now(timezone.utc)
    last_complete = expected_last_session(now)
    end_ts = min(pd.Timestamp(end).normalize(), last_complete)
    start_ts = pd.Timestamp(start).normalize()
    if start_ts > end_ts:
        raise ValueError(f"nothing to load: {start} is after the last complete session ({end_ts.date()})")
    path = _cache_path(symbol, interval_minutes)
    cached = _read_cache(path)
    if cached is not None:
        cached = cached[cached.index.normalize() <= last_complete]    # a half-finished session saved by an earlier run is not trusted

    def download(a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        raw = fetch(symbol, int(interval_minutes), a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"))
        clean, dropped = clean_candles(_ns(raw[COLUMNS]))
        if dropped:
            print(f"[intraday] {symbol}: dropped {dropped} impossible or out-of-session candle(s)")
        return clean[clean.index.normalize() <= last_complete]

    if cached is None or start_ts < cached.index.min().normalize() - pd.Timedelta(days=5):
        combined = download(start_ts, end_ts)                         # no cache, or the cache starts later than wanted: one download, one basis
    elif end_ts > cached.index.max().normalize():
        redo_from = max(cached.index.max().normalize() - pd.Timedelta(days=OVERLAP_DAYS), start_ts)
        fresh = download(redo_from, end_ts)
        if _overlap_agrees(cached, fresh):
            combined = pd.concat([cached[cached.index < fresh.index.min()] if len(fresh) else cached, fresh])
        else:
            print(f"[intraday] {symbol}: history was re-scaled (a split or bonus); downloading the whole range again")
            combined = download(min(start_ts, cached.index.min().normalize()), end_ts)
    else:
        combined = cached
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    os.makedirs(CACHE_DIR, exist_ok=True)
    combined.to_csv(path)
    return combined[(combined.index.normalize() >= start_ts) & (combined.index.normalize() <= end_ts)].copy()
