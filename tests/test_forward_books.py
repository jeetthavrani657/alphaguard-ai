"""
tests/test_forward_books.py

research/forward_books.py runs frozen candidate strategies on out-of-time data.
These tests use toy prices (no network, no real cache) and check the invariants
that make the output trustworthy:

  * the frozen registry is what the research registered (nothing re-tuned)
  * NOT_STARTED before the first countable day; RUNNING after
  * the charted series reproduce the headline figures (final growth - 100 ==
    return; deepest drawdown == max drawdown), for the book AND its benchmark
  * Sharpe is withheld until a year of forward days exists
  * the report is idempotent and the files are written safely
"""

import json

import numpy as np
import pandas as pd
import pytest

import config
import cross_sectional_momentum
import forward_books

END = pd.Timestamp("2026-10-20")
REPORT = {"usable": True, "checks": [], "discontinuities": []}


def _toy_universe(n_symbols=14, n_days=700, seed=11):
    """Random-walk stocks with a mild upward drift, ending on END."""
    idx = pd.bdate_range(end=END, periods=n_days)
    rng = np.random.default_rng(seed)
    data = {}
    for k in range(n_symbols):
        close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.014, n_days)))
        df = pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99, "close": close,
                           "volume": 1_000_000.0}, index=idx)
        data[f"S{k:02d}.NS"] = {"df": df, "report": REPORT, "symbol": f"S{k:02d}"}
    return data


@pytest.fixture
def window(monkeypatch):
    """Forward window = the last ~40 sessions of the toy data."""
    monkeypatch.setattr(forward_books, "FORWARD_START", "2026-09-01")
    monkeypatch.setattr(forward_books, "FIRST_COUNTED_DAY", "2026-09-02")


MA_BOOK = {
    "id": "toy_ma", "name": "toy MA", "kind": "per_symbol", "universe": "nifty50", "strategy": "ma_crossover",
    "params": {"fast": 10, "slow": 30}, "rationale": "r", "why_forward_tested": "w",
}
MOM_BOOK = {
    "id": "toy_mom", "name": "toy momentum", "kind": "portfolio", "universe": "nifty50",
    "params": {"lookback_days": 252, "skip_days": 21, "top_n": 10}, "rationale": "r", "why_forward_tested": "w",
}


# --- the frozen registry ---------------------------------------------------------------------

def test_the_books_are_exactly_what_the_research_registered():
    ids = [b["id"] for b in forward_books.BOOKS]
    assert ids == ["momentum_nifty50", "ma_crossover_smallcap250"] and len(set(ids)) == len(ids)
    mom = next(b for b in forward_books.BOOKS if b["id"] == "momentum_nifty50")
    assert mom["params"] == {"lookback_days": cross_sectional_momentum.LOOKBACK_DAYS,
                             "skip_days": cross_sectional_momentum.SKIP_DAYS, "top_n": cross_sectional_momentum.TOP_N}
    ma = next(b for b in forward_books.BOOKS if b["id"] == "ma_crossover_smallcap250")
    assert ma["params"] == config.MA_CROSSOVER_PARAMS and ma["liquidity_costs"] is True
    for b in forward_books.BOOKS:
        assert b["universe"] in forward_books.UNIVERSES
        assert b["kind"] == "portfolio" or b.get("strategy") in forward_books.STRATEGY_MODULES


def test_the_frozen_dates_and_gate_have_not_been_edited():
    assert forward_books.FORWARD_START == "2026-10-16"
    assert forward_books.FIRST_COUNTED_DAY == "2026-10-19"
    assert forward_books.MIN_DAYS_FOR_SHARPE == 252


# --- status -------------------------------------------------------------------------------------

def test_before_the_first_counted_day_the_book_is_not_started_and_shows_no_numbers(monkeypatch):
    monkeypatch.setattr(forward_books, "FIRST_COUNTED_DAY", "2027-01-04")           # after the toy data ends
    rep = forward_books.build_book_report(MA_BOOK, _toy_universe())
    assert rep["status"] == "NOT_STARTED" and rep["n_trading_days"] == 0
    assert rep["summary"] is None and rep["growth_book"] is None
    assert any("clock has started" in n for n in rep["notes"])


