"""
run_backtest.py

Single entry point: load and validate data, generate signals, run the
backtest (with both benchmarks), print metrics, save charts, write the
trade log to CSV.

Run from the project root:  python run_backtest.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "data"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "strategies"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "reports"))

import pandas as pd

import config
from loader import load_price_data
from validator import validate_price_data
import ma_crossover
import rsi_reversion
import buy_and_hold
from backtest import run_backtest
from metrics import compute_metrics, trade_contribution_table, exclude_largest_trade_analysis
import plots

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "reports", "output")

STRATEGY_MODULES = {
    "ma_crossover": (ma_crossover, config.MA_CROSSOVER_PARAMS),
    "rsi_reversion": (rsi_reversion, config.RSI_REVERSION_PARAMS),
}


def _run_symbol(loader_symbol: str, ticker: str, strategy_module, strategy_params, label: str) -> dict:
    """Load, validate, generate signals, and run one backtest. Returns run_backtest()'s result dict."""
    df = load_price_data(loader_symbol, config.START_DATE, config.END_DATE)
    report = validate_price_data(df, ticker)
    signal = strategy_module.generate_signals(df, **strategy_params)
    result = run_backtest(df, signal, report, config.START_DATE, config.END_DATE)
    result["df"] = df
    result["label"] = label
    return result


def _print_metrics_table(metrics_by_label: dict) -> None:
    rows_order = [
        ("total_return_pct", "Total Return (%)", "{:.2f}"),
        ("cagr_pct", "CAGR (%)", "{:.2f}"),
        ("max_drawdown_pct", "Max Drawdown (%)", "{:.2f}"),
        ("max_drawdown_duration_days", "Max DD Duration (days)", "{:.0f}"),
        ("sharpe_ratio", "Sharpe Ratio", "{:.2f}"),
        ("sortino_ratio", "Sortino Ratio", "{:.2f}"),
        ("win_rate_pct", "Win Rate (%)", "{:.2f}"),
        ("avg_win_pct", "Avg Win (%)", "{:.2f}"),
        ("avg_loss_pct", "Avg Loss (%)", "{:.2f}"),
        ("profit_factor", "Profit Factor", "{:.2f}"),
        ("total_trades", "Total Trades", "{:.0f}"),
        ("avg_holding_days", "Avg Holding Period (days)", "{:.1f}"),
        ("market_exposure_pct", "Market Exposure (%)", "{:.2f}"),
        ("final_equity", "Final Equity (Rs)", "{:,.2f}"),
    ]
    labels = list(metrics_by_label.keys())
    col_width = max(len(l) for l in labels) + 2
    name_width = max(len(name) for _, name, _ in rows_order) + 2

    header = " " * name_width + "".join(f"{l:>{col_width}}" for l in labels)
    print(header)
    print("-" * len(header))
    for key, name, fmt in rows_order:
        line = f"{name:<{name_width}}"
        for label in labels:
            value = metrics_by_label[label].get(key, float("nan"))
            try:
                cell = fmt.format(value)
            except (ValueError, TypeError):
                cell = "n/a"
            line += f"{cell:>{col_width}}"
        print(line)


def main():
    strategy_name = config.STRATEGY
    strategy_module, strategy_params = STRATEGY_MODULES[strategy_name]
    loader_symbol = config.SYMBOLS[0]
    ticker = loader_symbol + ".NS"

    print(f"Running {strategy_name} on {ticker}, {config.START_DATE} to {config.END_DATE}")
    print(f"Params: {strategy_params}\n")

    strategy_result = _run_symbol(loader_symbol, ticker, strategy_module, strategy_params, strategy_name)
    bh_result = _run_symbol(loader_symbol, ticker, buy_and_hold, {}, f"{loader_symbol} Buy & Hold")
    nifty_result = _run_symbol(config.BENCHMARK_INDEX, config.BENCHMARK_INDEX, buy_and_hold, {}, "Nifty 50 Buy & Hold")

    results = {strategy_name: strategy_result, "buy_and_hold": bh_result, "nifty": nifty_result}
    metrics_by_label = {}
    for key, result in results.items():
        m = compute_metrics(
            result["equity_curve"], result["trade_log"], config.INITIAL_CAPITAL,
            result["position"], risk_free_rate=config.RISK_FREE_RATE,
        )
        metrics_by_label[result["label"]] = m

    print("=" * 100)
    print("METRICS")
    print("=" * 100)
    _print_metrics_table(metrics_by_label)

    print()
    print("=" * 100)
    print("TRADE CONTRIBUTION (strategy, closed trades only)")
    print("=" * 100)
    contrib = trade_contribution_table(strategy_result["trade_log"])
    print(contrib.to_string(index=False))

    print()
    print("=" * 100)
    print("LARGEST-TRADE SENSITIVITY")
    print("=" * 100)
    excl = exclude_largest_trade_analysis(strategy_result["trade_log"])
    for k, v in excl.items():
        print(f"{k}: {v}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    plots.plot_equity_curves(
        {result["label"]: result["equity_curve"] for result in results.values()},
        os.path.join(OUTPUT_DIR, "equity_curves.png"),
    )
    plots.plot_underwater(strategy_result["equity_curve"], os.path.join(OUTPUT_DIR, "underwater.png"))
    plots.plot_monthly_returns_heatmap(strategy_result["equity_curve"], os.path.join(OUTPUT_DIR, "monthly_returns.png"))
    plots.plot_trade_return_histogram(strategy_result["trade_log"], os.path.join(OUTPUT_DIR, "trade_return_histogram.png"))

    trade_log_path = os.path.join(OUTPUT_DIR, "trade_log.csv")
    strategy_result["trade_log"].to_csv(trade_log_path, index=False)

    print()
    print(f"Charts and trade log saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
