"""
engine/backtest.py

Turns a strategy's signal into trades, a trade log, and a daily equity
curve. Single symbol, long-or-cash only (no shorting, no leverage).

======================================================================
LOOK-AHEAD PREVENTION -- read this before anything else in this file.
======================================================================

A strategy's signal on date T is computed FROM DATA THROUGH T'S CLOSE
(both ma_crossover and rsi_reversion use rolling/recursive functions of
`close`). That means, in real trading, you cannot know signal[T] until
the market has already closed on day T. Any position change implied by
signal[T] is therefore only tradeable starting the NEXT session, T+1.

The entire look-ahead prevention scheme is exactly this:

    position = signal.shift(1)

That single line is the lag. It appears once, in `_apply_look_ahead_lag`
below, and every calculation in this file uses `position`, never
`signal`, from that point on. Because it's one line in one place, there
is exactly one place a look-ahead bug could be reintroduced -- which is
also exactly the one place `_assert_no_look_ahead` independently checks.

EXECUTION ASSUMPTION: fills happen at the NEXT bar's OPEN, not close.
Rationale: the earliest a real order can be placed after seeing T's
close is the start of the T+1 session -- i.e. T+1's open. Filling at
T+1's close instead would mean waiting through an entire extra session
you had no reason to wait through, which is a different (and less
realistic) assumption than "trade as soon as you can." Open is applied
consistently for every entry and every exit below.
======================================================================
"""

import pandas as pd

import config
import costs
from validator import assert_backtest_safe


def _apply_look_ahead_lag(signal: pd.Series) -> pd.Series:
    """
    THE lag. Converts a same-day signal into a position that only takes
    effect starting the next bar. See the module docstring above.
    """
    position = signal.shift(1).fillna(0.0)
    position.name = "position"
    return position


def _assert_no_look_ahead(signal: pd.Series, position: pd.Series) -> None:
    """
    LOOK-AHEAD GUARD -- fails loudly if the lag is ever removed or
    bypassed.

    This deliberately does NOT just re-run signal.shift(1) and compare
    (that would trivially agree with _apply_look_ahead_lag even if both
    were broken the same way). Instead it re-derives the same invariant
    using plain positional array indexing, a completely different code
    path, and checks `position` actually satisfies it:

        position[0] must be 0 (no prior bar exists to have acted on)
        position[i] must equal signal[i-1] for every i >= 1

    If someone edits _apply_look_ahead_lag to remove the shift, or
    wires any part of this engine to consume `signal` directly instead
    of `position`, this raises immediately instead of letting a
    look-ahead bug run quietly to a plausible-looking result.
    """
    signal_values = signal.fillna(0.0).to_numpy()
    position_values = position.to_numpy()

    assert position_values[0] == 0.0, (
        "LOOK-AHEAD VIOLATION: the first bar's position must be 0 (cash) -- "
        "there is no prior bar's signal to have legitimately acted on yet."
    )

    matches = position_values[1:] == signal_values[:-1]
    assert matches.all(), (
        f"LOOK-AHEAD VIOLATION: position does not equal the PRIOR day's "
        f"signal on {(~matches).sum()} day(s). This means a trade could be "
        f"reacting to information from its own day instead of the day "
        f"before. Check that position is built from signal.shift(1), and "
        f"that nothing downstream reads `signal` directly instead of "
        f"`position`."
    )


