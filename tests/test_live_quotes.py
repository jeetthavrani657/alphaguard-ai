"""
tests/test_live_quotes.py

research/live_quotes.py writes the near-live prices file that the web app displays. No network here:
the Upstox client is faked. The tests check the parts a person would be misled by if they were wrong:
market hours, a zero or missing price never shown as a price, change % worked out once and correctly,
an expired token explained instead of crashing, and the file written atomically.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import live_quotes as lq

IST = timezone(timedelta(hours=5, minutes=30))


def _at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# Monday 2026-10-19 ... Saturday 2026-10-24
@pytest.mark.parametrize("when,expected", [
    (_at(2026, 10, 19, 9, 14), "pre-open"), (_at(2026, 10, 19, 9, 0), "pre-open"), (_at(2026, 10, 19, 8, 59), "closed"),
    (_at(2026, 10, 19, 9, 15), "open"), (_at(2026, 10, 19, 15, 29), "open"), (_at(2026, 10, 19, 15, 30), "closed"),
    (_at(2026, 10, 24, 11, 0), "closed"), (_at(2026, 10, 25, 11, 0), "closed"),
])
def test_market_status_follows_nse_hours_in_ist(when, expected):
    assert lq.market_status(when) == expected


def test_market_status_converts_other_timezones():
    assert lq.market_status(datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)) == "open"       # 04:00 UTC = 09:30 IST


def test_change_percent_is_worked_out_here_and_a_missing_price_stays_missing():
    now = _at(2026, 10, 19, 11, 0)
    quotes = {"RELIANCE": {"last_price": 1211.2, "prev_close": 1200.0, "volume": 10},
              "TCS": {"last_price": None, "prev_close": None, "volume": 0}}
    p = lq.build_payload(quotes, ["RELIANCE", "TCS", "ITC"], now)
    by = {r["symbol"]: r for r in p["quotes"]}
    assert by["RELIANCE"]["change_pct"] == 0.93                                                  # (1211.2-1200)/1200 = 0.9333%
    assert by["TCS"]["last_price"] is None and by["TCS"]["change_pct"] is None                    # not 0, not a made-up number
    assert by["ITC"]["last_price"] is None                                                       # asked for but not returned
    assert p["available"] is True and p["reason"] is None and p["market_status"] == "open" and p["n_requested"] == 3
    assert p["generated_at"] == "2026-10-19T05:30:00Z"


def test_an_error_payload_carries_a_reason_and_no_prices():
    p = lq.build_payload({"A": {"last_price": 1, "prev_close": 1}}, ["A"], _at(2026, 10, 19, 11, 0), error="expired")
    assert p["available"] is False and p["reason"] == "expired" and p["quotes"] == []


def test_symbols_come_from_every_books_holdings_and_say_which_book_holds_them(tmp_path):
    path = tmp_path / "books.json"
    path.write_text(json.dumps({"books": [{"id": "a", "holdings": [{"symbol": "TCS"}, {"symbol": "ITC"}]},
                                          {"id": "b", "holdings": [{"symbol": "ITC"}, {"symbol": "M&M"}]},
                                          {"id": "c", "holdings": []}]}))
    assert lq.symbols_from_books(str(path)) == ["ITC", "M&M", "TCS"]
    assert lq.holdings_by_symbol(str(path)) == {"ITC": ["a", "b"], "M&M": ["b"], "TCS": ["a"]}
    assert lq.symbols_from_books(str(tmp_path / "missing.json")) == [] and lq.holdings_by_symbol(str(tmp_path / "x")) == {}


def test_each_quote_row_says_which_books_hold_the_stock():
    p = lq.build_payload({"TCS": {"last_price": 2.0, "prev_close": 1.0, "volume": 1}}, ["TCS", "ITC"],
                         _at(2026, 10, 19, 11, 0), held_by={"TCS": ["quality_value_nifty50"]})
    by = {r["symbol"]: r for r in p["quotes"]}
    assert by["TCS"]["held_by"] == ["quality_value_nifty50"] and by["ITC"]["held_by"] == []


def test_run_once_writes_the_file_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(lq.upstox_client, "get_ltp",
                        lambda symbols, imap=None, token=None: {"TCS": {"last_price": 2449.4, "prev_close": 2440.0, "volume": 5}})
    path = str(tmp_path / "out" / "live.json")
    p = lq.run_once(["TCS"], {}, _at(2026, 10, 19, 10, 0), path)
    assert json.load(open(path)) == p and not os.path.exists(path + ".tmp")
    assert p["quotes"][0]["change_pct"] == 0.39


@pytest.mark.parametrize("message,expected", [
    ("UPSTOX_ACCESS_TOKEN is not set (see CLAUDE.md rule 5)", "No Upstox access token is set"),
    ("Upstox returned HTTP 401 [UDAPI100050 Invalid token] (request path: /v3/x)", "expired or is invalid"),
    ("could not reach Upstox (gaierror)", "Could not fetch quotes: could not reach Upstox"),
])
def test_a_failure_is_explained_in_plain_words_and_never_raised(tmp_path, monkeypatch, message, expected):
    def fail(*a, **k):
        raise RuntimeError(message)
    monkeypatch.setattr(lq.upstox_client, "get_ltp", fail)
    p = lq.run_once(["TCS"], {}, _at(2026, 10, 19, 10, 0), str(tmp_path / "live.json"))
    assert p["available"] is False and expected in p["reason"]


def test_polling_pace_depends_on_whether_it_is_working_and_the_market_is_open():
    assert lq.next_pause({"available": False, "market_status": "open"}) == lq.POLL_ERROR_SECONDS
    assert lq.next_pause({"available": True, "market_status": "open"}) == lq.POLL_OPEN_SECONDS
    assert lq.next_pause({"available": True, "market_status": "closed"}) == lq.POLL_CLOSED_SECONDS
