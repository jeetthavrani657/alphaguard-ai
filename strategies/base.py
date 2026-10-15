"""
strategies/base.py

Shared interface both strategy modules follow:

    generate_signals(df, **params) -> pd.Series

- df must have a 'close' column (extra columns are fine, ignored).
- Returns a Series indexed the same as df.
- Values are 1.0 (long) or 0.0 (cash), except during each indicator's
  warm-up period (not enough history yet to compute a signal), where
  the value is NaN.

No class hierarchy or plugin registry here. With two strategies, both
plain functions sharing one signature, there's nothing a base class or
registry would buy that a shared naming convention doesn't already give.
The one genuinely shared need is checking that a strategy's output
actually honors the contract above -- so that lives here as a plain
function both strategies (and later the engine) can call, rather than
each strategy re-checking its own output slightly differently.
"""

import pandas as pd


def validate_signals(signals: pd.Series, df: pd.DataFrame) -> None:
    """
    Check that a signal Series honors the shared strategy contract.
    Raises AssertionError with a clear message if it doesn't.
    """
    assert len(signals) == len(df), (
        f"Signal length ({len(signals)}) does not match input length ({len(df)})"
    )
    assert signals.index.equals(df.index), "Signal index does not match input DataFrame's index"

    after_warmup = signals.dropna()
    assert not after_warmup.empty, "Signal is entirely NaN -- warm-up period covers the whole series"
    assert after_warmup.isin([0.0, 1.0]).all(), (
        "Signal contains a value other than 0 or 1 after the warm-up period"
    )
