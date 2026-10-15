"""
engine/metrics.py

Performance metrics computed from an equity curve and a trade log (both
as produced by engine.backtest.run_backtest()).
"""

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _annualized_risk_free_daily(annual_rate: float) -> float:
    """Convert an annual risk-free rate to a daily rate (geometric, not simple division)."""
    return (1 + annual_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1


def drawdown_series_pct(equity_curve: pd.Series) -> pd.Series:
    """
    Underwater curve: for every date, how far (in percent, <= 0) equity sits
    below its highest value so far. Its minimum IS max_drawdown_pct --
    compute_metrics() below takes its figure from this function, so a chart
    of this series and the headline number cannot disagree.
    """
    running_max = equity_curve.cummax()
    return (equity_curve / running_max - 1) * 100


def growth_of_100(equity_curve: pd.Series, initial_capital: float) -> pd.Series:
    """
    Equity expressed as 'what 100 invested at the start became'. Its last value
    minus 100 IS total_return_pct, so the chart and the table agree by construction.

    Why this exists: a universe run sums one book per stock (initial_capital x N),
    while a portfolio strategy trades ONE book -- so their rupee curves are on
    different scales and cannot be drawn together. Dividing each by ITS OWN
    initial capital puts them on the same footing.
    """
    return equity_curve / initial_capital * 100


def exposure_series_pct(positions: dict) -> pd.Series:
    """
    Share of books invested on each date, in percent (0-100).

    positions: {symbol: lagged position Series (1.0 = long, 0.0 = cash)}, as
    returned in run_backtest()'s "position" for each symbol of a universe run.
    On a given date the denominator is the number of symbols that HAVE a row
    that date (a stock not yet listed is not a cash book, it is absent) and
    the numerator is how many of those are long.

    Note this weights every DATE equally, while compute_metrics()'s headline
    market_exposure_pct pools every (symbol, day) pair. The two are equal when
    every symbol covers the same dates and differ slightly otherwise.
    """
    is_long = pd.concat({s: (p == 1.0) for s, p in positions.items()}, axis=1).sort_index()
    present = is_long.notna()                      # NaN only where a symbol has no row that date
    return is_long.fillna(False).astype(float).sum(axis=1) / present.sum(axis=1) * 100


def non_cash_exposure_series_pct(dates: pd.DatetimeIndex, first_execution_date) -> pd.Series:
    """
    Exposure for a rebalanced portfolio, under the same definition
    research/run_momentum_strategy.py uses for its headline figure: 0% on
    every date before the first rebalance executes (nothing can be ranked
    until enough history exists), 100% from then on. It is NOT a measure of
    how much cash is held after that. If first_execution_date is None the
    headline treats the whole window as invested, and so does this.
    """
    if first_execution_date is None:
        return pd.Series(100.0, index=dates)
    return pd.Series(((dates >= first_execution_date) * 100.0), index=dates)


def compute_metrics(equity_curve: pd.Series, trade_log: pd.DataFrame, initial_capital: float,
                     position: pd.Series, risk_free_rate: float = 0.06) -> dict:
    """
    equity_curve: daily equity, from run_backtest().
    trade_log: closed trades only, from run_backtest() -- an open
        position at the end of the data is NOT in here and is
        deliberately excluded from every trade-level stat below (win
        rate, profit factor, etc.), since it hasn't realized a return.
    initial_capital: starting capital used for the backtest.
    position: the lagged position series, from run_backtest() -- used
        for market exposure.
    risk_free_rate: ANNUAL rate, e.g. 0.06 for 6%.

    Returns a flat dict of metric name -> value.
    """
    final_equity = equity_curve.iloc[-1]
    total_return = final_equity / initial_capital - 1

    n_days = (equity_curve.index[-1] - equity_curve.index[0]).days
    cagr = (final_equity / initial_capital) ** (365.25 / n_days) - 1 if n_days > 0 else float("nan")

    daily_returns = equity_curve.pct_change().dropna()
    rf_daily = _annualized_risk_free_daily(risk_free_rate)
    excess_returns = daily_returns - rf_daily

    sharpe = (excess_returns.mean() / daily_returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR) \
        if daily_returns.std() > 0 else float("nan")

    # Sortino: same idea as Sharpe, but the denominator only penalizes
    # downside variance. Textbook downside deviation squares the shortfall
    # below target (0 here, since we've already subtracted rf) and
    # averages over ALL periods (not just the negative ones) before
    # taking the square root -- dividing by only the negative-period count
    # would overstate downside risk.
    downside_sq = excess_returns.clip(upper=0) ** 2
    downside_deviation = np.sqrt(downside_sq.mean())
    sortino = (excess_returns.mean() / downside_deviation) * np.sqrt(TRADING_DAYS_PER_YEAR) \
        if downside_deviation > 0 else float("nan")

    max_drawdown_pct = drawdown_series_pct(equity_curve).min()
    max_drawdown_duration_days = _max_drawdown_duration_days(equity_curve)

    n_trades = len(trade_log)
    if n_trades > 0:
        pnl = _trade_pnl_rupees(trade_log)
        wins = trade_log["return_pct"] > 0
        losses = trade_log["return_pct"] < 0
        win_rate = wins.sum() / n_trades
        avg_win = trade_log.loc[wins, "return_pct"].mean() if wins.any() else float("nan")
        avg_loss = trade_log.loc[losses, "return_pct"].mean() if losses.any() else float("nan")
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = -pnl[pnl < 0].sum()
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_holding_days = trade_log["holding_days"].mean()
    else:
        win_rate = avg_win = avg_loss = profit_factor = avg_holding_days = float("nan")

    market_exposure_pct = (position == 1.0).sum() / len(position) * 100

    return {
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": max_drawdown_pct,
        "max_drawdown_duration_days": max_drawdown_duration_days,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "win_rate_pct": win_rate * 100 if n_trades > 0 else float("nan"),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor,
        "total_trades": n_trades,
        "avg_holding_days": avg_holding_days,
        "market_exposure_pct": market_exposure_pct,
        "final_equity": final_equity,
    }


def _max_drawdown_duration_days(equity_curve: pd.Series):
    """
    Longest stretch (in calendar days) between a peak in the equity
    curve and the next time equity reaches a new high. If the curve is
    still below its last peak at the end of the data, that final
    (unrecovered) stretch counts too -- capped at the last available date.
    """
    running_max = equity_curve.cummax()
    is_new_high = equity_curve >= running_max
    peak_dates = equity_curve.index[is_new_high]
    if len(peak_dates) == 0:
        return None

    durations = [(peak_dates[i + 1] - peak_dates[i]).days for i in range(len(peak_dates) - 1)]
    durations.append((equity_curve.index[-1] - peak_dates[-1]).days)  # final, possibly still-unrecovered stretch
    return max(durations)


def _trade_pnl_rupees(trade_log: pd.DataFrame) -> pd.Series:
    """Net rupee P&L per closed trade, derived from the trade log columns (no re-fetching needed)."""
    return trade_log["quantity"] * (trade_log["exit_price"] - trade_log["entry_price"]) - trade_log["total_costs"]


def trade_contribution_table(trade_log: pd.DataFrame) -> pd.DataFrame:
    """
    Each closed trade's net P&L (rupees) and its share of TOTAL REALIZED
    P&L across all closed trades -- i.e. "what fraction of the money the
    strategy actually made (or lost) came from this one trade."
    """
    pnl = _trade_pnl_rupees(trade_log)
    total_pnl = pnl.sum()

    table = trade_log[["entry_date", "exit_date", "return_pct", "holding_days"]].copy()
    table["pnl_rupees"] = pnl
    table["contribution_pct"] = pnl / total_pnl * 100 if total_pnl != 0 else float("nan")
    table = table.sort_values("pnl_rupees", ascending=False).reset_index(drop=True)
    return table


def exclude_largest_trade_analysis(trade_log: pd.DataFrame) -> dict:
    """
    Answers: "how much of the strategy's total (closed-trade) return
    comes from a single trade?" by comparing the COMPOUNDED return of
    all closed trades against the same compounding with the single
    largest-P&L trade removed.

    This uses each trade's net return_pct (already after costs) and
    compounds them multiplicatively -- valid because position sizing is
    a fixed fraction of current equity (config.POSITION_FRACTION),
    so trade-to-trade equity genuinely evolves as a product of
    (1 + return_i), not a sum. This ignores minor whole-share rounding
    drag and excludes any still-open position at the end of the data
    (which hasn't realized a return to compound).
    """
    if len(trade_log) == 0:
        return {"note": "No closed trades to analyze."}

    pnl = _trade_pnl_rupees(trade_log)
    largest_idx = pnl.idxmax()
    largest_trade = trade_log.loc[largest_idx]

    multipliers = 1 + trade_log["return_pct"] / 100
    compounded_all = multipliers.prod() - 1

    multipliers_excl = multipliers.drop(largest_idx)
    compounded_excl = multipliers_excl.prod() - 1 if len(multipliers_excl) > 0 else 0.0

    return {
        "largest_trade_entry_date": largest_trade["entry_date"],
        "largest_trade_exit_date": largest_trade["exit_date"],
        "largest_trade_return_pct": largest_trade["return_pct"],
        "largest_trade_pnl_rupees": pnl.loc[largest_idx],
        "compounded_return_all_trades_pct": compounded_all * 100,
        "compounded_return_excluding_largest_pct": compounded_excl * 100,
    }
