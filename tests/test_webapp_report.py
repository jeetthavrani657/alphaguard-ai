"""
tests/test_webapp_report.py

webapp/backend/report.py turns a stored series into the views of a strategy's report. Each is checked against a hand calculation: the return of each calendar month (including a window
that starts mid-month), the trades' returns counted into bins (edges belong to the bin that starts there), the deepest stretches below a peak (with one that has not recovered), and the
evidence figures (a single try expects no luck bar; more tries and fewer days raise it).
"""

import pytest

from webapp.backend import report as rp


# --- monthly returns --------------------------------------------------------------------------------------------------------------

def test_each_month_is_its_last_value_over_the_previous_months_last_value():
    dates = ["2024-01-02", "2024-01-31", "2024-02-15", "2024-02-29", "2024-03-28", "2024-04-30"]
    values = [100.0, 110.0, 99.0, 121.0, 133.1, 119.79]
    m = rp.monthly_returns(dates, values)
    assert [(x["year"], x["month"]) for x in m] == [(2024, 1), (2024, 2), (2024, 3), (2024, 4)]
    assert [round(x["return_pct"], 6) for x in m] == [10.0, 10.0, 10.0, -10.0]              # 110/100, 121/110, 133.1/121, 119.79/133.1


def test_a_window_that_starts_mid_month_reports_that_part_month_from_its_first_value():
    m = rp.monthly_returns(["2024-01-15", "2024-01-31", "2024-02-29"], [100.0, 105.0, 110.25])
    assert [round(x["return_pct"], 6) for x in m] == [5.0, 5.0]                              # January from 100 to 105, February from 105 to 110.25


def test_a_growth_series_that_already_moved_on_its_first_day_is_measured_from_its_base():
    # growth of 100 whose first listed day is already 99.778: January's return is from 100, not from 99.778 (found by the real-data smoke check: the months must compound to the total return)
    m = rp.monthly_returns(["2020-07-01", "2020-07-31", "2020-08-31"], [99.778, 102.0, 107.1], base=100.0)
    assert [round(x["return_pct"], 6) for x in m] == [2.0, 5.0]
    assert [round(x["return_pct"], 6) for x in rp.monthly_returns(["2020-07-01", "2020-07-31"], [99.778, 102.0])] == [round((102.0 / 99.778 - 1) * 100, 6)]    # without a base, from the first value


def test_months_are_reported_oldest_first_even_if_the_series_arrives_unsorted_and_a_single_point_gives_nothing():
    m = rp.monthly_returns(["2024-02-29", "2024-01-02", "2024-01-31"], [121.0, 100.0, 110.0])
    assert [(x["year"], x["month"]) for x in m] == [(2024, 1), (2024, 2)]
    assert rp.monthly_returns(["2024-01-02"], [100.0]) == [] and rp.monthly_returns([], []) == []


def test_the_year_changes_at_january():
    m = rp.monthly_returns(["2023-12-01", "2023-12-29", "2024-01-31"], [100.0, 102.0, 104.04])
    assert [(x["year"], x["month"]) for x in m] == [(2023, 12), (2024, 1)] and m[1]["return_pct"] == pytest.approx(2.0)


# --- the histogram of trades ------------------------------------------------------------------------------------------------------

def test_trade_returns_are_counted_into_bins_and_an_edge_belongs_to_the_bin_that_starts_there():
    h = rp.trade_histogram([-25.0, -20.0, -19.99, -0.01, 0.0, 2.49, 2.5, 25.0])
    counts = {(b["low_pct"], b["high_pct"]): b["count"] for b in h if b["count"]}
    assert counts == {(None, -20.0): 1, (-20.0, -15.0): 2, (-2.5, 0.0): 1, (0.0, 2.5): 2, (2.5, 5.0): 1, (20.0, None): 1}
    assert sum(b["count"] for b in h) == 8 and h[0]["low_pct"] is None and h[-1]["high_pct"] is None and len(h) == len(rp.HISTOGRAM_EDGES) + 1


def test_no_trades_gives_empty_bins_not_no_bins():
    h = rp.trade_histogram([])
    assert len(h) == len(rp.HISTOGRAM_EDGES) + 1 and sum(b["count"] for b in h) == 0


