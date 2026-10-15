"""
engine/portfolio_backtest.py

Backtests a WEIGHT-TARGET strategy (e.g. cross-sectional momentum) that
holds ONE shared portfolio across many symbols simultaneously, rebalanced
periodically -- a fundamentally different money model from
engine/backtest.py's N independent, separately-capitalized per-symbol
books. Does NOT modify or replace engine/backtest.py, which is correct
and tested for what it does; this is a second engine for a genuinely
different kind of strategy. See MOMENTUM_METHODOLOGY.md Section 2 for
why a per-symbol engine cannot express "hold whichever names rank
highest this month, sized as fractions of one shared portfolio."

LOOK-AHEAD DISCIPLINE (same principle as engine/backtest.py, expressed
differently): target_weights (from e.g.
strategies/cross_sectional_momentum.generate_target_weights()) are set
as of a formation date using only that date's close and earlier --
enforced by construction in the strategy module, not here. This engine's
own obligation is the execution side: a rebalance implied by formation
date T's weights is only ever executed at the FIRST TRADING DAY STRICTLY
AFTER T, at that day's open -- never on T itself, never at T's close.
`_map_formations_to_execution_dates` is the one place that mapping
happens; `test_portfolio_backtest.py` verifies it directly by changing a
post-execution-date price and confirming it cannot change what was
already traded.
"""

import pandas as pd

import config
import costs
from validator import assert_backtest_safe


def _eligible_symbols(universe_data: dict, start: str, end: str, override_discontinuity_gate: bool) -> tuple:
    """
    Pre-filters to symbols with no unresolved discontinuity-gate block
    anywhere in [start, end] -- checked ONCE, up front. A cross-sectional
    strategy can select a symbol on any formation date within the
    window, not just at one known entry point the way a per-symbol
    strategy does, so a blocked symbol is excluded from ranking
    ELIGIBILITY for the whole window, never selectable, rather than
    checked trade-by-trade.
    """
    eligible, blocked = {}, []
    for ticker, entry in universe_data.items():
        try:
            assert_backtest_safe(entry["report"], start, end, override=override_discontinuity_gate)
            eligible[ticker] = entry
        except RuntimeError as e:
            blocked.append((ticker, str(e)))
    return eligible, blocked


def _map_formations_to_execution_dates(formation_dates, window_dates: list) -> dict:
    """
    Maps each formation date to the first WINDOW trading day strictly
    after it -- the day its rebalance actually executes. A formation
    date with no later date in the window (e.g. the last formation date
    before `end`, with no more trading days left) produces no
    executable rebalance and is correctly dropped, not forced.
    """
    mapping = {}
    for f_date in formation_dates:
        later = [d for d in window_dates if d > f_date]
        if later:
            mapping[later[0]] = f_date
    return mapping


