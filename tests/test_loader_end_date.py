"""
tests/test_loader_end_date.py

Regression tests for two defects in data/loader.py, found by the web app's
smoke test (data/known_issues.md, "The last day of the research window is never
downloaded"):

1. yfinance treats `end` as EXCLUSIVE. load_price_data(sym, start, "2025-12-31")
   therefore never fetched the 2025-12-31 bar, and every later load made a
   futile 2025-12-31 -> 2025-12-31 request for it.

2. Extending a cache by appending a freshly downloaded tail splices two
   adjustment bases together. Yahoo re-scales adjusted history whenever a
   dividend goes ex, so the join showed a fake one-day move (COALINDIA -1.25%,
   TCS -0.53% on 2025-12-31 in the real Nifty 50 cache). An extension must
   re-download one contiguous range instead.

No network: _download_with_retry is replaced by a fake that behaves like Yahoo
in the two ways that matter (exclusive end; prices re-scaled between downloads).
"""

import numpy as np
import pandas as pd
import pytest

import loader

DAYS = pd.bdate_range("2025-12-01", "2026-01-30")        # the "market": every weekday, no holidays
BASE_CLOSE = pd.Series(100.0 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, len(DAYS)))), index=DAYS)


class FakeYahoo:
    """Stands in for loader._download_with_retry."""

    def __init__(self, scales=(1.0,)):
        self.calls = []                  # (symbol, start, end) exactly as the loader asked
        self._scales = list(scales)      # the adjustment basis of the 1st, 2nd, ... download

    def __call__(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        scale = self._scales[min(len(self.calls) - 1, len(self._scales) - 1)]
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        days = DAYS[(DAYS >= s) & (DAYS < e)]            # Yahoo: end is EXCLUSIVE
        close = BASE_CLOSE.loc[days] * scale
        # yfinance returns capitalised columns; loader._clean_columns lower-cases them
        return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                             "Volume": 1_000.0}, index=days)


@pytest.fixture
def yahoo(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)       # never touch the real cache
    fake = FakeYahoo()
    monkeypatch.setattr(loader, "_download_with_retry", fake)
    return fake


def test_the_last_day_of_the_window_is_downloaded(yahoo):
    """The original bug: end='2025-12-31' stopped at 2025-12-30."""
    df = loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    assert df.index.max() == pd.Timestamp("2025-12-31")
    assert len(df) == len(DAYS[(DAYS >= "2025-12-01") & (DAYS <= "2025-12-31")])


def test_yahoo_is_asked_for_the_day_after_the_requested_end(yahoo):
    loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    (_sym, start, end), = yahoo.calls
    assert start == "2025-12-01" and end == "2026-01-01"


def test_the_result_is_clipped_to_the_requested_window(yahoo):
    loader.load_price_data("TEST", "2025-12-01", "2026-01-15")          # fills the cache wide
    df = loader.load_price_data("TEST", "2025-12-10", "2025-12-31")
    assert df.index.min() == pd.Timestamp("2025-12-10") and df.index.max() == pd.Timestamp("2025-12-31")


def test_a_covered_window_makes_no_network_call(yahoo):
    loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    assert len(yahoo.calls) == 1
    again = loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    assert len(yahoo.calls) == 1                                          # the 12-31 bar IS cached now
    assert again.index.max() == pd.Timestamp("2025-12-31")


def test_extending_the_tail_redownloads_one_range_so_there_is_no_adjustment_seam(monkeypatch, tmp_path):
    """The second defect. Yahoo's 2nd download is on a different basis (x0.98: a dividend went ex)."""
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    fake = FakeYahoo(scales=(1.0, 0.98))
    monkeypatch.setattr(loader, "_download_with_retry", fake)

    loader.load_price_data("TEST", "2025-12-01", "2025-12-30")           # basis 1.00
    df = loader.load_price_data("TEST", "2025-12-01", "2026-01-09")      # needs more: re-download

    assert len(fake.calls) == 2
    assert fake.calls[1][1] == "2025-12-01"                               # from the START, not from the cache's tail
    # one basis throughout: every day-to-day return equals the market's own, including across the old seam
    expected = BASE_CLOSE.loc[df.index].pct_change().dropna()
    pd.testing.assert_series_equal(df["close"].pct_change().dropna(), expected, check_names=False, rtol=1e-9)
    assert df["close"].iloc[0] == pytest.approx(BASE_CLOSE.loc[df.index[0]] * 0.98)   # old rows were re-based too


