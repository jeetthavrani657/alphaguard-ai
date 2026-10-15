"""
research/run_dip_uptrend_strategy.py

ONE honest attempt at the owner's two goals together: profit AND a ~90%
win rate. Parameters fixed BEFORE any result was seen and not tuned:

  entry : RSI(14) < 30  AND  close above its own 200-day average
          (buy pullbacks in an uptrend, not falling knives)
  exit  : +4% take-profit  OR  -12% stop-loss  OR  60 trading days elapsed
          (every loser is REALIZED -- nothing sits open to flatter the win rate)

Why these numbers are stated up front, not discovered: with a +4% target
and a -12% stop the break-even win rate is 12 / (4 + 12) = 75% before
costs, higher after them (about 0.3% round-trip). A 90% win rate would
clear that comfortably IF the filter really picks better entries; if it
doesn't, the win rate falls toward what dips in general give (Variant B of
research/run_dip_target_strategy.py: 67% in-sample, 82% out-of-sample, no
trend filter, 10% stop) and the strategy loses money. Registered as one
hypothesis in the ledger (+1). The 90% target is reported against, never
tuned toward: if it isn't met, that is the finding.

Run from the project root:
    python research/run_dip_uptrend_strategy.py
    python research/run_dip_uptrend_strategy.py --no-register --n=6   (dry run)
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import config
import buy_and_hold
import dip_target
from universe import load_universe, run_strategy_on_universe
from harness import evaluate_strategy, run_harness, print_harness_report
from run_dip_target_strategy import window_stats

PARAMS = {"take_profit": 0.04, "stop_loss": 0.12, "trend_window": 200, "max_hold_days": 60}

RATIONALE = (
    "Short-term pullbacks in stocks that are still in a long-term uptrend (price above the "
    "200-day average) tend to retrace, while dips below it are more often the start of a "
    "decline; a fixed +4% target with a -12% stop and a 60-day time limit realizes every loser. "
    "Built to pursue a high win rate and profit together at the owner's request; the break-even "
    "win rate for these payoffs is about 75% before costs, so a high win rate is necessary, "
    "not sufficient, for profit."
)


def main():
    register = "--no-register" not in sys.argv
    n_limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--n=")), None)
    symbols = config.UNIVERSE[:n_limit] if n_limit else config.UNIVERSE

    universe_data, _ = load_universe(symbols, config.START_DATE, config.END_DATE, verbose=False)
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    windows = {"IN-SAMPLE": (config.START_DATE, config.IN_SAMPLE_END_DATE),
               "OUT-OF-SAMPLE": (oos_start, config.END_DATE)}

    out = {}
    for wname, (s, e) in windows.items():
        run = run_strategy_on_universe(universe_data, dip_target, PARAMS, s, e, verbose=False)
        same = {t: universe_data[t] for t in run["per_symbol"]}
        bh = run_strategy_on_universe(same, buy_and_hold, {}, s, e, verbose=False)
        out[wname] = {"agg": run["aggregate_metrics"], "bh": bh["aggregate_metrics"],
                      "stats": window_stats(run, universe_data, s, e),
                      "n_obs": len(run["combined_equity_curve"])}

    print("\n" + "=" * 100)
    print(f"DIP IN UPTREND, +4% target / -12% stop / 60-day limit  ({len(symbols)} symbols requested)")
    print("=" * 100)
    for wname, r in out.items():
        a, b, st = r["agg"], r["bh"], r["stats"]
        wr = st["win_rate_all_in"] / 100
        avg_w, avg_l = st["avg_win_pct"], st["avg_loss_pct"]
        breakeven = abs(avg_l) / (avg_w + abs(avg_l)) * 100 if pd.notna(avg_w) and pd.notna(avg_l) else float("nan")
        expectancy = wr * avg_w + (1 - wr) * avg_l if pd.notna(avg_w) and pd.notna(avg_l) else float("nan")
        print(f"\n--- {wname} ---   stocks run: {a['n_symbols_included']}")
        print(f"  WIN RATE (closed trades): {st['win_rate_closed']:.1f}%  of {st['n_closed']} trades "
              f"| counting {st['n_open']} still-open positions: {st['win_rate_all_in']:.1f}%")
        print(f"  Avg win {avg_w:+.2f}%   avg loss {avg_l:+.2f}%   worst closed trade {st['worst_closed_pct']:+.1f}%")
        print(f"  Break-even win rate for these payoffs: {breakeven:.1f}%   |   expectancy per trade (before costs): {expectancy:+.2f}%")
        print(f"  Profit factor {a['profit_factor']:.2f}   realized P&L Rs {st['realized_pnl_rs']:,.0f}   "
              f"unrealized (open) Rs {st['unrealized_pnl_rs']:,.0f}")
        print(f"  Strategy:   CAGR {a['cagr_pct']:.2f}%  Sharpe {a['sharpe_ratio']:.2f}  MaxDD {a['max_drawdown_pct']:.1f}%  "
              f"invested {a['market_exposure_pct']:.1f}%")
        print(f"  Buy & hold: CAGR {b['cagr_pct']:.2f}%  Sharpe {b['sharpe_ratio']:.2f}  MaxDD {b['max_drawdown_pct']:.1f}%")

    if register:
        is_r, oos_r = out["IN-SAMPLE"], out["OUT-OF-SAMPLE"]
        res = evaluate_strategy(
            name="Dip in uptrend (RSI<30, >200d avg; +4% / -12% / 60d), Nifty 50", rationale=RATIONALE,
            in_sample_sharpe=is_r["agg"]["sharpe_ratio"], in_sample_n_obs=is_r["n_obs"],
            out_of_sample_sharpe=oos_r["agg"]["sharpe_ratio"], out_of_sample_n_obs=oos_r["n_obs"],
        )
        h = run_harness([res], context="Dip in uptrend (RSI<30 & above 200d avg; +4% target, -12% stop, 60-day limit), "
                                        "Nifty 50 -- one pre-registered attempt at profit AND ~90% win rate")
        print()
        print_harness_report(h)
    else:
        print("\n(--no-register: harness/ledger NOT touched)")


if __name__ == "__main__":
    main()
