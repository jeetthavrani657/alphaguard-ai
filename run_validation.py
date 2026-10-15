"""
run_validation.py

Stage 5 validation tooling: multi-symbol universe run, stress cases
(Yes Bank / Vodafone Idea, run separately from the main universe), and
an in-sample / out-of-sample split. The parameter sweep is a separate,
much longer-running script -- see run_sweep.py.

Run from the project root:  python run_validation.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "data"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "strategies"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))

import pandas as pd

import config
import ma_crossover
import rsi_reversion
from universe import load_universe, run_strategy_on_universe, per_symbol_comparison_table

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "reports", "output")

STRATEGY_MODULES = {
    "ma_crossover": (ma_crossover, config.MA_CROSSOVER_PARAMS),
    "rsi_reversion": (rsi_reversion, config.RSI_REVERSION_PARAMS),
}


def _print_survivorship_disclosure():
    print("=" * 100)
    print("SURVIVORSHIP BIAS DISCLOSURE")
    print("=" * 100)
    print(
        "config.UNIVERSE is the CURRENT Nifty 50 constituent list (Dec 2025 / Sep 2026\n"
        "sources), not a point-in-time list from 2015 -- no reliable point-in-time index-\n"
        "membership source was available. This means the universe below only contains\n"
        "stocks that were good enough to STILL be in the index today. Every stock that was\n"
        "in the Nifty 50 at some point during 2015-2025 but has since been removed --\n"
        "demoted, delisted, or collapsed -- is silently absent. Yes Bank is the concrete\n"
        "example: it WAS a Nifty 50 constituent for years before its 2020 near-collapse got\n"
        "it removed, which is also exactly why it's excluded from this universe rather than\n"
        "showing up naturally.\n"
        "\n"
        "Rough magnitude, from published research (not calculated for this specific\n"
        "universe -- I don't have the historical membership data to compute the real\n"
        "number): large-cap index studies (S&P 500 analogues) put current-constituent-only\n"
        "backtesting at roughly +1 to +2 percentage points of annual return overstatement\n"
        "vs a true point-in-time universe. For context, one Indian-market study on the\n"
        "(much higher-turnover) NIFTY Smallcap 250 found survivor-only backtesting inflated\n"
        "annual returns by ~4.9 points (~23% relative). Nifty 50 is large-cap and lower-\n"
        "turnover than a smallcap index, so the S&P 500 analogue (+1-2 pts/year) is the more\n"
        "relevant comparison, but treat that as an informed estimate, not a fact about this\n"
        "specific run.\n"
    )


def main():
    strategy_name = config.STRATEGY
    strategy_module, strategy_params = STRATEGY_MODULES[strategy_name]

    _print_survivorship_disclosure()

    print("=" * 100)
    print(f"LOADING UNIVERSE ({len(config.UNIVERSE)} symbols) -- one-time load + validation")
    print("=" * 100)
    universe_data, failed = load_universe(config.UNIVERSE, config.START_DATE, config.END_DATE)

    print()
    print("=" * 100)
    print(f"MULTI-SYMBOL RUN: {strategy_name} {strategy_params}, full period {config.START_DATE} to {config.END_DATE}")
    print("=" * 100)
    universe_result = run_strategy_on_universe(universe_data, strategy_module, strategy_params,
                                                config.START_DATE, config.END_DATE)

    per_symbol = per_symbol_comparison_table(universe_result)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", 100)
    print("\n--- Per-symbol comparison table ---")
    print(per_symbol[["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe_ratio",
                       "total_trades", "win_rate_pct", "market_exposure_pct"]].round(2).to_string())

    agg = universe_result["aggregate_metrics"]
    print(f"\n--- Aggregate (pooled across {agg.get('n_symbols_included', 0)} symbols) ---")
    for k, v in agg.items():
        print(f"  {k}: {v}")
    print(f"\nTOTAL TRADES ACROSS THE UNIVERSE: {agg.get('total_trades', 0)}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    per_symbol.round(2).to_csv(os.path.join(OUTPUT_DIR, "per_symbol_comparison.csv"))
    universe_result["pooled_trade_log"].to_csv(os.path.join(OUTPUT_DIR, "pooled_trade_log.csv"), index=False)

    # --- Stress cases: run separately, never blended into the universe aggregate ---
    print()
    print("=" * 100)
    print(f"STRESS CASES (excluded from main universe): {config.STRESS_SYMBOLS}")
    print("=" * 100)
    stress_data, stress_failed = load_universe(config.STRESS_SYMBOLS, config.START_DATE, config.END_DATE)
    stress_result = run_strategy_on_universe(stress_data, strategy_module, strategy_params,
                                              config.START_DATE, config.END_DATE)
    stress_table = per_symbol_comparison_table(stress_result)
    print(stress_table[["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe_ratio",
                         "total_trades", "win_rate_pct"]].round(2).to_string())
    if stress_result["blocked"]:
        print("\nBlocked by the discontinuity gate:")
        for ticker, msg in stress_result["blocked"]:
            print(f"  {ticker}: {msg}")

    # --- In-sample / out-of-sample split ---
    print()
    print("=" * 100)
    print(f"IN-SAMPLE / OUT-OF-SAMPLE SPLIT at {config.IN_SAMPLE_END_DATE}")
    print("=" * 100)
    in_sample_end = pd.Timestamp(config.IN_SAMPLE_END_DATE)
    out_sample_start = (in_sample_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    in_sample_result = run_strategy_on_universe(universe_data, strategy_module, strategy_params,
                                                 config.START_DATE, config.IN_SAMPLE_END_DATE, verbose=False)
    out_sample_result = run_strategy_on_universe(universe_data, strategy_module, strategy_params,
                                                  out_sample_start, config.END_DATE, verbose=False)

    def _fmt_period_metrics(label, result, start, end):
        m = result["aggregate_metrics"]
        print(f"\n--- {label} ({start} to {end}) ---")
        for key in ["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe_ratio", "sortino_ratio",
                    "win_rate_pct", "profit_factor", "total_trades", "market_exposure_pct", "n_symbols_included"]:
            print(f"  {key}: {m.get(key)}")

    _fmt_period_metrics("IN-SAMPLE", in_sample_result, config.START_DATE, config.IN_SAMPLE_END_DATE)
    _fmt_period_metrics("OUT-OF-SAMPLE", out_sample_result, out_sample_start, config.END_DATE)

    print(f"\nSaved: per_symbol_comparison.csv, pooled_trade_log.csv in {OUTPUT_DIR}")
    print("Run run_sweep.py separately for the parameter sweep (long-running).")


if __name__ == "__main__":
    main()
