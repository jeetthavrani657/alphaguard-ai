"""
tests/test_options_real_data.py

Checks of the options engine against the REAL stored exchange files (data/fo/, git-ignored) and the project's own Nifty price cache. They exist because a synthetic market only
proves the engine does what its author assumed: a first version assumed an expiry day's settlement values were option intrinsics, which every synthetic test confirmed, and which
the real files contradict (every contract carries the underlying's final settlement level). Each test skips if the data is not on this computer.
"""

import os

import pandas as pd
import pytest

import fo_bhavcopy as fo
import options_backtest as ob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NSEI = os.path.join(ROOT, "data", "cache", "^NSEI.csv")


def _book(start, end):
    t = fo.load_fo(start, end, symbols=["NIFTY"], instruments=("OPTIDX",))
    if t.empty:
        pytest.skip(f"no stored F&O data for {start} to {end}")
    return ob.index_table(t)


@pytest.fixture(scope="module")
def spot():
    if not os.path.exists(NSEI):
        pytest.skip("no Nifty price cache")
    return pd.read_csv(NSEI, index_col=0, parse_dates=True)["close"].astype(float)


@pytest.mark.parametrize("start,end", [("2022-01-03", "2022-04-29"), ("2023-08-01", "2023-10-31"), ("2025-03-03", "2025-06-30")])
def test_the_final_level_equals_the_nifty_close_on_every_real_expiry_day(start, end, spot):
    book = _book(start, end)
    checked = 0
    for expiry in sorted({e for _, e in book if pd.Timestamp(start) <= e <= pd.Timestamp(end)}):
        if expiry not in spot.index:
            continue
        level, source = ob.final_level_with_source(book, expiry)
        assert level == pytest.approx(spot.loc[expiry], rel=5e-4), f"{expiry.date()}: level {level} ({source}) against the Nifty close {spot.loc[expiry]}"
        assert source == "settlement"
        checked += 1
    assert checked >= 8


def test_a_real_stretch_of_weekly_condors_obeys_the_cap_keeps_the_account_positive_and_reads_the_files_lot_size(spot):
    book = _book("2024-03-01", "2024-09-30")
    r = ob.run_condor_backtest(book, "weekly", initial=ob.INITIAL, rate=0.06)
    c = r["cycles"]
    assert len(c) >= 20 and (c["final_level_source"] == "settlement").all()
    assert (-c["gross_pnl"] <= c["max_loss_per_unit"] * c["units"] + 1e-6).all()                       # no cycle loses more than its worst case
    assert r["equity"].min() > 0.5 * ob.INITIAL
    assert set(c["lot_size"]) <= {50, 25}                                                              # 50 until the change on 2024-04-26, then 25, read from the files


@pytest.mark.parametrize("start,end,expected_lot", [("2024-03-04", "2024-03-08", 50), ("2024-05-06", "2024-05-10", 25), ("2025-03-03", "2025-03-07", 75), ("2026-03-02", "2026-03-06", 65)])
def test_the_lot_size_read_from_the_files_matches_the_changes_seen_in_them(start, end, expected_lot):
    book = _book(start, end)
    day = sorted({d for d, _ in book})[0]
    expiry = sorted(e for d, e in book if d == day and (e - day).days > 3)[0]
    assert ob.contract_lot(book, day, expiry) == expected_lot
