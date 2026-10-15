"""
research/run_midcap_smallcap_strategy.py

Control comparison: the SAME MA crossover rule, the SAME parameters
(config.MA_CROSSOVER_PARAMS, fast=50/slow=200 -- unchanged, not
retuned for this universe), run on Midcap150 and Smallcap250 instead of
the original Nifty 50 universe. Only the universe changes. Costs are
NOT inherited flat -- each symbol gets its own liquidity-based slippage
estimate from research/liquidity_costs.py, calibrated so a Nifty-50-
liquid stock still gets the original 0.05%.

Registers both universes' in-sample/out-of-sample results in the
research harness (research/harness.py) -- this adds to the cumulative
hypothesis count from the Nifty 50 sweep + pairs screen + MA-vs-RSI run.

Run from the project root: python research/run_midcap_smallcap_strategy.py
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "strategies"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import config
from universe import load_universe, run_strategy_on_universe, per_symbol_comparison_table
import ma_crossover
import buy_and_hold
from liquidity_costs import build_slippage_map
from harness import evaluate_strategy, run_harness, print_harness_report

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "reports", "output")

MA_RATIONALE = (
    "Once a trend is established (fast MA above slow MA), price is more likely to "
    "continue in that direction than reverse, because trend followers, momentum "
    "traders, and delayed institutional reaction to news all tend to reinforce an "
    "already-moving price -- the same rationale already used for the Nifty 50 run. "
    "Unchanged here on purpose: this is a control comparison of the universe, not a "
    "new hypothesis about mid/small caps specifically."
)


def run_one_universe(symbols, label, oos_start):
    print(f"\n{'=' * 100}\n{label}\n{'=' * 100}")
    universe_data, failed = load_universe(symbols, config.START_DATE, config.END_DATE, verbose=False)
    print(f"Loaded {len(universe_data)}/{len(symbols)}")

    slippage_map = build_slippage_map(universe_data, config.START_DATE, config.END_DATE)
    rates = sorted(slippage_map.values())
    n = len(rates)
    print(f"Liquidity-based slippage: min={rates[0]*100:.3f}%  median={rates[n//2]*100:.3f}%  max={rates[-1]*100:.3f}%  "
          f"(flat Nifty50 rate was 0.050%)")

    is_result = run_strategy_on_universe(
        universe_data, ma_crossover, config.MA_CROSSOVER_PARAMS,
        config.START_DATE, config.IN_SAMPLE_END_DATE, verbose=False,
        slippage_pct_by_symbol=slippage_map,
    )
    oos_result = run_strategy_on_universe(
        universe_data, ma_crossover, config.MA_CROSSOVER_PARAMS,
        oos_start, config.END_DATE, verbose=False,
        slippage_pct_by_symbol=slippage_map,
    )
    bh_result = run_strategy_on_universe(
        universe_data, buy_and_hold, {}, config.START_DATE, config.END_DATE, verbose=False,
        slippage_pct_by_symbol=slippage_map,
    )

    for tag, result in [("IN-SAMPLE", is_result), ("OUT-OF-SAMPLE", oos_result), ("FULL-PERIOD BUY&HOLD", bh_result)]:
        m = result["aggregate_metrics"]
        print(f"\n--- {label} {tag} ---")
        for key in ["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe_ratio", "sortino_ratio",
                    "win_rate_pct", "profit_factor", "total_trades", "market_exposure_pct", "n_symbols_included"]:
            print(f"  {key}: {m.get(key)}")
        if result["blocked"]:
            print(f"  blocked: {[t for t, _ in result['blocked']]}")

    return is_result, oos_result, bh_result, slippage_map


def main():
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    mid_is, mid_oos, mid_bh, mid_slip = run_one_universe(config.MIDCAP150_UNIVERSE, "NIFTY MIDCAP 150", oos_start)
    small_is, small_oos, small_bh, small_slip = run_one_universe(config.SMALLCAP250_UNIVERSE, "NIFTY SMALLCAP 250", oos_start)

    # --- Register through the harness (mandatory correction) ---
    mid_strategy_result = evaluate_strategy(
        name="MA Crossover on Nifty Midcap 150 (liquidity-adjusted costs)", rationale=MA_RATIONALE,
        in_sample_sharpe=mid_is["aggregate_metrics"]["sharpe_ratio"],
        in_sample_n_obs=len(mid_is["combined_equity_curve"]),
        out_of_sample_sharpe=mid_oos["aggregate_metrics"]["sharpe_ratio"],
        out_of_sample_n_obs=len(mid_oos["combined_equity_curve"]),
    )
    small_strategy_result = evaluate_strategy(
        name="MA Crossover on Nifty Smallcap 250 (liquidity-adjusted costs)", rationale=MA_RATIONALE,
        in_sample_sharpe=small_is["aggregate_metrics"]["sharpe_ratio"],
        in_sample_n_obs=len(small_is["combined_equity_curve"]),
        out_of_sample_sharpe=small_oos["aggregate_metrics"]["sharpe_ratio"],
        out_of_sample_n_obs=len(small_oos["combined_equity_curve"]),
    )

    run_output = run_harness(
        [mid_strategy_result, small_strategy_result],
        context="MA crossover (fast=50, slow=200, unchanged) on Midcap150 and Smallcap250 -- "
                "control comparison for the universe-dependence question, liquidity-adjusted slippage",
    )
    print()
    print_harness_report(run_output)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pd.DataFrame({"symbol": list(mid_slip), "slippage_pct": list(mid_slip.values())}).to_csv(
        os.path.join(OUTPUT_DIR, "midcap150_slippage.csv"), index=False)
    pd.DataFrame({"symbol": list(small_slip), "slippage_pct": list(small_slip.values())}).to_csv(
        os.path.join(OUTPUT_DIR, "smallcap250_slippage.csv"), index=False)


if __name__ == "__main__":
    main()
