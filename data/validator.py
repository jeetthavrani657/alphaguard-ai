"""
data/validator.py

Sanity-checks a downloaded OHLCV price DataFrame (as returned by
data.loader.load_price_data) before it's trusted for backtesting.

Note on holidays: pandas has no built-in NSE holiday calendar, and this
project's tech stack deliberately doesn't add a market-calendar library.
So the "missing trading days" check compares against plain Mon-Fri
business days and classifies gaps by RUN LENGTH: NSE holidays often
cluster back-to-back (e.g. two festivals on consecutive days), so a
short run of missing business days is far more likely to be holidays
than a genuine data gap. This is a heuristic, not a real calendar --
treat it as a hint to investigate, not a certainty.

Note on discontinuities: a single-day price move beyond the threshold
is classified as a SUSPECTED DISCONTINUITY only if it has no matching
entry in yf.Ticker(symbol).actions (splits/dividends) -- i.e. it's a
move auto_adjust could NOT have accounted for. This is what catches
demergers/spin-offs, which look exactly like a real crash to a naive
backtest. See data/known_issues.md for confirmed examples.
"""

import pandas as pd
import yfinance as yf

from discontinuity_registry import REVIEWS

# India's fixed-date national holidays (same calendar date every year).
# Most other NSE holidays (Diwali, Holi, etc.) move around the lunar
# calendar and can't be hardcoded reliably -- those are caught by the
# run-length heuristic below instead.
FIXED_DATE_HOLIDAYS_MM_DD = {"01-26", "08-15", "10-02"}  # Republic Day, Independence Day, Gandhi Jayanti

# A run of this many or fewer consecutive missing business days is
# classified as "likely holiday" (NSE holidays commonly cluster 1-3 days
# in a row). Longer runs are flagged as possible genuine data gaps.
MISSING_RUN_HOLIDAY_MAX = 3

LARGE_MOVE_THRESHOLD = 0.25  # configurable via validate_price_data(large_move_threshold=...)
DISCONTINUITY_ACTION_WINDOW_DAYS = 1  # match a flagged move to an action within +/- this many days
FLAT_STRETCH_MIN_DAYS = 5

# Absolute tolerance (rupees) for the OHLC logic check below. yfinance's
# split/dividend adjustment arithmetic leaves floating-point rounding
# noise on the order of 1e-14 to 1e-15 -- e.g. an adjusted close landing
# 0.0000000000000018 below the adjusted low, which a strict `<` treats
# as a genuine violation. Found running this validator on the Midcap
# 150 / Smallcap 250 universes (8 symbols flagged "OHLC violations" with
# zero real economic difference between the compared prices -- see
# data/known_issues.md). A real violation is always many orders of
# magnitude larger than this tolerance.
_OHLC_TOLERANCE = 1e-6


def _check_missing_trading_days(df: pd.DataFrame) -> dict:
    expected = pd.bdate_range(df.index.min(), df.index.max())
    missing = expected.difference(df.index)

    likely_holiday = []
    genuine_gap = []

    if len(missing) > 0:
        # Find each missing date's position in the full business-day sequence,
        # then group consecutive positions into runs. This correctly treats
        # e.g. two holidays in a row as one 2-day cluster, not two isolated gaps.
        position_of = pd.Series(range(len(expected)), index=expected)
        missing_positions = position_of.loc[missing]
        run_id = (missing_positions.diff() != 1).cumsum()
        run_length = missing_positions.groupby(run_id).transform("size")

        for date, length in zip(missing, run_length):
            is_fixed_holiday = date.strftime("%m-%d") in FIXED_DATE_HOLIDAYS_MM_DD
            if is_fixed_holiday or length <= MISSING_RUN_HOLIDAY_MAX:
                likely_holiday.append(date)
            else:
                genuine_gap.append(date)

    return {
        "name": "Missing trading days",
        "passed": len(missing) == 0,
        "count": len(missing),
        "dates": list(missing),
        "detail": {
            "likely_holiday_or_short_run": likely_holiday,
            "possible_genuine_gap": genuine_gap,
        },
    }


