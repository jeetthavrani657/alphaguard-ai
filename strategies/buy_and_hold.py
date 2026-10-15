"""
strategies/buy_and_hold.py

Trivial "strategy": always long, for every row. This exists so the
buy-and-hold benchmark in engine/metrics.py can be run through the exact
same engine.run_backtest() as a real strategy -- same look-ahead lag,
same next-day-open execution assumption, same cost model -- instead of
a separately hand-rolled benchmark calculation that could quietly drift
out of sync with how real trades are costed.
"""

import pandas as pd

from base import validate_signals


def generate_signals(df: pd.DataFrame, **params) -> pd.Series:
    """
    Always 1.0 (long). No warm-up period -- there's no indicator here,
    so nothing needs history to "warm up" before it's valid. **params
    is accepted (and ignored) only to match the shared strategy
    signature; buy-and-hold takes no parameters.
    """
    signal = pd.Series(1.0, index=df.index, name="signal")
    validate_signals(signal, df)
    return signal
