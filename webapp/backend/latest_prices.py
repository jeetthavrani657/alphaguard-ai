"""
webapp/backend/latest_prices.py

The newest close of every stock the daily run keeps in data/cache/, written to webapp/snapshots/latest_prices.json for the web app to DISPLAY.

Why it exists: the research snapshot is computed on the backtest window (to 2025-12-31), so a stock's page said its price was ten months old while the daily run
already had last week's. This file carries only what a person looking at a stock wants to see (the latest close, its date, the day's change) and is kept apart
from every result: no backtest, status or strategy reads it. It is read from the cache and not validated like the research data, so a move that is too large to
trust is marked `suspect` and a stock whose newest bar is old is marked `stale`; the page shows both rather than hiding them.

    python -m webapp.backend.latest_prices      # rewrite webapp/snapshots/latest_prices.json (takes a few seconds; the daily run does it each evening)
"""

import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(ROOT, "data", "cache")
OUT_NAME = "latest_prices.json"
SUSPECT_MOVE_PCT = 25.0              # a one-day move beyond this is the validator's own "large move" line; it is shown with a warning, not trusted silently
STALE_AFTER_DAYS = 7                 # a newest bar this many days behind the freshest stock means the stock stopped updating (delisted, renamed, a failed download)


def last_two_closes(path: str):
    """(date, close, previous close or None) of the last row of one cache file, or None if the file has no usable close. Reads the whole small CSV, ignores bad rows."""
    import pandas as pd
    try:
        frame = pd.read_csv(path, usecols=["date", "close"], parse_dates=["date"])
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return None
    frame = frame.dropna(subset=["close"])
    frame = frame[frame["close"] > 0]
    if frame.empty:
        return None
    last = frame.iloc[-1]
    prev = float(frame.iloc[-2]["close"]) if len(frame) > 1 else None
    return last["date"], float(last["close"]), prev


def build(cache_dir: str = CACHE_DIR) -> dict:
    """{"as_of", "generated_at", "prices": {SYMBOL: {date, close, prev_close, change_pct, suspect, stale}}} for every *.NS.csv in `cache_dir`."""
    import pandas as pd
    found = {}
    for name in sorted(os.listdir(cache_dir)):
        if not name.endswith(".NS.csv"):
            continue
        got = last_two_closes(os.path.join(cache_dir, name))
        if got is not None:
            found[name[: -len(".NS.csv")]] = got
    if not found:
        return {"as_of": None, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prices": {}}
    as_of = max(d for d, _, _ in found.values())
    prices = {}
    for symbol, (d, close, prev) in found.items():
        change = 100.0 * (close / prev - 1.0) if prev else None
        prices[symbol] = {"date": d.strftime("%Y-%m-%d"), "close": round(close, 2), "prev_close": None if prev is None else round(prev, 2),
                          "change_pct": None if change is None else round(change, 2),
                          "suspect": change is not None and abs(change) > SUSPECT_MOVE_PCT,
                          "stale": (as_of - d).days > STALE_AFTER_DAYS}
    return {"as_of": as_of.strftime("%Y-%m-%d"), "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prices": prices}


def write(out_dir: str, cache_dir: str = CACHE_DIR) -> dict:
    data = build(cache_dir)
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, OUT_NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, allow_nan=False)                        # NaN would be invalid JSON: fail loudly, never write it
    os.replace(tmp, os.path.join(out_dir, OUT_NAME))
    return data


def main() -> int:
    out_dir = os.environ.get("WEBAPP_SNAPSHOT_DIR", os.path.join(ROOT, "webapp", "snapshots"))
    data = write(out_dir)
    n = len(data["prices"])
    print(f"[latest-prices] {n} stocks, newest close {data['as_of']}, "
          f"{sum(1 for p in data['prices'].values() if p['suspect'])} suspect, {sum(1 for p in data['prices'].values() if p['stale'])} stale -> {out_dir}")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
