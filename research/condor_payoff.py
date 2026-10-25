"""
research/condor_payoff.py

DESCRIPTION, not a hypothesis: shows how the two frozen iron-condor rules (OPTIONS_IDEAS.md) really paid, for the web app's "How a condor pays" panel.

  * the payoff at expiry of four REAL trades per rule (the worst, the best, a typical one and the latest), with the strikes, the credit, the breakevens and where the Nifty
    actually finished;
  * the implied volatility against the volatility that really followed, by year (the variance risk premium that the rules try to collect), from research/options_vol.py's output.

It re-runs the backtest on the stored F&O data exactly as research/options_condors.py does (same function, same settings), registers nothing and changes no status.

    python research/condor_payoff.py        # writes reports/output/condor_payoff_latest.json
"""

import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd

OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "condor_payoff_latest.json")
VOL_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "options_vol_latest.csv")
SERIES_EVERY = 5                           # the implied-vs-realised line keeps every 5th trading day: enough to draw, small to send


def payoff_points(trade: dict) -> list:
    """
    The profit or loss of one condor at expiry, GROSS of costs, in rupees, at the levels where it changes slope and a little beyond each end:
    [{"level", "pnl"}] from low to high. pnl = (credit + what the four legs settle at) x units.
    """
    lp, sp, sc, lc = trade["long_put"], trade["short_put"], trade["short_call"], trade["long_call"]
    credit, units = trade["credit_per_unit"], trade["units"]
    wing = max(sp - lp, lc - sc)
    levels = [lp - wing, lp, sp, sc, lc, lc + wing]

    def per_unit(s: float) -> float:
        return credit + max(lp - s, 0.0) - max(sp - s, 0.0) - max(s - sc, 0.0) + max(s - lc, 0.0)     # long put, short put, short call, long call at expiry

    return [{"level": float(s), "pnl": float(per_unit(s) * units)} for s in levels]


def trade_record(label: str, row: pd.Series) -> dict:
    """One real trade from the backtest's cycle log, with its payoff curve and the figures that describe it."""
    t = {k: float(row[k]) for k in ("long_put", "short_put", "short_call", "long_call", "credit_per_unit", "width", "units", "final_level", "gross_pnl", "net_pnl", "entry_cost", "exit_cost")}
    t.update({"label": label, "entry_day": str(pd.Timestamp(row["entry_day"]).date()), "expiry": str(pd.Timestamp(row["expiry"]).date()), "lots": int(row["lots"])})
    t["breakeven_low"] = t["short_put"] - t["credit_per_unit"]
    t["breakeven_high"] = t["short_call"] + t["credit_per_unit"]
    t["max_profit"] = t["credit_per_unit"] * t["units"]
    t["max_loss"] = (t["width"] - t["credit_per_unit"]) * t["units"]
    t["payoff"] = payoff_points(t)
    return t


def pick_trades(cycles: pd.DataFrame) -> list:
    """The worst and best trade by net result, the one whose result is closest to the middle one, and the most recent: four real trades, each labelled."""
    if cycles.empty:
        return []
    c = cycles.reset_index(drop=True)
    middle = c["net_pnl"].median()
    picks = [("worst", c["net_pnl"].idxmin()), ("best", c["net_pnl"].idxmax()), ("typical", (c["net_pnl"] - middle).abs().idxmin()), ("latest", c["entry_day"].idxmax())]
    return [trade_record(label, c.loc[i]) for label, i in picks]


def cycle_points(cycles: pd.DataFrame) -> list:
    """Every trade as one dot: where the Nifty finished against the two short strikes, and what the trade made after costs."""
    return [{"expiry": str(pd.Timestamp(r["expiry"]).date()), "final_level": float(r["final_level"]), "short_put": float(r["short_put"]), "short_call": float(r["short_call"]),
             "net_pnl": float(r["net_pnl"])} for _, r in cycles.sort_values("expiry").iterrows()]


def yearly_vol(frame: pd.DataFrame) -> list:
    """By calendar year: days, mean implied and realised volatility and their gap (all in volatility points, i.e. %), the share of days implied was above realised, and the worst gap."""
    f = frame.copy()
    f["year"] = pd.to_datetime(f["date"]).dt.year
    out = []
    for year, g in f.groupby("year"):
        out.append({"year": int(year), "days": int(len(g)), "implied_pct": float(g["implied_30d"].mean() * 100), "realised_pct": float(g["realised_30d"].mean() * 100),
                    "premium_pct": float(g["premium"].mean() * 100), "share_implied_above_pct": float((g["premium"] > 0).mean() * 100), "worst_premium_pct": float(g["premium"].min() * 100)})
    return out


def vol_series(frame: pd.DataFrame, every: int = SERIES_EVERY) -> list:
    return [{"date": str(r["date"]), "implied_pct": float(r["implied_30d"] * 100), "realised_pct": float(r["realised_30d"] * 100)} for _, r in frame.iloc[::every].iterrows()]


def build(book_runs: dict, vol: pd.DataFrame, data_through: str, names: dict | None = None) -> dict:
    """The file's content from {rule id: backtest result} and the volatility table (days with no following 30 days yet have no realised volatility and are left out)."""
    vol = vol.dropna(subset=["implied_30d", "realised_30d"])
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data_through": data_through,
            "rules": {rid: {"name": (names or {}).get(rid, rid), "trades": pick_trades(res["cycles"]), "cycles": cycle_points(res["cycles"])} for rid, res in book_runs.items()},
            "volatility": {"years": yearly_vol(vol), "series": vol_series(vol)}}


def main() -> int:
    import fo_bhavcopy as fo
    import options_backtest as ob
    import options_condors as oc
    table = fo.load_fo(oc.START, pd.Timestamp.today().strftime("%Y-%m-%d"), symbols=["NIFTY"], instruments=("OPTIDX",))
    if table.empty or not os.path.exists(VOL_PATH):
        print("[payoff] needs the stored F&O data (research/backfill_fo.py) and research/options_vol.py's output")
        return 1
    book = ob.index_table(table)
    runs = {r["id"]: oc.run_rule(book, r) for r in oc.RULES}
    data_through = str(ob.trading_days(book)[-1].date())
    out = build(runs, pd.read_csv(VOL_PATH, encoding="utf-8-sig"), data_through, {r["id"]: r["name"] for r in oc.RULES})
    tmp = OUTPUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, allow_nan=False)
    os.replace(tmp, OUTPUT_PATH)
    print(f"[payoff] wrote {OUTPUT_PATH}: " + ", ".join(f"{k} {len(v['cycles'])} trades" for k, v in out["rules"].items()) + f"; data through {data_through}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
