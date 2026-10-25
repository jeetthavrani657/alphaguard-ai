"""
data/refresh_display.py

Keeps the web app's stock pages fresh for stocks the daily run does not otherwise update (the Midcap 150 and Smallcap 250 lists), WITHOUT touching the research cache.

Why a separate store: data/loader.py never splices a new tail onto old history (the prices are re-scaled retroactively when a dividend goes ex, so a spliced tail shows a fake
one-day move). To add a few new days it re-downloads the whole history and replaces the cache, and that changes the cached prices a little, so every result already worked out
on them (Sharpe ratios in the second or third decimal) would no longer match the cache until all results are regenerated. For a display that is the wrong trade. So this writes
a SHORT recent history (about four months) into data/display_cache/, which only webapp/backend/latest_prices.py reads, for DISPLAY: no backtest, status or gate ever sees it.

    python data/refresh_display.py                      # every stock whose research cache is more than 5 days behind the freshest
    python data/refresh_display.py --universe midcap150 # only one list
    python data/refresh_display.py --all                # every stock of the chosen lists, stale or not

Per-stock failures are reported and skipped, never fatal; a stock that fails keeps whatever display file it had. The exit code is 0 unless nothing at all could be downloaded.
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data"))
sys.path.insert(0, ROOT)

import pandas as pd

CACHE_DIR = os.path.join(ROOT, "data", "cache")
DISPLAY_DIR = os.path.join(ROOT, "data", "display_cache")
STALE_AFTER_DAYS = 5               # a research-cache bar this many days behind the freshest stock counts as not being kept up
HISTORY_DAYS = 130                 # about four months of calendar days: enough for a 60-day line and a one-month change
MIN_ROWS = 22                      # fewer usable rows than this is not worth showing (a one-month change needs 22)
PAUSE_SECONDS = 0.5                # a short pause between requests, so a list of 150 is not a burst


def newest_date(path: str):
    """The date of the last usable row of a cache file, or None."""
    try:
        frame = pd.read_csv(path, usecols=["date", "close"], parse_dates=["date"]).dropna(subset=["close"])
    except (OSError, ValueError, pd.errors.EmptyDataError):
        return None
    frame = frame[frame["close"] > 0]
    return None if frame.empty else frame["date"].max()


def stale_symbols(symbols: list, cache_dir: str = CACHE_DIR, max_age_days: int = STALE_AFTER_DAYS, everything: bool = False) -> list:
    """The symbols whose research-cache newest bar is more than `max_age_days` behind the freshest one among `symbols` (or all of them when `everything`); no file counts as stale."""
    newest = {s: newest_date(os.path.join(cache_dir, f"{s}.NS.csv")) for s in symbols}
    known = [d for d in newest.values() if d is not None]
    if everything or not known:
        return list(symbols)
    freshest = max(known)
    return [s for s, d in newest.items() if d is None or (freshest - d).days > max_age_days]


def refresh(symbols: list, out_dir: str = DISPLAY_DIR, today: pd.Timestamp | None = None, fetch=None, pause: float = PAUSE_SECONDS) -> dict:
    """
    Download about four months of prices for each symbol into `out_dir` as SYMBOL.NS.csv. `fetch(symbol, start, end)` returns a frame (default: the loader's own downloader, with its retries and
    its Yahoo-unreachable breaker). Returns {"written": [...], "failed": [(symbol, reason)], "newest": date or None}.
    """
    import loader
    fetch = fetch or loader._download_with_retry
    today = today or pd.Timestamp.today().normalize()
    start, end = today - pd.Timedelta(days=HISTORY_DAYS), today + pd.Timedelta(days=1)       # yfinance's end is exclusive
    os.makedirs(out_dir, exist_ok=True)
    written, failed, newest = [], [], None
    for i, sym in enumerate(symbols):
        try:
            frame = loader._drop_incomplete_today(loader._drop_phantom_rows(loader._clean_columns(fetch(f"{sym}.NS", str(start.date()), str(end.date())))))
        except Exception as e:                       # one stock failing never stops the rest
            failed.append((sym, str(e)[:120]))
            continue
        if frame is None or len(frame) < MIN_ROWS:
            failed.append((sym, f"only {0 if frame is None else len(frame)} usable rows"))
            continue
        tmp = os.path.join(out_dir, f"{sym}.NS.csv.tmp")
        frame.to_csv(tmp, index_label="date")
        os.replace(tmp, os.path.join(out_dir, f"{sym}.NS.csv"))
        written.append(sym)
        last = frame.index.max()
        newest = last if newest is None or last > newest else newest
        if pause and i + 1 < len(symbols):
            time.sleep(pause)
    return {"written": written, "failed": failed, "newest": newest}


def main() -> int:
    import config
    lists = {"midcap150": config.MIDCAP150_UNIVERSE, "smallcap250": config.SMALLCAP250_UNIVERSE, "nifty50": config.UNIVERSE}
    ap = argparse.ArgumentParser(description="Refresh the display-only price store for stocks the daily run does not update.")
    ap.add_argument("--universe", choices=[*lists, "all"], default="all")
    ap.add_argument("--all", action="store_true", help="every stock of the chosen lists, not only the stale ones")
    args = ap.parse_args()
    chosen = list(lists) if args.universe == "all" else [args.universe]
    symbols = sorted({s for k in chosen for s in lists[k]})
    todo = stale_symbols(symbols, everything=args.all)
    print(f"[display] {len(todo)} of {len(symbols)} stocks to refresh ({'all' if args.all else 'research cache more than ' + str(STALE_AFTER_DAYS) + ' days behind'})", flush=True)
    if not todo:
        return 0
    t0 = time.time()
    done = refresh(todo)
    print(f"[display] wrote {len(done['written'])}, {len(done['failed'])} failed, newest bar {done['newest'].date() if done['newest'] is not None else None}, {time.time() - t0:.0f}s -> {DISPLAY_DIR}")
    for sym, why in done["failed"][:15]:
        print(f"  FAILED {sym}: {why}")
    return 0 if done["written"] else 1


if __name__ == "__main__":
    sys.exit(main())