# --- running books: the numbers must reconcile ----------------------------------------------------

def _reconcile(rep):
    s = rep["summary"]
    gb, gm = rep["growth_book"], rep["growth_benchmark"]
    assert len(gb["dates"]) == len(gb["values"]) == rep["n_trading_days"]
    assert abs((gb["values"][-1] - 100) - s["return_pct"]) < 5e-3
    assert abs((gm["values"][-1] - 100) - s["benchmark_return_pct"]) < 5e-3
    assert max(rep["drawdown_book"]["values"]) <= 0 and max(rep["drawdown_benchmark"]["values"]) <= 0
    assert abs(min(rep["drawdown_book"]["values"]) - s["max_drawdown_pct"]) < 5e-3
    assert abs(min(rep["drawdown_benchmark"]["values"]) - s["benchmark_max_drawdown_pct"]) < 5e-3
    ex = rep["exposure"]["values"]
    assert min(ex) >= 0 and max(ex) <= 100 + 1e-9


def test_a_per_symbol_book_runs_and_its_charts_match_its_headline_numbers(window):
    rep = forward_books.build_book_report(MA_BOOK, _toy_universe())
    assert rep["status"] == "RUNNING" and rep["n_trading_days"] > 20
    assert rep["data_through"] == "2026-10-20"
    _reconcile(rep)


def test_a_portfolio_book_runs_and_its_charts_match_its_headline_numbers(window):
    rep = forward_books.build_book_report(MOM_BOOK, _toy_universe())
    assert rep["status"] == "RUNNING"
    _reconcile(rep)
    assert 0 < len(rep["holdings"]) <= 10
    assert sum(h["target_weight_pct"] for h in rep["holdings"]) == pytest.approx(100.0, abs=0.1)


def test_sharpe_is_withheld_until_a_year_of_forward_days_exists(window, monkeypatch):
    rep = forward_books.build_book_report(MA_BOOK, _toy_universe())
    s = rep["summary"]
    assert s["sharpe"] is None and s["benchmark_sharpe"] is None
    assert "withheld" in s["sharpe_note"] and str(forward_books.MIN_DAYS_FOR_SHARPE) in s["sharpe_note"]
    monkeypatch.setattr(forward_books, "MIN_DAYS_FOR_SHARPE", 5)                      # the gate, lowered for this test only
    s2 = forward_books.build_book_report(MA_BOOK, _toy_universe())["summary"]
    assert s2["sharpe"] is not None and s2["sharpe_note"] == ""


def test_the_report_is_idempotent(window):
    a = forward_books.build_book_report(MA_BOOK, _toy_universe())
    b = forward_books.build_book_report(MA_BOOK, _toy_universe())
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


# --- persistence ----------------------------------------------------------------------------------

def test_history_has_one_row_per_book_and_data_date(tmp_path, window):
    path = str(tmp_path / "h.csv")
    rep = forward_books.build_book_report(MA_BOOK, _toy_universe())
    forward_books.append_history(rep, path)
    forward_books.append_history(rep, path)                                    # same data again: replaces
    other = dict(rep, id="other_book")
    forward_books.append_history(other, path)                                  # a different book: adds
    later = dict(rep, data_through="2026-10-21")
    forward_books.append_history(later, path)                                  # a later date: adds
    df = pd.read_csv(path)
    assert len(df) == 3 and set(df["book_id"]) == {"toy_ma", "other_book"}
    assert df[(df.book_id == "toy_ma") & (df.data_through == "2026-10-20")].shape[0] == 1


def test_latest_json_is_valid_and_a_nan_is_refused_not_written(tmp_path):
    path = str(tmp_path / "latest.json")
    forward_books.write_latest([{"id": "x", "value": 1.5}], path)
    assert json.load(open(path))["books"][0]["value"] == 1.5
    with pytest.raises(ValueError):
        forward_books.write_latest([{"id": "x", "value": float("nan")}], str(tmp_path / "bad.json"))
    assert not (tmp_path / "bad.json").exists()
