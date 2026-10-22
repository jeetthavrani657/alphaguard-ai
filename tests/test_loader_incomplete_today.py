"""
tests/test_loader_incomplete_today.py

Today's bar must never be stored while the NSE session is still running. Found 2026-10-22: a catch-up run of the
daily batch at noon IST pulled Yahoo's live, half-finished bar for that day, cached it, and logged it in the forward
books as if it were the close. The loader now drops today's bar until 16:00 IST, from downloads and from the cache.

No network: the download is a fake and the clock is set by the test.
"""

from datetime import datetime, timezone

import pandas as pd
import pytest

import loader

DAYS = pd.bdate_range("2026-10-12", "2026-10-22")          # the last day, 2026-10-22, is "today"


def _ist(hour, minute=0):
    """A UTC timestamp for 2026-10-22 at the given Indian time (IST = UTC + 5:30)."""
    ist = pd.Timestamp(2026, 10, 22, hour, minute) - pd.Timedelta(hours=5, minutes=30)
    return datetime(ist.year, ist.month, ist.day, ist.hour, ist.minute, tzinfo=timezone.utc)


def _fake_yahoo(symbol, start, end):
    """Yahoo: every weekday, the last one included, end exclusive."""
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS < pd.Timestamp(end))]
    close = pd.Series([100.0 + i for i in range(len(days))], index=days)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1_000.0},
                        index=days)


@pytest.fixture
def market(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(loader, "_download_with_retry", _fake_yahoo)

    def set_clock(hour, minute=0):
        monkeypatch.setattr(loader, "_now_utc", lambda: _ist(hour, minute))
    return set_clock


def test_a_download_during_the_session_does_not_keep_todays_bar(market):
    market(12)
    df = loader.load_price_data("TEST", "2026-10-12", "2026-10-22")
    assert df.index.max() == pd.Timestamp("2026-10-21")
    assert loader._load_cache("TEST.NS").index.max() == pd.Timestamp("2026-10-21")      # and not on disk either


def test_after_the_settle_time_todays_bar_is_kept(market):
    market(16)
    df = loader.load_price_data("TEST", "2026-10-12", "2026-10-22")
    assert df.index.max() == pd.Timestamp("2026-10-22")


def test_just_before_the_settle_time_it_is_still_dropped(market):
    market(15, 59)
    df = loader.load_price_data("TEST", "2026-10-12", "2026-10-22")
    assert df.index.max() == pd.Timestamp("2026-10-21")


def test_a_partial_bar_already_in_the_cache_is_cleared_on_the_next_load(market):
    market(17)
    loader.load_price_data("TEST", "2026-10-12", "2026-10-22")          # evening run: the full day is cached
    market(12)                                                            # a later run that pretends it is noon
    df = loader.load_price_data("TEST", "2026-10-12", "2026-10-22")
    assert df.index.max() == pd.Timestamp("2026-10-21")                   # the cache is not served as complete


def test_earlier_days_are_never_touched(market):
    market(9)
    df = loader.load_price_data("TEST", "2026-10-12", "2026-10-22")
    assert list(df.index) == list(DAYS[DAYS < "2026-10-22"])
