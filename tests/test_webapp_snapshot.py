"""
tests/test_webapp_snapshot.py

Two things the web app's chart depends on:

1. The strategy modules now export their indicator series
   (ma_crossover.moving_average, rsi_reversion.rsi). The point of exporting
   them is that the line a chart draws is *the same function* the strategy
   trades on -- so these tests prove generate_signals() really calls them,
   rather than carrying a private copy that could drift.

2. The snapshot command writes price files whose indicator columns are those
   functions' output, untouched.

Toy, hand-checkable data only: no network, no real cache.
"""

import json
import sys

import numpy as np
import pandas as pd
import pytest

import ma_crossover
import rsi_reversion


def _toy_df(n=320, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    idx = pd.bdate_range("2019-01-01", periods=n)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.005, "low": close * 0.995,
                         "close": close, "volume": 1_000.0}, index=idx)


# --- the exports -----------------------------------------------------------------

def test_moving_average_is_a_plain_trailing_mean_with_nan_warmup():
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    ma = ma_crossover.moving_average(close, 3)
    assert ma.isna().tolist() == [True, True, False, False, False]
    assert ma.iloc[2:].tolist() == [2.0, 3.0, 4.0]


def test_generate_signals_really_uses_the_exported_moving_average(monkeypatch):
    """If the strategy carried its own copy, patching the export would change nothing."""
    df = _toy_df()
    calls = []

    def fake(close, window):
        calls.append(window)
        # fast (50) pinned far above slow (200) -> signal is long wherever both exist
        return pd.Series(1_000.0 if window == 50 else 1.0, index=close.index).where(
            pd.Series(np.arange(len(close)) >= window - 1, index=close.index))

    monkeypatch.setattr(ma_crossover, "moving_average", fake)
    sig = ma_crossover.generate_signals(df, fast=50, slow=200)
    assert calls == [50, 200]
    assert sig.iloc[:199].isna().all() and (sig.iloc[199:] == 1.0).all()


def test_rsi_export_is_the_strategys_rsi_and_stays_in_range():
    df = _toy_df()
    pd.testing.assert_series_equal(rsi_reversion.rsi(df["close"], 14), rsi_reversion._wilders_rsi(df["close"], 14))
    r = rsi_reversion.rsi(df["close"], 14).dropna()
    assert len(r) == len(df) - 14 and r.between(0, 100).all()


def test_rsi_signal_is_driven_by_the_exported_series(monkeypatch):
    """Force RSI below oversold on day 20 and above exit on day 40; the signal must follow it."""
    df = _toy_df(n=60)

    def fake_wilders(close, period):
        r = pd.Series(50.0, index=close.index)
        r.iloc[:14] = float("nan")
        r.iloc[20] = 10.0
        r.iloc[40] = 80.0
        return r

    monkeypatch.setattr(rsi_reversion, "_wilders_rsi", fake_wilders)
    sig = rsi_reversion.generate_signals(df, period=14, oversold=30, exit_level=50)
    assert sig.iloc[14:20].eq(0.0).all() and sig.iloc[20:40].eq(1.0).all() and sig.iloc[40:].eq(0.0).all()


# --- the snapshot's price files ------------------------------------------------------

def test_snapshot_price_files_carry_the_library_series_unchanged(tmp_path, monkeypatch):
    from webapp.backend import snapshot

    df = _toy_df(n=520)
    df = df.loc["2019-01-01":]
    report = {"usable": True, "checks": [], "discontinuities": []}
    monkeypatch.setattr(snapshot, "get_universe",
                        lambda key: {"AAA.NS": {"df": df, "report": report, "symbol": "AAA"}})
    monkeypatch.setattr(snapshot, "get_slippage", lambda key: None)

    rows = snapshot.build_symbol_files("nifty50", str(tmp_path), "2026-01-01T00:00:00+00:00")
    assert len(rows) == 1 and rows[0].symbol == "AAA" and rows[0].usable is True
    assert rows[0].last_close == pytest.approx(round(float(df["close"].iloc[-1]), 2))

    stored = json.loads((tmp_path / "symbols" / "AAA.json").read_text())
    assert len(stored["dates"]) == len(df) == len(stored["close"]) == len(stored["volume"])
    sma50 = ma_crossover.moving_average(df["close"], 50).round(2)
    got = pd.Series(stored["indicators"]["sma_50"], dtype=float)
    pd.testing.assert_series_equal(got.reset_index(drop=True), sma50.reset_index(drop=True), check_names=False)
    rsi = rsi_reversion.rsi(df["close"], 14).round(2)
    got = pd.Series(stored["indicators"]["rsi_14"], dtype=float)
    pd.testing.assert_series_equal(got.reset_index(drop=True), rsi.reset_index(drop=True), check_names=False)
    assert stored["indicator_sources"]["sma_50"].startswith("strategies/ma_crossover.py")
    assert stored["adjusted"] is True
    assert sum(1 for v in stored["indicators"]["sma_200"] if v is None) == 199   # warm-up is null, not 0


