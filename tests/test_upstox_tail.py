"""
tests/test_upstox_tail.py

data/upstox_tail.py fills the newest sessions Yahoo has not priced yet, from the read-only Upstox client, and data/loader.py's
tail hook decides what is kept. No test touches the network: the fetch functions are stubs. What matters: it asks for nothing
when no new session should exist, it never supplies a day Yahoo already priced, a bad row is never kept, a failing second
source never breaks the primary load, and Yahoo's own value replaces the filled one once Yahoo has it.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

import loader
import upstox_tail as ut


def utc(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# --- which session should exist --------------------------------------------------------------------------------------

@pytest.mark.parametrize("now,expected", [
    (utc(2026, 10, 19, 13, 0), "2026-10-19"),      # Mon 18:30 India time: the day is over
    (utc(2026, 10, 19, 8, 0), "2026-10-16"),       # Mon 13:30 India time: still trading, so Friday is the last complete day
    (utc(2026, 10, 17, 10, 0), "2026-10-16"),      # Saturday: Friday
    (utc(2026, 10, 18, 20, 0), "2026-10-16"),      # Sunday evening: Friday
    (utc(2026, 10, 20, 2, 0), "2026-10-19"),       # Tue 07:30 India time, before the open: Monday
])
def test_the_last_complete_session_is_a_weekday_after_the_close(now, expected):
    assert ut.expected_last_session(now) == pd.Timestamp(expected)


# --- the source itself ----------------------------------------------------------------------------------------------

def _frame(days, close=100.0):
    idx = pd.DatetimeIndex(days)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0}, index=idx)


def _tail(now, range_days=(), today_days=(), tmp_path=None):
    calls = {"range": [], "today": []}

    def fetch_range(symbol, start, end, imap):
        calls["range"].append((symbol, start, end))
        return _frame(range_days) if range_days else pd.DataFrame()

    def fetch_today(symbol, imap):
        calls["today"].append(symbol)
        return _frame(today_days, 105.0) if today_days else pd.DataFrame()

    t = ut.UpstoxTail(now=lambda: now, fetch_range=fetch_range, fetch_today=fetch_today, log_path=str(tmp_path / "log.csv") if tmp_path else None)
    t._map = {"ABC": "x"}
    return t, calls


def test_no_request_at_all_when_no_new_session_should_exist_yet():
    t, calls = _tail(utc(2026, 10, 19, 8, 0))                                    # Mon 13:30: Friday is the last complete day
    out = t("ABC", pd.Timestamp("2026-10-17"), pd.Timestamp("2026-10-19"))        # Yahoo already has Friday
    assert out.empty and calls == {"range": [], "today": []}


def test_a_session_before_today_comes_from_the_completed_days_endpoint_and_is_trimmed_to_the_wanted_window(tmp_path):
    t, calls = _tail(utc(2026, 10, 20, 2, 0), range_days=["2026-10-15", "2026-10-16", "2026-10-19"], tmp_path=tmp_path)   # Tue before the open
    out = t("ABC", pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20"))
    assert list(out.index) == [pd.Timestamp("2026-10-19")] and calls["today"] == [] and len(calls["range"]) == 1
    assert (tmp_path / "log.csv").read_text().count("ABC") == 1                  # every filled day is logged


def test_todays_candle_comes_from_the_intraday_endpoint_after_the_close():
    t, calls = _tail(utc(2026, 10, 20, 13, 0), range_days=["2026-10-19"], today_days=["2026-10-20"])     # Tue 18:30
    out = t("ABC", pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20"))
    assert list(out.index) == [pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20")] and calls["today"] == ["ABC"]
    only_today, calls2 = _tail(utc(2026, 10, 20, 13, 0), today_days=["2026-10-20"])
    assert list(only_today("ABC", pd.Timestamp("2026-10-20"), pd.Timestamp("2026-10-20")).index) == [pd.Timestamp("2026-10-20")]
    assert calls2["range"] == []


# --- the loader's hook ---------------------------------------------------------------------------------------------

@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    yield tmp_path
    loader.set_tail_source(None)


def _yahoo(days, last_close=np.nan):
    idx = pd.DatetimeIndex(days)
    df = pd.DataFrame({"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "Volume": 100}, index=idx)
    df.iloc[-1, df.columns.get_indexer(["Open", "High", "Low", "Close"])] = [last_close] * 4          # Yahoo's newest row: a volume, no prices
    return df


def _load(monkeypatch, yahoo, end="2026-10-20"):
    monkeypatch.setattr(loader, "_download_with_retry", lambda *a, **k: yahoo)
    return loader.load_price_data("ABC.NS", "2026-10-14", end)


def test_a_day_yahoo_has_not_priced_is_filled_from_the_second_source_saved_and_later_replaced_by_yahoo(cache, monkeypatch):
    days = pd.bdate_range("2026-10-14", "2026-10-19")
    loader.set_tail_source(lambda symbol, start, end: _frame(["2026-10-19"]).rename_axis("date"))
    out = _load(monkeypatch, _yahoo(days))                                          # Yahoo: nothing priced for the 19th
    assert out.index.max() == pd.Timestamp("2026-10-19") and out["close"].iloc[-1] == 100.0
    assert loader._load_cache("ABC.NS").index.max() == pd.Timestamp("2026-10-19")  # kept in the cache
    loader.set_tail_source(None)
    priced = _yahoo(days, last_close=12.0)                                          # Yahoo prices the 19th later: its value wins
    assert _load(monkeypatch, priced)["close"].iloc[-1] == 12.0


def test_the_second_source_is_not_asked_for_a_day_yahoo_already_priced(cache, monkeypatch):
    asked = []
    loader.set_tail_source(lambda symbol, start, end: asked.append((start, end)) or pd.DataFrame())
    days = pd.bdate_range("2026-10-14", "2026-10-19")
    out = _load(monkeypatch, _yahoo(days, last_close=11.0), end="2026-10-19")      # the window ends on a day Yahoo priced
    assert out["close"].iloc[-1] == 11.0 and asked == []


def test_bad_rows_from_the_second_source_are_never_kept_and_a_failing_source_never_breaks_the_load(cache, monkeypatch):
    days = pd.bdate_range("2026-10-14", "2026-10-19")
    bad = pd.concat([_frame(["2026-10-19"]).assign(high=1.0, low=5.0),            # high below low: impossible
                     _frame(["2026-10-20"]).assign(close=np.nan)])                 # no price
    loader.set_tail_source(lambda symbol, start, end: bad)
    assert _load(monkeypatch, _yahoo(days)).index.max() == pd.Timestamp("2026-10-16")        # nothing bad was added (the 19th stays absent)

    def boom(symbol, start, end):
        raise RuntimeError("token expired")
    loader.set_tail_source(boom)
    assert _load(monkeypatch, _yahoo(days)).index.max() == pd.Timestamp("2026-10-16")        # the primary load still worked


def test_a_rejected_token_costs_one_request_not_hundreds():
    calls = []

    def rejected(symbol, start, end, imap):
        calls.append(symbol)
        raise RuntimeError("Upstox returned HTTP 403 (request path: /v3/historical-candle/x)")

    t = ut.UpstoxTail(now=lambda: utc(2026, 10, 20, 13, 0), fetch_range=rejected, fetch_today=lambda s, m: pd.DataFrame(), log_path=None)
    t._map = {"ABC": "x", "DEF": "y"}
    assert t("ABC", pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20")).empty
    assert t("DEF", pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20")).empty
    assert calls == ["ABC"]                                                      # the second symbol never reached the network
    other = ut.UpstoxTail(now=lambda: utc(2026, 10, 20, 13, 0), fetch_range=lambda *a: (_ for _ in ()).throw(RuntimeError("Upstox returned HTTP 500")),
                          fetch_today=lambda s, m: pd.DataFrame(), log_path=None)
    other._map = {"ABC": "x"}
    with pytest.raises(RuntimeError):                                            # any other failure still propagates (the loader reports it per symbol)
        other("ABC", pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20"))
