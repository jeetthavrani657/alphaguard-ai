"""
research/compare_upstox_yfinance.py

Does Upstox's free daily data agree with the yfinance cache this project's research uses? Read-only:
it fetches daily candles (data/upstox_client.py) and compares them with data/cache/*.NS.csv. It
changes nothing in the cache or the research.

What matters, and how it is measured:
  * Prices can differ by a roughly constant factor because the two sources adjust for DIVIDENDS
    differently. That is harmless for returns, so the test is on daily RETURNS, not price levels.
  * A split or bonus that one source adjusts and the other does not shows up as ONE huge one-day
    return difference. That is the failure that would silently corrupt a backtest, so the largest
    return differences are listed with their dates.
  * Missing days on either side are counted.

Default symbols were chosen because they had splits or bonus issues inside 2015-2025.

    python research/compare_upstox_yfinance.py
    python research/compare_upstox_yfinance.py --symbols RELIANCE TCS --start 2018-01-01
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

import upstox_client

# companies with a split or bonus inside the window, so the adjustment question is actually tested
DEFAULT_SYMBOLS = ["RELIANCE", "HDFCBANK", "INFY", "TATASTEEL", "TCS", "ITC", "MARUTI", "ASIANPAINT"]
CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "cache")
SAVE_DIR = os.path.join(upstox_client.CACHE_DIR, "daily")
SMALL_DIFF, BIG_DIFF = 0.005, 0.05          # a daily-return gap of 0.5% / 5% between the two sources


def compare_one(up: pd.DataFrame, yf: pd.DataFrame) -> dict:
    """Pure comparison of two daily frames (index = date, column 'close'). Returns the numbers, prints nothing."""
    yf = yf.loc[up.index.min():up.index.max()]               # compare only the span Upstox was asked for (the cache runs to today)
    common = up.index.intersection(yf.index)
    only_up, only_yf = up.index.difference(yf.index), yf.index.difference(up.index)
    if len(common) < 30:
        return {"overlap_days": len(common), "error": "too little overlap to compare"}
    u, y = up.loc[common, "close"], yf.loc[common, "close"]
    ru, ry = u.pct_change().dropna(), y.pct_change().dropna()
    diff = (ru - ry).abs()
    ratio = u / y
    worst = diff.sort_values(ascending=False).head(3)
    return {
        "overlap_days": len(common), "days_only_in_upstox": len(only_up), "days_only_in_yfinance": len(only_yf),
        "first": common.min().date(), "last": common.max().date(),
        "ratio_first": float(ratio.iloc[0]), "ratio_last": float(ratio.iloc[-1]),
        "ratio_last_year_median": float(ratio.iloc[-250:].median()),
        "return_corr": float(ru.corr(ry)),
        "days_diff_over_small": int((diff > SMALL_DIFF).sum()), "days_diff_over_big": int((diff > BIG_DIFF).sum()),
        "worst": [(d.date(), float(ru[d]), float(ry[d])) for d in worst.index],
    }


def load_yfinance_cache(symbol: str) -> pd.DataFrame:
    path = os.path.join(CACHE_DIR, f"{symbol}.NS.csv")
    return pd.read_csv(path, index_col=0, parse_dates=True)


def verdict_line(r: dict) -> str:
    if "error" in r:
        return r["error"]
    if r["days_diff_over_big"] == 0:
        return "AGREES on every split/bonus-sized move (no daily-return gap over 5%)"
    return f"DIFFERS: {r['days_diff_over_big']} day(s) with a return gap over 5% (a split/bonus handled differently?)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare Upstox daily candles with the yfinance cache (read-only).")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    ap.add_argument("--start", default="2015-01-02")
    ap.add_argument("--end", default="2025-12-31")
    args = ap.parse_args(argv)

    instruments = upstox_client.load_instrument_map()
    os.makedirs(SAVE_DIR, exist_ok=True)
    for symbol in args.symbols:
        print(f"\n=== {symbol}")
        if symbol not in instruments:
            print("  not in Upstox's NSE equity list")
            continue
        try:
            up = upstox_client.fetch_symbol_daily(symbol, args.start, args.end, instruments)
            up.to_csv(os.path.join(SAVE_DIR, f"{symbol}.csv"))                 # kept (git-ignored) for the full download later
            r = compare_one(up, load_yfinance_cache(symbol))
        except (RuntimeError, FileNotFoundError, KeyError) as e:
            print(f"  could not compare: {e}")
            continue
        if "error" in r:
            print("  " + r["error"])
            continue
        print(f"  {len(up)} Upstox days vs overlap {r['overlap_days']} ({r['first']}..{r['last']}); "
              f"only in Upstox {r['days_only_in_upstox']}, only in yfinance {r['days_only_in_yfinance']}")
        print(f"  price ratio Upstox/yfinance: first {r['ratio_first']:.3f}, last {r['ratio_last']:.3f}, "
              f"last-year median {r['ratio_last_year_median']:.4f}   return correlation {r['return_corr']:.5f}")
        print(f"  days with a return gap > 0.5%: {r['days_diff_over_small']};  > 5%: {r['days_diff_over_big']}")
        for d, ru, ry in r["worst"]:
            print(f"    largest gap {d}: Upstox {ru:+.2%} vs yfinance {ry:+.2%}")
        print("  -> " + verdict_line(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
