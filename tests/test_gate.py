"""
tests/test_gate.py

assert_backtest_safe() exists specifically to fail CLOSED: an unreviewed
or unresolved discontinuity should block a backtest, and nothing should
be able to slip through silently. This was previously verified by
reasoning about the code, never by constructing a report with a bad
status and confirming the block actually fires. This file does that
directly, including the case that turned out to matter most: a
malformed status value, not just a missing one.
"""

import pandas as pd
import pytest

from validator import assert_backtest_safe, _review_for


def _report_with(status, date="2020-06-15", magnitude=-0.30, symbol="TEST.NS"):
    return {
        "symbol": symbol,
        "discontinuities": [{
            "date": pd.Timestamp(date), "magnitude": magnitude,
            "status": status, "reviewed": None, "reason": "test fixture",
        }],
    }


def test_unreviewed_blocks():
    report = _report_with("UNREVIEWED")
    with pytest.raises(RuntimeError, match="BACKTEST BLOCKED"):
        assert_backtest_safe(report, "2020-01-01", "2020-12-31")


def test_artifact_blocks():
    report = _report_with("ARTIFACT")
    with pytest.raises(RuntimeError, match="BACKTEST BLOCKED"):
        assert_backtest_safe(report, "2020-01-01", "2020-12-31")


def test_genuine_does_not_block():
    report = _report_with("GENUINE")
    assert_backtest_safe(report, "2020-01-01", "2020-12-31")  # must not raise


def test_out_of_range_discontinuity_does_not_block():
    """An unresolved discontinuity outside the requested date range is irrelevant -- must not block."""
    report = _report_with("UNREVIEWED", date="2020-06-15")
    assert_backtest_safe(report, "2021-01-01", "2021-12-31")  # different year, must not raise


def test_override_allows_proceeding_past_a_block(capsys):
    report = _report_with("ARTIFACT")
    assert_backtest_safe(report, "2020-01-01", "2020-12-31", override=True)  # must not raise
    assert "GATE OVERRIDE" in capsys.readouterr().out


def test_missing_registry_entry_defaults_to_unreviewed():
    """A symbol/date genuinely never reviewed at all -- _review_for must default to UNREVIEWED, not silently assume safe."""
    review = _review_for("NOT_A_REAL_SYMBOL.NS", pd.Timestamp("2099-01-01"))
    assert review["status"] == "UNREVIEWED"


def test_malformed_status_blocks_rather_than_passes():
    """
    A malformed status -- e.g. a wrong-case typo made hand-editing
    data/discontinuity_registry.py ("Unreviewed" instead of
    "UNREVIEWED") -- must NOT be silently treated as safe. Only an
    exact, affirmative "GENUINE" may pass; anything else, including
    garbage, must block. This is the case that actually failed the
    first time this test was written -- see the session notes for the
    fix this drove in validator.py.
    """
    for bad_status in ["Unreviewed", "unreviewed", "ARTFACT", "", "GENUINE ", "genuine", None]:
        report = _report_with(bad_status)
        with pytest.raises(RuntimeError, match="BACKTEST BLOCKED"):
            assert_backtest_safe(report, "2020-01-01", "2020-12-31")
