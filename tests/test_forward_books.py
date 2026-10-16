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
    assert ids == ["momentum_nifty50", "ma_crossover_smallcap250", "quality_value_nifty50"] and len(set(ids)) == len(ids)
    qv = next(b for b in forward_books.BOOKS if b["id"] == "quality_value_nifty50")
    assert qv["kind"] == "fundamental" and qv["params"] == {"top_n": 10} and qv["universe"] == "nifty50"
    mom = next(b for b in forward_books.BOOKS if b["id"] == "momentum_nifty50")
    assert mom["params"] == {"lookback_days": cross_sectional_momentum.LOOKBACK_DAYS,
                             "skip_days": cross_sectional_momentum.SKIP_DAYS, "top_n": cross_sectional_momentum.TOP_N}
    ma = next(b for b in forward_books.BOOKS if b["id"] == "ma_crossover_smallcap250")
    assert ma["params"] == config.MA_CROSSOVER_PARAMS and ma["liquidity_costs"] is True
    for b in forward_books.BOOKS:
        assert b["universe"] in forward_books.UNIVERSES
        assert b["kind"] in ("portfolio", "fundamental") or b.get("strategy") in forward_books.STRATEGY_MODULES


def test_each_report_carries_its_own_verdict_gate_and_criteria_document(window, monkeypatch):
    """The page must not claim 252 days for a book whose pre-registered gate is 504 days and two rebalances."""
    old = forward_books.build_book_report(MA_BOOK, _toy_universe())
    assert (old["verdict_gate_days"], old["verdict_note"], old["criteria_document"]) == (252, None, "FORWARD_BOOKS.md")
    qv = next(b for b in forward_books.BOOKS if b["id"] == "quality_value_nifty50")
    assert forward_books._gate_fields(qv) == {"verdict_gate_days": 504, "criteria_document": "FUNDAMENTALS_PREREG.md",
                                              "verdict_note": "and two completed June rebalances (2027 and 2028)"}
    _use_archive(monkeypatch, *_toy_archive())                                 # and the running report carries it too
    rep = forward_books.build_book_report(dict(QV_BOOK, verdict_days=504, criteria_document="FUNDAMENTALS_PREREG.md"),
                                          _same_price_universe(25))
    assert rep["verdict_gate_days"] == 504 and rep["criteria_document"] == "FUNDAMENTALS_PREREG.md"


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


# --- the quality + value (fundamentals) book --------------------------------------------------------------

QV_BOOK = {
    "id": "toy_qv", "name": "toy quality value", "kind": "fundamental", "universe": "nifty50",
    "params": {"top_n": 10}, "rationale": "r", "why_forward_tested": "w",
}


def _toy_archive(n=25, seen="2026-08-01"):
    """Archive-shaped facts for S00..S{n-1}: higher k = more profit on the same equity and price = better."""
    rows = []
    for k in range(n):
        ni, shares = 100.0 + k, 10.0
        for item, v in (("Net Income Common Stockholders", ni), ("Stockholders Equity", 500.0),
                        ("Ordinary Shares Number", shares), ("Basic EPS", ni / shares)):
            rows.append({"symbol": f"S{k:02d}", "freq": "annual", "period_end": pd.Timestamp("2026-03-31"), "item": item,
                         "value": v, "assumed_available_from": pd.Timestamp("2026-06-29"),
                         "first_seen_date": pd.Timestamp(seen)})
    return pd.DataFrame(rows), {f"S{k:02d}": "INR" for k in range(n)}


def _same_price_universe(n):
    """n stocks sharing one price path, so only the fundamentals (not price) can separate them."""
    base = _toy_universe(n_symbols=1)["S00.NS"]
    return {f"S{k:02d}.NS": {"df": base["df"].copy(), "report": REPORT, "symbol": f"S{k:02d}"} for k in range(n)}


def _use_archive(monkeypatch, facts, ccy):
    monkeypatch.setattr(forward_books.fundamentals_snapshot, "load_snapshot", lambda: facts)
    monkeypatch.setattr(forward_books.fundamentals_snapshot, "load_currency", lambda: ccy)


def test_the_fundamental_book_runs_picks_the_top_ten_and_reconciles(window, monkeypatch):
    _use_archive(monkeypatch, *_toy_archive())
    rep = forward_books.build_book_report(QV_BOOK, _same_price_universe(25))
    assert rep["status"] == "RUNNING"
    _reconcile(rep)
    assert {h["symbol"] for h in rep["holdings"]} == {f"S{k:02d}" for k in range(15, 25)}      # the ten most profitable
    assert all(h["target_weight_pct"] == pytest.approx(10.0) for h in rep["holdings"])
    assert any("once a year" in n for n in rep["notes"])


def test_the_report_calls_a_fundamental_book_a_portfolio_because_the_api_only_knows_two_kinds(window, monkeypatch):
    _use_archive(monkeypatch, *_toy_archive())
    assert forward_books.build_book_report(QV_BOOK, _same_price_universe(25))["kind"] == "portfolio"
    monkeypatch.setattr(forward_books, "FIRST_COUNTED_DAY", "2027-01-04")           # and in the not-started report too
    assert forward_books.build_book_report(QV_BOOK, _same_price_universe(25))["kind"] == "portfolio"


def test_the_fundamental_book_with_nothing_archived_holds_cash_and_does_not_crash(window, monkeypatch):
    _use_archive(monkeypatch, pd.DataFrame(), {})
    rep = forward_books.build_book_report(QV_BOOK, _toy_universe(n_symbols=25))
    assert rep["status"] == "RUNNING" and rep["holdings"] == []
    assert rep["summary"]["return_pct"] == 0.0


def test_figures_first_seen_after_the_freeze_day_cannot_form_the_first_portfolio(window, monkeypatch):
    """Strict point in time: the archive had not seen these numbers on the formation date, so the book cannot use them."""
    _use_archive(monkeypatch, *_toy_archive(seen="2026-09-15"))                    # seen after the 2026-09-01 formation
    assert forward_books.build_book_report(QV_BOOK, _toy_universe(n_symbols=25))["holdings"] == []


def test_before_the_first_counted_day_the_fundamental_book_shows_its_frozen_picks(monkeypatch):
    monkeypatch.setattr(forward_books, "FIRST_COUNTED_DAY", "2027-01-04")
    monkeypatch.setattr(forward_books, "FORWARD_START", "2026-10-20")
    _use_archive(monkeypatch, *_toy_archive())
    rep = forward_books.build_book_report(QV_BOOK, _toy_universe(n_symbols=25))
    assert rep["status"] == "NOT_STARTED"
    assert "Frozen picks: " in rep["notes"][0] and "S24" in rep["notes"][0]


def test_formation_dates_are_the_freeze_day_then_the_last_trading_day_of_each_june(monkeypatch):
    monkeypatch.setattr(forward_books, "FORWARD_START", "2026-10-16")
    idx = pd.bdate_range("2026-09-01", "2028-07-31")
    uni = {"X.NS": {"df": pd.DataFrame({"close": 1.0}, index=idx)}}
    got = forward_books._fundamental_formation_dates(uni, pd.Timestamp("2028-07-15"))
    assert got == [pd.Timestamp("2026-10-16"), pd.Timestamp("2027-06-30"), pd.Timestamp("2028-06-30")]
    early = forward_books._fundamental_formation_dates(uni, pd.Timestamp("2028-06-20"))   # June 2028 not over yet
    assert early == [pd.Timestamp("2026-10-16"), pd.Timestamp("2027-06-30")]


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
