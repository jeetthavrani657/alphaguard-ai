"""
research/backfill_fo.py

Downloads the exchange's published end-of-day F&O files (data/fo_bhavcopy.py) month by month, from a start date to today, and keeps index futures, index
options and stock futures. Safe to stop and restart: days already stored are skipped, and holidays are remembered. About one request a second.

    python research/backfill_fo.py                  # from 2022-01-03 to today
    python research/backfill_fo.py 2024-01-01       # from a chosen start
    python research/backfill_fo.py 2024-04-01 2024-12-31   # between two dates (several runs can cover different months at once)
"""

import os
import sys
from datetime import date, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))

import fo_bhavcopy as fo


def month_ranges(start: date, end: date):
    """(first, last) of each calendar month from start's month to end's month, clipped to start..end."""
    cursor = start
    while cursor <= end:
        nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)       # the first of the next month
        yield cursor, min(nxt - timedelta(days=1), end)
        cursor = nxt


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    start = date.fromisoformat(argv[0]) if argv else date(2022, 1, 3)
    end = date.fromisoformat(argv[1]) if len(argv) > 1 else date.today()
    total = {"downloaded": 0, "no_file": 0, "problems": 0}
    for a, b in month_ranges(start, end):
        s = fo.update_range(a.isoformat(), b.isoformat())
        total["downloaded"] += len(s["downloaded"])
        total["no_file"] += len(s["no_file"])
        total["problems"] += len(s["checked_with_problems"])
        extra = f"  PROBLEMS on {sorted(s['checked_with_problems'])}" if s["checked_with_problems"] else ""
        print(f"[fo] {a:%Y-%m}: downloaded {len(s['downloaded'])}, already stored {s['already_stored']}, no file {len(s['no_file'])}{extra}", flush=True)
    print(f"[fo] done: {total['downloaded']} days downloaded, {total['no_file']} days without a file, {total['problems']} days with hard problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
