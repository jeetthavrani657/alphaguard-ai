"""
tests/test_webapp_api.py

Contract tests for the read-only results API (webapp/backend/).

These tests protect the rules the web app was built under:

  * No Sharpe or Sortino ever leaves the API without its validation status
    and the hypothesis count that status is "as of".
  * The API is read-only: every route is a GET.
  * The API layer cannot calculate anything: it does not import the engine,
    strategies, research or data modules (checked in a fresh interpreter).
  * An id from the URL can never be turned into a file path (traversal).

They use a tiny SYNTHETIC snapshot written to a temp folder and never touch
the real webapp/snapshots/ or the real hypothesis ledger. No network, no
strategy run.
"""

import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from webapp.backend import schemas
from webapp.backend.main import app


# --- synthetic snapshot ----------------------------------------------------------

def _ratio(kind, value, window, status="VALIDATED_FAILED", total=204):
    return schemas.RiskAdjustedRatio(kind=kind, value=value, window=window, status=status, as_of_hypotheses=total,
                                     p_value=0.2 if kind == "sharpe" else None,
                                     bonferroni_bar=0.05 / total if kind == "sharpe" else None,
                                     clears_bar=False if kind == "sharpe" else None)


def _metrics(window, status="VALIDATED_FAILED", total=204):
    return schemas.WindowMetrics(
        sharpe=_ratio("sharpe", 0.5, window, status, total), sortino=_ratio("sortino", 0.7, window, status, total),
        total_return_pct=10.0, cagr_pct=5.0, max_drawdown_pct=-12.0, max_drawdown_duration_days=100.0,
        win_rate_pct=50.0, avg_win_pct=3.0, avg_loss_pct=-2.0, profit_factor=None, total_trades=5,
        avg_holding_days=10.0, market_exposure_pct=60.0, final_equity=110000.0, n_symbols_included=3)


def _window_info(window):
    return schemas.WindowInfo(
        window=window, start="2015-01-01", end="2020-06-30", n_observations=3,
        strategy=_metrics(window), benchmark=_metrics(window, "BENCHMARK_NOT_A_HYPOTHESIS"))


def _prov(total=204):
    return schemas.Provenance(generated_at="2026-10-16T00:00:00+00:00", git_commit="abc1234", git_dirty=False,
                              ledger_total_at_snapshot=total, bonferroni_bar_at_snapshot=0.05 / total,
                              data_through="2025-12-31", in_sample_end="2020-06-30",
                              risk_free_rate=0.065, initial_capital=100000.0)


def _strategy_file(sid, kind="per_symbol", n_trades=7):
    curve = schemas.EquityCurve(dates=["2020-01-01", "2020-01-02", "2020-01-03"], values=[100.0, 101.0, 102.5])
    trades = [schemas.ClosedTrade(symbol="AAA", entry_date="2020-01-01", exit_date="2020-01-05", entry_price=10.0,
                                  exit_price=11.0, quantity=1, return_pct=9.5, holding_days=4, total_costs=0.1)
              for _ in range(n_trades)]
    execs = [schemas.Execution(date="2020-01-01", symbol="AAA", side="buy", shares=1, price=10.0, costs=0.1)
             for _ in range(n_trades)]
    rebs = [schemas.Rebalance(formation_date="2020-01-01", execution_date="2020-01-02", n_held=1,
                              turnover_value=10.0, portfolio_value_pre_rebalance=100.0, turnover_pct=10.0)]
    window_data = schemas.StoredWindowData(
        equity_strategy=curve, equity_benchmark=curve,
        drawdown_strategy_pct=schemas.EquityCurve(dates=curve.dates, values=[0.0, 0.0, -1.5]),
        drawdown_benchmark_pct=schemas.EquityCurve(dates=curve.dates, values=[0.0, -2.0, -3.0]),
        exposure_strategy_pct=schemas.EquityCurve(dates=curve.dates, values=[0.0, 50.0, 100.0]),
        exposure_definition="share of books long",
        growth_strategy=schemas.EquityCurve(dates=curve.dates, values=[100.0, 101.0, 102.5]),
        growth_benchmark=schemas.EquityCurve(dates=curve.dates, values=[100.0, 99.0, 105.0]),
        closed_trades=trades if kind == "per_symbol" else [],
        executions=execs if kind == "portfolio" else [], rebalances=rebs if kind == "portfolio" else [])
    detail = schemas.StrategyDetail(
        id=sid, name=sid, family="Test", universe="nifty50", kind=kind, params={}, rationale="r",
        status="VALIDATED_FAILED", as_of_hypotheses=204, in_sample=_window_info("in_sample"),
        out_of_sample=_window_info("out_of_sample"), provenance=_prov())
    return schemas.StrategyFile(detail=detail, data={"in_sample": window_data, "out_of_sample": window_data})


def _quality():
    # AAA fails a soft check (like every real symbol failing "Missing trading days" on NSE holidays)
    # and has a GENUINE reviewed discontinuity: it must NOT count as an "issue".
    ok = schemas.SymbolQuality(
        symbol="AAA", universe="nifty50", rows=10, first_date="2015-01-01", last_date="2025-12-31", usable=True,
        checks=[schemas.QualityCheck(name="Missing trading days", passed=False, affected_rows=158)],
        discontinuities=[schemas.Discontinuity(date="2020-03-23", magnitude_pct=-27.0, status="GENUINE",
                                               reason="COVID crash trough")])
    bad = schemas.SymbolQuality(
        symbol="BBB", universe="midcap150", rows=10, first_date="2015-01-01", last_date="2025-12-31", usable=True,
        checks=[schemas.QualityCheck(name="c", passed=True, affected_rows=0)],
        discontinuities=[schemas.Discontinuity(date="2020-03-01", magnitude_pct=-60.0, status="UNREVIEWED")])
    return schemas.DataQualityResponse(generated_at="x", n_symbols=2, n_usable=2,
                                       n_with_unresolved_discontinuity=1, symbols=[ok, bad])


def _slice_metrics(window, parent_status="VALIDATED_FAILED", total=204, sharpe=1.1):
    return schemas.SliceMetrics(
        sharpe=schemas.RiskAdjustedRatio(
            kind="sharpe", value=sharpe, window=window, status="SLICE_OF_POOLED_HYPOTHESIS", as_of_hypotheses=total,
            parent_strategy_id="alpha", parent_status=parent_status),
        total_return_pct=12.0, cagr_pct=6.0, max_drawdown_pct=-9.0, win_rate_pct=55.0, total_trades=4,
        market_exposure_pct=40.0, buy_hold_return_pct=30.0)


def _slices():
    return schemas.SymbolSlices(
        strategy_id="alpha", parent_status="VALIDATED_FAILED", as_of_hypotheses=204,
        windows={"in_sample": {"AAA": _slice_metrics("in_sample")},
                 "out_of_sample": {"AAA": _slice_metrics("out_of_sample")}},
        excluded={"in_sample": {}, "out_of_sample": {"CCC": "blocked by the discontinuity gate"}})


def _screener_rows():
    def row(sym, uni, sector, usable=True, flagged=False):
        return schemas.ScreenerRow(
            symbol=sym, universe=uni, sector=sector, rows=5, first_date="2020-01-01", last_date="2020-01-07",
            last_close=104.0, usable=usable, has_unresolved_discontinuity=flagged,
            buy_hold_return_in_sample_pct=10.0, buy_hold_return_out_of_sample_pct=None,
            buy_hold_max_drawdown_out_of_sample_pct=None)
    return [row("AAA", "nifty50", "Bank"), row("BBB", "midcap150", None, flagged=True)]


def _prices(symbol="AAA"):
    dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"]
    return schemas.PriceSeries(
        symbol=symbol, dates=dates, open=[100.0, 101, 102, 103, 104], high=[101.0, 102, 103, 104, 105],
        low=[99.0, 100, 101, 102, 103], close=[100.5, 101.5, 102.5, 103.5, 104.0], volume=[10.0, 11, 12, 13, 14],
        indicators={"sma_50": [None, None, 101.0, 102.0, 103.0], "rsi_14": [None, None, None, 55.0, 60.0]},
        indicator_sources={"sma_50": "strategies/ma_crossover.py moving_average",
                           "rsi_14": "strategies/rsi_reversion.py rsi"})


