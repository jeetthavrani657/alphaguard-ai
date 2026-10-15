"""
research/forward_test_2026.py

Forward test, NOT a search: runs two ALREADY-FIXED dip configurations once
on 2026-01-01 .. latest data -- parameters set before this script existed
and not changed after seeing any result:

  A: RSI<30, +3% target, no stop      (the "maximum win rate" version;
                                       registered, run_dip_target_strategy.py)
  U: RSI<30 & above 200d avg, +4% target, -12% stop, 60-day limit
                                       (registered, run_dip_uptrend_strategy.py)

Answers "what win rate should I actually expect if I run this live?" with
the only evidence that isn't in-sample: months of data these configs never
saw. Not registered in the ledger -- these are re-runs of registered
hypotheses on new data, not new hypotheses -- and not a basis for choosing
between A and U (that would be a selection made after seeing results).
Positions carried in from before 2026 are excluded from the win-rate
statistics, as in the other dip scripts.
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
from run_dip_target_strategy import window_stats

CONFIGS = {
    "A: +3% target, NO stop": {"take_profit": 0.03, "stop_loss": None},
    "U: uptrend, +4% / -12% / 60d": {"take_profit": 0.04, "stop_loss": 0.12, "trend_window": 200, "max_hold_days": 60},
}
START = "2026-01-01"


def main():
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    universe_data, _ = load_universe(config.UNIVERSE, config.START_DATE, today, verbose=False)
    last = max(e["df"].index.max() for e in universe_data.values()).strftime("%Y-%m-%d")

    print("\n" + "=" * 100)
    print(f"FORWARD TEST {START} to {last} (data these configurations never saw)")
    print("=" * 100)
    for name, params in CONFIGS.items():
        run = run_strategy_on_universe(universe_data, dip_target, params, START, last, verbose=False)
        same = {t: universe_data[t] for t in run["per_symbol"]}
        bh = run_strategy_on_universe(same, buy_and_hold, {}, START, last, verbose=False)
        st, a, b = window_stats(run, universe_data, START, last), run["aggregate_metrics"], bh["aggregate_metrics"]
        print(f"\n--- {name} ---   stocks: {a['n_symbols_included']}")
        print(f"  WIN RATE closed trades: {st['win_rate_closed']:.1f}% of {st['n_closed']}"
              f"   |   counting {st['n_open']} still-open positions: {st['win_rate_all_in']:.1f}%"
              f" ({st['open_underwater']} of the open ones underwater)")
        print(f"  Avg win {st['avg_win_pct']:+.2f}%   avg loss {st['avg_loss_pct']:+.2f}%   "
              f"worst closed {st['worst_closed_pct']:+.1f}%   worst open {st['worst_open_pct']:+.1f}%")
        print(f"  Realized P&L Rs {st['realized_pnl_rs']:,.0f}   unrealized (open) Rs {st['unrealized_pnl_rs']:,.0f}")
        print(f"  Strategy:   CAGR {a['cagr_pct']:.2f}%  Sharpe {a['sharpe_ratio']:.2f}  invested {a['market_exposure_pct']:.1f}%")
        print(f"  Buy & hold: CAGR {b['cagr_pct']:.2f}%  Sharpe {b['sharpe_ratio']:.2f}")


if __name__ == "__main__":
    main()