def run_backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    report: dict,
    start: str,
    end: str,
    initial_capital: float = None,
    position_fraction: float = None,
    override_discontinuity_gate: bool = False,
    slippage_pct_override: float = None,
) -> dict:
    """
    df: OHLCV data (from data.loader.load_price_data), 'open' and
        'close' columns required.
    signal: strategy output (from a strategies/*.py generate_signals()),
        same index as df.
    report: the dict returned by validator.validate_price_data() for
        this symbol -- required so the discontinuity gate below can
        actually check something.
    start, end: the date range this backtest actually simulates trades
        over. `signal`/`position` are still computed from `df`'s FULL
        history (so a moving average has real warm-up data from before
        `start`, and a trend already established going into `start` is
        correctly reflected as an immediate position on day 1 rather
        than an artificial few-week ramp-up) -- but the trading loop,
        equity curve, and trade log are restricted to [start, end], and
        EVERY call starts flat (no carried-over position) with its own
        fresh `initial_capital`, as an independent deployment beginning
        on `start`. (Also passed straight through to the gate.)

        HISTORY: prior to this fix, start/end were used ONLY by the
        gate check below -- the trading loop ran over the entirety of
        `df` regardless of what range was requested. This meant every
        "in-sample vs out-of-sample" comparison built on top of this
        function (run_validation.py, the harness demo scripts, the
        Midcap/Smallcap control comparison) was running the exact same
        full-history backtest twice, not two genuinely different
        windows -- confirmed by hand-tracing a real symbol (HAVELLS):
        the "in-sample" and "out-of-sample" equity curves were
        byte-identical. See MIDCAP_SMALLCAP_FINDINGS.md's amendment
        note and known_issues.md for the full incident writeup.
    override_discontinuity_gate: passed straight through to
        assert_backtest_safe's `override` parameter. Defaults to False.
        This function does NOT set it to True on your behalf under any
        circumstance -- if you want to run across an unresolved
        discontinuity, that has to be an explicit choice at the call
        site, every time.
    slippage_pct_override: passed straight through to every
        costs.calculate_trade_cost() call this backtest makes (both
        legs of every trade). None (the default) reproduces the exact
        prior flat-rate behavior. Set this to run the same strategy
        with a symbol-specific liquidity-based slippage estimate
        instead -- see research/liquidity_costs.py.

    Returns {"trade_log": pd.DataFrame, "equity_curve": pd.Series,
    "position": pd.Series, "open_position_at_end": dict or None}.
    """
    # Hard gate, called unconditionally, before anything else runs.
    assert_backtest_safe(report, start, end, override=override_discontinuity_gate)

    initial_capital = config.INITIAL_CAPITAL if initial_capital is None else initial_capital
    position_fraction = config.POSITION_FRACTION if position_fraction is None else position_fraction

    # Computed on the FULL df/signal, not the [start, end] window -- see
    # the docstring above. _assert_no_look_ahead's invariant (bar 0 of
    # the whole series must be flat) is about the dataset's true start,
    # not about wherever this particular window happens to begin, so it
    # must run before slicing.
    position_full = _apply_look_ahead_lag(signal)
    _assert_no_look_ahead(signal, position_full)

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    window_df = df.loc[start_ts:end_ts]
    position = position_full.loc[start_ts:end_ts]
    if window_df.empty:
        raise ValueError(f"No rows in df between {start} and {end} -- nothing to backtest.")

    cash = initial_capital
    shares = 0
    open_trade = None  # entry details for the currently-open trade, if any
    trades = []
    equity_curve = pd.Series(index=window_df.index, dtype=float)

    # Every window starts flat: prev_position=0.0 means "no shares held
    # YET IN THIS BACKTEST," which correctly triggers an immediate entry
    # on day 1 if position.iloc[0] is already 1.0 (the trend was already
    # up going into `start`) rather than pretending the strategy has no
    # memory of history before the window.
    prev_position = 0.0
    for i in range(len(window_df)):
        date = window_df.index[i]
        pos_today = position.iloc[i]
        open_price = window_df["open"].iloc[i]
        close_price = window_df["close"].iloc[i]

        if pos_today == 1.0 and prev_position == 0.0:
            # ENTER at today's open. While flat, cash == total equity
            # (no shares held), so sizing off `cash` directly is correct.
            entry_price = open_price
            allocated_capital = cash * position_fraction
            quantity = int(allocated_capital // entry_price)  # whole shares only
            trade_value = quantity * entry_price
            buy_costs = costs.calculate_trade_cost(trade_value, "buy", slippage_pct_override=slippage_pct_override)

            cash -= trade_value + buy_costs["total"]
            shares = quantity
            open_trade = {
                "entry_date": date,
                "entry_price": entry_price,
                "quantity": quantity,
                "buy_costs_total": buy_costs["total"],
            }

        elif pos_today == 0.0 and prev_position == 1.0:
            # EXIT at today's open.
            exit_price = open_price
            gross_proceeds = shares * exit_price
            sell_costs = costs.calculate_trade_cost(gross_proceeds, "sell", slippage_pct_override=slippage_pct_override)
            net_proceeds = gross_proceeds - sell_costs["total"]
            cash += net_proceeds

            net_entry_cost = open_trade["quantity"] * open_trade["entry_price"] + open_trade["buy_costs_total"]
            return_pct = (net_proceeds - net_entry_cost) / net_entry_cost * 100
            entry_loc = window_df.index.get_loc(open_trade["entry_date"])
            holding_days = i - entry_loc  # trading sessions actually held

            trades.append({
                "entry_date": open_trade["entry_date"],
                "exit_date": date,
                "entry_price": open_trade["entry_price"],
                "exit_price": exit_price,
                "quantity": open_trade["quantity"],
                "return_pct": return_pct,
                "holding_days": holding_days,
                "total_costs": open_trade["buy_costs_total"] + sell_costs["total"],
            })

            shares = 0
            open_trade = None

        equity_curve.iloc[i] = cash + shares * close_price
        prev_position = pos_today

    trade_log = pd.DataFrame(trades, columns=[
        "entry_date", "exit_date", "entry_price", "exit_price",
        "quantity", "return_pct", "holding_days", "total_costs",
    ])

    return {
        "trade_log": trade_log,
        "equity_curve": equity_curve,
        "position": position,
        "open_position_at_end": open_trade,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "../data")
    sys.path.insert(0, "../strategies")
    from loader import load_price_data
    from validator import validate_price_data
    import ma_crossover

    symbol_loader, ticker = config.SYMBOLS[0], config.SYMBOLS[0] + ".NS"
    df = load_price_data(symbol_loader, config.START_DATE, config.END_DATE)
    report = validate_price_data(df, ticker)
    signal = ma_crossover.generate_signals(df, **config.MA_CROSSOVER_PARAMS)

    result = run_backtest(df, signal, report, config.START_DATE, config.END_DATE)
    pd.set_option("display.width", 120)
    print(result["trade_log"])
    print(f"\nFinal equity: {result['equity_curve'].iloc[-1]:,.2f}")