# --- the worst stretches below a peak ---------------------------------------------------------------------------------------------

DATES = [f"2024-01-{d:02d}" for d in range(1, 10)]


def test_each_fall_reports_its_peak_trough_recovery_depth_and_days():
    dd = [0, 0, -2, -5, -3, 0, -1, -8, -4]                                                   # one fall that recovered, one still under water at the end
    first, second = sorted(rp.drawdown_periods(DATES, dd, top=5), key=lambda p: p["peak_date"])
    assert first == {"peak_date": "2024-01-02", "trough_date": "2024-01-04", "recovered_date": "2024-01-06", "depth_pct": -5.0, "days_peak_to_trough": 2, "days_underwater": 4}
    assert second == {"peak_date": "2024-01-06", "trough_date": "2024-01-08", "recovered_date": None, "depth_pct": -8.0, "days_peak_to_trough": 2, "days_underwater": 3}


def test_the_deepest_come_first_and_only_the_top_are_kept():
    dd = [0, 0, -2, -5, -3, 0, -1, -8, -4]
    top = rp.drawdown_periods(DATES, dd, top=1)
    assert [p["depth_pct"] for p in top] == [-8.0]
    assert [p["depth_pct"] for p in rp.drawdown_periods(DATES, dd, top=5)] == [-8.0, -5.0]


def test_a_series_that_starts_below_its_peak_and_one_that_never_falls():
    p = rp.drawdown_periods(["2024-01-01", "2024-01-02", "2024-01-03"], [-3.0, -1.0, 0.0])
    assert p == [{"peak_date": "2024-01-01", "trough_date": "2024-01-01", "recovered_date": "2024-01-03", "depth_pct": -3.0, "days_peak_to_trough": 0, "days_underwater": 2}]
    assert rp.drawdown_periods(DATES[:3], [0.0, 0.0, 0.0]) == []


# --- the evidence figures ---------------------------------------------------------------------------------------------------------

def test_a_single_try_expects_no_luck_bar_and_more_tries_and_fewer_days_raise_it():
    one = rp.evidence(504, 1)
    assert one["luck_bar_annual"] == 0.0 and one["window_years"] == 2.0 and one["ideas_tried"] == 1
    assert rp.evidence(504, 10)["luck_bar_annual"] < rp.evidence(504, 220)["luck_bar_annual"]
    assert rp.evidence(252, 220)["luck_bar_annual"] > rp.evidence(1260, 220)["luck_bar_annual"] > 0.0
    assert 1.2 < rp.evidence(1175, 220)["luck_bar_annual"] < 1.4                             # by hand: 2.80 x (1/sqrt(1174)) x sqrt(252) = 1.30 a year, as OVERFIT_CHECKS.md says (1.2 to 1.45)


def test_the_standard_library_formulas_match_the_research_codes_over_a_grid():
    """The API cannot import scipy, so report.py repeats the formulas; this keeps the two identical."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))
    import overfit_checks as oc
    for tries in (1, 2, 10, 220, 5000):
        for var in (1 / 251.0, 1 / 1174.0, 1 / 2500.0):
            assert rp._expected_max_sharpe(tries, var) == pytest.approx(oc.expected_max_sharpe(tries, var), rel=1e-9)
        for sr in (0.5, 1.0, 1.5, 4.0, 8.0):
            assert rp._years_needed(sr, tries) == oc.years_needed(sr, tries)
    assert rp._years_needed(0.01, 220) is None and oc.years_needed(0.01, 220) is None                  # a tiny edge never shows within 300 years


def test_how_long_a_real_edge_takes_to_show_depends_on_how_many_ideas_were_tried():
    e = rp.evidence(1175, 220)
    assert 2.6 < e["years_needed_for_edge_of_1_single_try"] < 3.0                           # about 2.8 years if it was the only idea
    assert 18.5 < e["years_needed_for_edge_of_1"] < 21.0                                    # and close to 20 once about 220 were tried
    assert e["years_needed_for_edge_of_1"] > e["years_needed_for_edge_of_1_single_try"]
