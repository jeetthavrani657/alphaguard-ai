"""
data/refresh_cache.py -- re-download the price cache so every series is on ONE
adjustment basis and includes the last day of the research window.

    python data/refresh_cache.py                    # all three universes
    python data/refresh_cache.py --universe nifty50 # one of: nifty50, midcap150, smallcap250
    python data/refresh_cache.py --through 2025-12-31

Why this exists: Yahoo's adjusted prices are re-scaled retroactively whenever a
dividend goes ex. A cache built up from downloads made on different days mixes
bases, which shows up as a fake one-day move where two downloads meet (see
data/known_issues.md, "The last day of the research window is never
downloaded"). Re-downloading each symbol in one request removes the seams.

Safe to re-run. It changes cached prices (slightly: only by the retroactive
dividend adjustment), so results computed before and after can differ in the
second or third decimal of a Sharpe. Re-generate the web app's results after
running it:  python -m webapp.backend.snapshot

Per-symbol failures are reported and skipped, never fatal: a symbol that fails
keeps its previous cache.
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "data"))
sys.path.insert(0, ROOT)

import pandas as pd

import config
from loader import load_price_data

UNIVERSES = {
    "nifty50": lambda: config.UNIVERSE,
    "midcap150": lambda: config.MIDCAP150_UNIVERSE,
    "smallcap250": lambda: config.SMALLCAP250_UNIVERSE,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-download the price cache (one adjustment basis, inclusive end).")
    ap.add_argument("--universe", choices=[*UNIVERSES, "all"], default="all")
    ap.add_argument("--through", default=pd.Timestamp.today().strftime("%Y-%m-%d"),
                    help="last day to keep in the cache, inclusive (default: today)")
    args = ap.parse_args()

    keys = list(UNIVERSES) if args.universe == "all" else [args.universe]
    failed, done, t0 = [], 0, time.time()
    for key in keys:
        symbols = UNIVERSES[key]()
        print(f"[{key}] {len(symbols)} symbols, {config.START_DATE} -> {args.through}", flush=True)
        for i, sym in enumerate(symbols, 1):
            try:
                df = load_price_data(sym, config.START_DATE, args.through, force_refresh=True)
                done += 1
            except Exception as e:                      # keep going; the old cache for this symbol is untouched
                failed.append((key, sym, str(e)[:120]))
                continue
            if i % 25 == 0:
                print(f"  {i}/{len(symbols)}  (last: {sym} -> {df.index.max().date()})", flush=True)
    print(f"\nrefreshed {done} symbols in {time.time() - t0:.0f}s; {len(failed)} failed")
    for key, sym, why in failed:
        print(f"  FAILED [{key}] {sym}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
