"""
strategies/dip_target.py

"Buy the dip, take a small profit" -- a strategy built to maximize WIN RATE
rather than expectancy, at the owner's request (target: 90% of closed
trades profitable).

Rule:
- ENTER long when RSI(14) falls below `oversold` (same oversold signal as
  rsi_reversion.py -- a sharp short-term drop).
- EXIT only when price has risen `take_profit` (e.g. 3%) above the close
  the entry signal fired on.
- Optionally EXIT at a loss if price falls `stop_loss` below that close.
  With stop_loss=None (the maximum-win-rate version) a losing position is
  simply held, however long it takes and however far it falls.

Why this is a different animal from the other strategies, and why its win
rate is not evidence of profit: a win rate is just the share of CLOSED
trades that made money. Taking a small fixed profit and never realizing a
loss pushes that share toward 100% by construction -- the losing trades
don't show up as losses, they show up as positions that are still open.
engine/metrics.py (correctly) counts only closed trades, so for this
strategy the win rate has to be read together with the open positions and
their unrealized loss; research/run_dip_target_strategy.py reports both.
Small wins capped at `take_profit`, uncapped losses: that asymmetry is the
entire trade-off, and it is why high-win-rate/no-stop strategies are
famous for working steadily until they don't.

Like rsi_reversion.py, this is a STATEFUL rule -- once in a position it
stays until an exit condition fires. The stateful loop is a separate pure
function so its exit logic can be tested on hand-built numbers.
"""

import pandas as pd

from base import validate_signals
from rsi_reversion import _wilders_rsi


def _stateful_signal(close: pd.Series, rsi: pd.Series, oversold: float,
                     take_profit: float, stop_loss,
                     entry_ok: pd.Series = None, max_hold_days: int = None) -> pd.Series:
    """
    close, rsi: same index. Returns 1.0 (long) / 0.0 (cash) / NaN (RSI not
    yet defined). `entry_close` is the close on the day the entry signal
    fired; take-profit and stop-loss are measured from it. `entry_ok`
    (optional, same index) is an extra yes/no gate on entries -- e.g.
    "price is above its 200-day average" -- and `max_hold_days` (optional)
    force-exits a position that hasn't hit either level after that many
    bars, so no loser can sit open indefinitely. (The engine
    fills one bar later, at the next open, and measures the REAL trade
    return from that fill -- this reference price only decides when the
    rule says "exit".)
    """
    signal = pd.Series(index=close.index, dtype=float)
    in_position = False
    entry_close = None
    bars_held = 0

    for i in range(len(close)):
        if pd.isna(rsi.iloc[i]):
            signal.iloc[i] = float("nan")
            continue

        price = close.iloc[i]
        if not in_position:
            gate_open = True if entry_ok is None else bool(entry_ok.iloc[i])
            if rsi.iloc[i] < oversold and gate_open:
                in_position = True
                entry_close = price
                bars_held = 0
        else:
            bars_held += 1
            hit_target = price >= entry_close * (1 + take_profit)
            hit_stop = stop_loss is not None and price <= entry_close * (1 - stop_loss)
            timed_out = max_hold_days is not None and bars_held >= max_hold_days
            if hit_target or hit_stop or timed_out:
                in_position = False
                entry_close = None

        signal.iloc[i] = 1.0 if in_position else 0.0

    signal.name = "signal"
    return signal


def generate_signals(df: pd.DataFrame, period: int = 14, oversold: float = 30,
                     take_profit: float = 0.03, stop_loss=None,
                     trend_window: int = None, max_hold_days: int = None) -> pd.Series:
    """
    df must have a 'close' column. take_profit / stop_loss are fractions
    (0.03 = 3%). stop_loss=None means never cut a loser.
    trend_window (e.g. 200): only enter while close is above its own
    trend_window-day simple average -- buy pullbacks in an uptrend, not
    falling knives. None = no filter (the original behaviour).
    max_hold_days: force-exit after this many bars. None = no limit.
    Returns a float Series: NaN during RSI warm-up, then 1.0 / 0.0.
    """
    rsi = _wilders_rsi(df["close"], period)
    entry_ok = None
    if trend_window is not None:
        # NaN comparison is False, so no entries until the average exists.
        entry_ok = (df["close"] > df["close"].rolling(trend_window).mean()).fillna(False)
    signal = _stateful_signal(df["close"], rsi, oversold, take_profit, stop_loss,
                              entry_ok=entry_ok, max_hold_days=max_hold_days)
    validate_signals(signal, df)
    return signal
