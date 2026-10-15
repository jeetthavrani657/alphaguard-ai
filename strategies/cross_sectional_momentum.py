"""
strategies/cross_sectional_momentum.py

Cross-sectional momentum: rank every symbol in a universe against each
OTHER at each monthly formation date by trailing 12-1 return, and select
the top N. This is fundamentally different from every other strategy in
this project (ma_crossover.py, rsi_reversion.py) -- those rank a symbol
against its OWN history and return a per-symbol long/cash signal;
this ranks symbols against EACH OTHER and returns a per-UNIVERSE set of
selections. See MOMENTUM_METHODOLOGY.md (frozen 2026-09-06, before any
result existed) for the economic rationale and every parameter choice
below, none of which are free -- change none of them without a new,
separately-registered hypothesis.

Still a pure function: universe price data in, target weights out. No
knowledge of money, costs, or execution -- same boundary as every other
strategies/*.py module, just operating on a dict of symbols instead of
one DataFrame.
"""

import pandas as pd

LOOKBACK_DAYS = 252   # ~12 months of trading days
SKIP_DAYS = 21        # ~1 month, skipped per the standard "12-1" convention
TOP_N = 10            # top quintile of a 50-symbol universe -- MOMENTUM_METHODOLOGY.md Section 1


def _month_end_dates(all_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """
    The last trading day of every calendar month present in the union of
    the universe's trading calendar -- these are the formation dates.
    Grouping by (year, month) and taking the max date per group is
    calendar-correct regardless of NSE holidays shifting a month's last
    trading day around (no assumption that it's always the 28th/30th/31st).
    """
    dates = pd.Series(all_dates, index=all_dates)
    period = dates.index.to_period("M")
    return dates.groupby(period).max().sort_values().to_numpy()


def _momentum_score(close: pd.Series, formation_date: pd.Timestamp) -> float:
    """
    Trailing 12-1 momentum score as of formation_date: the return from
    (formation_date - LOOKBACK_DAYS trading days) to (formation_date -
    SKIP_DAYS trading days), skipping the most recent ~month per
    MOMENTUM_METHODOLOGY.md Section 1. Returns NaN if the symbol doesn't
    have LOOKBACK_DAYS of history as of formation_date (a genuine "not
    enough history yet," never a fabricated score) or if formation_date
    is not (on or after) a date this symbol has actually traded.
    """
    history = close.loc[:formation_date]
    if len(history) < LOOKBACK_DAYS + 1:
        return float("nan")
    recent_price = history.iloc[-1 - SKIP_DAYS]
    old_price = history.iloc[-1 - LOOKBACK_DAYS]
    return recent_price / old_price - 1.0


def generate_target_weights(universe_data: dict, lookback_days: int = LOOKBACK_DAYS,
                             skip_days: int = SKIP_DAYS, top_n: int = TOP_N) -> pd.DataFrame:
    """
    universe_data: {ticker: {"df": DataFrame with a 'close' column, ...}}
    -- same shape as engine.universe.load_universe()'s return value.

    Returns a DataFrame indexed by FORMATION DATE (the last trading day
    of each calendar month present in the universe), one column per
    ticker, values = target portfolio weight effective from the NEXT
    trading day's open (long-only, equal-weight: 1/top_n for that
    month's top-ranked names by trailing 12-1 return, 0.0 for
    everyone else, including any ticker without enough history yet to
    be ranked at all -- MOMENTUM_METHODOLOGY.md Section 1). This
    function only ever uses price history UP TO AND INCLUDING each
    formation date -- executing on this is the caller's (engine/
    portfolio_backtest.py's) responsibility, at the next trading day's
    open, same look-ahead convention as engine/backtest.py.
    """
    closes = {ticker: entry["df"]["close"] for ticker, entry in universe_data.items()}
    all_dates = sorted(set().union(*(c.index for c in closes.values())))
    formation_dates = _month_end_dates(pd.DatetimeIndex(all_dates))

    weights = pd.DataFrame(0.0, index=formation_dates, columns=list(closes.keys()))

    for formation_date in formation_dates:
        scores = {}
        for ticker, close in closes.items():
            score = _momentum_score(close, pd.Timestamp(formation_date))
            if not pd.isna(score):
                scores[ticker] = score

        if not scores:
            continue  # no symbol has enough history yet -- every weight stays 0 for this date

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        selected = [ticker for ticker, _ in ranked[:top_n]]
        weights.loc[formation_date, selected] = 1.0 / len(selected)

    return weights


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "../data")
    sys.path.insert(0, "../engine")
    sys.path.insert(0, "..")
    import config
    from universe import load_universe

    data, _ = load_universe(config.UNIVERSE[:10], config.START_DATE, config.END_DATE, verbose=False)
    w = generate_target_weights(data)
    print(w.tail(3).T)