def run_portfolio_backtest(universe_data: dict, target_weights: pd.DataFrame, start: str, end: str,
                            initial_capital: float = None, slippage_pct_override: float = None,
                            override_discontinuity_gate: bool = False) -> dict:
    """
    universe_data: {ticker: {"df": OHLCV DataFrame, "report": validator report}}.
    target_weights: from strategies/cross_sectional_momentum.py, computed
        on universe_data's FULL history (for correct lookback) -- indexed
        by formation date, one column per ticker, values = target weight
        effective from the next trading day's open.
    start, end: the window this backtest actually simulates -- same
        restriction discipline as engine/backtest.py's date-window fix.
        The portfolio starts on `start` already holding whatever the most
        recent formation date AT OR BEFORE `start` prescribes (using
        only real, already-public information) rather than pretending to
        have no memory of history before the window -- the same
        principle engine/backtest.py applies when a moving-average
        signal is already trending into a window's first day.

    Returns {"equity_curve": pd.Series, "trade_log": pd.DataFrame (one
    row per executed leg), "rebalance_log": pd.DataFrame (one row per
    rebalance: formation/execution date, names held, turnover),
    "blocked": [(ticker, reason)], "eligible_symbols": list}.
    """
    initial_capital = config.INITIAL_CAPITAL if initial_capital is None else initial_capital
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)

    eligible, blocked = _eligible_symbols(universe_data, start, end, override_discontinuity_gate)
    if not eligible:
        raise ValueError("No eligible symbols (all blocked by the discontinuity gate) -- nothing to backtest.")

    closes = {t: e["df"]["close"] for t, e in eligible.items()}
    opens = {t: e["df"]["open"] for t, e in eligible.items()}

    # Trading calendar for the window: the union of every eligible
    # symbol's own trading days within [start, end] -- a symbol not yet
    # listed simply has no rows here yet (same convention as
    # engine/universe.py's pre-listing handling).
    window_dates = sorted(set().union(*(c.loc[start_ts:end_ts].index for c in closes.values())))
    if not window_dates:
        raise ValueError(f"No trading days in [{start}, {end}] for any eligible symbol.")

    # MARK-TO-MARKET CLOSES, forward-filled onto the FULL window
    # calendar. Without this, a currently-held symbol missing a row on
    # some date (a data gap, or a bad print dropped by
    # data/loader.py's phantom-row filter that another symbol didn't
    # share) makes `closes[t].get(date, 0.0)` silently price that
    # holding at ZERO for the day -- a real bug this project's own
    # design philosophy exists to prevent (see data/loader.py's
    # docstring on the exact same failure mode for a delisted symbol).
    # Caught by hand-tracing a genuine run: 2025-03-18 is a known
    # market-wide data artifact (data/known_issues.md) that
    # data/loader.py correctly strips from every symbol's OWN frame --
    # but the window's UNION calendar still includes that date because
    # at least one OTHER (non-held) symbol in the universe still has a
    # row for it, so every held symbol missing that date got marked to
    # zero, producing a fabricated ~99.8% one-day "crash" that reverted
    # the next day. Forward-filling means a missing day just carries the
    # last real price forward -- correct, since nothing traded that
    # symbol that day, its marked value hasn't changed. Trades
    # themselves are NOT affected by this -- `opens` (below) is left
    # un-filled on purpose, so a rebalance still correctly refuses to
    # trade a symbol with no real open price that day (see the
    # `open_price is None` guards in the loop below), rather than
    # inventing a fill price to trade at.
    # fillna(0.0) AFTER ffill() catches the one gap forward-fill cannot:
    # dates before a symbol's own first real row (e.g. a late listing --
    # ETERNAL in 2021, JIOFIN in 2023 -- inside an early window like
    # 2015-2020). ffill() alone leaves genuine NaN there, and
    # `shares[t] * NaN` is NaN in Python even when shares[t] == 0,
    # which poisons the WHOLE portfolio's summed equity for every day
    # until that symbol lists -- caught because the in-sample window's
    # entire Sharpe/CAGR came back NaN on the first real run. Safe
    # because a symbol can only ever be bought (shares[t] > 0) on a date
    # where it has a REAL open price (see the buy loop's `open_price is
    # None` guard below) -- by the time shares[t] is ever nonzero,
    # marking_closes[t] already has real, forward-filled values, never
    # NaN. The 0.0 here is only ever multiplied by a guaranteed-zero
    # share count.
    marking_closes = {t: c.reindex(window_dates).ffill().fillna(0.0) for t, c in closes.items()}

    # A formation date at or before `start` still matters (see the
    # module docstring: the window doesn't pretend to have no memory of
    # history before it) and is included via `<= end_ts` below.
    # _map_formations_to_execution_dates already maps EVERY formation
    # date -- including one from before the window -- to the first
    # WINDOW date strictly after it, so a pre-window formation
    # automatically executes on window_dates[0] (as long as it doesn't
    # equal window_dates[0] exactly, in which case honest execution is
    # correctly window_dates[1], not the same day -- executing on the
    # same day as the formation date would be look-ahead). Later
    # formation dates naturally overwrite earlier ones that map to the
    # same execution date, since `relevant_formations` is processed in
    # ascending order -- the most recent known formation wins, not a
    # stale one. No separate "catch-up" step is needed or safe to add.
    relevant_formations = target_weights.index[target_weights.index <= end_ts]
    formation_to_exec_date = _map_formations_to_execution_dates(relevant_formations, window_dates)

    tickers = list(eligible.keys())
    cash = initial_capital
    shares = {t: 0 for t in tickers}

    trades = []
    rebalance_log = []
    equity_curve = pd.Series(index=window_dates, dtype=float)

    for date in window_dates:
        if date in formation_to_exec_date:
            f_date = formation_to_exec_date[date]
            new_weights = target_weights.loc[f_date].reindex(tickers).fillna(0.0)

            # Size every target position off portfolio value marked at
            # TODAY's open where a real one exists (the same price the
            # rebalance trades themselves execute at), falling back to
            # the forward-filled close (never a raw, possibly-missing
            # close) for a held symbol with no trade today.
            portfolio_value = cash + sum(
                shares[t] * opens[t].get(date, marking_closes[t].get(date, 0.0)) for t in tickers
            )

            turnover_value = 0.0

            # Sells first -- frees cash before buy sizing needs it.
            for t in tickers:
                open_price = opens[t].get(date)
                if open_price is None or open_price <= 0 or shares[t] == 0:
                    continue
                target_value = new_weights[t] * portfolio_value
                current_value = shares[t] * open_price
                if target_value >= current_value:
                    continue
                target_shares = int(target_value // open_price) if target_value > 0 else 0
                sell_shares = shares[t] - target_shares
                if sell_shares <= 0:
                    continue
                proceeds = sell_shares * open_price
                sell_costs = costs.calculate_trade_cost(proceeds, "sell", slippage_pct_override=slippage_pct_override)
                cash += proceeds - sell_costs["total"]
                shares[t] = target_shares
                turnover_value += proceeds
                trades.append({"date": date, "symbol": t, "side": "sell", "shares": sell_shares,
                                "price": open_price, "costs": sell_costs["total"]})

            # Then buys, sized off the cash sells just freed.
            for t in tickers:
                open_price = opens[t].get(date)
                if open_price is None or open_price <= 0:
                    continue
                target_value = new_weights[t] * portfolio_value
                target_shares = int(target_value // open_price) if target_value > 0 else 0
                buy_shares = target_shares - shares[t]
                if buy_shares <= 0:
                    continue
                trade_value = buy_shares * open_price
                buy_costs = costs.calculate_trade_cost(trade_value, "buy", slippage_pct_override=slippage_pct_override)
                total_cost = trade_value + buy_costs["total"]
                if total_cost > cash:
                    buy_shares = int(cash // (open_price * (1 + 0.002)))  # conservative: leave room for costs
                    if buy_shares <= 0:
                        continue
                    trade_value = buy_shares * open_price
                    buy_costs = costs.calculate_trade_cost(trade_value, "buy", slippage_pct_override=slippage_pct_override)
                    total_cost = trade_value + buy_costs["total"]
                cash -= total_cost
                shares[t] += buy_shares
                turnover_value += trade_value
                trades.append({"date": date, "symbol": t, "side": "buy", "shares": buy_shares,
                                "price": open_price, "costs": buy_costs["total"]})

            rebalance_log.append({
                "formation_date": f_date, "execution_date": date,
                "n_held": int((new_weights > 0).sum()),
                "turnover_value": turnover_value,
                "portfolio_value_pre_rebalance": portfolio_value,
                "turnover_pct": turnover_value / portfolio_value * 100 if portfolio_value > 0 else 0.0,
            })

        equity_curve.loc[date] = cash + sum(shares[t] * marking_closes[t].get(date, 0.0) for t in tickers)

    return {
        "equity_curve": equity_curve,
        "trade_log": pd.DataFrame(trades),
        "rebalance_log": pd.DataFrame(rebalance_log),
        "blocked": blocked,
        "eligible_symbols": tickers,
        "final_shares": shares,
    }