def _check_duplicate_dates(df: pd.DataFrame) -> dict:
    dupes = df.index[df.index.duplicated(keep=False)].unique()
    return {
        "name": "Duplicate dates",
        "passed": len(dupes) == 0,
        "count": len(dupes),
        "dates": list(dupes),
    }


def _check_invalid_prices(df: pd.DataFrame) -> dict:
    ohlc = df[["open", "high", "low", "close"]]
    bad_mask = (ohlc <= 0).any(axis=1) | ohlc.isna().any(axis=1)
    bad_dates = df.index[bad_mask]
    return {
        "name": "Zero/negative/NaN OHLC prices",
        "passed": len(bad_dates) == 0,
        "count": len(bad_dates),
        "dates": list(bad_dates),
    }


def _check_ohlc_logic(df: pd.DataFrame) -> dict:
    tol = _OHLC_TOLERANCE
    high_lt_low = df["high"] < df["low"] - tol
    close_out_of_range = (df["close"] > df["high"] + tol) | (df["close"] < df["low"] - tol)
    open_out_of_range = (df["open"] > df["high"] + tol) | (df["open"] < df["low"] - tol)
    bad_mask = high_lt_low | close_out_of_range | open_out_of_range
    bad_dates = df.index[bad_mask]
    return {
        "name": "OHLC logic violations (high<low, close/open outside range)",
        "passed": len(bad_dates) == 0,
        "count": len(bad_dates),
        "dates": list(bad_dates),
    }


def _fetch_actions(symbol: str):
    """
    Fetch yfinance's recorded splits/dividends for a symbol, once.
    Returns None (rather than raising) on failure -- callers must treat
    None as "could not confirm" and stay conservative, not assume clean.
    """
    try:
        actions = yf.Ticker(symbol).actions
        return actions if actions is not None else pd.DataFrame()
    except Exception as e:
        print(f"[validator] Could not fetch corporate actions for {symbol}: {e}. "
              f"Large moves will be conservatively treated as unconfirmed.")
        return None


def _matches_known_action(date: pd.Timestamp, actions) -> bool:
    if actions is None or actions.empty:
        return False
    # actions.index is tz-aware (Yahoo returns Asia/Kolkata-localized timestamps);
    # strip tz so it compares against our tz-naive price index dates.
    action_dates = actions.index.tz_localize(None)
    window = pd.Timedelta(days=DISCONTINUITY_ACTION_WINDOW_DAYS)
    nearby = actions[(action_dates >= date - window) & (action_dates <= date + window)]
    if nearby.empty:
        return False
    return (nearby.get("Dividends", 0) != 0).any() or (nearby.get("Stock Splits", 0) != 0).any()


def _review_for(symbol: str, date: pd.Timestamp) -> dict:
    """
    Look up the human review status for a flagged date in the
    discontinuity registry (data/discontinuity_registry.py). Anything
    with no entry defaults to UNREVIEWED -- silence must never mean safe.
    """
    return REVIEWS.get((symbol, str(date.date())), {
        "status": "UNREVIEWED",
        "reviewed": None,
        "reason": "Not yet reviewed against yf.Ticker().actions, trend, and volume.",
    })


def _check_large_moves(df: pd.DataFrame, symbol: str, threshold: float) -> dict:
    daily_return = df["close"].pct_change()
    flagged = daily_return[daily_return.abs() > threshold]

    actions = _fetch_actions(symbol) if len(flagged) > 0 else pd.DataFrame()
    could_confirm = actions is not None
    actions = actions if could_confirm else pd.DataFrame()

    discontinuities = []  # unexplained by actions -- these get a GENUINE/ARTIFACT/UNREVIEWED review
    explained = []        # matches a recorded split/dividend -- not a discontinuity at all
    for date, move in flagged.items():
        matched = could_confirm and _matches_known_action(date, actions)
        entry = {"date": date, "magnitude": move}
        if matched:
            explained.append(entry)
        else:
            review = _review_for(symbol, date)
            discontinuities.append({**entry, **review})

    detail = {}
    for e in explained:
        detail[str(e["date"].date())] = f"{e['magnitude']:+.1%} (matches a recorded split/dividend)"
    for e in discontinuities:
        confirm_note = "" if could_confirm else ", actions fetch failed -- unconfirmed"
        detail[str(e["date"].date())] = f"{e['magnitude']:+.1%} ({e['status']}{confirm_note})"

    return {
        "name": f"Single-day moves > {int(threshold * 100)}%",
        "passed": len(flagged) == 0,
        "count": len(flagged),
        "dates": list(flagged.index),
        "detail": detail,
        "discontinuities": discontinuities,  # unexplained-by-actions moves, each carrying a review status
        "explained_large_moves": explained,
    }


