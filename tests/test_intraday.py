"""
tests/test_intraday.py

data/intraday.py caches minute candles from the read-only Upstox client. What must hold: impossible candles never survive, today's
half-finished session is never kept, a cache extended later stays on ONE price basis (a split must trigger a full re-download), and
the validation report says what is wrong with a series. No network: the fetch function is a fake with a controllable price basis.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

import intraday as it

INTERVAL = 15


def _ist(day: str, hour: int, minute: int = 0) -> datetime:
    """A UTC datetime for the given Indian date and time (IST = UTC + 5:30)."""
    ist = pd.Timestamp(f"{day} {hour:02d}:{minute:02d}") - pd.Timedelta(hours=5, minutes=30)
    return datetime(ist.year, ist.month, ist.day, ist.hour, ist.minute, tzinfo=timezone.utc)


def _candles(start: str, end: str, scale: float = 1.0, only_until_hour: int | None = None) -> pd.DataFrame:
    """Full 15-minute sessions for every weekday in start..end, on price basis `scale`. Prices drift smoothly with the day."""
    rows, index = [], []
    for day in pd.bdate_range(start, end):
        for k in range(25):                                            # 09:15 to 15:15 candle starts
            ts = day + pd.Timedelta(hours=9, minutes=15 + 15 * k)
            if only_until_hour is not None and ts.hour >= only_until_hour:
                continue
            base = (100.0 + day.dayofyear * 0.5 + k * 0.01) * scale
            rows.append([base, base * 1.001, base * 0.999, base * 1.0005, 1000.0 + k])
            index.append(ts)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index, name="time"), columns=it.COLUMNS)


def same(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """True if two candle frames are identical in values and index (the index resolution is normalised first)."""
    pd.testing.assert_frame_equal(it._ns(a), it._ns(b), check_freq=False)
    return True


class Fake:
    """Stands in for the Upstox fetch; remembers every request and serves the candles on its current price basis."""

    def __init__(self, scale=1.0, partial_today=None):
        self.scale, self.calls, self.partial_today = scale, [], partial_today

    def __call__(self, symbol, interval, start, end):
        self.calls.append((start, end))
        frame = _candles(start, end, self.scale)
        if self.partial_today:
            today = pd.Timestamp(self.partial_today)
            frame = frame[(frame.index.normalize() != today) | (frame.index.hour < 12)]
        return frame


@pytest.fixture(autouse=True)
def cache(monkeypatch, tmp_path):
    monkeypatch.setattr(it, "CACHE_DIR", str(tmp_path))


def test_impossible_and_out_of_session_candles_are_dropped_and_counted():
    good = _candles("2026-10-19", "2026-10-19")
    bad = good.iloc[:4].copy()
    bad.index = [pd.Timestamp("2026-10-19 08:00"), pd.Timestamp("2026-10-19 16:00"), pd.Timestamp("2026-10-19 10:00:30"), pd.Timestamp("2026-10-19 15:30")]
    bad.iloc[0, bad.columns.get_loc("open")] = 0.0                      # a priceless candle (and out of session)
    bad.iloc[2, bad.columns.get_loc("high")] = 1.0                      # high below low
    clean, dropped = it.clean_candles(pd.concat([good, bad]).sort_index())
    assert dropped == 4 and len(clean) == len(good)                      # all four bad candles go, every good one stays
    assert (clean[["open", "high", "low", "close"]] > 0).all().all() and (clean["high"] >= clean["low"]).all()
    assert all(it.SESSION_OPEN <= t < it.SESSION_CLOSE for t in clean.index.time)


def test_the_validation_report_flags_short_days_and_candle_jumps_but_not_overnight_gaps():
    frame = _candles("2026-10-19", "2026-10-21")
    frame = frame[~((frame.index.normalize() == "2026-10-20") & (frame.index.hour >= 11))]     # a day cut off at 11:00
    frame.iloc[40, frame.columns.get_loc("close")] *= 1.5                                       # one candle jumps 50%
    report = it.validate_intraday(frame, INTERVAL)
    assert report["n_days"] == 3 and [d["date"] for d in report["short_days"]] == ["2026-10-20"] and len(report["jumps"]) >= 1
    clean = it.validate_intraday(_candles("2026-10-19", "2026-10-21", scale=1.0), INTERVAL)
    assert clean["short_days"] == [] and clean["jumps"] == []                                   # the next day's opening gap is not a jump


def test_a_second_load_of_the_same_window_makes_no_request():
    fake = Fake()
    now = _ist("2026-10-22", 18)
    a = it.load_intraday("TEST", INTERVAL, "2026-10-12", "2026-10-21", fetch=fake, now=now)
    b = it.load_intraday("TEST", INTERVAL, "2026-10-12", "2026-10-21", fetch=fake, now=now)
    assert len(fake.calls) == 1 and same(a, b) and a.index.max().date().isoformat() == "2026-10-21"


def test_todays_half_finished_session_is_never_kept():
    fake = Fake(partial_today="2026-10-22")
    noon = it.load_intraday("TEST", INTERVAL, "2026-10-19", "2026-10-22", fetch=fake, now=_ist("2026-10-22", 12))
    assert noon.index.max().date().isoformat() == "2026-10-21"                                  # today is cut at 16:00 India time
    evening = Fake()
    full = it.load_intraday("TEST", INTERVAL, "2026-10-19", "2026-10-22", fetch=evening, now=_ist("2026-10-22", 17))
    assert full.index.max().date().isoformat() == "2026-10-22" and (full.index.normalize() == "2026-10-22").sum() == 25
    assert len(evening.calls) == 1 and evening.calls[0][0] <= "2026-10-21"                       # the cache never held today, so a tail extension, with overlap


def test_extending_the_tail_downloads_only_a_few_overlapping_days_and_stays_continuous():
    fake = Fake()
    it.load_intraday("TEST", INTERVAL, "2026-10-05", "2026-10-16", fetch=fake, now=_ist("2026-10-19", 17))
    later = it.load_intraday("TEST", INTERVAL, "2026-10-05", "2026-10-21", fetch=fake, now=_ist("2026-10-22", 9))
    assert fake.calls[1][0] == "2026-10-12" and fake.calls[1][1] == "2026-10-21"               # from 4 days before the cache's end, not from the start
    assert not later.index.duplicated().any() and later.index.is_monotonic_increasing
    assert same(later, _candles("2026-10-05", "2026-10-21"))                                    # identical to one clean download


def test_a_split_between_downloads_triggers_a_full_redownload_on_one_basis():
    fake = Fake(scale=1.0)
    it.load_intraday("TEST", INTERVAL, "2026-10-05", "2026-10-16", fetch=fake, now=_ist("2026-10-19", 17))
    fake.scale = 0.5                                                                             # a 2-for-1 split: Upstox re-scales all history
    later = it.load_intraday("TEST", INTERVAL, "2026-10-05", "2026-10-21", fetch=fake, now=_ist("2026-10-22", 9))
    assert len(fake.calls) == 3 and fake.calls[2][0] == "2026-10-05"                             # tail attempt, then the whole range again
    assert same(later, _candles("2026-10-05", "2026-10-21", scale=0.5))                         # every row on the new basis, no seam


def test_asking_for_earlier_history_downloads_the_whole_range_again():
    fake = Fake()
    it.load_intraday("TEST", INTERVAL, "2026-10-12", "2026-10-16", fetch=fake, now=_ist("2026-10-19", 17))
    fake.scale = 0.9
    early = it.load_intraday("TEST", INTERVAL, "2026-09-14", "2026-10-16", fetch=fake, now=_ist("2026-10-19", 17))
    assert fake.calls[1] == ("2026-09-14", "2026-10-16") and same(early, _candles("2026-09-14", "2026-10-16", scale=0.9))


def test_a_window_that_starts_after_the_last_complete_session_is_refused():
    with pytest.raises(ValueError, match="nothing to load"):
        it.load_intraday("TEST", INTERVAL, "2026-10-22", "2026-10-22", fetch=Fake(), now=_ist("2026-10-22", 12))
