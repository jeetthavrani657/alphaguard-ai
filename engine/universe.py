"""
engine/universe.py

Runs a strategy across many symbols at once and aggregates the results.
This is the core of Stage 5: a single symbol gives ~6 trades, which is
not a sample. Pooling trades across dozens of symbols is.
"""

import pandas as pd

import config
from loader import load_price_data
from validator import validate_price_data
from backtest import run_backtest
from metrics import compute_metrics


def load_universe(symbols: list, start: str, end: str, verbose: bool = True) -> tuple:
    """
    Loads and validates every symbol ONCE (reused across every strategy
    run and every parameter combination that follows -- no repeated
    downloads or repeated corporate-actions lookups).

    Returns (data, failed):
      data: {ticker: {"df": df, "report": report, "symbol": symbol}}
      failed: [(symbol, error message), ...] for anything that couldn't
        be loaded at all (bad symbol, no data, etc.) -- skipped, not
        silently dropped: the caller sees exactly what didn't make it in.
    """
    data = {}
    failed = []
    for symbol in symbols:
        ticker = symbol if symbol.startswith("^") else symbol + ".NS"
        try:
            df = load_price_data(symbol, start, end)
            report = validate_price_data(df, ticker)
            data[ticker] = {"df": df, "report": report, "symbol": symbol}
        except Exception as e:
            failed.append((symbol, str(e)))

    if verbose:
        print(f"[universe] Loaded {len(data)}/{len(symbols)} symbols.")
        if failed:
            print(f"[universe] {len(failed)} symbol(s) failed to load and were skipped:")
            for symbol, err in failed:
                print(f"  {symbol}: {err}")
    return data, failed


