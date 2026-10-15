"""
research/forward_log.py

Forward paper-trade log for the rule frozen in FORWARD_TEST.md. Research
only -- logs what the rule WOULD have done; places no orders.

Everything is recomputed from raw prices with the same engine as the
backtests, so the report is idempotent: running it twice on the same data
gives the same answer, and it cannot depend on when it was run. A dated
summary row is appended to reports/output/forward_snapshots.csv so the
history of the numbers is kept (prices can be re-adjusted by the data
vendor; the snapshot file shows if that ever happened).

Run from the project root:  python research/forward_log.py
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd
from scipy.stats import binomtest

import config
import buy_and_hold
import dip_target
from universe import load_universe, run_strategy_on_universe

# ---- FROZEN in FORWARD_TEST.md (2026-10-16). Do not edit. ----
RULE = {"oversold": 40, "take_profit": 0.02, "stop_loss": 0.12,
        "max_hold_days": 60, "trend_window": 200}
FORWARD_START = "2026-10-16"          # engine window start (freeze day)
FIRST_COUNTED_ENTRY = "2026-10-19"    # first fill after the freeze-day close
BREAKEVEN_WIN_RATE = 79.1             # % -- from the rule's 2015-2025 payoffs
TARGET_WIN_RATE = 90.0                # % -- the owner's goal
MIN_POSITIONS = 100                   # no conclusion before this many counted positions
SNAPSHOT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "forward_snapshots.csv")


def summarize(closed: pd.DataFrame, opened: pd.DataFrame) -> dict:
    """
    closed: one row per closed counted trade, column 'ret' (net % return after costs).
    opened: one row per still-open counted position, column 'unreal_pct' (mark-to-market %).
    Win rule (FORWARD_TEST.md): closed with net return > 0, or open with
    mark-to-market return > 0 -- an underwater open position counts as a loss.
    """
    n_closed, n_open = len(closed), len(opened)
    wins_closed = int((closed["ret"] > 0).sum()) if n_closed else 0
    wins_open = int((opened["unreal_pct"] > 0).sum()) if n_open else 0
    n_all = n_closed + n_open
    avg_win = closed.loc[closed["ret"] > 0, "ret"].mean() if wins_closed else float("nan")
    losses = closed.loc[closed["ret"] <= 0, "ret"]
    avg_loss = losses.mean() if len(losses) else float("nan")
    p = float("nan")
    if n_closed:
        p = binomtest(wins_closed, n_closed, BREAKEVEN_WIN_RATE / 100, alternative="greater").pvalue
    return {
        "n_closed": n_closed, "n_open": n_open, "n_all": n_all,
        "win_rate_closed": wins_closed / n_closed * 100 if n_closed else float("nan"),
        "win_rate_all_in": (wins_closed + wins_open) / n_all * 100 if n_all else float("nan"),
        "open_underwater": int((opened["unreal_pct"] <= 0).sum()) if n_open else 0,
        "avg_win_pct": avg_win, "avg_loss_pct": avg_loss,
        "worst_closed_pct": closed["ret"].min() if n_closed else float("nan"),
        "worst_open_pct": opened["unreal_pct"].min() if n_open else float("nan"),
        "expectancy_pct": closed["ret"].mean() if n_closed else float("nan"),
        "p_vs_breakeven": p,
        "enough_to_conclude": n_all >= MIN_POSITIONS,
    }


def build_report(universe_data: dict) -> dict:
    """
    Returns {"status", "last_date", "summary", "closed", "open", "pending_entries",
    "pending_exits", "pooled_return_pct", "buy_hold_return_pct"}.
    """
    last = max(e["df"].index.max() for e in universe_data.values())
    out = {"last_date": last, "rule": RULE}

    # --- today's signals: what the rule will do at the NEXT open (independent of the engine run) ---
    pending_entries, pending_exits = [], []
    for ticker, entry in universe_data.items():
        df = entry["df"]
        try:
            sig = dip_target.generate_signals(df, **RULE)
        except AssertionError:
            continue  # too little history for the 200-day filter -- cannot trade yet
        if len(sig) < 2 or pd.isna(sig.iloc[-1]):
            continue
        close = float(df["close"].iloc[-1])
        if sig.iloc[-1] == 1.0 and sig.iloc[-2] != 1.0:
            pending_entries.append({
                "symbol": ticker.replace(".NS", ""), "signal_date": df.index[-1].date(),
                "reference_close": round(close, 2),
                "target_price": round(close * (1 + RULE["take_profit"]), 2),
                "stop_price": round(close * (1 - RULE["stop_loss"]), 2),
            })
        elif sig.iloc[-1] == 0.0 and sig.iloc[-2] == 1.0:
            pending_exits.append({"symbol": ticker.replace(".NS", ""), "signal_date": df.index[-1].date()})
    out["pending_entries"] = pd.DataFrame(pending_entries)
    out["pending_exits"] = pd.DataFrame(pending_exits)

    if last < pd.Timestamp(FIRST_COUNTED_ENTRY):
        out.update(status="NOT_STARTED", summary=summarize(pd.DataFrame({"ret": []}), pd.DataFrame({"unreal_pct": []})),
                   closed=pd.DataFrame(), open=pd.DataFrame(), pooled_return_pct=float("nan"),
                   buy_hold_return_pct=float("nan"))
        return out

    end = last.strftime("%Y-%m-%d")
    run = run_strategy_on_universe(universe_data, dip_target, RULE, FORWARD_START, end, verbose=False)
    first_ok = pd.Timestamp(FIRST_COUNTED_ENTRY)

    closed_rows, open_rows = [], []
    for ticker, r in run["per_symbol"].items():
        tl = r["trade_log"]
        if len(tl):
            for _, t in tl[tl["entry_date"] >= first_ok].iterrows():
                closed_rows.append({"symbol": ticker.replace(".NS", ""), "entry_date": t["entry_date"].date(),
                                    "exit_date": t["exit_date"].date(), "ret": t["return_pct"],
                                    "days": t["holding_days"]})
        op = r["open_position_at_end"]
        if op is not None and op["entry_date"] >= first_ok:
            last_close = float(universe_data[ticker]["df"]["close"].iloc[-1])
            open_rows.append({"symbol": ticker.replace(".NS", ""), "entry_date": op["entry_date"].date(),
                              "entry_price": round(op["entry_price"], 2), "last_close": round(last_close, 2),
                              "unreal_pct": (last_close / op["entry_price"] - 1) * 100})

    closed = pd.DataFrame(closed_rows, columns=["symbol", "entry_date", "exit_date", "ret", "days"])
    opened = pd.DataFrame(open_rows, columns=["symbol", "entry_date", "entry_price", "last_close", "unreal_pct"])

    same = {t: universe_data[t] for t in run["per_symbol"]}
    bh = run_strategy_on_universe(same, buy_and_hold, {}, FORWARD_START, end, verbose=False)
    curve, bh_curve = run["combined_equity_curve"], bh["combined_equity_curve"]
    out.update(status="RUNNING", summary=summarize(closed, opened), closed=closed, open=opened,
               pooled_return_pct=(curve.iloc[-1] / curve.iloc[0] - 1) * 100 if len(curve) > 1 else float("nan"),
               buy_hold_return_pct=(bh_curve.iloc[-1] / bh_curve.iloc[0] - 1) * 100 if len(bh_curve) > 1 else float("nan"))
    return out


def append_snapshot(report: dict) -> None:
    s = report["summary"]
    row = pd.DataFrame([{
        "run_date": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "data_through": report["last_date"].strftime("%Y-%m-%d"), "status": report["status"],
        "n_closed": s["n_closed"], "n_open": s["n_open"],
        "win_rate_all_in": s["win_rate_all_in"], "win_rate_closed": s["win_rate_closed"],
        "expectancy_pct": s["expectancy_pct"], "pooled_return_pct": report["pooled_return_pct"],
        "buy_hold_return_pct": report["buy_hold_return_pct"],
    }])
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    if os.path.exists(SNAPSHOT_PATH):
        old = pd.read_csv(SNAPSHOT_PATH)
        # one row per data date -- re-running on the same data replaces, not duplicates
        old = old[old["data_through"] != row.iloc[0]["data_through"]]
        row = pd.concat([old, row], ignore_index=True)
    row.to_csv(SNAPSHOT_PATH, index=False)


def main():
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    universe_data, failed = load_universe(config.UNIVERSE, config.START_DATE, today, verbose=False)
    rep = build_report(universe_data)
    s = rep["summary"]

    print("\n" + "=" * 90)
    print(f"FORWARD TEST (FORWARD_TEST.md)   rule: RSI<{RULE['oversold']} & >200d avg, "
          f"+{RULE['take_profit']:.0%} / -{RULE['stop_loss']:.0%} / {RULE['max_hold_days']}d")
    print(f"Data through {rep['last_date'].date()}   status: {rep['status']}   "
          f"first counted entry: {FIRST_COUNTED_ENTRY}")
    print("=" * 90)
    if rep["status"] == "NOT_STARTED":
        print("No counted forward data yet -- the first countable fill is the "
              f"{FIRST_COUNTED_ENTRY} open. Nothing to evaluate.")
    else:
        print(f"Counted positions: {s['n_all']}  ({s['n_closed']} closed, {s['n_open']} open, "
              f"{s['open_underwater']} of the open ones underwater)")
        print(f"WIN RATE, all positions (open marked to market): {s['win_rate_all_in']:.1f}%   "
              f"[target {TARGET_WIN_RATE:.0f}%]   closed only: {s['win_rate_closed']:.1f}%")
        print(f"Avg win {s['avg_win_pct']:+.2f}%   avg loss {s['avg_loss_pct']:+.2f}%   "
              f"worst closed {s['worst_closed_pct']:+.1f}%   worst open {s['worst_open_pct']:+.1f}%")
        print(f"Net expectancy {s['expectancy_pct']:+.2f}%/closed trade   break-even win rate {BREAKEVEN_WIN_RATE}%   "
              f"p vs break-even {s['p_vs_breakeven']:.3f}")
        print(f"Pooled return since start {rep['pooled_return_pct']:+.2f}%   buy & hold same stocks "
              f"{rep['buy_hold_return_pct']:+.2f}%")
        if not s["enough_to_conclude"]:
            print(f"\n*** TOO FEW POSITIONS TO CONCLUDE ({s['n_all']} of {MIN_POSITIONS} needed). "
                  "These numbers are monitoring, not evidence. ***")
    print(f"\nSignals at the last close ({rep['last_date'].date()}) -- would be filled at the next open:")
    print(f"  Entries: {len(rep['pending_entries'])}   Exits: {len(rep['pending_exits'])}")
    if len(rep["pending_entries"]):
        print(rep["pending_entries"].to_string(index=False))
    append_snapshot(rep)
    print(f"\nSnapshot appended to {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