def _check_zero_volume(df: pd.DataFrame) -> dict:
    zero_vol_dates = df.index[df["volume"] == 0]
    return {
        "name": "Zero-volume days",
        "passed": len(zero_vol_dates) == 0,
        "count": len(zero_vol_dates),
        "dates": list(zero_vol_dates),
    }


def _check_flat_stretches(df: pd.DataFrame) -> dict:
    # A "run" of identical consecutive closes: group consecutive equal values
    # by comparing each close to the previous one and cumulative-summing the
    # change points to form a run id, then count each run's length.
    close = df["close"]
    changed = close.ne(close.shift()).cumsum()
    run_lengths = close.groupby(changed).transform("size")
    flat_mask = run_lengths >= FLAT_STRETCH_MIN_DAYS

    flagged_dates = list(df.index[flat_mask])
    # Report the start date of each qualifying flat run, not every date in it.
    run_starts = df.index[flat_mask & (changed != changed.shift())]

    return {
        "name": f"Flat closing price for {FLAT_STRETCH_MIN_DAYS}+ consecutive days",
        "passed": len(flagged_dates) == 0,
        "count": len(flagged_dates),
        "dates": flagged_dates,
        "detail": {"run_start_dates": list(run_starts)},
    }


def validate_price_data(df: pd.DataFrame, symbol: str, large_move_threshold: float = LARGE_MOVE_THRESHOLD) -> dict:
    """
    Run all data-quality checks on a price DataFrame and print a console
    report. Returns the report as a dict (checks, overall verdict, and a
    flat "discontinuities" list) for programmatic use -- see
    assert_backtest_safe(), which the backtest engine should call with
    this report before running.

    symbol must be the actual yfinance ticker (e.g. "RELIANCE.NS") --
    it's used to fetch corporate actions for discontinuity classification.
    """
    checks = [
        _check_missing_trading_days(df),
        _check_duplicate_dates(df),
        _check_invalid_prices(df),
        _check_ohlc_logic(df),
        _check_large_moves(df, symbol, large_move_threshold),
        _check_zero_volume(df),
        _check_flat_stretches(df),
    ]

    # Hard failures make the data unusable outright. Missing trading days
    # and explained large moves are informational; suspected discontinuities
    # don't block the *general* verdict either -- they only matter if your
    # specific backtest window overlaps them, which is what the separate
    # assert_backtest_safe() gate (range-aware) is for.
    hard_fail_names = {
        "Duplicate dates",
        "Zero/negative/NaN OHLC prices",
        "OHLC logic violations (high<low, close/open outside range)",
    }
    hard_failed = [c for c in checks if c["name"] in hard_fail_names and not c["passed"]]
    usable = len(hard_failed) == 0

    large_move_check = next(c for c in checks if c["name"].startswith("Single-day moves"))
    discontinuities = large_move_check["discontinuities"]

    _print_report(symbol, df, checks, usable)

    return {"symbol": symbol, "checks": checks, "usable": usable, "discontinuities": discontinuities}


