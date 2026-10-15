"""
engine/sweep.py

Grid search over strategy parameters, evaluated across the whole
universe (not one symbol) so every grid cell's stats are backed by a
pooled trade count instead of a handful of trades from a single stock.
"""

import pandas as pd

from universe import run_strategy_on_universe


def run_ma_crossover_sweep(universe_data: dict, fast_values: list, slow_values: list,
                            start: str, end: str, verbose: bool = True) -> pd.DataFrame:
    """
    Runs ma_crossover across universe_data for every (fast, slow) pair
    where fast < slow (fast >= slow isn't a valid crossover and is
    skipped). universe_data should already be loaded via
    universe.load_universe() -- this function does no downloading.

    Returns a DataFrame, one row per (fast, slow) combination, with the
    aggregate metrics for that combination across the whole universe.
    """
    import ma_crossover  # imported here, not at module level, to avoid a hard dependency for callers that only sweep other strategies later

    rows = []
    total = sum(1 for f in fast_values for s in slow_values if f < s)
    done = 0

    for fast in fast_values:
        for slow in slow_values:
            if fast >= slow:
                continue
            result = run_strategy_on_universe(
                universe_data, ma_crossover, {"fast": fast, "slow": slow},
                start, end, verbose=False,
            )
            m = result["aggregate_metrics"]
            rows.append({
                "fast": fast,
                "slow": slow,
                "cagr_pct": m.get("cagr_pct", float("nan")),
                "sharpe_ratio": m.get("sharpe_ratio", float("nan")),
                "sortino_ratio": m.get("sortino_ratio", float("nan")),
                "max_drawdown_pct": m.get("max_drawdown_pct", float("nan")),
                "total_trades": m.get("total_trades", 0),
                "win_rate_pct": m.get("win_rate_pct", float("nan")),
                "profit_factor": m.get("profit_factor", float("nan")),
            })
            done += 1
            if verbose and done % 10 == 0:
                print(f"[sweep] {done}/{total} parameter combinations done")

    if verbose:
        print(f"[sweep] {done}/{total} parameter combinations done")

    return pd.DataFrame(rows)