@pytest.fixture
def client(tmp_path, monkeypatch):
    snap = tmp_path / "snap"
    (snap / "strategies").mkdir(parents=True)
    (snap / "symbols").mkdir()
    ids = ["alpha", "beta_portfolio"]
    (snap / "strategies" / "alpha.json").write_text(_strategy_file("alpha").model_dump_json())
    (snap / "strategies" / "alpha.symbols.json").write_text(_slices().model_dump_json())
    (snap / "strategies" / "beta_portfolio.json").write_text(
        _strategy_file("beta_portfolio", kind="portfolio").model_dump_json())
    (snap / "screener.json").write_text(schemas.ScreenerResponse(
        generated_at="x", data_through="2020-01-07", in_sample="a to b", out_of_sample="c to d",
        rows=_screener_rows()).model_dump_json())
    (snap / "symbols" / "AAA.json").write_text(_prices("AAA").model_dump_json())
    (snap / "data_quality.json").write_text(_quality().model_dump_json())
    (snap / "manifest.json").write_text(schemas.Manifest(provenance=_prov(), strategy_ids=ids).model_dump_json())
    # A secret next to the snapshot, to prove a traversal id cannot reach it.
    (tmp_path / "secret.json").write_text('{"secret": true}')

    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"cumulative_hypotheses": 204, "runs": [{
        "run_id": "r1", "timestamp": "2026-10-15T00:00:00+00:00", "context": "c", "n_hypotheses_this_run": 204,
        "cumulative_hypotheses_before_run": 0, "cumulative_hypotheses_after_run": 204}]}))
    forward = tmp_path / "forward.csv"
    forward.write_text("run_date,data_through,status,n_closed,n_open,win_rate_all_in,win_rate_closed,"
                       "expectancy_pct,pooled_return_pct,buy_hold_return_pct\n"
                       "2026-10-16,2026-10-15,NOT_STARTED,0,0,,,,,\n")
    monkeypatch.setenv("WEBAPP_SNAPSHOT_DIR", str(snap))
    monkeypatch.setenv("WEBAPP_LEDGER_PATH", str(ledger))
    monkeypatch.setenv("WEBAPP_FORWARD_CSV", str(forward))
    c = TestClient(app)
    c.ledger_path = ledger
    return c


# --- rule 5: no bare Sharpe -----------------------------------------------------------

def test_a_ratio_cannot_be_constructed_without_status_and_hypothesis_count():
    with pytest.raises(ValidationError):
        schemas.RiskAdjustedRatio(kind="sharpe", value=1.2, window="in_sample")
    with pytest.raises(ValidationError):
        schemas.RiskAdjustedRatio(kind="sharpe", value=1.2, window="in_sample", status="VALIDATED_CONFIRMED")


def _find_bare_ratios(node, path="$"):
    """Any key containing 'sharpe' or 'sortino' whose value is not a status-carrying object."""
    bad = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}"
            if "sharpe" in k.lower() or "sortino" in k.lower():
                if not (isinstance(v, dict) and "status" in v and "as_of_hypotheses" in v and "value" in v):
                    bad.append(here)
            bad += _find_bare_ratios(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += _find_bare_ratios(v, f"{path}[{i}]")
    return bad


@pytest.mark.parametrize("url", ["/api/strategies", "/api/strategies/alpha", "/api/strategies/beta_portfolio", "/api/symbols/AAA"])
def test_no_response_contains_a_bare_sharpe_or_sortino(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert _find_bare_ratios(r.json()) == []


def test_benchmark_ratios_are_labelled_not_unlabelled(client):
    d = client.get("/api/strategies/alpha").json()
    assert d["in_sample"]["benchmark"]["sharpe"]["status"] == "BENCHMARK_NOT_A_HYPOTHESIS"
    assert d["in_sample"]["strategy"]["sharpe"]["status"] == "VALIDATED_FAILED"


# --- rule 3: read-only -------------------------------------------------------------------

def test_every_route_is_get_only():
    methods = set()
    for route in app.routes:
        for m in getattr(route, "methods", None) or []:
            methods.add(m)
    assert methods <= {"GET", "HEAD"}, f"non-read methods exposed: {methods - {'GET', 'HEAD'}}"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_write_methods_are_rejected(client, method):
    assert getattr(client, method)("/api/strategies").status_code == 405


# --- rule 2: the API layer cannot calculate ----------------------------------------------------

def test_api_import_pulls_in_no_engine_strategy_research_or_data_code():
    code = (
        "import sys\n"
        "import webapp.backend.main\n"
        "banned = ['backtest','metrics','costs','harness','universe','loader','validator','ma_crossover',"
        "'rsi_reversion','dip_target','portfolio_backtest','cross_sectional_momentum','liquidity_costs',"
        "'buy_and_hold','pandas','numpy','yfinance','scipy','statsmodels']\n"
        "print(','.join(b for b in banned if b in sys.modules))\n"
    )
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "", f"API pulled in: {out.stdout.strip()}"


# --- id safety -------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["nope", "..%2Fsecret", "%2e%2e%2fsecret", "..%5Csecret", "alpha.json", "alpha%00",
                                 "manifest", "data_quality"])
def test_unknown_or_traversal_ids_are_404_never_a_file_read(client, bad):
    # "manifest" and "data_quality" are real files in the snapshot folder but not
    # strategy ids: without the manifest guard they would be read (or crash with a 500).
    for suffix in ("", "/equity?window=in_sample", "/trades?window=in_sample"):
        r = client.get(f"/api/strategies/{bad}{suffix}")
        assert r.status_code == 404, (bad, suffix, r.status_code)
        assert "true" not in r.text      # the planted secret file's content never appears


# --- shapes and pagination -----------------------------------------------------------------------------

def test_strategy_list_has_statuses_and_ledger_total(client):
    d = client.get("/api/strategies").json()
    assert d["ledger_total_now"] == 204
    assert [s["id"] for s in d["strategies"]] == ["alpha", "beta_portfolio"]
    assert all(s["status"] and s["as_of_hypotheses"] == 204 and s["stale"] is False for s in d["strategies"])


def test_status_goes_stale_when_the_ledger_grows_after_the_snapshot(client):
    client.ledger_path.write_text(json.dumps({"cumulative_hypotheses": 205, "runs": []}))
    d = client.get("/api/strategies").json()
    assert d["ledger_total_now"] == 205
    assert all(s["stale"] is True for s in d["strategies"])
    assert client.get("/api/strategies/alpha").json()["stale"] is True
    led = client.get("/api/ledger").json()
    assert led["snapshot_is_stale"] is True and led["snapshot_total"] == 204


def test_equity_is_two_parallel_equal_length_arrays(client):
    d = client.get("/api/strategies/alpha/equity?window=out_of_sample").json()
    assert len(d["strategy"]["dates"]) == len(d["strategy"]["values"]) == 3
    assert len(d["benchmark"]["dates"]) == len(d["benchmark"]["values"])


def test_trades_are_paginated_with_a_total(client):
    d = client.get("/api/strategies/alpha/trades?window=in_sample&limit=3&offset=0").json()
    assert d["total"] == 7 and len(d["closed_trades"]) == 3
    d2 = client.get("/api/strategies/alpha/trades?window=in_sample&limit=3&offset=6").json()
    assert len(d2["closed_trades"]) == 1
    d3 = client.get("/api/strategies/alpha/trades?window=in_sample&limit=3&offset=50").json()
    assert d3["closed_trades"] == [] and d3["total"] == 7


def test_portfolio_strategy_returns_executions_and_rebalances_not_closed_trades(client):
    d = client.get("/api/strategies/beta_portfolio/trades?window=in_sample").json()
    assert d["kind"] == "portfolio" and d["closed_trades"] is None
    assert len(d["executions"]) == 7 and len(d["rebalances"]) == 1


@pytest.mark.parametrize("qs", ["window=sideways", "", "window=in_sample&limit=0", "window=in_sample&limit=100000",
                                "window=in_sample&offset=-1"])
def test_bad_query_parameters_are_422(client, qs):
    assert client.get(f"/api/strategies/alpha/trades?{qs}").status_code == 422


def test_data_quality_filters(client):
    assert len(client.get("/api/data-quality").json()["symbols"]) == 2
    assert [s["symbol"] for s in client.get("/api/data-quality?universe=midcap150").json()["symbols"]] == ["BBB"]
    issues = client.get("/api/data-quality?only_issues=true").json()
    assert [s["symbol"] for s in issues["symbols"]] == ["BBB"]
    assert issues["n_symbols"] == 2     # totals still describe the whole snapshot
    # Regression: soft-check failures + reviewed-GENUINE discontinuities are not "issues".
    assert "AAA" not in [s["symbol"] for s in issues["symbols"]]


def test_ledger_and_forward_test(client):
    led = client.get("/api/ledger").json()
    assert led["cumulative_hypotheses"] == 204 and len(led["runs"]) == 1
    assert "bonferroni_bar_now" not in led      # the API must not compute a bar of its own
    fwd = client.get("/api/forward-test").json()
    assert fwd["rows"][0]["status"] == "NOT_STARTED" and fwd["rows"][0]["win_rate_all_in"] is None


def test_missing_snapshot_is_a_helpful_503_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_SNAPSHOT_DIR", str(tmp_path / "nothing_here"))
    c = TestClient(app)
    r = c.get("/api/strategies")
    assert r.status_code == 503 and "webapp.backend.snapshot" in r.json()["detail"]
    h = c.get("/api/health").json()
    assert h["ok"] is False and h["snapshot_present"] is False


# --- per-stock views (screener, cockpit) -----------------------------------------------

def test_a_slice_ratio_must_name_its_parent():
    base = dict(kind="sharpe", value=1.0, window="in_sample", status="SLICE_OF_POOLED_HYPOTHESIS", as_of_hypotheses=204)
    with pytest.raises(ValidationError):
        schemas.RiskAdjustedRatio(**base)                                    # no parent at all
    with pytest.raises(ValidationError):
        schemas.RiskAdjustedRatio(**base, parent_strategy_id="alpha")        # parent id but no parent status
    with pytest.raises(ValidationError):
        schemas.RiskAdjustedRatio(**base, parent_strategy_id="alpha",
                                  parent_status="SLICE_OF_POOLED_HYPOTHESIS")  # a slice of a slice
    ok = schemas.RiskAdjustedRatio(**base, parent_strategy_id="alpha", parent_status="VALIDATED_FAILED")
    assert ok.parent_status == "VALIDATED_FAILED"