def test_the_old_splice_would_have_produced_a_fake_move(monkeypatch, tmp_path):
    """Documents the failure the above prevents: appending a tail on a new basis jumps by the factor."""
    old_basis = BASE_CLOSE.loc[:"2025-12-30"] * 1.0
    new_tail = BASE_CLOSE.loc["2025-12-31":] * 0.98
    spliced = pd.concat([old_basis, new_tail])
    jump = spliced.loc["2025-12-31"] / spliced.loc["2025-12-30"] - 1
    true = BASE_CLOSE.loc["2025-12-31"] / BASE_CLOSE.loc["2025-12-30"] - 1
    assert jump - true == pytest.approx(-0.02, abs=0.02 * abs(1 + true))   # about -2% of fake move


def test_extending_the_head_also_redownloads_everything(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    fake = FakeYahoo(scales=(1.0, 0.97))
    monkeypatch.setattr(loader, "_download_with_retry", fake)
    loader.load_price_data("TEST", "2025-12-15", "2025-12-31")
    df = loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    assert len(fake.calls) == 2 and fake.calls[1][1] == "2025-12-01"
    assert df["close"].iloc[-1] == pytest.approx(BASE_CLOSE.loc["2025-12-31"] * 0.97)   # whole series, new basis


def test_extending_never_shrinks_the_cache(yahoo):
    loader.load_price_data("TEST", "2025-12-01", "2026-01-23")           # wide cache
    loader.load_price_data("TEST", "2025-11-24", "2025-12-31")            # head extension (Nov 24-28 before the market data)
    df = loader.load_price_data("TEST", "2025-12-01", "2026-01-23")
    assert df.index.max() == pd.Timestamp("2026-01-23")                   # the tail was not lost


def test_an_empty_extension_keeps_the_existing_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    good = FakeYahoo()
    monkeypatch.setattr(loader, "_download_with_retry", good)
    first = loader.load_price_data("TEST", "2025-12-01", "2025-12-31")

    def nothing(symbol, start, end):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    monkeypatch.setattr(loader, "_download_with_retry", nothing)
    # a window ending past the cache (e.g. a weekend) triggers a download that returns nothing
    again = loader.load_price_data("TEST", "2025-12-01", "2026-01-04")
    pd.testing.assert_frame_equal(again, first, check_freq=False)
    assert loader._load_cache("TEST.NS").index.max() == pd.Timestamp("2025-12-31")   # cache intact


def test_no_cache_and_nothing_downloaded_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(loader, "_download_with_retry",
                        lambda s, a, b: pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]))
    with pytest.raises(ValueError, match="No data returned"):
        loader.load_price_data("NOSUCH", "2025-12-01", "2025-12-31")


def test_force_refresh_ignores_the_cache_and_replaces_it(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    fake = FakeYahoo(scales=(1.0, 0.9))
    monkeypatch.setattr(loader, "_download_with_retry", fake)
    loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    df = loader.load_price_data("TEST", "2025-12-01", "2025-12-31", force_refresh=True)
    assert len(fake.calls) == 2
    assert df["close"].iloc[0] == pytest.approx(BASE_CLOSE.loc[df.index[0]] * 0.9)


def test_a_vendor_truncated_download_never_replaces_a_deeper_cache(monkeypatch, tmp_path):
    """HEG.NS: after a re-listing Yahoo served only the new history; a refresh would have wiped 2015-2025."""
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    full = FakeYahoo()
    monkeypatch.setattr(loader, "_download_with_retry", full)
    first = loader.load_price_data("TEST", "2025-12-01", "2025-12-31")
    assert first.index.min() == pd.Timestamp("2025-12-01")

    def truncated(symbol, start, end):                       # only the last few days survive at the vendor
        return FakeYahoo()(symbol, "2026-01-20", end)
    monkeypatch.setattr(loader, "_download_with_retry", truncated)

    for kwargs in ({}, {"force_refresh": True}):              # a window needing extension, and an explicit refresh
        df = loader.load_price_data("TEST", "2025-12-01", "2026-01-23", **kwargs)
        assert df.index.min() == pd.Timestamp("2025-12-01")   # old history served from the cache
    assert loader._load_cache("TEST.NS").index.min() == pd.Timestamp("2025-12-01")    # and still on disk


def test_a_stock_that_listed_after_start_is_not_mistaken_for_truncation(monkeypatch, tmp_path):
    """The guard must not fire when the cache never had the early history (a recent listing)."""
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    fake = FakeYahoo(scales=(1.0, 0.99))
    monkeypatch.setattr(loader, "_download_with_retry", fake)
    loader.load_price_data("NEW", "2025-11-01", "2025-12-31")      # market data begins 2025-12-01: "listed" then
    df = loader.load_price_data("NEW", "2025-11-01", "2026-01-23")
    assert df.index.min() == pd.Timestamp("2025-12-01") and df.index.max() == pd.Timestamp("2026-01-23")
    assert len(fake.calls) == 2                                    # it did extend (no false positive)
