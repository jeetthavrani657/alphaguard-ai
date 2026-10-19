"""
tests/test_loader_artifact_rows.py

data/loader.py's _drop_phantom_rows() removes two kinds of Yahoo artifact
row: the zero-volume flat-OHLC "phantom" (2025-03-18) and, added when the
cache was first extended to the present, the still-forming current-day bar
that arrives with a volume but NaN prices. No test existed for either.
"""

import numpy as np
import pandas as pd

from loader import _drop_phantom_rows


def _frame(rows):
    idx = pd.date_range("2026-10-12", periods=len(rows), freq="D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def test_a_nan_price_row_with_volume_is_dropped():
    df = _frame([
        [100, 101, 99, 100, 1000],
        [100, 102, 99, 101, 1200],
        [np.nan, np.nan, np.nan, np.nan, 900],   # today's incomplete bar
    ])
    out = _drop_phantom_rows(df)
    assert len(out) == 2
    assert not out[["open", "high", "low", "close"]].isna().any().any()


def test_the_original_zero_volume_phantom_row_is_still_dropped():
    df = _frame([
        [100, 101, 99, 100, 1000],
        [100, 100, 100, 100, 0],                 # flat, zero volume, == prior close
        [101, 103, 100, 102, 1500],
    ])
    assert len(_drop_phantom_rows(df)) == 2


def test_ordinary_rows_including_a_real_zero_volume_day_with_a_price_move_are_kept():
    df = _frame([
        [100, 101, 99, 100, 1000],
        [100, 102, 99, 101, 0],                  # zero volume but prices moved -> not the artifact
        [101, 103, 100, 102, 1500],
    ])
    assert len(_drop_phantom_rows(df)) == 3


def test_a_refresh_keeps_a_cached_day_that_yahoo_lists_without_prices_and_lets_a_priced_day_win(tmp_path, monkeypatch):
    import loader
    monkeypatch.setattr(loader, "CACHE_DIR", tmp_path)
    idx = pd.bdate_range("2026-10-14", periods=4)                                    # Wed 14 .. Mon 19
    cached = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": [10.0, 11.0, 12.0, 13.0], "volume": 100}, index=idx)
    cached.index.name = "date"
    loader._save_cache("ABC.NS", cached)
    unpriced = cached.copy()
    unpriced.loc[idx[-1], ["open", "high", "low", "close"]] = np.nan                  # Yahoo: a volume, no prices yet
    monkeypatch.setattr(loader, "_download_with_retry", lambda *a, **k: unpriced.rename(columns=str.title))
    out = loader.load_price_data("ABC.NS", "2026-10-14", "2026-10-20")
    assert list(out.index) == list(idx) and out["close"].iloc[-1] == 13.0              # the provisional 19th survives
    priced = cached.copy()
    priced.loc[idx[-1], "close"] = 13.5                                               # later Yahoo prices it: the fresh value wins
    monkeypatch.setattr(loader, "_download_with_retry", lambda *a, **k: priced.rename(columns=str.title))
    assert loader.load_price_data("ABC.NS", "2026-10-14", "2026-10-21")["close"].iloc[-1] == 13.5
