"""
strategies/rsi_reversion.py

RSI (Relative Strength Index) mean-reversion strategy: go long when RSI
falls into oversold territory, exit back to cash once it recovers past
the midpoint. Implemented manually with pandas -- no TA library.

RSI smoothing method: this uses WILDER'S SMOOTHING, the original RSI
definition (and what most charting platforms, e.g. TradingView, use) --
NOT a simple moving average of gains and losses. The two give different
RSI values on identical price data:
- Simple-MA RSI re-averages the last `period` days' gains/losses equally
  every time, so it reacts quickly whenever an old data point rolls off
  the window.
- Wilder's smoothing is a recursive exponential average (each day's
  average = mostly yesterday's average, plus a small pull from today),
  so it reacts more slowly and never fully "forgets" old data.
We use Wilder's here so the values match what you'd see on a normal
chart or broker platform, since that's almost certainly what "RSI" means
to you already.
"""

import pandas as pd

from base import validate_signals


def _wilders_rsi(close: pd.Series, period: int) -> pd.Series:
    """
    Compute RSI using Wilder's original smoothing method (the textbook
    definition, not an approximation via pandas' built-in .ewm()).

    Steps:
    1. Daily price change -> split into "gain" (up moves, 0 on down days)
       and "loss" (down moves stored as a positive number, 0 on up days).
    2. Seed the average gain/loss as a plain average of the first
       `period` days.
    3. From the next day onward, smooth recursively:
           avg_today = (avg_yesterday * (period - 1) + value_today) / period
       This recursive formula IS Wilder's smoothing. It's mathematically
       the same shape as an exponential moving average with
       alpha = 1/period, but pandas' .ewm() seeds itself from the very
       first data point rather than a period-average, which would give
       very slightly different values for the first several dozen rows.
       Seeding manually here matches Wilder's original hand calculation
       exactly.
    4. RS (relative strength) = avg_gain / avg_loss.
       RSI = 100 - 100 / (1 + RS).

    A plain Python loop is used for step 3 on purpose: it makes the
    recursive formula explicit and easy to check by hand against a
    calculator, and RSI over a decade of daily data is only ~2700 rows,
    so performance is not a concern here.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)  # stored as a positive number

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    # close.diff() leaves gain[0]/loss[0] as NaN (there's no prior day to
    # diff against), which pulls the very first valid rolling-mean position
    # to `period`, not `period - 1` as you'd expect from the window size
    # alone -- rolling().mean() needs `period` non-NaN values, and that
    # first NaN pushes the window that satisfies it one row later. Find the
    # seed position directly instead of assuming period - 1, so this stays
    # correct even if that leading-NaN behaviour ever changes.
    seed_pos = avg_gain.index.get_loc(avg_gain.first_valid_index())
    for i in range(seed_pos + 1, len(close)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Public name for the strategy's RSI series (Wilder's smoothing; see
    _wilders_rsi). Added so the web app's chart can plot the exact series
    the strategy trades on without reaching for a private function or
    recomputing it. Identical to _wilders_rsi -- no behaviour of its own.
    """
    return _wilders_rsi(close, period)


def generate_signals(df: pd.DataFrame, period: int = 14, oversold: float = 30, exit_level: float = 50) -> pd.Series:
    """
    df must have a 'close' column.
    period: RSI lookback window (default 14, the standard).
    oversold: enter long when RSI drops below this (default 30).
    exit_level: exit to cash when RSI rises above this (default 50).

    Returns a float Series indexed like df, holding position state:
    - NaN for the warm-up period (fewer than `period` days of history yet)
    - 1.0 while long, 0.0 while in cash

    This is a STATEFUL threshold strategy, not a per-day snapshot: once
    RSI drops below `oversold` and you enter, you STAY long -- even while
    RSI sits in the 30-50 zone -- until RSI actually rises above
    `exit_level`. Without this hold behaviour, the signal would flicker
    on and off every time RSI wobbled near the oversold line, which
    isn't what "enter at 30, exit at 50" means as a trading rule. Before
    the first entry, position defaults to cash (0.0).
    """
    rsi = _wilders_rsi(df["close"], period)

    signal = pd.Series(index=df.index, dtype=float)
    position = 0.0  # start in cash, before any entry has triggered

    for i in range(len(df)):
        if pd.isna(rsi.iloc[i]):
            signal.iloc[i] = float("nan")
            continue
        if position == 0.0 and rsi.iloc[i] < oversold:
            position = 1.0
        elif position == 1.0 and rsi.iloc[i] > exit_level:
            position = 0.0
        signal.iloc[i] = position

    signal.name = "signal"

    validate_signals(signal, df)
    return signal


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "../data")
    from loader import load_price_data

    df = load_price_data("RELIANCE", "2024-01-01", "2024-12-31")
    rsi = _wilders_rsi(df["close"], 14)
    signal = generate_signals(df, period=14, oversold=30, exit_level=50)
    print(pd.concat([df["close"], rsi.rename("rsi"), signal], axis=1).tail(10))
