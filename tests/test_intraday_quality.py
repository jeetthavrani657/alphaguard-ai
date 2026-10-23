"""
tests/test_intraday_quality.py

research/intraday_quality.py rolls 15-minute candles up to daily bars and compares them with Yahoo's. What must hold: the roll-up takes the
first open, highest high, lowest low, last close and summed volume; matching data scores perfectly; small close-definition noise and a
dividend step are NOT errors; a real mismatch (a day closing far from Yahoo's, a distorted high, a missing weekday) is caught and flagged.
"""

import pandas as pd
import pytest

import intraday_quality as q


def _candles(days, closes):
    """Two candles a day: the day opens at close-1 and ends at the given close."""
    rows, idx = [], []
    for d, c in zip(days, closes):
        for k, (o, cl) in enumerate(((c - 1.0, c - 0.5), (c - 0.5, c))):
            rows.append({"open": o, "high": c + 1.0, "low": c - 2.0, "close": cl, "volume": 100.0})
            idx.append(pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=15 + 15 * k))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="time"))


DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"]
CLOSES = [100.0, 102.0, 101.0, 103.0]


def _yahoo(closes=CLOSES, days=DAYS):
    return pd.DataFrame({"open": [c - 1 for c in closes], "high": [c + 1 for c in closes], "low": [c - 2 for c in closes], "close": closes,
                         "volume": [200.0] * len(closes)}, index=pd.DatetimeIndex(days, name="date"))


def test_the_roll_up_is_first_open_highest_high_lowest_low_last_close_summed_volume():
    d = q.daily_from_intraday(_candles(DAYS[:1], [100.0])).iloc[0]
    assert (d["open"], d["high"], d["low"], d["close"], d["volume"]) == (99.0, 101.0, 98.0, 100.0, 200.0)


def test_matching_data_agrees_everywhere_and_is_not_flagged():
    r = q.compare(q.daily_from_intraday(_candles(DAYS, CLOSES)), _yahoo())
    assert r["days_compared"] == 4 and r["return_gap_median"] == 0.0 and r["return_gap_p95"] == 0.0 and r["extreme_days"] == []
    assert r["high_agree_share"] == 1.0 and r["low_agree_share"] == 1.0 and r["volume_ratio_median"] == 1.0
    assert r["only_intraday"] == [] and r["only_yahoo"] == [] and q.flagged(r) == []


def test_a_cumulative_dividend_adjustment_is_not_an_error_even_when_large():
    deep = _yahoo(closes=[c * 0.88 for c in CLOSES])                               # Yahoo's prices all 12% lower: returns unchanged
    deep["high"], deep["low"] = deep["close"] * (1 + 1.0 / 100.0), deep["close"] * (1 - 2.0 / 100.0)     # same day shape as the candles: high 1% over the close, low 2% under
    r = q.compare(q.daily_from_intraday(_candles(DAYS, CLOSES)), deep)
    assert r["return_gap_p95"] == pytest.approx(0.0, abs=1e-12) and r["high_agree_share"] == 1.0 and r["low_agree_share"] == 1.0 and q.flagged(r) == []


def test_a_one_percent_dividend_step_on_one_day_is_not_flagged_but_close_definition_noise_is_measured():
    div = _yahoo([CLOSES[0] * 0.99, CLOSES[1] * 0.99, CLOSES[2], CLOSES[3]])      # a 1% dividend goes ex on day 3: Yahoo's earlier closes are 1% lower
    r = q.compare(q.daily_from_intraday(_candles(DAYS, CLOSES)), div)
    assert r["extreme_days"] == [] and q.flagged(r) == [] and 0.0 < r["return_gap_p95"] < 0.01
    noisy = _yahoo([c * f for c, f in zip(CLOSES, (1.0, 1.001, 0.999, 1.001))])      # the official close is a few tenths of a percent from the last trade
    assert q.flagged(q.compare(q.daily_from_intraday(_candles(DAYS, CLOSES)), noisy)) == []


def test_a_wrong_close_a_distorted_high_and_a_big_unexplained_gap_are_caught():
    wrong = q.compare(q.daily_from_intraday(_candles(DAYS, [100.0, 102.0, 108.0, 103.0])), _yahoo())      # day 3 closes 7% from Yahoo's
    assert wrong["extreme_days"] == ["2026-10-21", "2026-10-22"] and q.flagged(wrong)                       # that day's return AND the next day's return differ
    y = _yahoo()
    y.loc["2026-10-21", "high"] = 150.0
    r = q.compare(q.daily_from_intraday(_candles(DAYS, CLOSES)), y)
    assert r["high_agree_share"] < 1.0 and r["high_agree_share"] >= 0.7 and r["low_agree_share"] == 1.0
    big_div = _yahoo([CLOSES[0] * 0.92, CLOSES[1] * 0.92, CLOSES[2], CLOSES[3]])                           # an 8% step is too big to be a normal dividend
    assert q.compare(q.daily_from_intraday(_candles(DAYS, CLOSES)), big_div)["extreme_days"] == ["2026-10-21"]


def test_days_only_one_source_has_are_listed_and_weekends_are_named_as_special_sessions():
    candles = _candles(DAYS + ["2026-10-24"], CLOSES + [104.0])                    # 24 Oct 2026 is a Saturday: a special session Yahoo does not have
    y = _yahoo(CLOSES[:2] + CLOSES[3:], DAYS[:2] + DAYS[3:])                        # 21 Oct is missing from Yahoo
    r = q.compare(q.daily_from_intraday(candles), y)
    assert r["only_intraday"] == ["2026-10-21", "2026-10-24"] or r["only_intraday"] == ["2026-10-24", "2026-10-21"] or set(r["only_intraday"]) == {"2026-10-21", "2026-10-24"}
    note = q.explain_missing_days(r)
    assert "1 weekend special sessions" in note and "2026-10-21" in note
    gap = q.compare(q.daily_from_intraday(_candles(DAYS[:2] + DAYS[3:], CLOSES[:2] + CLOSES[3:])), _yahoo())
    assert gap["only_yahoo"] == ["2026-10-21"] and "only in Yahoo" in q.explain_missing_days(gap)
