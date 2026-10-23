"""
research/options_vol.py

STEP 0 of OPTIONS_IDEAS.md: a description, not a hypothesis. How does the Nifty's IMPLIED volatility (what the options priced in, 30 days out) compare with the
volatility that REALLY followed? The difference is the variance risk premium that the short-premium rules try to collect. This registers nothing and changes no status.

  implied_30d(day)  : the at-the-money implied volatility interpolated, in total variance, between the listed expiries on either side of 30 calendar days.
  realised_30d(day) : the annualised standard deviation of the Nifty's daily log returns over the NEXT 30 calendar days.
  premium(day)      : implied - realised (in volatility points). Positive means options were dear.

Pure functions of the option table and a spot series; the runner at the bottom reads the stored F&O data.
"""

import math
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd

import options_backtest as ob
import options_chain as ch
import options_math as om

TARGET_DAYS = 30
TRADING_DAYS = 252


def atm_iv(book: dict, day, expiry, rate: float) -> tuple:
    """(atm implied volatility, years to expiry) for one expiry on one day: the strike-interpolated volatility at the forward. NaN if there is no chain."""
    g = book.get((day, expiry))
    if g is None:
        return float("nan"), float("nan")
    table, forward, t = ch.with_greeks(ch.chain(g, "NIFTY", expiry), day, expiry, rate)
    usable = table["iv"].dropna()
    if not math.isfinite(forward) or len(usable) < 2:
        return float("nan"), t
    strikes, ivs = usable.index.to_numpy(), usable.to_numpy()
    if forward < strikes.min() or forward > strikes.max():
        return float("nan"), t
    return float(np.interp(forward, strikes, ivs)), t


def implied_30d(book: dict, day, rate: float, expiries_by_day: dict) -> float:
    """
    The 30-day constant-maturity implied volatility: take the nearest listed expiry at or below 30 days and the nearest above, and interpolate TOTAL variance
    (volatility squared times time) linearly in time, as is usual. NaN unless both sides exist.
    """
    exps = expiries_by_day.get(day, [])
    pts = []
    for e in exps:
        if not 2 <= (e - day).days <= 90:                           # only expiries that can bracket 30 days matter; skip the long-dated ones (a lot of work for nothing)
            continue
        iv, t = atm_iv(book, day, e, rate)
        if math.isfinite(iv) and t > 0:
            pts.append((t, iv))
    below = [p for p in pts if p[0] * 365.0 <= TARGET_DAYS and p[0] * 365.0 >= 2]
    above = [p for p in pts if p[0] * 365.0 > TARGET_DAYS]
    if not below or not above:
        return float("nan")
    t1, v1 = max(below)                                              # the nearest from below: the largest t
    t2, v2 = min(above)                                              # the nearest from above: the smallest t
    target = TARGET_DAYS / 365.0
    w1, w2 = v1 * v1 * t1, v2 * v2 * t2
    w = w1 + (w2 - w1) * (target - t1) / (t2 - t1)
    return float(math.sqrt(w / target)) if w > 0 else float("nan")


def realised_30d(spot: pd.Series, day, min_obs: int = 15) -> float:
    """Annualised volatility of the daily log returns over the 30 calendar days AFTER `day`; NaN if the spot series is too short there."""
    window = spot.loc[(spot.index > day) & (spot.index <= day + pd.Timedelta(days=TARGET_DAYS))]
    base = spot.loc[:day]
    if len(window) < min_obs or base.empty:
        return float("nan")
    path = pd.concat([base.iloc[[-1]], window])                      # include the starting level so the first return is from `day`'s close
    return float(np.log(path).diff().dropna().std(ddof=1) * math.sqrt(TRADING_DAYS))


def premium_table(book: dict, spot: pd.Series, rate: float = ob.DISCOUNT_RATE) -> pd.DataFrame:
    """One row per trading day: implied_30d, realised_30d and their difference."""
    expiries_by_day = {}
    for (d, e) in book:
        expiries_by_day.setdefault(d, []).append(e)
    rows = []
    for day in sorted(expiries_by_day):
        iv = implied_30d(book, day, rate, expiries_by_day)
        rv = realised_30d(spot, day)
        rows.append((day, iv, rv))
    out = pd.DataFrame(rows, columns=["date", "implied_30d", "realised_30d"]).set_index("date")
    out["premium"] = out["implied_30d"] - out["realised_30d"]
    return out


def by_year(table: pd.DataFrame) -> pd.DataFrame:
    """Per calendar year: mean implied and realised volatility, mean premium, the share of days implied was above realised, and the worst day for a seller."""
    t = table.dropna()
    g = t.groupby(t.index.year)
    return pd.DataFrame({"days": g.size(), "implied": g["implied_30d"].mean() * 100, "realised": g["realised_30d"].mean() * 100,
                         "premium": g["premium"].mean() * 100, "share_implied_above": g["premium"].apply(lambda s: (s > 0).mean()),
                         "worst_premium": g["premium"].min() * 100}).round(2)


def spot_series(book_table: pd.DataFrame, cache_path: str) -> pd.Series:
    """The Nifty index close: the local price cache where it exists, then the underlying price recorded in the F&O files after it ends."""
    spot = pd.read_csv(cache_path, index_col=0, parse_dates=True)["close"].astype(float)
    t = book_table[(book_table["symbol"] == "NIFTY") & book_table["underlying"].notna() & (book_table["underlying"] > 0)]
    later = t[t["date"] > spot.index.max()].groupby("date")["underlying"].median()
    return pd.concat([spot, later]).sort_index()


def main() -> int:
    import fo_bhavcopy as fo
    table = fo.load_fo("2022-01-03", pd.Timestamp.today().strftime("%Y-%m-%d"), symbols=["NIFTY"], instruments=("OPTIDX",))
    if table.empty:
        print("[vol] no stored F&O data: run research/backfill_fo.py first")
        return 1
    book = ob.index_table(table)
    spot = spot_series(fo.load_fo("2022-01-03", pd.Timestamp.today().strftime("%Y-%m-%d"), symbols=["NIFTY"]), os.path.join(PROJECT_ROOT, "data", "cache", "^NSEI.csv"))
    prem = premium_table(book, spot)
    print(f"[vol] {prem['premium'].notna().sum()} days with both an implied and a following realised volatility, "
          f"{prem.dropna().index.min().date()} to {prem.dropna().index.max().date()}")
    print(by_year(prem).to_string())
    out = os.path.join(PROJECT_ROOT, "reports", "output", "options_vol_latest.csv")
    prem.to_csv(out)
    print(f"[vol] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
