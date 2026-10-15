"""
run_sweep.py

Stage 5 parameter sweep: grid search over MA crossover's (fast, slow)
windows, evaluated across the whole universe (not one symbol), so each
grid cell's CAGR/Sharpe is backed by a pooled trade count instead of a
handful of trades from a single stock.

This is the long-running piece of Stage 5 -- kept as its own script
(separate from run_validation.py) since a full 10x11 grid across ~48-50
symbols means several thousand individual backtests.

Run from the project root:  python run_sweep.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "data"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "strategies"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "reports"))

import config
from universe import load_universe
from sweep import run_ma_crossover_sweep
import plots

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "reports", "output")


def main():
    print(f"Loading universe ({len(config.UNIVERSE)} symbols)...")
    universe_data, failed = load_universe(config.UNIVERSE, config.START_DATE, config.END_DATE)

    fast_values = config.MA_SWEEP_FAST_VALUES
    slow_values = config.MA_SWEEP_SLOW_VALUES
    n_combos = sum(1 for f in fast_values for s in slow_values if f < s)
    print(f"Sweeping {n_combos} (fast, slow) combinations "
          f"(fast: {fast_values}, slow: {slow_values}) across {len(universe_data)} symbols...")

    t0 = time.time()
    sweep_df = run_ma_crossover_sweep(universe_data, fast_values, slow_values, config.START_DATE, config.END_DATE)
    elapsed = time.time() - t0
    print(f"Sweep finished in {elapsed / 60:.1f} minutes.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    sweep_df.to_csv(os.path.join(OUTPUT_DIR, "param_sweep.csv"), index=False)

    plots.plot_sweep_heatmap(sweep_df, "cagr_pct", "CAGR (%)", os.path.join(OUTPUT_DIR, "sweep_heatmap_cagr.png"))
    plots.plot_sweep_heatmap(sweep_df, "sharpe_ratio", "Sharpe Ratio", os.path.join(OUTPUT_DIR, "sweep_heatmap_sharpe.png"))

    print("\nTop 10 by CAGR:")
    print(sweep_df.sort_values("cagr_pct", ascending=False).head(10).to_string(index=False))
    print("\nTop 10 by Sharpe:")
    print(sweep_df.sort_values("sharpe_ratio", ascending=False).head(10).to_string(index=False))
    print(f"\nSaved param_sweep.csv, sweep_heatmap_cagr.png, sweep_heatmap_sharpe.png to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
