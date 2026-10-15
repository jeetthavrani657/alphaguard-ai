"""
research/run_ma_vs_rsi_harness_demo.py

A real (not toy) first use of the harness: registers ma_crossover and
rsi_reversion, both run on the full 48-symbol universe, in-sample and
out-of-sample, through research/harness.py. This is also the first time
rsi_reversion has been run at universe scale in this project -- a gap
flagged in the earlier technical-debt list.

Run from the project root: python research/run_ma_vs_rsi_harness_demo.py
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
from universe import load_universe, run_strategy_on_universe
import ma_crossover
import rsi_reversion
from harness import evaluate_strategy, run_harness, print_harness_report, get_best_strategy

MA_RATIONALE = (
    "Once a trend is established (fast MA above slow MA), price is more likely to "
    "continue in that direction than reverse, because trend followers, momentum "
    "traders, and delayed institutional reaction to news all tend to reinforce an "
    "already-moving price -- this is the standard trend-following/momentum rationale."
)
RSI_RATIONALE = (
    "After a sharp short-term move, prices tend to partially revert as the initial "
    "overreaction (panic selling or euphoric buying) fades and value-oriented buyers "
    "or sellers step in -- this is the standard short-term mean-reversion rationale "
    "RSI oversold/overbought thresholds are built to capture."
)


def main():
    universe_data, _ = load_universe(config.UNIVERSE, config.START_DATE, config.END_DATE, verbose=False)
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    def run_both(module, params):
        is_r = run_strategy_on_universe(universe_data, module, params, config.START_DATE,
                                         config.IN_SAMPLE_END_DATE, verbose=False)
        oos_r = run_strategy_on_universe(universe_data, module, params, oos_start,
                                          config.END_DATE, verbose=False)
        return is_r, oos_r

    ma_is, ma_oos = run_both(ma_crossover, config.MA_CROSSOVER_PARAMS)
    rsi_is, rsi_oos = run_both(rsi_reversion, config.RSI_REVERSION_PARAMS)

    ma_result = evaluate_strategy(
        name="MA Crossover (fast=50, slow=200)", rationale=MA_RATIONALE,
        in_sample_sharpe=ma_is["aggregate_metrics"]["sharpe_ratio"],
        in_sample_n_obs=len(ma_is["combined_equity_curve"]),
        out_of_sample_sharpe=ma_oos["aggregate_metrics"]["sharpe_ratio"],
        out_of_sample_n_obs=len(ma_oos["combined_equity_curve"]),
    )
    rsi_result = evaluate_strategy(
        name="RSI Reversion (period=14, oversold=30, exit=50)", rationale=RSI_RATIONALE,
        in_sample_sharpe=rsi_is["aggregate_metrics"]["sharpe_ratio"],
        in_sample_n_obs=len(rsi_is["combined_equity_curve"]),
        out_of_sample_sharpe=rsi_oos["aggregate_metrics"]["sharpe_ratio"],
        out_of_sample_n_obs=len(rsi_oos["combined_equity_curve"]),
    )

    run_output = run_harness(
        [ma_result, rsi_result],
        context="MA crossover vs RSI reversion, both on the 48-symbol universe, "
                "in-sample vs out-of-sample (first harness-governed run)",
    )
    print_harness_report(run_output)
    print()
    get_best_strategy(run_output)


if __name__ == "__main__":
    main()