def test_symbol_detail_has_no_bare_sharpe_and_labels_every_stock_sharpe_as_a_slice(client):
    d = client.get("/api/symbols/AAA").json()
    assert _find_bare_ratios(d) == []
    alpha = next(r for r in d["results"] if r["strategy_id"] == "alpha")
    for w in ("in_sample", "out_of_sample"):
        s = alpha[w]["sharpe"]
        assert s["status"] == "SLICE_OF_POOLED_HYPOTHESIS"
        assert s["parent_strategy_id"] == "alpha" and s["parent_status"] == "VALIDATED_FAILED"
        assert s["as_of_hypotheses"] == 204
    assert "not independent hypotheses" in d["caveat"]


def test_symbol_detail_includes_markers_executions_and_portfolio_note(client):
    d = client.get("/api/symbols/AAA").json()
    assert len(d["markers"]) == 14            # 7 closed trades x 2 windows, from the 'alpha' strategy only
    assert {m["strategy_id"] for m in d["markers"]} == {"alpha"}
    assert len(d["executions"]) == 14 and {e["strategy_id"] for e in d["executions"]} == {"beta_portfolio"}
    beta = next(r for r in d["results"] if r["strategy_id"] == "beta_portfolio")
    assert beta["in_sample"] is None and "no per-stock result" in beta["note"]
    assert d["quality"]["symbol"] == "AAA"


def test_a_strategy_only_appears_on_stocks_of_its_own_universe(client):
    d = client.get("/api/symbols/BBB").json()           # a midcap stock; both test strategies are nifty50
    assert d["results"] == [] and d["markers"] == []


def test_screener_rows_and_filters(client):
    d = client.get("/api/screener").json()
    assert [r["symbol"] for r in d["rows"]] == ["AAA", "BBB"]
    assert [r["symbol"] for r in client.get("/api/screener?universe=midcap150").json()["rows"]] == ["BBB"]
    assert [r["symbol"] for r in client.get("/api/screener?sector=Bank").json()["rows"]] == ["AAA"]
    assert [r["symbol"] for r in client.get("/api/screener?flagged_only=true").json()["rows"]] == ["BBB"]
    assert not any("sharpe" in k.lower() for r in d["rows"] for k in r)   # a screener never ranks by Sharpe


def test_prices_are_columnar_and_trimmed_by_date_with_aligned_indicators(client):
    full = client.get("/api/symbols/AAA/prices").json()
    assert len(full["dates"]) == 5
    for col in ("open", "high", "low", "close", "volume"):
        assert len(full[col]) == 5
    assert all(len(v) == 5 for v in full["indicators"].values())
    assert full["indicator_sources"]["sma_50"].startswith("strategies/ma_crossover.py")

    cut = client.get("/api/symbols/AAA/prices?from_date=2020-01-02&to_date=2020-01-06").json()
    assert cut["dates"] == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert cut["indicators"]["sma_50"] == [None, 101.0, 102.0]
    assert len(cut["close"]) == len(cut["volume"]) == 3


@pytest.mark.parametrize("qs", ["from_date=yesterday", "to_date=2020-1-1", "from_date=2020-01-01;drop"])
def test_bad_price_date_parameters_are_422(client, qs):
    assert client.get(f"/api/symbols/AAA/prices?{qs}").status_code == 422


@pytest.mark.parametrize("bad", ["NOPE", "..%2Fsecret", "%2e%2e%2fsecret", "manifest", "screener", "AAA.json"])
def test_unknown_or_traversal_symbols_are_404(client, bad):
    for suffix in ("", "/prices"):
        r = client.get(f"/api/symbols/{bad}{suffix}")
        assert r.status_code == 404, (bad, suffix, r.status_code)


def test_symbol_with_a_url_unsafe_name_round_trips(client, tmp_path):
    # NSE has tickers like M&M and BAJAJ-AUTO; the guard works on the decoded name.
    snap = tmp_path / "snap"
    rows = _screener_rows() + [_screener_rows()[0].model_copy(update={"symbol": "M&M"})]
    (snap / "screener.json").write_text(schemas.ScreenerResponse(
        generated_at="x", data_through="2020-01-07", in_sample="a", out_of_sample="b", rows=rows).model_dump_json())
    (snap / "symbols" / "M&M.json").write_text(_prices("M&M").model_dump_json())
    assert client.get("/api/symbols/M%26M/prices").status_code == 200


def test_equity_response_carries_drawdown_exposure_and_growth_series_on_the_same_dates(client):
    d = client.get("/api/strategies/alpha/equity?window=in_sample").json()
    dates = d["strategy"]["dates"]
    for key in ("drawdown_strategy_pct", "drawdown_benchmark_pct", "exposure_strategy_pct",
                "growth_strategy", "growth_benchmark"):
        assert d[key]["dates"] == dates and len(d[key]["values"]) == len(dates), key
    assert all(v <= 0 for v in d["drawdown_strategy_pct"]["values"])
    assert all(0 <= v <= 100 for v in d["exposure_strategy_pct"]["values"])
    assert d["growth_strategy"]["values"][0] == 100.0          # both start at 100: comparable by construction
    assert d["exposure_definition"]
    assert "do not compare the two rupee curves" in d["note"]