def test_a_stock_too_new_for_an_rsi_gets_null_indicators_not_a_crash(tmp_path, monkeypatch):
    """Regression: a Smallcap stock listed days before the window ended has < 15 closes, and the
    library's RSI raises when there is no valid seed. The snapshot must write nulls instead."""
    from webapp.backend import snapshot

    df = _toy_df(n=320).iloc[-9:]                      # nine trading days of history
    report = {"usable": True, "checks": [], "discontinuities": []}
    monkeypatch.setattr(snapshot, "get_universe", lambda key: {"NEW.NS": {"df": df, "report": report, "symbol": "NEW"}})
    monkeypatch.setattr(snapshot, "get_slippage", lambda key: None)

    rows = snapshot.build_symbol_files("smallcap250", str(tmp_path), "2026-01-01T00:00:00+00:00")
    assert len(rows) == 1 and rows[0].symbol == "NEW"
    stored = json.loads((tmp_path / "symbols" / "NEW.json").read_text())
    assert len(stored["dates"]) == 9
    assert all(v is None for k in ("rsi_14", "sma_50", "sma_200") for v in stored["indicators"][k])


# --- manifest provenance: the snapshot may only claim what its OLDEST result can back ---------

def _prov(generated_at, data_through, ledger, commit="aaaaaaa", dirty=False):
    from webapp.backend import schemas
    return schemas.Provenance(
        generated_at=generated_at, git_commit=commit, git_dirty=dirty, ledger_total_at_snapshot=ledger,
        bonferroni_bar_at_snapshot=0.05 / ledger, data_through=data_through, in_sample_end="2020-06-30",
        risk_free_rate=0.06, initial_capital=1_000_000.0)


def test_manifest_provenance_is_that_of_the_oldest_strategy_result():
    from webapp.backend.snapshot import manifest_provenance

    older = _prov("2026-10-15T20:00:00+00:00", "2025-12-30", 200, commit="old1111", dirty=False)
    newer = _prov("2026-10-15T21:30:00+00:00", "2025-12-31", 204, commit="new2222", dirty=True)
    p = manifest_provenance([newer, older])           # order must not matter
    assert p.generated_at == older.generated_at and p.git_commit == "old1111"
    assert p.data_through == "2025-12-30"             # the weakest link
    assert p.ledger_total_at_snapshot == 200          # so a grown ledger shows STALE
    assert p.bonferroni_bar_at_snapshot == pytest.approx(0.05 / 200)
    assert p.git_dirty is True                        # any dirty source taints the whole


def test_write_manifest_covers_every_strategy_file_and_ignores_symbol_slices(tmp_path):
    from webapp.backend import schemas, snapshot
    sdir = tmp_path / "strategies"
    sdir.mkdir()

    def write(sid, prov):
        curve = schemas.EquityCurve(dates=["2020-01-01", "2020-01-02"], values=[1.0, 2.0])
        def ratio(k, w):
            return schemas.RiskAdjustedRatio(kind=k, value=0.1, window=w, status="UNVALIDATED", as_of_hypotheses=prov.ledger_total_at_snapshot)
        def wm(w):
            return schemas.WindowMetrics(sharpe=ratio("sharpe", w), sortino=ratio("sortino", w), total_return_pct=1.0, cagr_pct=1.0,
                                         max_drawdown_pct=-1.0, max_drawdown_duration_days=1.0, win_rate_pct=None, avg_win_pct=None,
                                         avg_loss_pct=None, profit_factor=None, total_trades=None, avg_holding_days=None,
                                         market_exposure_pct=None, final_equity=None, n_symbols_included=1)
        def wi(w):
            return schemas.WindowInfo(window=w, start="a", end="b", n_observations=2, strategy=wm(w), benchmark=wm(w))
        d = schemas.StrategyDetail(id=sid, name=sid, family="t", universe="nifty50", kind="per_symbol", params={}, rationale="r",
                                   status="UNVALIDATED", as_of_hypotheses=prov.ledger_total_at_snapshot,
                                   in_sample=wi("in_sample"), out_of_sample=wi("out_of_sample"), provenance=prov)
        data = schemas.StoredWindowData(equity_strategy=curve, equity_benchmark=curve)
        (sdir / f"{sid}.json").write_text(schemas.StrategyFile(detail=d, data={"in_sample": data, "out_of_sample": data}).model_dump_json())

    write("a_strategy", _prov("2026-10-15T20:00:00+00:00", "2025-12-30", 200))
    write("b_strategy", _prov("2026-10-15T21:00:00+00:00", "2025-12-31", 204))
    (sdir / "a_strategy.symbols.json").write_text("{}")      # must not be mistaken for a strategy
    m = snapshot.write_manifest(str(tmp_path), known=["b_strategy", "a_strategy"])
    assert m.strategy_ids == ["b_strategy", "a_strategy"]
    assert m.provenance.generated_at == "2026-10-15T20:00:00+00:00"
    assert (tmp_path / "manifest.json").exists()
