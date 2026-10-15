"""
strategies/ma_crossover.py

Moving-average crossover strategy: go long when the fast (short-window)
moving average is above the slow (long-window) moving average, hold cash
otherwise. Classic trend-following signal.
"""

import pandas as pd

from base import validate_signals


def moving_average(close: pd.Series, window: int) -> pd.Series:
    """
    Simple moving average of `close` over `window` trading days; NaN until
    `window` days of history exist. This is the one place the strategy's
    average is computed -- generate_signals() below calls it, and the web
    app's chart reads the same function, so the line drawn on a chart is
    by construction the line the strategy traded on.
    """
    return close.rolling(window=window).mean()


def generate_signals(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    """
    df must have a 'close' column.
    fast, slow: moving average windows, in trading days.

    Returns a float Series indexed like df:
    - NaN for the warm-up period (fewer than `slow` days of history yet)
    - 1.0 when fast MA > slow MA (long)
    - 0.0 otherwise (cash)
    """
    fast_ma = moving_average(df["close"], fast)
    slow_ma = moving_average(df["close"], slow)

    signal = (fast_ma > slow_ma).astype(float)
    # rolling() leaves the first (window-1) rows of each MA as NaN. The
    # comparison above turns "NaN > NaN" into False (0.0), which is wrong:
    # there's no MA to compare yet, so the signal is undefined, not "cash".
    # Restore NaN wherever either MA isn't computable yet.
    signal[fast_ma.isna() | slow_ma.isna()] = float("nan")
    signal.name = "signal"

    validate_signals(signal, df)
    return signal


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "../data")
    from loader import load_price_data

    df = load_price_data("RELIANCE", "2024-01-01", "2024-12-31")
    signal = generate_signals(df, fast=50, slow=200)
    print(pd.concat([df["close"], signal], axis=1).tail(10))
