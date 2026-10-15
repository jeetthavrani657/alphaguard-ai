"""
research/run_dip_target_strategy.py

"Buy the dip, take a small profit" on the Nifty 50 universe -- built to
maximize win rate (owner's target: 90%), reported so that win rate can be
read next to what produces it.

PARAMETERS FIXED BEFORE ANY RESULT WAS SEEN (not tuned to hit a target):
  entry: RSI(14) < 30     exit: +3% take-profit from the signal close
  Variant A: no stop-loss (the maximum-win-rate version -- never realize a loss)
  Variant B: same, plus a 10% stop-loss (the same idea with losses allowed)
Both are registered as hypotheses in the research ledger (+2).

For each variant and window it reports, alongside the Sharpe:
  - win rate on CLOSED trades (what engine/metrics.py reports),
  - the open positions still held at the window's end, and their
    unrealized loss -- the other half of the story for a never-stop rule,
  - an "all-in" win rate that counts open positions at their current
    mark, which is the honest number,
  - average win vs average loss, and the worst single loss.
Positions carried in from before a window are excluded from the win-rate
statistics (the engine opens them on the window's first day at that day's
open, which would flatter the rule).

Run from the project root:
    python research/run_dip_target_strategy.py              (full, registers in ledger)
    python research/run_dip_target_strategy.py --no-register --n=6   (dry run)
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
import buy_and_hold
import dip_target
from universe import load_universe, run_strategy_on_universe
from harness import evaluate_strategy, run_harness, print_harness_report

VARIANTS = {
    "A: 3% target, NO stop": {"take_profit": 0.03, "stop_loss": None},
    "B: 3% target, 10% stop": {"take_profit": 0.03, "stop_loss": 0.10},
}

RATIONALE = (
    "Short-term oversold bounce: after a sharp drop (RSI below 30) large, liquid stocks tend to "
    "retrace a few percent, so a small fixed profit target is hit often. Built to maximize win "
    "rate rather than expectancy at the owner's request; it is expected to show a high win rate "
    "because small capped wins plus unrealized (never-stopped) losses inflate the closed-trade "
    "win rate -- the open positions and unrealized loss are reported next to it for that reason."
)


def window_stats(result, universe_data, start, end):
    """Win-rate / open-position statistics for one strategy run over one window."""
    closed_rows, open_rows = [], []
    for ticker, r in result["per_symbol"].items():
        first_day = r["equity_curve"].index[0]
        tl = r["trade_log"]
        if len(tl):
            tl = tl[tl["entry_date"] != first_day]  # drop positions carried in from before the window
            for _, t in tl.iterrows():
                pnl = t["quantity"] * (t["exit_price"] - t["entry_price"]) - t["total_costs"]
                closed_rows.append({"symbol": ticker, "ret": t["return_pct"], "pnl": pnl, "days": t["holding_days"]})
        op = r["open_position_at_end"]
        if op is not None and op["entry_date"] != first_day:
            df = universe_data[ticker]["df"]
            last_close = float(df["close"].loc[:end].iloc[-1])
            unreal_pct = (last_close / op["entry_price"] - 1) * 100
            unreal_rs = op["quantity"] * (last_close - op["entry_price"]) - op["buy_costs_total"]
            age = (pd.Timestamp(end) - pd.Timestamp(op["entry_date"])).days
            open_rows.append({"symbol": ticker, "unreal_pct": unreal_pct, "unreal_rs": unreal_rs, "age_days": age})

    closed = pd.DataFrame(closed_rows)
    opened = pd.DataFrame(open_rows)
    n_closed, n_open = len(closed), len(opened)
    wins = int((closed["ret"] > 0).sum()) if n_closed else 0
    open_up = int((opened["unreal_pct"] > 0).sum()) if n_open else 0
    return {
        "n_closed": n_closed, "n_open": n_open,
        "win_rate_closed": wins / n_closed * 100 if n_closed else float("nan"),
        "win_rate_all_in": (wins + open_up) / (n_closed + n_open) * 100 if (n_closed + n_open) else float("nan"),
        "avg_win_pct": closed.loc[closed["ret"] > 0, "ret"].mean() if n_closed else float("nan"),
        "avg_loss_pct": closed.loc[closed["ret"] <= 0, "ret"].mean() if n_closed and (closed["ret"] <= 0).any() else float("nan"),
        "worst_closed_pct": closed["ret"].min() if n_closed else float("nan"),
        "realized_pnl_rs": closed["pnl"].sum() if n_closed else 0.0,
        "unrealized_pnl_rs": opened["unreal_rs"].sum() if n_open else 0.0,
        "worst_open_pct": opened["unreal_pct"].min() if n_open else float("nan"),
        "median_open_age_days": opened["age_days"].median() if n_open else float("nan"),
        "open_underwater": int((opened["unreal_pct"] < 0).sum()) if n_open else 0,
    }


def main():
    register = "--no-register" not in sys.argv
    n_limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--n=")), None)
    symbols = config.UNIVERSE[:n_limit] if n_limit else config.UNIVERSE

    universe_data, _ = load_universe(symbols, config.START_DATE, config.END_DATE, verbose=False)
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    windows = {"IN-SAMPLE": (config.START_DATE, config.IN_SAMPLE_END_DATE),
               "OUT-OF-SAMPLE": (oos_start, config.END_DATE)}

    results = {}   # (variant, window) -> dict
    for vname, params in VARIANTS.items():
        for wname, (s, e) in windows.items():
            run = run_strategy_on_universe(universe_data, dip_target, params, s, e, verbose=False)
            same = {t: universe_data[t] for t in run["per_symbol"]}
            bh = run_strategy_on_universe(same, buy_and_hold, {}, s, e, verbose=False)
            results[(vname, wname)] = {
                "agg": run["aggregate_metrics"], "bh": bh["aggregate_metrics"],
                "stats": window_stats(run, universe_data, s, e),
                "n_obs": len(run["combined_equity_curve"]),
            }

    print("\n" + "=" * 100)
    print(f"DIP + TAKE-PROFIT, Nifty 50 ({len(symbols)} symbols requested)")
    print("=" * 100)
    for (vname, wname), r in results.items():
        a, b, st = r["agg"], r["bh"], r["stats"]
        print(f"\n--- {vname} | {wname} ---")
        print(f"  Stocks run: {a['n_symbols_included']}")
        print(f"  WIN RATE, closed trades only:      {st['win_rate_closed']:.1f}%   ({st['n_closed']} closed trades)")
        print(f"  WIN RATE, counting open positions: {st['win_rate_all_in']:.1f}%   ({st['n_open']} still open, "
              f"{st['open_underwater']} of them underwater)")
        print(f"  Avg win {st['avg_win_pct']:+.2f}%   avg loss {st['avg_loss_pct']:+.2f}%   "
              f"worst closed trade {st['worst_closed_pct']:+.1f}%   worst OPEN position {st['worst_open_pct']:+.1f}%")
        print(f"  Realized P&L Rs {st['realized_pnl_rs']:,.0f}   Unrealized P&L on open positions Rs {st['unrealized_pnl_rs']:,.0f}")
        print(f"  Median age of still-open positions: {st['median_open_age_days']:.0f} days")
        print(f"  Strategy:   CAGR {a['cagr_pct']:.2f}%  Sharpe {a['sharpe_ratio']:.2f}  MaxDD {a['max_drawdown_pct']:.1f}%  "
              f"invested {a['market_exposure_pct']:.1f}%  profit factor {a['profit_factor']:.2f}")
        print(f"  Buy & hold: CAGR {b['cagr_pct']:.2f}%  Sharpe {b['sharpe_ratio']:.2f}  MaxDD {b['max_drawdown_pct']:.1f}%")

    if register:
        batch = []
        for vname in VARIANTS:
            is_r, oos_r = results[(vname, "IN-SAMPLE")], results[(vname, "OUT-OF-SAMPLE")]
            batch.append(evaluate_strategy(
                name=f"Dip + take-profit ({vname}), Nifty 50", rationale=RATIONALE,
                in_sample_sharpe=is_r["agg"]["sharpe_ratio"], in_sample_n_obs=is_r["n_obs"],
                out_of_sample_sharpe=oos_r["agg"]["sharpe_ratio"], out_of_sample_n_obs=oos_r["n_obs"],
            ))
        out = run_harness(batch, context="Dip + take-profit (RSI<30 entry, +3% target; A: no stop, B: 10% stop), "
                                          "Nifty 50 -- built to maximize win rate at the owner's request")
        print()
        print_harness_report(out)
    else:
        print("\n(--no-register: harness/ledger NOT touched)")


if __name__ == "__main__":
    main()