def assert_backtest_safe(report: dict, start: str, end: str, override: bool = False) -> None:
    """
    Hard gate for the backtest engine to call before running.

    Raises RuntimeError if the requested [start, end] range overlaps any
    discontinuity classified ARTIFACT or UNREVIEWED in
    data/discontinuity_registry.py -- a price change that either didn't
    happen economically, or hasn't been checked yet. GENUINE moves (real
    market history, e.g. a crisis crash) pass silently: reviewed history
    should not keep blocking every backtest that crosses it, or you'll
    end up passing override=True reflexively and the gate stops
    protecting anything.

    Pass override=True to proceed past an ARTIFACT/UNREVIEWED block
    anyway (only after you've actually looked at the cause -- see
    data/known_issues.md). This fails loudly on purpose: a quiet warning
    here is exactly the failure mode this gate exists to prevent.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    in_range = [d for d in report["discontinuities"] if start_ts <= d["date"] <= end_ts]
    # Block on anything that is not an exact, affirmative "GENUINE" --
    # not just the two known statuses. A malformed status (a hand-edit
    # typo in discontinuity_registry.py, e.g. "Unreviewed" wrong case)
    # must fail closed like everything else, not silently pass through
    # because it happened not to match "ARTIFACT" or "UNREVIEWED"
    # literally. Found by tests/test_gate.py, which is why it exists.
    blocking = [d for d in in_range if d.get("status") != "GENUINE"]

    if not blocking:
        return

    detail = "; ".join(f"{d['date'].date()} ({d['magnitude']:+.1%}, {d['status']})" for d in blocking)
    plural = "y" if len(blocking) == 1 else "ies"
    message = (
        f"BACKTEST BLOCKED for {report['symbol']}: {len(blocking)} unresolved "
        f"discontinuit{plural} in range [{start}, {end}]: {detail}. "
        f"ARTIFACT means the move didn't happen economically (e.g. an unadjusted "
        f"demerger); UNREVIEWED means nobody has classified it yet. See "
        f"data/known_issues.md and data/discontinuity_registry.py, review/resolve "
        f"the cause, or pass override=True to proceed anyway."
    )
    if not override:
        raise RuntimeError(message)
    print(f"[GATE OVERRIDE] {message}")


def _print_report(symbol: str, df: pd.DataFrame, checks: list, usable: bool) -> None:
    print("=" * 70)
    print(f"Data validation report: {symbol}")
    print(f"Rows: {len(df)}  Range: {df.index.min().date()} to {df.index.max().date()}")
    print("=" * 70)

    for c in checks:
        status = "PASS" if c["passed"] else "FAIL"
        print(f"[{status}] {c['name']}  (affected rows: {c['count']})")

        if c["name"] == "Missing trading days" and c["count"] > 0:
            likely = c["detail"]["likely_holiday_or_short_run"]
            genuine = c["detail"]["possible_genuine_gap"]
            print(f"         likely holiday (run <= {MISSING_RUN_HOLIDAY_MAX} days) ({len(likely)}): "
                  f"{[str(d.date()) for d in likely[:10]]}{' ...' if len(likely) > 10 else ''}")
            print(f"         possible genuine gap -- worth checking manually ({len(genuine)}): "
                  f"{[str(d.date()) for d in genuine[:10]]}{' ...' if len(genuine) > 10 else ''}")
            print("         (assessment only, not a certainty -- no real NSE holiday calendar is used here)")
        elif c["name"].startswith("Single-day moves") and c["count"] > 0:
            for date_str, move in c["detail"].items():
                print(f"         {date_str}: {move}")
        elif c["count"] > 0 and c["name"] != "Missing trading days":
            dates_preview = [str(pd.Timestamp(d).date()) for d in c["dates"][:10]]
            print(f"         dates: {dates_preview}{' ...' if c['count'] > 10 else ''}")

    print("-" * 70)
    verdict = "USABLE for backtesting" if usable else "NOT USABLE -- fix data issues first"
    print(f"Overall verdict: {verdict}")
    print("=" * 70)
    print()


if __name__ == "__main__":
    from loader import load_price_data

    df = load_price_data("RELIANCE", "2024-01-01", "2024-06-30")
    validate_price_data(df, "RELIANCE.NS")