def test_health_exposes_snapshot_provenance_for_the_status_strip(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True
    assert h["data_through"] == "2025-12-31" and h["git_commit"] == "abc1234" and h["git_dirty"] is False
    assert h["ledger_total_now"] == 204 and h["snapshot_ledger_total"] == 204 and h["snapshot_stale"] is False
    client.ledger_path.write_text(json.dumps({"cumulative_hypotheses": 210, "runs": []}))
    assert client.get("/api/health").json()["snapshot_stale"] is True


# --- serving the built frontend (Stage E: one process, one port) ------------------------------

@pytest.fixture
def served(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>APP SHELL</html>")
    (dist / "assets" / "app.js").write_text("console.log('ui')")
    (tmp_path / "outside.txt").write_text("SECRET OUTSIDE DIST")
    monkeypatch.setenv("WEBAPP_FRONTEND_DIST", str(dist))
    return client


def test_root_and_client_side_routes_get_the_app_shell(served):
    for path in ("/", "/strategies", "/stock/RELIANCE", "/research"):
        r = served.get(path)
        assert r.status_code == 200 and "APP SHELL" in r.text, path


def test_built_assets_are_served_as_files(served):
    r = served.get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_unknown_api_routes_are_json_404_not_the_web_page(served):
    for path in ("/api/nope", "/api/strategies/alpha/bogus", "/api"):
        r = served.get(path)
        assert r.status_code == 404, path
        assert "APP SHELL" not in r.text and "detail" in r.json()


def test_the_api_and_docs_still_win_over_the_catch_all(served):
    assert served.get("/api/health").json()["ok"] is True
    assert served.get("/openapi.json").json()["info"]["title"]
    assert "swagger" in served.get("/docs").text.lower()


@pytest.mark.parametrize("path", ["/../outside.txt", "/%2e%2e/outside.txt", "/assets/../../outside.txt",
                                  "/..%2foutside.txt", "/%2e%2e%2foutside.txt"])
def test_files_outside_dist_are_never_served(served, path):
    r = served.get(path)
    assert "SECRET OUTSIDE DIST" not in r.text


def test_unbuilt_frontend_says_how_to_build_it(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_FRONTEND_DIST", str(tmp_path / "does_not_exist"))
    r = client.get("/")
    assert r.status_code == 404 and "npm run build" in r.json()["detail"]


def test_the_app_shell_is_always_revalidated_and_hashed_assets_are_cached_for_a_year(served):
    assert served.get("/").headers["cache-control"] == "no-cache"                       # else a browser keeps showing yesterday's page after a rebuild
    assert served.get("/advisory").headers["cache-control"] == "no-cache"
    assert "immutable" in served.get("/assets/app.js").headers["cache-control"]


def test_the_ui_is_read_only_too(served):
    assert served.post("/").status_code == 405


# --- forward paper books (FORWARD_BOOKS.md) -----------------------------------------------------

def _book_json(running: bool, sharpe=None):
    series = {"dates": ["2026-10-19", "2026-10-20", "2026-10-21"], "values": [100.0, 101.5, 100.8]}
    dd = {"dates": series["dates"], "values": [0.0, 0.0, -0.69]}
    exp = {"dates": series["dates"], "values": [0.0, 50.0, 50.0]}
    base = {"id": "toy_book", "name": "Toy book", "kind": "per_symbol", "universe": "nifty50", "rationale": "r",
            "why_forward_tested": "w", "start": "2026-10-16", "first_counted_day": "2026-10-19", "pending": [], "notes": [],
            "holdings": [{"symbol": "AAA", "since": "2026-10-20", "entry_price": 10.0, "last_close": 10.5}]}
    if not running:
        return dict(base, status="NOT_STARTED", data_through="2026-10-16", n_trading_days=0, summary=None, growth_book=None,
                    growth_benchmark=None, drawdown_book=None, drawdown_benchmark=None, exposure=None, holdings=[])
    return dict(base, status="RUNNING", data_through="2026-10-21", n_trading_days=3, growth_book=series,
                growth_benchmark=series, drawdown_book=dd, drawdown_benchmark=dd, exposure=exp,
                summary={"return_pct": 0.8, "benchmark_return_pct": 0.8, "max_drawdown_pct": -0.69,
                         "benchmark_max_drawdown_pct": -0.69, "market_exposure_pct": 50.0, "n_open_positions": 1,
                         "n_closed_trades": 0, "sharpe": sharpe, "benchmark_sharpe": None if sharpe is None else 0.4,
                         "sharpe_note": "withheld: 3 of 252 trading days of forward data" if sharpe is None else ""})


@pytest.fixture
def books(client, tmp_path, monkeypatch):
    def write(book):
        path = tmp_path / "books.json"
        path.write_text(json.dumps({"generated_at": "2026-10-21T14:00:00Z", "start": "2026-10-16",
                                    "first_counted_day": "2026-10-19", "min_days_for_sharpe": 252, "books": [book]}))
        monkeypatch.setenv("WEBAPP_FORWARD_BOOKS", str(path))
        return client
    return write


def test_a_book_that_has_not_started_shows_no_numbers_and_says_so(books):
    d = books(_book_json(running=False)).get("/api/forward-books").json()
    b = d["books"][0]
    assert b["status"] == "NOT_STARTED" and b["summary"] is None and b["growth_book"] is None
    assert b["risk_adjusted"]["book"] is None and b["days_needed_for_verdict"] == 252
    assert "monitoring, not evidence" in d["disclaimer"]


def test_a_running_book_withholds_sharpe_until_a_year_of_days(books):
    d = books(_book_json(running=True, sharpe=None)).get("/api/forward-books").json()
    b = d["books"][0]
    assert b["risk_adjusted"]["book"] is None and "withheld" in b["risk_adjusted"]["withheld_reason"]
    assert len(b["growth_book"]["dates"]) == len(b["growth_book"]["values"]) == b["n_trading_days"]
    assert b["summary"]["return_pct"] == 0.8 and b["holdings"][0]["symbol"] == "AAA"


def test_a_running_book_serves_its_simulated_orders_and_a_book_without_any_serves_an_empty_list(books):
    book = _book_json(running=True)
    book["orders"] = [{"date": "2026-10-20", "symbol": "AAA", "side": "BUY", "shares": 10, "price": 10.0, "costs": 1.5},
                      {"date": "2026-10-21", "symbol": "BBB", "side": "SELL", "shares": 5, "price": 20.0, "costs": None}]
    b = books(book).get("/api/forward-books").json()["books"][0]
    assert [o["side"] for o in b["orders"]] == ["BUY", "SELL"] and b["orders"][1]["costs"] is None
    assert books(_book_json(running=True)).get("/api/forward-books").json()["books"][0]["orders"] == []


def test_once_shown_a_forward_sharpe_carries_status_and_the_hypothesis_count(books):
    d = books(_book_json(running=True, sharpe=1.2)).get("/api/forward-books").json()
    r = d["books"][0]["risk_adjusted"]
    assert _find_bare_ratios(d) == []
    for side in ("book", "benchmark"):
        assert r[side]["status"] == "UNVALIDATED" and r[side]["as_of_hypotheses"] == 204
        assert r[side]["kind"] == "sharpe" and r[side]["window"] == "out_of_sample"
    assert r["book"]["value"] == 1.2 and r["benchmark"]["value"] == 0.4


def test_forward_books_missing_is_a_helpful_404_not_a_crash(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_FORWARD_BOOKS", str(tmp_path / "nope.json"))
    r = client.get("/api/forward-books")
    assert r.status_code == 404 and "forward_books.py" in r.json()["detail"]


# --- live prices ------------------------------------------------------------------------------------------

def _live_file(tmp_path, monkeypatch, **over):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc) - timedelta(seconds=over.pop("age", 5))
    payload = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "market_status": "open", "market_note": "note",
               "available": True, "reason": None, "n_requested": 2,
               "quotes": [{"symbol": "TCS", "last_price": 2449.4, "prev_close": 2440.0, "change_pct": 0.39, "volume": 5,
                           "held_by": ["quality_value_nifty50"]},
                          {"symbol": "ITC", "last_price": None, "prev_close": None, "change_pct": None, "volume": None,
                           "held_by": []}]}
    payload.update(over)
    path = tmp_path / "live.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("WEBAPP_LIVE_QUOTES", str(path))


def test_live_quotes_are_served_as_written_with_their_age(client, tmp_path, monkeypatch):
    _live_file(tmp_path, monkeypatch)
    d = client.get("/api/live-quotes").json()
    assert d["available"] is True and d["market_status"] == "open" and d["is_stale"] is False
    assert 0 <= d["age_seconds"] < 60
    by = {q["symbol"]: q for q in d["quotes"]}
    assert by["TCS"]["change_pct"] == 0.39 and by["TCS"]["held_by"] == ["quality_value_nifty50"]
    assert by["ITC"]["last_price"] is None                                    # a missing price stays missing


def test_an_old_file_is_flagged_stale_with_a_shorter_limit_while_the_market_is_open(client, tmp_path, monkeypatch):
    _live_file(tmp_path, monkeypatch, age=120)
    assert client.get("/api/live-quotes").json()["is_stale"] is True          # 2 minutes old while open
    _live_file(tmp_path, monkeypatch, age=120, market_status="closed")
    assert client.get("/api/live-quotes").json()["is_stale"] is False         # the same age is fine when closed


def test_an_expired_token_arrives_as_a_reason_not_an_error(client, tmp_path, monkeypatch):
    _live_file(tmp_path, monkeypatch, available=False, reason="The Upstox access token has expired.", quotes=[])
    r = client.get("/api/live-quotes")
    assert r.status_code == 200 and r.json()["available"] is False and "expired" in r.json()["reason"]


def test_no_live_file_yet_explains_how_to_start_the_writer(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_LIVE_QUOTES", str(tmp_path / "nope.json"))
    r = client.get("/api/live-quotes")
    assert r.status_code == 200 and r.json()["available"] is False and "live_quotes.py" in r.json()["reason"]


# --- the forward test's own health in the status strip -------------------------------------------------------------

def _health_file(tmp_path, monkeypatch, hours_old=1, overall="OK", checks=None):
    from datetime import datetime, timedelta, timezone
    when = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    checks = checks or [{"id": "a", "label": "A", "status": "OK", "detail": "fine"}]
    path = tmp_path / "health.json"
    path.write_text(json.dumps({"generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "overall": overall, "checks": checks}))
    monkeypatch.setenv("WEBAPP_HEALTH_LATEST", str(path))


def test_the_status_strip_gets_the_forward_tests_health(client, tmp_path, monkeypatch):
    _health_file(tmp_path, monkeypatch, overall="WARN", checks=[
        {"id": "a", "label": "News archive", "status": "OK", "detail": "fine"},
        {"id": "b", "label": "Paper books history", "status": "WARN", "detail": "newest entry 2026-10-15, 2 weekday(s) ago"}])
    h = client.get("/api/health").json()
    assert h["forward_health"] == "WARN" and h["forward_health_stale"] is False
    assert h["forward_health_problems"] == ["Paper books history: newest entry 2026-10-15, 2 weekday(s) ago"]   # only the non-OK ones


def test_a_health_checker_that_has_itself_stopped_is_reported_as_stale(client, tmp_path, monkeypatch):
    """The dead-man guard: silence from the monitor must not look like good news."""
    _health_file(tmp_path, monkeypatch, hours_old=100)
    assert client.get("/api/health").json()["forward_health_stale"] is True
    _health_file(tmp_path, monkeypatch, hours_old=72)                           # a normal Friday-to-Monday gap
    assert client.get("/api/health").json()["forward_health_stale"] is False


def test_no_health_file_yet_leaves_the_fields_empty_without_breaking_health(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_HEALTH_LATEST", str(tmp_path / "nope.json"))
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["forward_health"] is None and h["forward_health_problems"] == []


# --- multi-asset advisory ---------------------------------------------------------------------------------------

def _advisory_file(tmp_path, monkeypatch, ledger_total_now=204, with_prices=False):
    import advisory as adv
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(4)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range("2020-01-01", periods=1500)
    r = pd.DataFrame({k: rng.normal(0.0003, v, 1500) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    # made-up prices that start at 100 (bitcoin at 1,000,000 so it cannot buy a whole unit), built from the same returns
    prices = None
    if with_prices:
        prices = (1 + r[list(vols)]).cumprod() * 100.0
        prices["crypto"] = prices["crypto"] * 10_000
    payload = adv.build(r, prices, register=False, ledger_total_now=ledger_total_now)
    path = tmp_path / "advisory.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("WEBAPP_ADVISORY", str(path))


def test_advisory_serves_three_profiles_with_allocation_risk_metrics_and_series(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch)
    d = client.get("/api/advisory").json()
    assert [p["id"] for p in d["profiles"]] == ["conservative", "moderate", "aggressive"] and d["is_stale"] is False
    p = d["profiles"][1]
    assert abs(sum(a["weight_pct"] for a in p["allocation"]) - 100) < 0.2
    oos = p["strategy"]["out_of_sample"]
    assert oos["var95_pct"] > 0 and oos["cvar95_pct"] >= oos["var95_pct"] and oos["max_drawdown_pct"] < 0
    assert len(p["growth_strategy"]["dates"]) == len(p["exposure_pct"]["dates"]) == len(p["drawdown_strategy_pct"]["dates"])
    assert "not investment advice" in d["disclaimer"] and len(d["questions"]) == 5


def test_every_advisory_sharpe_carries_its_status_and_hypothesis_count_and_the_benchmark_is_not_a_hypothesis(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch)
    d = client.get("/api/advisory").json()
    assert _find_bare_ratios(d) == []
    p = d["profiles"][0]
    s = p["strategy"]["out_of_sample"]["sharpe"]
    assert s["status"] == p["harness_status"] and s["as_of_hypotheses"] == d["ledger_total_at_generation"] and s["bonferroni_bar"] > 0
    assert p["benchmark"]["in_sample"]["sharpe"]["status"] == "BENCHMARK_NOT_A_HYPOTHESIS"


def test_advisory_results_are_flagged_stale_when_the_ledger_has_grown_since(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, ledger_total_now=200)         # generated when the ledger said 200; the fixture ledger says 204
    d = client.get("/api/advisory").json()
    assert d["is_stale"] is True and d["ledger_total_at_generation"] == 200 and d["ledger_total_now"] == 204


def test_advisory_explains_each_weight_and_the_risk_shares_add_up(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    d = client.get("/api/advisory").json()
    for p in d["profiles"]:
        held = [a for a in p["allocation"] if a["asset_id"] != "cash"]
        assert all(a["role"] and a["why"] for a in p["allocation"])
        assert abs(sum(a["risk_contribution_pct"] for a in held) - 100) < 0.5      # the shares of risk cover the whole portfolio
    assert {t["signal"] for t in d["trend"]} <= {"UPTREND", "DOWNTREND"} and len(d["trend"]) == 6
    assert all(a["last_price"] for a in d["assets"] if a["id"] != "cash")


def test_basket_turns_weights_into_rupees_and_whole_units_and_never_overspends(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    b = client.get("/api/advisory/basket", params={"profile": "moderate", "amount": 500000}).json()
    assert b["amount"] == 500000 and b["profile_id"] == "moderate"
    spent = 0.0
    for line in b["lines"]:
        if line["asset_id"] == "cash":
            continue
        assert line["rupees_used"] <= line["rupees"] + 0.01
        if line["asset_id"] != "crypto":
            assert line["units"] == int(line["units"])                              # exchange-traded funds: whole units only
        spent += line["rupees_used"]
    assert spent <= 500000 and abs(b["cash_left"] - (500000 - spent)) < 0.05
    assert any("places no orders" in n for n in b["notes"])


def test_basket_rejects_unknown_profiles_and_tiny_or_huge_amounts(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    assert client.get("/api/advisory/basket", params={"profile": "nope", "amount": 500000}).status_code == 404
    assert client.get("/api/advisory/basket", params={"profile": "moderate", "amount": 50}).status_code == 422
    assert client.get("/api/advisory/basket", params={"profile": "moderate", "amount": 5e10}).status_code == 422


def test_rebalance_from_all_cash_buys_toward_the_target_and_never_spends_more_than_the_total(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    r = client.get("/api/advisory/rebalance", params={"profile": "moderate", "holdings": "cash:500000"}).json()
    assert r["total"] == 500000
    lines = {l["asset_id"]: l for l in r["lines"]}
    assert lines["cash"]["current_pct"] == 100 and all(l["action"] in ("BUY", "HOLD") for l in r["lines"])
    bought = sum(l["rupees_to_trade"] for l in r["lines"] if l["action"] == "BUY")
    assert 0 < bought <= 500000 and r["estimated_cost"] == pytest.approx(bought * 0.1 / 100, abs=0.02)
    assert all(l["units"] == int(l["units"]) for l in r["lines"] if l["units"] and l["asset_id"] != "crypto")


def test_rebalance_sells_what_is_over_target_and_leaves_small_drifts_alone(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    mix = client.get("/api/advisory/basket", params={"profile": "moderate", "amount": 1000000}).json()
    exact = ",".join(f"{l['asset_id']}:{l['rupees']}" for l in mix["lines"])               # already at the target: nothing to do
    still = client.get("/api/advisory/rebalance", params={"profile": "moderate", "holdings": exact}).json()
    assert all(l["action"] == "HOLD" for l in still["lines"]) and still["estimated_cost"] == 0
    heavy = client.get("/api/advisory/rebalance", params={"profile": "moderate", "holdings": "equity_large:1000000"}).json()
    lines = {l["asset_id"]: l for l in heavy["lines"]}
    assert lines["equity_large"]["action"] == "SELL" and lines["debt"]["action"] == "BUY"


def test_random_holdings_never_produce_a_plan_that_spends_money_you_do_not_have(client, tmp_path, monkeypatch):
    import random
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    rnd = random.Random(7)
    ids = ["equity_large", "equity_mid", "intl_equity", "gold", "debt", "crypto", "cash"]
    for _ in range(40):                                                          # found by fuzzing: a plan could need more cash than the holdings gave
        held = {k: rnd.choice([0, 0, rnd.randint(1000, 900000)]) for k in ids}
        if sum(held.values()) < 10000:
            held["cash"] = rnd.randint(10000, 500000)
        profile = rnd.choice(["conservative", "moderate", "aggressive"])
        r = client.get("/api/advisory/rebalance", params={"profile": profile, "holdings": ",".join(f"{k}:{v}" for k, v in held.items() if v)}).json()
        buys = sum(l["rupees_to_trade"] for l in r["lines"] if l["action"] == "BUY")
        sells = sum(l["rupees_to_trade"] for l in r["lines"] if l["action"] == "SELL")
        assert r["cash_after"] >= -0.01
        assert held["cash"] + sells - buys - r["estimated_cost"] == pytest.approx(r["cash_after"], abs=0.1)
    for amount in (10000, 12345, 99999, 7777777, 900000000, 1000000000):         # the stored weights can add to 100.01, which overspent big amounts
        b = client.get("/api/advisory/basket", params={"profile": rnd.choice(["conservative", "moderate", "aggressive"]), "amount": amount}).json()
        assert b["cash_left"] >= -0.01


def test_rebalance_rejects_bad_input_with_a_helpful_message(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    get = lambda profile, holdings: client.get("/api/advisory/rebalance", params={"profile": profile, "holdings": holdings})
    assert get("nope", "cash:500000").status_code == 404
    assert get("moderate", "bitcoinz:500000").status_code == 422
    assert get("moderate", "cash:abc").status_code == 422
    assert get("moderate", "cash:-5").status_code == 422
    assert get("moderate", "cash:nan").status_code == 422 and get("moderate", "cash:500000,gold:NaN").status_code == 422     # NaN used to slip through as a 200 with invalid JSON
    assert get("moderate", "cash:inf").status_code == 422
    assert get("moderate", "cash:500").status_code == 422 and "10,000" in get("moderate", "cash:500").json()["detail"]


def _multiasset_file(tmp_path, monkeypatch, ledger_total_now=204):
    import multiasset_trend as mt
    import numpy as np
    import pandas as pd
    import advisory as adv
    rng = np.random.default_rng(6)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range("2019-01-01", periods=1700)
    r = pd.DataFrame({k: rng.normal(0.0003, v, 1700) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[list(vols)]).cumprod() * 100.0
    path = tmp_path / "multiasset.json"
    path.write_text(json.dumps(mt.build(prices, r, register=False, ledger_total_now=ledger_total_now)))
    monkeypatch.setenv("WEBAPP_MULTIASSET", str(path))


def _momentum_file(tmp_path, monkeypatch, ledger_total_now=204):
    import multiasset_momentum as mm
    import numpy as np
    import pandas as pd
    import advisory as adv
    rng = np.random.default_rng(7)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range("2019-01-01", periods=1700)
    r = pd.DataFrame({k: rng.normal(0.0003, v, 1700) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    prices = (1 + r[list(vols)]).cumprod() * 100.0
    path = tmp_path / "momentum.json"
    path.write_text(json.dumps(mm.build(prices, r, register=False, ledger_total_now=ledger_total_now)))
    monkeypatch.setenv("WEBAPP_MULTIASSET_MOMENTUM", str(path))


def test_the_momentum_family_is_served_with_its_own_signals_and_the_default_family_is_still_trend(client, tmp_path, monkeypatch):
    _momentum_file(tmp_path, monkeypatch)
    _multiasset_file(tmp_path, monkeypatch)
    d = client.get("/api/multiasset", params={"family": "momentum"}).json()
    assert d["family"] == "momentum" and d["lookback_days"] == 252 and d["trend_days"] is None
    assert [s["id"] for s in d["strategies"]] == ["momentum_top2", "momentum_top3_risk_managed"] and _find_bare_ratios(d) == []
    assert len(d["signals_now"]) == 6 and all(g["return_12m_pct"] is not None and g["uptrend"] is None for g in d["signals_now"])
    assert d["strategies"][0]["metrics"]["out_of_sample"]["sharpe"]["status"] == d["strategies"][0]["harness_status"]
    t = client.get("/api/multiasset").json()
    assert t["family"] == "trend" and t["trend_days"] == 210 and [s["id"] for s in t["strategies"]] == ["trend_equal_weight", "trend_risk_managed"]
    assert client.get("/api/multiasset", params={"family": "nope"}).status_code == 422


def test_a_missing_momentum_file_is_a_helpful_404_naming_the_command(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_MULTIASSET_MOMENTUM", str(tmp_path / "nope.json"))
    r = client.get("/api/multiasset", params={"family": "momentum"})
    assert r.status_code == 404 and "multiasset_momentum.py" in r.json()["detail"]


def test_multiasset_serves_two_strategies_two_benchmarks_signals_and_stress(client, tmp_path, monkeypatch):
    _multiasset_file(tmp_path, monkeypatch)
    d = client.get("/api/multiasset").json()
    assert [s["id"] for s in d["strategies"]] == ["trend_equal_weight", "trend_risk_managed"] and d["is_stale"] is False
    assert d["static_benchmark"]["id"] == "static_equal_weight" and d["nifty_benchmark"]["id"] == "nifty50_etf"
    s = d["strategies"][0]
    assert s["growth"]["values"][0] == 100.0 and len(s["growth"]["dates"]) == len(s["exposure_pct"]["dates"]) == len(s["drawdown_pct"]["dates"])
    assert abs(sum(h["weight_pct"] for h in s["held_now"]) - 100) < 0.2
    assert len(d["signals_now"]) == 6 and {e["id"] for e in d["stress"]} >= {"covid", "bear_2021_22"} and "not investment advice" in d["disclaimer"]


def test_every_multiasset_sharpe_carries_status_and_count_and_the_benchmarks_are_not_hypotheses(client, tmp_path, monkeypatch):
    _multiasset_file(tmp_path, monkeypatch)
    d = client.get("/api/multiasset").json()
    assert _find_bare_ratios(d) == []
    s = d["strategies"][1]
    oos = s["metrics"]["out_of_sample"]["sharpe"]
    assert oos["status"] == s["harness_status"] and oos["as_of_hypotheses"] == d["ledger_total_at_generation"] and oos["bonferroni_bar"] > 0
    assert d["static_benchmark"]["metrics"]["in_sample"]["sharpe"]["status"] == "BENCHMARK_NOT_A_HYPOTHESIS"


def test_multiasset_results_are_flagged_stale_when_the_ledger_has_grown_and_missing_is_a_helpful_404(client, tmp_path, monkeypatch):
    _multiasset_file(tmp_path, monkeypatch, ledger_total_now=200)
    d = client.get("/api/multiasset").json()
    assert d["is_stale"] is True and d["ledger_total_at_generation"] == 200
    monkeypatch.setenv("WEBAPP_MULTIASSET", str(tmp_path / "nope.json"))
    r = client.get("/api/multiasset")
    assert r.status_code == 404 and "multiasset_trend.py" in r.json()["detail"]


def _independent_oos_metrics(growth: dict, oos_start: str):
    """Sharpe, CAGR and worst fall of the out-of-sample part of a served growth series, written out from scratch (no engine code)."""
    import numpy as np
    import pandas as pd
    v = pd.Series(growth["values"], index=pd.to_datetime(growth["dates"])).loc[oos_start:]
    r = v.pct_change().dropna()
    rf = 1.06 ** (1 / 252) - 1
    sharpe = float((r - rf).mean() / r.std() * np.sqrt(252))
    years = (v.index[-1] - v.index[0]).days / 365.25
    cagr = ((v.iloc[-1] / v.iloc[0]) ** (1 / years) - 1) * 100
    worst = float((v / v.cummax() - 1).min() * 100)
    return sharpe, cagr, worst


def test_the_served_risk_numbers_match_an_independent_recomputation_from_the_served_growth_series(client, tmp_path, monkeypatch):
    """The page shows a Sharpe, a return and a worst fall AND the curve they came from; rebuilding them from the curve must agree."""
    _advisory_file(tmp_path, monkeypatch, with_prices=True)
    a = client.get("/api/advisory").json()
    for p in a["profiles"]:
        sharpe, cagr, worst = _independent_oos_metrics(p["growth_strategy"], a["out_of_sample_start"])
        served = p["strategy"]["out_of_sample"]
        assert sharpe == pytest.approx(served["sharpe"]["value"], abs=0.02), p["id"]
        assert cagr == pytest.approx(served["cagr_pct"], abs=0.1), p["id"]
        assert worst == pytest.approx(served["max_drawdown_pct"], abs=0.05), p["id"]
    _multiasset_file(tmp_path, monkeypatch)
    m = client.get("/api/multiasset").json()
    for s in m["strategies"]:
        sharpe, _cagr, worst = _independent_oos_metrics(s["growth"], m["out_of_sample_start"])
        served = s["metrics"]["out_of_sample"]
        assert sharpe == pytest.approx(served["sharpe"]["value"], abs=0.02), s["id"]
        assert worst == pytest.approx(served["max_drawdown_pct"], abs=0.05), s["id"]


def test_advisory_serves_stress_episodes_and_marks_one_the_simulation_does_not_reach_as_not_covered(client, tmp_path, monkeypatch):
    _advisory_file(tmp_path, monkeypatch, with_prices=True)                       # made-up history starts 2020-01-01, so COVID precedes the simulation
    d = client.get("/api/advisory").json()
    rows = {e["id"]: e for e in d["stress"]}
    assert rows["covid"]["covered"] is False and rows["covid"]["profiles"] == [] and rows["covid"]["benchmark"] is None
    bear = rows["bear_2021_22"]
    assert bear["covered"] and [p["id"] for p in bear["profiles"]] == ["conservative", "moderate", "aggressive"]
    assert all(p["max_drawdown_pct"] <= 0 for p in bear["profiles"]) and len(bear["assets"]) == 6


def test_advisory_forward_serves_the_three_profiles_with_a_clock_and_no_early_sharpe(client, tmp_path, monkeypatch):
    import numpy as np
    import pandas as pd
    import advisory as adv
    import advisory_forward as fwd
    rng = np.random.default_rng(8)
    vols = {"equity_large": 0.010, "equity_mid": 0.013, "intl_equity": 0.012, "gold": 0.008, "debt": 0.004, "crypto": 0.035}
    idx = pd.bdate_range(end="2026-10-23", periods=1500)
    r = pd.DataFrame({k: rng.normal(0.0003, v, 1500) for k, v in vols.items()}, index=idx)
    r["cash"] = (1 + adv.CASH_RATE) ** (1 / adv.TRADING_DAYS) - 1
    path = tmp_path / "fwd.json"
    fwd.write_latest([fwd.build_profile(pid, r) for pid in adv.PROFILES], str(path))
    monkeypatch.setenv("WEBAPP_ADVISORY_FORWARD", str(path))
    d = client.get("/api/advisory/forward").json()
    assert [p["id"] for p in d["profiles"]] == ["conservative", "moderate", "aggressive"] and d["days_needed_for_verdict"] == 252
    p = d["profiles"][1]
    assert p["status"] == "RUNNING" and p["n_trading_days"] == 4 and p["growth_strategy"]["values"][0] == 100.0
    assert "sharpe" not in p["summary"] and p["summary"]["withheld_reason"].startswith("withheld")
    assert abs(sum(m["weight_pct"] for m in p["current_mix"]) - 100) < 0.2
    assert _find_bare_ratios(d) == []


def test_advisory_forward_missing_is_a_helpful_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_ADVISORY_FORWARD", str(tmp_path / "nope.json"))
    r = client.get("/api/advisory/forward")
    assert r.status_code == 404 and "advisory_forward.py" in r.json()["detail"]


def test_advisory_missing_is_a_helpful_404(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_ADVISORY", str(tmp_path / "nope.json"))
    r = client.get("/api/advisory")
    assert r.status_code == 404 and "advisory.py" in r.json()["detail"]


# --- stock-selection ideas (research/factor_ideas.py, FACTOR_IDEAS.md) -------------------------------------------------------

def _window(start, end, sharpe, cagr, dd, percentile=62.5, turnover=28.0):
    return {"start": start, "end": end, "n_obs": 1400, "n_eligible": 50, "blocked": [], "sharpe": sharpe, "cagr_pct": cagr,
            "max_drawdown_pct": dd, "exposure_pct": 99.2, "avg_turnover_pct": turnover, "n_rebalances": 65, "avg_names_held": 10.0,
            "universe_sharpe": 0.31, "universe_cagr_pct": 9.5, "universe_max_drawdown_pct": -31.0,
            "zero_skill": {"n_sims": 200, "mean": 0.3, "percentile": percentile}}


def _idea(name, status, universe="nifty50", top_n=10, **kw):
    return {"in_sample": _window("2015-01-01", "2020-06-30", 0.49, 11.9, -25.4, **kw),
            "out_of_sample": _window("2020-07-01", "2025-12-31", 0.99, 18.3, -17.8, **kw),
            "name": name, "rationale": "A reason.", "universe": universe, "top_n": top_n, "harness_status": status,
            "p_in_sample": 0.13, "p_out_of_sample": 0.0105, "bonferroni_bar": 0.05 / 215}


def _factor_file(tmp_path, monkeypatch, with_survivorship=True, **kw):
    ideas = {"lowvol_nifty50": _idea("Low volatility", "VALIDATED_FAILED", **kw),
             "reversal1m_nifty50": _idea("One-month reversal", "OOS_ONLY_SIGNIFICANT"),
             "momentum_midcap150": _idea("Momentum Midcap", "OOS_ONLY_SIGNIFICANT", universe="midcap150", top_n=30)}
    path = tmp_path / "factor_ideas.json"
    path.write_text(json.dumps({"ledger_total": 215, "registered": True, "ideas": ideas}))
    monkeypatch.setenv("WEBAPP_FACTOR_IDEAS", str(path))
    sv = tmp_path / "survivorship.json"
    metric = lambda c, d: {"sharpe": 1.0, "cagr_pct": c, "max_drawdown_pct": d}
    if not with_survivorship:
        sv.unlink(missing_ok=True)                                              # a leftover file from an earlier call would still be served
    else:
        sv.write_text(json.dumps({"generated_at": "2026-10-22T16:00:00Z", "idea_id": "momentum_midcap150", "design_document": "FACTOR_IDEAS.md",
                                  "casualties": ["JETAIRWAYS.NS"], "n_universe": 145, "n_late_listed": 50, "rows": [
            {"window": "out_of_sample", "start": "2020-07-01", "end": "2025-12-31", "todays_list": metric(55.2, -23.2),
             "with_casualties": metric(54.7, -23.6), "without_late_listed": metric(42.0, -25.0), "n_without_late_listed": 92,
             "late_listed_share_of_universe_pct": 35.2, "late_listed_share_of_picks_pct": 20.8, "casualty_picks": 66}]}))
    monkeypatch.setenv("WEBAPP_MIDCAP_SURVIVORSHIP", str(sv))


def test_stock_selection_serves_three_ideas_each_sharpe_with_status_and_count_and_a_benchmark_that_is_not_a_hypothesis(client, tmp_path, monkeypatch):
    _factor_file(tmp_path, monkeypatch)
    d = client.get("/api/stockselection").json()
    assert [i["id"] for i in d["ideas"]] == ["lowvol_nifty50", "reversal1m_nifty50", "momentum_midcap150"]
    assert _find_bare_ratios(d) == []
    low = d["ideas"][0]
    assert low["strategy"]["out_of_sample"]["sharpe"]["status"] == "VALIDATED_FAILED" and low["strategy"]["out_of_sample"]["sharpe"]["as_of_hypotheses"] == 215
    assert low["strategy"]["out_of_sample"]["sharpe"]["clears_bar"] is False                       # p 0.0105 is far above 0.05/215
    assert low["universe_benchmark"]["out_of_sample"]["sharpe"]["status"] == "BENCHMARK_NOT_A_HYPOTHESIS"
    assert low["universe_benchmark"]["out_of_sample"]["cagr_pct"] == 9.5 and low["universe_benchmark"]["in_sample"]["sharpe"]["value"] == 0.31
    assert [w["window"] for w in low["windows"]] == ["in_sample", "out_of_sample"] and low["windows"][1]["zero_skill_percentile"] == 62.5
    assert d["ledger_total_at_generation"] == 215 and isinstance(d["is_stale"], bool) and d["design_document"] == "FACTOR_IDEAS.md"


def test_stock_selection_carries_the_survivorship_check_without_its_sharpe_and_works_without_it(client, tmp_path, monkeypatch):
    _factor_file(tmp_path, monkeypatch)
    sv = client.get("/api/stockselection").json()["survivorship"]
    row = sv["rows"][0]
    assert sv["idea_id"] == "momentum_midcap150" and row["without_late_listed"] == {"cagr_pct": 42.0, "max_drawdown_pct": -25.0}
    assert "sharpe" not in row["todays_list"]                                 # a Sharpe may only be drawn through the ratio object
    _factor_file(tmp_path, monkeypatch, with_survivorship=False)
    assert client.get("/api/stockselection").json()["survivorship"] is None


def test_a_nan_turnover_is_served_as_null_not_as_invalid_json(client, tmp_path, monkeypatch):
    _factor_file(tmp_path, monkeypatch, turnover=float("nan"))
    r = client.get("/api/stockselection")
    assert r.status_code == 200 and r.json()["ideas"][0]["windows"][0]["avg_turnover_pct"] is None


def test_missing_stock_selection_results_are_a_helpful_404_naming_the_command(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_FACTOR_IDEAS", str(tmp_path / "nope.json"))
    r = client.get("/api/stockselection")
    assert r.status_code == 404 and "factor_ideas.py --register" in r.json()["detail"]


# --- options and intraday rules (research/options_condors.py, research/intraday_rules.py) ----------------------------------------

def _metrics_block(sharpe_is, sharpe_oos):
    m = lambda s: {"sharpe": s, "cagr_pct": -5.0, "max_drawdown_pct": -20.0, "volatility_pct": 10.0, "var95_pct": -1.0, "cvar95_pct": -1.5,
                   "worst_month_pct": -8.0, "calmar": -0.2, "n_days": 500}
    return {"in_sample": m(sharpe_is), "out_of_sample": m(sharpe_oos)}


def _other_files(tmp_path, monkeypatch, options=True, intraday=True, ledger=220, nan=False, intraday_ledger=None):
    judged = {"harness_status": "VALIDATED_FAILED", "p_in_sample": 0.4, "p_out_of_sample": 0.5, "bonferroni_bar": 0.05 / ledger}
    intraday_ledger = ledger if intraday_ledger is None else intraday_ledger
    cycles = lambda n, win: ({"n_cycles": 0} if n == 0 else {"n_cycles": n, "win_rate_pct": win, "total_net_pnl": 37061.5, "worst_cycle": -139773.2,
                                                           "total_net_pnl_without_worst_cycle": 176834.7, "costs_paid": 9145.0, "gross_pnl": 46206.5, "mean_net_pnl": 1158.0, "best_cycle": 46158.6})
    trades = lambda g, c, n: {"n_trades": 100, "n_days_traded": 10, "trades_per_day": 10.0, "mean_gross_pct": g, "mean_net_pct": g - c, "bar_pct": 0.2,
                              "gross_minus_bar_pct": g - 0.2, "mean_cost_pct": c, "win_rate_pct": n, "long_share_pct": 50.0, "mean_net_pct_without_best_5pct": -0.3}
    o = tmp_path / "options.json"
    i = tmp_path / "intraday.json"
    o.unlink(missing_ok=True)
    i.unlink(missing_ok=True)
    if options:
        o.write_text(json.dumps({"generated_at": "2026-10-22T21:54:57Z", "ledger_total": ledger, "registered": True, "rules": {
            "condor_monthly": {"name": "Nifty monthly iron condor", "metrics": _metrics_block(0.5, 0.6), "cycles_in_sample": cycles(22, 81.8),
                               "cycles_out_of_sample": cycles(32, float("nan") if nan else 84.4), **judged},
            "condor_weekly": {"name": "Nifty weekly iron condor", "metrics": _metrics_block(-0.2, -0.1), "cycles_in_sample": cycles(0, 0),
                              "cycles_out_of_sample": cycles(0, 0), **judged}}, "benchmarks": {}}))
    if intraday:
        i.write_text(json.dumps({"generated_at": "2026-10-24T18:30:00Z", "ledger_total": intraday_ledger, "registered": True, "rules": {
            "orb_30": {"name": "Opening-range breakout", "metrics": _metrics_block(-9.6, -12.7), "trades_in_sample": trades(0.034, 0.207, 39.6),
                       "trades_out_of_sample": trades(-0.002, 0.207, 38.7), **judged}}, "benchmarks": {}}))
    monkeypatch.setenv("WEBAPP_OPTIONS_CONDORS", str(o))
    monkeypatch.setenv("WEBAPP_INTRADAY_RULES", str(i))


def test_other_rules_serve_options_and_intraday_each_sharpe_with_status_and_count_and_the_gain_per_trade_against_the_bar(client, tmp_path, monkeypatch):
    _other_files(tmp_path, monkeypatch)
    d = client.get("/api/otherrules").json()
    assert [r["id"] for r in d["rules"]] == ["condor_monthly", "condor_weekly", "orb_30"] and [r["family"] for r in d["rules"]] == ["options", "options", "intraday"]
    assert _find_bare_ratios(d) == []
    m = d["rules"][0]
    assert m["harness_status"] == "VALIDATED_FAILED" and m["strategy"]["out_of_sample"]["sharpe"]["as_of_hypotheses"] == 220
    assert m["strategy"]["out_of_sample"]["sharpe"]["clears_bar"] is False and m["strategy"]["out_of_sample"]["sharpe"]["status"] == "VALIDATED_FAILED"
    w = m["options_windows"][1]
    assert w["window"] == "out_of_sample" and w["n_trades"] == 32 and w["win_rate_pct"] == 84.4 and w["total_net_profit"] == 37061.5 and w["worst_trade"] == -139773.2
    assert w["total_net_profit_without_worst_trade"] == 176834.7 and m["intraday_windows"] == []
    o = d["rules"][2]
    iw = o["intraday_windows"][1]
    assert o["options_windows"] == [] and iw["window"] == "out_of_sample" and iw["mean_gross_pct"] == -0.002 and iw["bar_pct"] == 0.2 and iw["mean_cost_pct"] == 0.207
    assert iw["mean_net_pct"] == pytest.approx(-0.209) and d["ledger_total_at_generation"] == 220 and isinstance(d["is_stale"], bool)
    assert d["generated_at"] == "2026-10-22T21:54:57Z"                                       # the OLDEST of the two files


def test_a_zero_trade_window_and_a_nan_figure_are_served_without_breaking(client, tmp_path, monkeypatch):
    _other_files(tmp_path, monkeypatch, nan=True)
    d = client.get("/api/otherrules").json()
    assert d["rules"][0]["options_windows"][1]["win_rate_pct"] is None                       # a NaN is null, never invalid JSON
    empty = d["rules"][1]["options_windows"][0]
    assert empty["n_trades"] == 0 and empty["win_rate_pct"] is None and empty["total_net_profit"] is None


def test_other_rules_work_with_only_one_family_and_say_what_to_run_when_there_is_none(client, tmp_path, monkeypatch):
    _other_files(tmp_path, monkeypatch, intraday=False)
    assert [r["id"] for r in client.get("/api/otherrules").json()["rules"]] == ["condor_monthly", "condor_weekly"]
    _other_files(tmp_path, monkeypatch, options=False)
    assert [r["id"] for r in client.get("/api/otherrules").json()["rules"]] == ["orb_30"]
    _other_files(tmp_path, monkeypatch, options=False, intraday=False)
    r = client.get("/api/otherrules")
    assert r.status_code == 404 and "options_condors.py --register" in r.json()["detail"] and "intraday_rules.py --register" in r.json()["detail"]


def test_other_rules_report_the_smallest_ledger_count_any_file_was_judged_at(client, tmp_path, monkeypatch):
    _other_files(tmp_path, monkeypatch, ledger=217, intraday_ledger=220)                    # the options file is older: judged at 217, the intraday file at 220
    d = client.get("/api/otherrules").json()
    assert d["ledger_total_at_generation"] == 217
    assert d["rules"][0]["strategy"]["out_of_sample"]["sharpe"]["as_of_hypotheses"] == 217 and d["rules"][2]["strategy"]["out_of_sample"]["sharpe"]["as_of_hypotheses"] == 220


# --- latest prices (webapp/backend/latest_prices.py): display only, kept apart from every result ----------------------------------

def _latest_file(prices, as_of="2026-10-23", raw=None):
    import os
    path = os.path.join(os.environ["WEBAPP_SNAPSHOT_DIR"], "latest_prices.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else json.dumps({"as_of": as_of, "generated_at": "2026-10-24T20:00:00Z", "prices": prices}))


def test_the_screener_carries_the_latest_close_for_stocks_that_have_one_and_null_for_the_rest(client):
    _latest_file({"AAA": {"date": "2026-10-23", "close": 1190.0, "prev_close": 1184.5, "change_pct": 0.46, "suspect": False, "stale": False}})
    d = client.get("/api/screener").json()
    rows = {r["symbol"]: r for r in d["rows"]}
    assert d["latest_prices_through"] == "2026-10-23"
    assert rows["AAA"]["latest"] == {"date": "2026-10-23", "close": 1190.0, "prev_close": 1184.5, "change_pct": 0.46, "suspect": False, "stale": False}
    assert rows["BBB"]["latest"] is None                                                   # not in the file: nothing is invented
    assert rows["AAA"]["last_close"] == 104.0                                              # the backtest-window close is untouched


def test_without_a_latest_prices_file_everything_still_works_and_nothing_is_shown_as_latest(client):
    d = client.get("/api/screener").json()
    assert d["latest_prices_through"] is None and all(r["latest"] is None for r in d["rows"])
    assert client.get("/api/symbols/AAA").json()["latest"] is None
    assert client.get("/api/health").json()["latest_prices_through"] is None


def test_a_damaged_latest_prices_file_never_takes_the_stock_pages_down(client):
    _latest_file(None, raw="{ this is not json")
    assert client.get("/api/screener").status_code == 200 and client.get("/api/symbols/AAA").status_code == 200
    assert client.get("/api/symbols/AAA").json()["latest"] is None and client.get("/api/health").json()["latest_prices_through"] is None


def test_the_stock_page_and_the_status_strip_show_the_latest_close_and_its_warnings(client):
    _latest_file({"AAA": {"date": "2026-10-23", "close": 133.0, "prev_close": 100.0, "change_pct": 33.0, "suspect": True, "stale": False},
                  "BBB": {"date": "2026-10-14", "close": 50.0, "prev_close": 50.0, "change_pct": 0.0, "suspect": False, "stale": True}})
    a, b = client.get("/api/symbols/AAA").json(), client.get("/api/symbols/BBB").json()
    assert a["latest"]["close"] == 133.0 and a["latest"]["suspect"] is True and b["latest"]["stale"] is True and b["latest"]["date"] == "2026-10-14"
    assert client.get("/api/health").json()["latest_prices_through"] == "2026-10-23"
    assert a["last_close"] == 104.0 and a["last_date"] == "2020-01-07"                     # the research window's own figures are unchanged


# --- go-live gates (research/golive_gates.py, GO_LIVE_GATES.md) -------------------------------------------------------------------

def _golive_file(tmp_path, monkeypatch, amendment_status="NOT_MET", with_amendment_gate=True, eligible=False):
    gate = lambda name, status, detail="d": {"gate": name, "status": status, "detail": detail}
    project = [gate("Paper layer: weeks of clean reconciliation", "NOT_YET")]
    if with_amendment_gate:
        project.append(gate("Owner's written amendment of rule 5", amendment_status, "CLAUDE.md rule 5 still forbids order placement"))
    path = tmp_path / "golive.json"
    path.write_text(json.dumps({
        "generated_at": "2026-10-24T20:56:33Z", "thresholds": {"win_rate_min_pct": 85.0, "min_closed_trades": 100, "max_drawdown_pct": 10.0},
        "project_gates": project, "note": "Allocation profiles hold weights, not trades: under a win-rate gate they cannot unlock.",
        "rules": [
            {"id": "m", "name": "Momentum", "kind": "book", "days": 4, "gate_days": 252, "n_trades": 10, "min_trades": 100, "eligible": eligible, "unmet": ["Forward test complete"],
             "gates": [gate("Forward test complete", "NOT_YET", "4 of 252 trading days"), gate("Worst single loss within 2.0% of the account", "MET", "-0.91%")]},
            {"id": "c", "name": "Conservative", "kind": "allocation", "days": 3, "gate_days": 252, "n_trades": None, "min_trades": 100, "eligible": False, "unmet": ["Win rate"],
             "gates": [gate("Win rate at least 85%", "CANNOT_MEASURE", "no trade statistics")]}]}))
    monkeypatch.setenv("WEBAPP_GOLIVE_GATES", str(path))


def test_golive_serves_every_rule_with_its_gates_progress_and_the_locked_flag(client, tmp_path, monkeypatch):
    _golive_file(tmp_path, monkeypatch)
    d = client.get("/api/golive").json()
    assert [r["id"] for r in d["rules"]] == ["m", "c"] and d["execution_locked"] is True and d["generated_at"] == "2026-10-24T20:56:33Z"
    m = d["rules"][0]
    assert (m["days"], m["gate_days"], m["n_trades"], m["min_trades"], m["kind"]) == (4, 252, 10, 100, "book") and m["eligible"] is False
    assert [g["status"] for g in m["gates"]] == ["NOT_YET", "MET"] and m["gates"][0]["detail"] == "4 of 252 trading days" and m["unmet"] == ["Forward test complete"]
    assert d["rules"][1]["kind"] == "allocation" and d["rules"][1]["n_trades"] is None and d["rules"][1]["gates"][0]["status"] == "CANNOT_MEASURE"
    assert d["thresholds"]["win_rate_min_pct"] == 85.0 and "cannot unlock" in d["note"]
    assert [g["gate"] for g in d["project_gates"]][-1] == "Owner's written amendment of rule 5"


def test_execution_is_locked_unless_the_amendment_gate_is_clearly_met_and_it_fails_closed(client, tmp_path, monkeypatch):
    _golive_file(tmp_path, monkeypatch, amendment_status="MET")
    assert client.get("/api/golive").json()["execution_locked"] is False
    _golive_file(tmp_path, monkeypatch, amendment_status="NOT_YET")
    assert client.get("/api/golive").json()["execution_locked"] is True
    _golive_file(tmp_path, monkeypatch, with_amendment_gate=False)                          # no such gate in the file: locked, not open
    assert client.get("/api/golive").json()["execution_locked"] is True


def test_the_app_shows_the_eligible_flag_the_file_gives_and_never_decides_it_itself(client, tmp_path, monkeypatch):
    _golive_file(tmp_path, monkeypatch, amendment_status="MET", eligible=True)
    d = client.get("/api/golive").json()
    assert d["rules"][0]["eligible"] is True and d["execution_locked"] is False             # both come from the file; neither is worked out here


def test_missing_golive_results_are_a_helpful_404_naming_the_command(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAPP_GOLIVE_GATES", str(tmp_path / "nope.json"))
    r = client.get("/api/golive")
    assert r.status_code == 404 and "golive_gates.py" in r.json()["detail"]