def run_strategy_on_universe(universe_data: dict, strategy_module, strategy_params: dict,
                              start: str, end: str, initial_capital: float = None,
                              override_discontinuity_gate: bool = False, verbose: bool = True,
                              slippage_pct_by_symbol: dict = None) -> dict:
    """
    Runs one strategy independently on every symbol in universe_data.
    Each symbol gets its own fresh `initial_capital` -- these are
    parallel books of equal size, not one shared pool, which is what
    makes summing them into a combined equity curve meaningful.

    A symbol whose date range overlaps an unresolved discontinuity
    (ARTIFACT or UNREVIEWED -- see data/discontinuity_registry.py) is
    BLOCKED by run_backtest()'s gate, exactly as designed. This function
    does not override that; it catches the block, excludes that symbol
    from the aggregate, and reports it -- it does not silently swallow
    the block, and it does not crash the whole universe run over one
    symbol's known issue.

    slippage_pct_by_symbol: optional {ticker: slippage_pct} map, e.g.
        from research/liquidity_costs.py's per-symbol ADV-based
        estimate. A symbol missing from the map falls back to
        config.COSTS's flat default. None (the default) reproduces
        the exact prior flat-rate-for-everyone behavior.

    Returns:
      {"per_symbol": {ticker: run_backtest() result, ...},
       "blocked": [(ticker, error message), ...],
       "combined_equity_curve": pd.Series (sum of every included symbol's equity curve),
       "pooled_trade_log": pd.DataFrame (every included symbol's closed trades, with a 'symbol' column),
       "aggregate_metrics": dict}
    """
    initial_capital = config.INITIAL_CAPITAL if initial_capital is None else initial_capital
    slippage_pct_by_symbol = slippage_pct_by_symbol or {}

    per_symbol = {}
    blocked = []
    equity_curves = []
    trade_logs = []
    position_series = []

    for ticker, entry in universe_data.items():
        df, report = entry["df"], entry["report"]
        try:
            # A symbol with fewer trading days than the strategy's own
            # warm-up window (e.g. a stock listed 34 days ago being run
            # through an MA-200 rule) makes generate_signals() return an
            # entirely-NaN series -- validate_signals() correctly raises
            # rather than fake a signal. That's not a bug to catch and
            # hide; it's a real "this symbol cannot be traded with this
            # configuration" case, handled the same way a gate block is:
            # excluded from the aggregate, reported, batch continues.
            signal = strategy_module.generate_signals(df, **strategy_params)
            result = run_backtest(
                df, signal, report, start, end,
                initial_capital=initial_capital,
                override_discontinuity_gate=override_discontinuity_gate,
                slippage_pct_override=slippage_pct_by_symbol.get(ticker),
            )
        except RuntimeError as e:
            blocked.append((ticker, str(e)))
            continue
        except AssertionError as e:
            blocked.append((ticker, f"insufficient history for this strategy's warm-up period: {e}"))
            continue
        except ValueError as e:
            # run_backtest() raises ValueError when a symbol has zero rows
            # inside [start, end] -- e.g. a 2023 IPO queried on a
            # 2015-2020 "in-sample" window. Not a crash: this symbol
            # simply didn't exist yet during this window, excluded the
            # same way a gate block or warm-up shortfall is.
            blocked.append((ticker, f"no data in this window: {e}"))
            continue

        per_symbol[ticker] = result
        equity_curves.append(result["equity_curve"].rename(ticker))
        position_series.append(result["position"])

        tl = result["trade_log"].copy()
        tl.insert(0, "symbol", ticker)
        trade_logs.append(tl)

    if verbose and blocked:
        print(f"[universe] {len(blocked)} symbol(s) blocked by the discontinuity gate and excluded:")
        for ticker, _ in blocked:
            print(f"  {ticker}")

    if not equity_curves:
        return {"per_symbol": {}, "blocked": blocked, "combined_equity_curve": pd.Series(dtype=float),
                "pooled_trade_log": pd.DataFrame(), "aggregate_metrics": {}}

    # Combined equity curve: align every symbol's curve on the union of
    # dates, then sum across symbols -- equivalent to running N
    # equal-sized books in parallel and looking at total wealth.
    #
    # Several universe symbols listed AFTER 2015 (e.g. JIOFIN in 2023,
    # ETERNAL in 2021) -- their equity_curve simply doesn't have rows
    # before their listing date. A plain .ffill() would leave those
    # leading rows as NaN, and .sum(skipna=True) would then silently
    # drop that book from the total for the whole pre-listing period --
    # understating combined equity (and the total_return/CAGR computed
    # against initial_capital * n_symbols below) for years at a stretch.
    # The economically correct treatment is: before a symbol lists, its
    # book is 100% uninvested cash, sitting flat at initial_capital --
    # not zero and not simply absent. ffill() handles ordinary mid-series
    # gaps (a symbol's own missing trading days); fillna(initial_capital)
    # afterward catches only the genuine leading gap.
    combined = pd.concat(equity_curves, axis=1).sort_index().ffill()
    combined = combined.fillna(initial_capital)
    combined_equity_curve = combined.sum(axis=1)

    pooled_trade_log = pd.concat(trade_logs, ignore_index=True) if trade_logs else pd.DataFrame()

    # Pooled position, purely for the market-exposure stat -- concatenated
    # (not date-aligned) since only the fraction of long days matters here.
    pooled_position = pd.concat(position_series, ignore_index=True)

    aggregate_metrics = compute_metrics(
        combined_equity_curve, pooled_trade_log,
        initial_capital=initial_capital * len(equity_curves),
        position=pooled_position,
        risk_free_rate=config.RISK_FREE_RATE,
    )
    aggregate_metrics["n_symbols_included"] = len(equity_curves)

    return {
        "per_symbol": per_symbol,
        "blocked": blocked,
        "combined_equity_curve": combined_equity_curve,
        "pooled_trade_log": pooled_trade_log,
        "aggregate_metrics": aggregate_metrics,
    }


def per_symbol_comparison_table(universe_result: dict) -> pd.DataFrame:
    """One row per symbol: its own metrics, for the per-symbol comparison view."""
    rows = []
    for ticker, result in universe_result["per_symbol"].items():
        m = compute_metrics(
            result["equity_curve"], result["trade_log"], config.INITIAL_CAPITAL,
            result["position"], risk_free_rate=config.RISK_FREE_RATE,
        )
        m["symbol"] = ticker
        rows.append(m)
    df = pd.DataFrame(rows).set_index("symbol")
    return df
