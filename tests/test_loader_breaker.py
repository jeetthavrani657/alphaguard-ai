"""
tests/test_loader_breaker.py

When Yahoo is unreachable, yfinance returns EMPTY frames after about 15 seconds each instead of raising, so a run over hundreds of
symbols can take hours (found 2026-10-22, right after the laptop woke). The loader now stops asking after five long-range downloads in
a row come back empty, serves the cache for five minutes, and then probes again. No network: yf.download and the clock are faked.
"""

import pandas as pd
import pytest

import loader

LONG = ("2015-01-01", "2026-10-23")       # a download that is never legitimately empty
SHORT = ("2026-10-20", "2026-10-23")      # a few days: empty on a weekend or holiday, which is normal


class FakeYahoo:
    """Yahoo for ordinary symbols. The canary index is answered from `canary_up`, and its requests are counted apart."""

    def __init__(self, empty=True, canary_up=False):
        self.empty, self.canary_up, self.calls, self.canary_calls = empty, canary_up, 0, 0

    def __call__(self, symbol, **kwargs):
        if symbol == loader.CANARY_SYMBOL:
            self.canary_calls += 1
            return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-10-21"])) if self.canary_up else pd.DataFrame(columns=loader._EMPTY)
        self.calls += 1
        if self.empty:
            return pd.DataFrame(columns=loader._EMPTY)
        return pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1.0]},
                            index=pd.DatetimeIndex(["2026-10-21"]))


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 1000.0}
    monkeypatch.setattr(loader.time, "monotonic", lambda: state["now"])
    monkeypatch.setitem(loader._BREAKER, "failures", 0)
    monkeypatch.setitem(loader._BREAKER, "open_until", 0.0)
    return state


def _ask(n, rng=LONG):
    for i in range(n):
        loader._download_with_retry(f"S{i}.NS", *rng)


def test_five_empty_long_downloads_in_a_row_stop_further_requests(monkeypatch, clock):
    fake = FakeYahoo(empty=True)
    monkeypatch.setattr(loader.yf, "download", fake)
    _ask(5)
    assert fake.calls == 5
    result = loader._download_with_retry("NEXT.NS", *LONG)
    assert fake.calls == 5 and result.empty and list(result.columns) == loader._EMPTY       # no sixth request


def test_a_success_in_between_resets_the_count(monkeypatch, clock):
    bad, good = FakeYahoo(empty=True), FakeYahoo(empty=False)
    monkeypatch.setattr(loader.yf, "download", bad)
    _ask(4)
    monkeypatch.setattr(loader.yf, "download", good)
    _ask(1)
    monkeypatch.setattr(loader.yf, "download", bad)
    _ask(4)
    assert bad.calls == 8 and loader._BREAKER["open_until"] == 0.0                         # four, a success, four more: never opened


def test_after_the_cooldown_it_asks_again(monkeypatch, clock):
    fake = FakeYahoo(empty=True)
    monkeypatch.setattr(loader.yf, "download", fake)
    _ask(5)
    clock["now"] += loader.BREAKER_COOLDOWN_SECONDS - 1
    loader._download_with_retry("EARLY.NS", *LONG)
    assert fake.calls == 5                                                                  # still closed to requests
    clock["now"] += 2
    monkeypatch.setattr(loader.yf, "download", FakeYahoo(empty=False))
    assert not loader._download_with_retry("PROBE.NS", *LONG).empty                         # the probe goes out and succeeds
    assert loader._BREAKER["failures"] == 0


def test_short_range_empties_are_normal_and_never_count(monkeypatch, clock):
    fake = FakeYahoo(empty=True)
    monkeypatch.setattr(loader.yf, "download", fake)
    _ask(20, SHORT)
    assert fake.calls == 20 and loader._BREAKER["open_until"] == 0.0


def test_while_open_load_price_data_serves_the_cache_untouched(monkeypatch, clock, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    days = pd.bdate_range("2025-01-01", "2026-10-19")
    cached = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1000.0}, index=days)
    cached.index.name = "date"
    cached.to_csv(tmp_path / "KEEP.NS.csv")
    fake = FakeYahoo(empty=True)
    monkeypatch.setattr(loader.yf, "download", fake)
    _ask(5)
    before = fake.calls
    df = loader.load_price_data("KEEP", "2025-01-01", "2026-10-21")                          # asks for days the cache lacks
    assert fake.calls == before and df.index.max() == pd.Timestamp("2026-10-19") and len(df) == len(days)


def test_five_bad_tickers_while_the_index_still_answers_do_not_open_the_breaker(monkeypatch, clock):
    fake = FakeYahoo(empty=True, canary_up=True)                                           # delisted tickers, but Yahoo itself is fine
    monkeypatch.setattr(loader.yf, "download", fake)
    _ask(5)
    assert fake.canary_calls == 1 and loader._BREAKER["open_until"] == 0.0 and loader._BREAKER["failures"] == 0
    _ask(3)
    assert fake.calls == 8                                                                  # it keeps asking


def test_a_canary_that_raises_counts_as_yahoo_down(monkeypatch, clock):
    def boom(symbol, **kwargs):
        if symbol == loader.CANARY_SYMBOL:
            raise ConnectionError("no network")
        return pd.DataFrame(columns=loader._EMPTY)
    monkeypatch.setattr(loader.yf, "download", boom)
    _ask(5)
    assert loader._BREAKER["open_until"] > 0.0
