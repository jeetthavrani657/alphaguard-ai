"""
webapp/backend/main.py

The FastAPI application: a thin, READ-ONLY layer between the snapshot files
and whoever asks (the React frontend, later; your browser's /docs page now).

Run it from the project root:

    python -m uvicorn webapp.backend.main:app --port 8000

then open http://127.0.0.1:8000/docs -- an interactive page FastAPI builds
for you from the code below.

Ground rules this file keeps (and tests/test_webapp_api.py enforces):

  * Every route is GET. There is no route that writes, deletes or runs
    anything, so "read-only" is a property of the program, not a promise.
  * It imports nothing from engine/, strategies/ or research/ -- it could
    not compute a metric even if someone wanted it to. (A test checks this
    in a fresh interpreter.)
  * Every response is a Pydantic model from schemas.py, validated before it
    leaves. A Sharpe ratio cannot be sent without its status.
  * The only logic here is selection: filter, paginate, look up. No
    arithmetic on financial values. (One labelled exception: /advisory/basket
    converts a user's amount into rupees and whole units from stored weights
    and prices. It is a unit conversion, not a metric.)
"""

import math
import os
from datetime import datetime, timezone
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from . import report as rp
from . import schemas, store

app = FastAPI(
    title="AlphaGuard AI: results API",
    description=(
        "Read-only access to precomputed backtest results. Every Sharpe/Sortino "
        "is returned together with its validation status and the hypothesis "
        "count that status is valid 'as of'. Results are produced by "
        "`python -m webapp.backend.snapshot`; this API never runs a strategy."
    ),
    version="1.0.0",
)


# --- error handling --------------------------------------------------------------
# Domain errors from store.py become honest HTTP errors with a message a human
# can act on, instead of a 500 stack trace.

@app.exception_handler(store.SnapshotMissing)
async def _snapshot_missing(_request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(store.NotFound)
async def _not_found(_request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


# Everything lives under /api so the frontend can later be served from the same
# origin without path clashes.
api = APIRouter(prefix="/api")


# --- helpers (selection only) ---------------------------------------------------------

def _is_stale(as_of_hypotheses: int) -> bool:
    """True when the ledger has grown since a status was computed (an integer comparison)."""
    now = store.ledger_total_now()
    return now is not None and now != as_of_hypotheses


def _summary(detail: schemas.StrategyDetail) -> schemas.StrategySummary:
    return schemas.StrategySummary(
        id=detail.id, name=detail.name, family=detail.family, universe=detail.universe, kind=detail.kind,
        status=detail.status, as_of_hypotheses=detail.as_of_hypotheses,
        in_sample_sharpe=detail.in_sample.strategy.sharpe,
        out_of_sample_sharpe=detail.out_of_sample.strategy.sharpe,
        stale=_is_stale(detail.as_of_hypotheses),
    )


# --- routes -------------------------------------------------------------------------

# The health checker runs once per weekday, so Friday evening to Monday evening is 72 hours of silence by design.
FORWARD_HEALTH_STALE_HOURS = 80


def _forward_health_fields() -> dict:
    raw = store.load_health_latest_raw()
    if raw is None:
        return {}
    age_hours = (datetime.now(timezone.utc) - datetime.strptime(raw["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
                 .replace(tzinfo=timezone.utc)).total_seconds() / 3600
    return {"forward_health": raw["overall"], "forward_health_generated_at": raw["generated_at"],
            "forward_health_stale": age_hours > FORWARD_HEALTH_STALE_HOURS,
            "forward_health_problems": [f"{c['label']}: {c['detail']}" for c in raw["checks"] if c["status"] != "OK"]}


@api.get("/health", response_model=schemas.Health, summary="Is the API up, and is there data behind it?")
def health():
    manifest = None
    try:
        manifest = store.load_manifest()
    except store.SnapshotMissing:
        pass
    snapshot = manifest is not None
    now = store.ledger_total_now()
    ledger = now is not None
    prov = manifest.provenance if manifest else None
    return schemas.Health(
        ok=snapshot and ledger, snapshot_present=snapshot, ledger_present=ledger,
        detail="ok" if snapshot and ledger else
        "Run `python -m webapp.backend.snapshot` to generate results." if not snapshot else "Ledger file missing.",
        data_through=prov.data_through if prov else None,
        latest_prices_through=(store.load_latest_prices() or {}).get("as_of"),
        snapshot_generated_at=prov.generated_at if prov else None,
        git_commit=prov.git_commit if prov else None, git_dirty=prov.git_dirty if prov else None,
        ledger_total_now=now, snapshot_ledger_total=prov.ledger_total_at_snapshot if prov else None,
        snapshot_stale=(now != prov.ledger_total_at_snapshot) if (prov and ledger) else None,
        **_forward_health_fields())


@api.get("/strategies", response_model=schemas.StrategyList,
         summary="Every strategy with its validation status (the home-page table).")
def list_strategies():
    manifest = store.load_manifest()
    details = [store.load_strategy_file(i).detail for i in manifest.strategy_ids]
    return schemas.StrategyList(
        ledger_total_now=store.ledger_total_now() or 0,
        snapshot_generated_at=manifest.provenance.generated_at,
        strategies=[_summary(d) for d in details])


@api.get("/strategies/{strategy_id}", response_model=schemas.StrategyDetail,
         summary="One strategy: parameters, rationale, both windows' metrics, provenance.")
def get_strategy(strategy_id: str):
    detail = store.load_strategy_file(strategy_id).detail
    return detail.model_copy(update={"stale": _is_stale(detail.as_of_hypotheses)})


@api.get("/strategies/{strategy_id}/equity", response_model=schemas.EquityResponse,
         summary="Equity, drawdown and exposure series (strategy and buy-and-hold) for one window, as parallel arrays.")
def get_equity(strategy_id: str, window: schemas.Window = Query(..., description="in_sample or out_of_sample")):
    data = store.load_strategy_file(strategy_id).data[window]
    return schemas.EquityResponse(
        strategy_id=strategy_id, window=window, strategy=data.equity_strategy, benchmark=data.equity_benchmark,
        drawdown_strategy_pct=data.drawdown_strategy_pct, drawdown_benchmark_pct=data.drawdown_benchmark_pct,
        exposure_strategy_pct=data.exposure_strategy_pct, exposure_definition=data.exposure_definition,
        growth_strategy=data.growth_strategy, growth_benchmark=data.growth_benchmark)


@api.get("/strategies/{strategy_id}/trades", response_model=schemas.TradePage,
         summary="Trade log, paginated. Closed trades for per-symbol strategies; executions + rebalances for portfolios.")
def get_trades(
    strategy_id: str,
    window: schemas.Window = Query(...),
    limit: int = Query(100, ge=1, le=1000, description="Page size."),
    offset: int = Query(0, ge=0, description="Rows to skip."),
):
    sf = store.load_strategy_file(strategy_id)
    data = sf.data[window]
    page = dict(strategy_id=strategy_id, window=window, kind=sf.detail.kind, limit=limit, offset=offset)
    if sf.detail.kind == "portfolio":
        return schemas.TradePage(total=len(data.executions), executions=data.executions[offset:offset + limit],
                                 rebalances=data.rebalances if offset == 0 else None, **page)
    return schemas.TradePage(total=len(data.closed_trades), closed_trades=data.closed_trades[offset:offset + limit], **page)


@api.get("/strategies/{strategy_id}/report", response_model=schemas.StrategyReport,
         summary="Monthly returns, the spread of the trades, the deepest falls and the evidence for one window: other views of numbers already stored.")
def get_report(strategy_id: str, window: schemas.Window = Query(..., description="in_sample or out_of_sample")):
    sf = store.load_strategy_file(strategy_id)
    data = sf.data[window]
    growth, bench = data.growth_strategy or data.equity_strategy, data.growth_benchmark or data.equity_benchmark
    base = 100.0 if data.growth_strategy else None            # a "growth of 100" series starts from 100 on the day BEFORE its first value, so the first month is measured from there
    dd_s, dd_b = data.drawdown_strategy_pct, data.drawdown_benchmark_pct
    return schemas.StrategyReport(
        strategy_id=strategy_id, window=window,
        monthly_strategy=rp.monthly_returns(growth.dates, growth.values, base),
        monthly_benchmark=rp.monthly_returns(bench.dates, bench.values, base if data.growth_benchmark else None),
        trade_histogram=None if sf.detail.kind == "portfolio" else rp.trade_histogram([t.return_pct for t in data.closed_trades]),
        drawdown_periods_strategy=rp.drawdown_periods(dd_s.dates, dd_s.values) if dd_s else [],
        drawdown_periods_benchmark=rp.drawdown_periods(dd_b.dates, dd_b.values) if dd_b else [],
        evidence=rp.evidence(len(growth.dates), sf.detail.as_of_hypotheses))


@api.get("/data-quality", response_model=schemas.DataQualityResponse,
         summary="Per-symbol validator results and price discontinuities.")
def data_quality(
    universe: Optional[Literal["nifty50", "midcap150", "smallcap250"]] = None,
    only_issues: bool = Query(
        False, description="Only symbols the validator marked unusable, or with a discontinuity that is not "
                           "reviewed as GENUINE. Soft-check failures alone (every symbol 'misses' NSE holidays "
                           "against a weekday calendar) do not count."),
):
    report = store.load_data_quality()
    symbols = report.symbols
    if universe:
        symbols = [s for s in symbols if s.universe == universe]
    if only_issues:
        # Uses only fields the validator produced: `usable` already encodes which check failures are
        # disqualifying, and each discontinuity carries its own review status.
        symbols = [s for s in symbols if (not s.usable) or any(d.status != "GENUINE" for d in s.discontinuities)]
    # Totals describe the whole snapshot; `symbols` is the filtered list.
    return report.model_copy(update={"symbols": symbols})


@api.get("/screener", response_model=schemas.ScreenerResponse,
         summary="Every stock with its buy-and-hold return per window (screener table and sector heatmap).")
def screener(
    universe: Optional[Literal["nifty50", "midcap150", "smallcap250"]] = None,
    sector: Optional[str] = Query(None, description="Exact sector name from config.SECTOR_MAP (Nifty 50 only)."),
    flagged_only: bool = Query(False, description="Only stocks that are unusable or have an unresolved discontinuity."),
):
    data = store.load_screener()
    rows = data.rows
    if universe:
        rows = [r for r in rows if r.universe == universe]
    if sector:
        rows = [r for r in rows if r.sector == sector]
    if flagged_only:
        rows = [r for r in rows if (not r.usable) or r.has_unresolved_discontinuity]
    latest = store.load_latest_prices() or {}
    prices = latest.get("prices", {})
    rows = [r.model_copy(update={"latest": schemas.LatestPrice(**prices[r.symbol]) if r.symbol in prices else None}) for r in rows]
    return data.model_copy(update={"rows": rows, "latest_prices_through": latest.get("as_of"), "sectors": sorted({r.sector for r in data.rows if r.sector})})


@api.get("/symbols/{symbol}", response_model=schemas.SymbolDetail,
         summary="One stock: every strategy's result on it (as labelled slices), trade markers, data quality.")
def symbol_detail(symbol: str):
    row = store.known_symbol(symbol)
    manifest = store.load_manifest()
    quality = next((s for s in store.load_data_quality().symbols if s.symbol == symbol), None)

    results, markers, executions = [], [], []
    for sid in manifest.strategy_ids:
        sf = store.load_strategy_file(sid)
        d = sf.detail
        if d.universe != row.universe:
            continue                                # a strategy only ever ran on its own universe
        if d.kind == "portfolio":
            results.append(schemas.SymbolStrategyResult(
                strategy_id=sid, strategy_name=d.name, kind=d.kind, parent_status=d.status,
                as_of_hypotheses=d.as_of_hypotheses,
                note="Portfolio strategy: the test is of the whole selection process, so there is no per-stock "
                     "result. Its buys and sells in this stock are shown as executions."))
            for w in ("in_sample", "out_of_sample"):
                executions += [schemas.SymbolExecution(strategy_id=sid, strategy_name=d.name, date=e.date, side=e.side,
                                                       shares=e.shares, price=e.price)
                               for e in sf.data[w].executions if e.symbol == symbol]
            continue
        slices = store.load_symbol_slices(sid)
        res = schemas.SymbolStrategyResult(
            strategy_id=sid, strategy_name=d.name, kind=d.kind, parent_status=d.status,
            as_of_hypotheses=d.as_of_hypotheses)
        if slices is not None:
            res.in_sample = slices.windows["in_sample"].get(symbol)
            res.out_of_sample = slices.windows["out_of_sample"].get(symbol)
            res.excluded_in_sample = slices.excluded["in_sample"].get(symbol)
            res.excluded_out_of_sample = slices.excluded["out_of_sample"].get(symbol)
        results.append(res)
        for w in ("in_sample", "out_of_sample"):
            markers += [schemas.SymbolMarker(
                strategy_id=sid, strategy_name=d.name, entry_date=t.entry_date, exit_date=t.exit_date,
                entry_price=t.entry_price, exit_price=t.exit_price, return_pct=t.return_pct)
                for t in sf.data[w].closed_trades if t.symbol == symbol]
    return schemas.SymbolDetail(
        symbol=symbol, universe=row.universe, sector=row.sector, usable=row.usable, first_date=row.first_date,
        last_date=row.last_date, last_close=row.last_close, latest=store.latest_for(symbol), quality=quality, results=results, markers=markers,
        executions=executions)


@api.get("/symbols/{symbol}/prices", response_model=schemas.PriceSeries,
         summary="Adjusted OHLCV plus indicator series (read from the strategy modules), optionally date-trimmed.")
def symbol_prices(
    symbol: str,
    from_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Inclusive, YYYY-MM-DD."),
    to_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Inclusive, YYYY-MM-DD."),
):
    ps = store.load_prices(symbol)
    if from_date is None and to_date is None:
        return ps
    # ISO dates sort as text, so trimming is a plain slice: selection, not calculation.
    lo = bisect_left(ps.dates, from_date) if from_date else 0
    hi = bisect_right(ps.dates, to_date) if to_date else len(ps.dates)
    cut = lambda xs: xs[lo:hi]
    return ps.model_copy(update=dict(
        dates=cut(ps.dates), open=cut(ps.open), high=cut(ps.high), low=cut(ps.low), close=cut(ps.close),
        volume=cut(ps.volume), indicators={k: cut(v) for k, v in ps.indicators.items()}))


@api.get("/ledger", response_model=schemas.LedgerResponse,
         summary="The hypothesis ledger: how many things have been tried, and when.")
def ledger():
    raw = store.load_ledger()
    snapshot_total = snapshot_bar = None
    try:
        m = store.load_manifest()
        snapshot_total = m.provenance.ledger_total_at_snapshot
        snapshot_bar = m.provenance.bonferroni_bar_at_snapshot
    except store.SnapshotMissing:
        pass
    total = int(raw["cumulative_hypotheses"])
    return schemas.LedgerResponse(
        cumulative_hypotheses=total, bonferroni_bar_at_snapshot=snapshot_bar, snapshot_total=snapshot_total,
        snapshot_is_stale=None if snapshot_total is None else snapshot_total != total,
        runs=[schemas.LedgerRun(**{k: r[k] for k in schemas.LedgerRun.model_fields}) for r in raw["runs"]])


@api.get("/forward-books", response_model=schemas.ForwardBooksResponse,
         summary="The frozen paper-trading books (FORWARD_BOOKS.md): forward performance against buy-and-hold.")
def forward_books():
    raw = store.load_forward_books_raw()
    total = store.ledger_total_now() or 0
    needed = int(raw["min_days_for_sharpe"])

    def ratio(value):
        # Labelling only: a forward Sharpe is out-of-time but not yet judged against its pre-registered
        # criteria, so it is UNVALIDATED, and it carries the hypothesis count like every other ratio.
        return None if value is None else schemas.RiskAdjustedRatio(
            kind="sharpe", value=value, window="out_of_sample", status="UNVALIDATED", as_of_hypotheses=total)

    books = []
    for b in raw["books"]:
        sm = b.get("summary")
        risk = schemas.BookRiskAdjusted(withheld_reason="no forward days yet" if sm is None else None)
        if sm is not None:
            risk = schemas.BookRiskAdjusted(book=ratio(sm.get("sharpe")), benchmark=ratio(sm.get("benchmark_sharpe")),
                                            withheld_reason=sm.get("sharpe_note") or None)
        books.append(schemas.ForwardBook(
            id=b["id"], name=b["name"], kind=b["kind"], universe=b["universe"], rationale=b["rationale"],
            why_forward_tested=b["why_forward_tested"], status=b["status"], data_through=b["data_through"],
            start=b["start"], first_counted_day=b["first_counted_day"], n_trading_days=b["n_trading_days"],
            days_needed_for_verdict=int(b.get("verdict_gate_days", needed)),
            verdict_note=b.get("verdict_note"), criteria_document=b.get("criteria_document", "FORWARD_BOOKS.md"),
            summary=None if sm is None else schemas.BookSummary(**{k: sm.get(k) for k in schemas.BookSummary.model_fields}),
            risk_adjusted=risk, growth_book=b.get("growth_book"), growth_benchmark=b.get("growth_benchmark"),
            drawdown_book=b.get("drawdown_book"), drawdown_benchmark=b.get("drawdown_benchmark"),
            exposure=b.get("exposure"), holdings=b.get("holdings", []), pending=b.get("pending", []), orders=b.get("orders", []),
            notes=b.get("notes", [])))
    return schemas.ForwardBooksResponse(generated_at=raw["generated_at"], start=raw["start"],
                                        first_counted_day=raw["first_counted_day"], books=books)


def _finite(x):
    """None for a missing or NaN number (JSON cannot carry NaN), otherwise the number."""
    return None if x is None or not math.isfinite(x) else x


def _advisory_metrics(m: dict, window: str, status: str, total: int, p_value, bar) -> schemas.AdvisoryRiskMetrics:
    clears = None if p_value is None or bar is None else bool(p_value < bar)
    ratio = schemas.RiskAdjustedRatio(kind="sharpe", value=m.get("sharpe"), window=window, status=status, as_of_hypotheses=total,
                                      p_value=p_value, bonferroni_bar=bar, clears_bar=clears)
    return schemas.AdvisoryRiskMetrics(
        sharpe=ratio, cagr_pct=m.get("cagr_pct"), volatility_pct=m.get("volatility_pct"), max_drawdown_pct=m.get("max_drawdown_pct"),
        var95_pct=m.get("var95_pct"), cvar95_pct=m.get("cvar95_pct"), worst_month_pct=m.get("worst_month_pct"), calmar=m.get("calmar"),
        n_days=int(m["n_days"]))


@api.get("/advisory", response_model=schemas.AdvisoryResponse,
         summary="The multi-asset, risk-managed allocation tool: recommended mixes, risk metrics and a historical simulation per profile.")
def advisory():
    raw = store.load_advisory_raw()
    total = int(raw["ledger_total"])
    now = store.ledger_total_now()
    profiles = []
    for p in raw["profiles"]:
        def windows(key, status, pv_is, pv_oos, bar):
            m = p[key]
            return schemas.AdvisoryWindows(in_sample=_advisory_metrics(m["in_sample"], "in_sample", status, total, pv_is, bar),
                                           out_of_sample=_advisory_metrics(m["out_of_sample"], "out_of_sample", status, total, pv_oos, bar))
        profiles.append(schemas.AdvisoryProfile(
            id=p["id"], name=p["name"], blurb=p["blurb"], target_volatility_pct=p["target_volatility_pct"],
            drawdown_limit_pct=p["drawdown_limit_pct"], caps_pct=p["caps_pct"], recommended_on=p["recommended_on"], guard_on=p["guard_on"],
            allocation=[schemas.AdvisoryWeight(**a) for a in p["allocation"]], excluded=p.get("excluded", []), harness_status=p["harness_status"],
            strategy=windows("metrics", p["harness_status"], p["p_value_in_sample"], p["p_value_out_of_sample"], p["bonferroni_bar"]),
            benchmark=windows("benchmark_metrics", "BENCHMARK_NOT_A_HYPOTHESIS", None, None, None),
            growth_strategy=p["growth_strategy"], growth_benchmark=p["growth_benchmark"],
            drawdown_strategy_pct=p["drawdown_strategy_pct"], drawdown_benchmark_pct=p["drawdown_benchmark_pct"],
            exposure_pct=p["exposure_pct"], n_rebalances=p["n_rebalances"], cost_paid_pct_of_start=p["cost_paid_pct_of_start"]))
    return schemas.AdvisoryResponse(
        generated_at=raw["generated_at"], data_through=raw["data_through"], simulation_start=raw["simulation_start"],
        in_sample_end=raw["in_sample_end"], out_of_sample_start=raw["out_of_sample_start"], ledger_total_at_generation=total,
        ledger_total_now=now, is_stale=(now is not None and now != total), disclaimer=raw["disclaimer"], benchmark=raw["benchmark"],
        rule=raw["rule"], data_cleaning=raw["data_cleaning"], assets=raw["assets"], correlation=raw["correlation"],
        trend=raw.get("trend", []), stress=raw.get("stress", []), questions=raw["questionnaire"]["questions"], bands=raw["questionnaire"]["bands"], profiles=profiles)


@api.get("/multiasset", response_model=schemas.MultiassetResponse,
         summary="Multi-asset trading rules (research/multiasset_trend.py or multiasset_momentum.py): two registered hypotheses each, against a no-selection benchmark.")
def multiasset(family: Literal["trend", "momentum"] = Query("trend", description="trend (the 210-day trend filter) or momentum (dual momentum).")):
    raw = store.load_multiasset_raw(family)
    total = int(raw["ledger_total"])
    now = store.ledger_total_now()

    def windows(m: dict, status: str, pv_is, pv_oos, bar):
        return schemas.AdvisoryWindows(in_sample=_advisory_metrics(m["in_sample"], "in_sample", status, total, pv_is, bar),
                                       out_of_sample=_advisory_metrics(m["out_of_sample"], "out_of_sample", status, total, pv_oos, bar))

    strategies = [schemas.MultiassetStrategy(
        id=s["id"], name=s["name"], blurb=s["blurb"], harness_status=s["harness_status"],
        metrics=windows(s["metrics"], s["harness_status"], s["p_value_in_sample"], s["p_value_out_of_sample"], s["bonferroni_bar"]),
        growth=s["growth"], drawdown_pct=s["drawdown_pct"], exposure_pct=s["exposure_pct"], n_rebalances=s["n_rebalances"],
        cost_paid_pct_of_start=s["cost_paid_pct_of_start"], held_now=s["held_now"], held_decided_on=s["held_decided_on"]) for s in raw["strategies"]]
    bench = {k: schemas.MultiassetBenchmark(id=b["id"], name=b["name"], metrics=windows(b["metrics"], "BENCHMARK_NOT_A_HYPOTHESIS", None, None, None),
                                            growth=b["growth"], drawdown_pct=b["drawdown_pct"]) for k, b in raw["benchmarks"].items()}
    return schemas.MultiassetResponse(
        generated_at=raw["generated_at"], data_through=raw["data_through"], simulation_start=raw["simulation_start"],
        in_sample_end=raw["in_sample_end"], out_of_sample_start=raw["out_of_sample_start"], ledger_total_at_generation=total,
        ledger_total_now=now, is_stale=(now is not None and now != total), disclaimer=raw["disclaimer"], family=family, trend_days=raw.get("trend_days"), lookback_days=raw.get("lookback_days"),
        design_document=raw["design_document"], rule=raw["rule"], strategies=strategies, static_benchmark=bench["static"],
        nifty_benchmark=bench["nifty"], signals_now=raw["signals_now"], stress=raw["stress"], assets=raw["assets"])


@api.get("/stockselection", response_model=schemas.StockSelectionResponse,
         summary="Stock-selection ideas (research/factor_ideas.py): three registered hypotheses against a no-selection benchmark and random picks.")
def stock_selection():
    raw = store.load_factor_ideas_raw()
    total = int(raw["ledger_total"])
    now = store.ledger_total_now()

    def metrics(w: dict, status: str, p_value, bar, prefix: str = ""):
        """One window's numbers in the shape the rest of the API uses (the writer calls the day count n_obs)."""
        key = (lambda k: f"{prefix}{k}")
        m = {"sharpe": w[key("sharpe")], "cagr_pct": w[key("cagr_pct")], "max_drawdown_pct": w[key("max_drawdown_pct")], "n_days": w["n_obs"]}
        return m, status, p_value, bar

    def windows(idea: dict, status: str, pv_is, pv_oos, bar, prefix: str = ""):
        a = metrics(idea["in_sample"], status, pv_is, bar, prefix)
        b = metrics(idea["out_of_sample"], status, pv_oos, bar, prefix)
        return schemas.AdvisoryWindows(in_sample=_advisory_metrics(a[0], "in_sample", status, total, pv_is, bar),
                                       out_of_sample=_advisory_metrics(b[0], "out_of_sample", status, total, pv_oos, bar))

    ideas = []
    for idea_id, idea in raw["ideas"].items():
        detail = [schemas.StockSelectionWindow(
            window=name, start=w["start"], end=w["end"], n_eligible=w["n_eligible"], exposure_pct=w["exposure_pct"],
            avg_turnover_pct=_finite(w.get("avg_turnover_pct")), avg_names_held=w["avg_names_held"],
            zero_skill_percentile=w["zero_skill"].get("percentile"), zero_skill_n_portfolios=int(w["zero_skill"]["n_sims"]))
            for name, w in (("in_sample", idea["in_sample"]), ("out_of_sample", idea["out_of_sample"]))]
        ideas.append(schemas.StockSelectionIdea(
            id=idea_id, name=idea["name"], rationale=idea["rationale"], universe=idea["universe"], top_n=idea["top_n"],
            harness_status=idea["harness_status"],
            strategy=windows(idea, idea["harness_status"], idea["p_in_sample"], idea["p_out_of_sample"], idea["bonferroni_bar"]),
            universe_benchmark=windows(idea, "BENCHMARK_NOT_A_HYPOTHESIS", None, None, None, prefix="universe_"), windows=detail))
    survivorship = store.load_survivorship_raw()
    return schemas.StockSelectionResponse(
        generated_at=raw["generated_at"], ledger_total_at_generation=total, ledger_total_now=now,
        is_stale=(now is not None and now != total), ideas=ideas,
        survivorship=None if survivorship is None else schemas.SurvivorshipCheck(**survivorship))


@api.get("/claim-check", response_model=schemas.ClaimCheck,
         summary="Judge a claim 'annual Sharpe X over Y years after Z attempts' against what luck alone would produce (webapp/backend/report.py).")
def claim_check(claimed: float = Query(..., ge=-5, le=10, description="The claimed annual Sharpe ratio."),
                years: float = Query(..., ge=0.5, le=50, description="Years of data the claim rests on."),
                tries: int = Query(1, ge=1, le=100000, description="How many variants or ideas were tried to get this result.")):
    return schemas.ClaimCheck(**rp.claim_check(claimed, years, tries))


@api.get("/track-record", response_model=schemas.TrackRecord,
         summary="Checks, made from git history, that the idea count and the forward results were never rewritten (research/track_record.py).")
def track_record():
    return schemas.TrackRecord(**store.load_track_record_raw())


@api.get("/options-explainer", response_model=schemas.CondorExplainer,
         summary="Real condor trades with their payoff at expiry, where the Nifty landed against the shorts, and implied against realised volatility by year (research/condor_payoff.py).")
def options_explainer():
    raw = store.load_condor_payoff_raw()
    return schemas.CondorExplainer(
        generated_at=raw["generated_at"], data_through=raw["data_through"],
        rules=[schemas.CondorRuleView(id=rid, **r) for rid, r in raw["rules"].items()],
        years=raw["volatility"]["years"], series=raw["volatility"]["series"])


@api.get("/otherrules", response_model=schemas.OtherRulesResponse,
         summary="The Nifty options rules (research/options_condors.py) and the intraday rules (research/intraday_rules.py): each registered, counted and judged like every other strategy.")
def other_rules():
    raw = store.load_other_rules_raw()
    now = store.ledger_total_now()
    rules, totals, stamps = [], [], []
    for family, file in raw.items():
        if file is None:
            continue
        total = int(file["ledger_total"])
        totals.append(total)
        stamps.append(file["generated_at"])
        for rule_id, r in file["rules"].items():
            status, p_is, p_oos, bar = r["harness_status"], r["p_in_sample"], r["p_out_of_sample"], r["bonferroni_bar"]
            strategy = schemas.AdvisoryWindows(
                in_sample=_advisory_metrics(r["metrics"]["in_sample"], "in_sample", status, total, p_is, bar),
                out_of_sample=_advisory_metrics(r["metrics"]["out_of_sample"], "out_of_sample", status, total, p_oos, bar))
            options_windows, intraday_windows = [], []
            for window, key in (("in_sample", "in_sample"), ("out_of_sample", "out_of_sample")):
                if family == "options":
                    c = r[f"cycles_{key}"]
                    options_windows.append(schemas.OptionsRuleWindow(
                        window=window, n_trades=int(c.get("n_cycles", 0)), win_rate_pct=_finite(c.get("win_rate_pct")), total_net_profit=_finite(c.get("total_net_pnl")),
                        worst_trade=_finite(c.get("worst_cycle")), total_net_profit_without_worst_trade=_finite(c.get("total_net_pnl_without_worst_cycle")),
                        costs_paid=_finite(c.get("costs_paid"))))
                else:
                    t = r[f"trades_{key}"]
                    intraday_windows.append(schemas.IntradayRuleWindow(
                        window=window, n_trades=int(t.get("n_trades", 0)), trades_per_day=_finite(t.get("trades_per_day")), mean_gross_pct=_finite(t.get("mean_gross_pct")),
                        mean_cost_pct=_finite(t.get("mean_cost_pct")), mean_net_pct=_finite(t.get("mean_net_pct")), bar_pct=_finite(t.get("bar_pct")),
                        win_rate_pct=_finite(t.get("win_rate_pct"))))
            rules.append(schemas.OtherRule(id=rule_id, name=r["name"], family=family, harness_status=status, strategy=strategy,
                                           options_windows=options_windows, intraday_windows=intraday_windows))
    return schemas.OtherRulesResponse(generated_at=min(stamps), ledger_total_at_generation=min(totals), ledger_total_now=now,
                                      is_stale=(now is not None and any(t != now for t in totals)), rules=rules)


@api.get("/golive", response_model=schemas.GoLiveResponse,
         summary="Each paper-traded rule against the go-live gates (research/golive_gates.py). Display only: it unlocks nothing and places no order.")
def golive():
    raw = store.load_golive_raw()
    amendment = [g for g in raw["project_gates"] if g["gate"].startswith("Owner's written amendment")]
    locked = not (len(amendment) == 1 and amendment[0]["status"] == "MET")             # anything but a clear MET keeps it locked (fails closed)
    return schemas.GoLiveResponse(generated_at=raw["generated_at"], execution_locked=locked, thresholds=raw["thresholds"], project_gates=raw["project_gates"],
                                  rules=[schemas.GoLiveRule(**{k: r[k] for k in ("id", "name", "kind", "days", "gate_days", "n_trades", "min_trades", "eligible", "unmet", "gates")})
                                         for r in raw["rules"]], note=raw["note"])


@api.get("/advisory/forward", response_model=schemas.AdvisoryForwardResponse,
         summary="The three advisory profiles run forward on paper (research/advisory_forward.py): return against the Nifty 50 ETF, no early verdict.")
def advisory_forward():
    raw = store.load_advisory_forward_raw()
    return schemas.AdvisoryForwardResponse(
        generated_at=raw["generated_at"], start=raw["start"], first_counted_day=raw["first_counted_day"],
        days_needed_for_verdict=int(raw["min_days_for_sharpe"]), disclaimer=raw["disclaimer"], benchmark=raw["benchmark"],
        profiles=[schemas.AdvisoryForwardProfile(**p) for p in raw["profiles"]])


REBALANCE_BAND_PCT = 1.0       # an asset within 1% of the whole portfolio from its target is left alone


@api.get("/advisory/rebalance", response_model=schemas.RebalanceResponse,
         summary="Current holdings in, buy/sell/hold list out: what to change to reach a profile's recommended mix. Not an order.")
def advisory_rebalance(profile: str = Query(..., description="Profile id, e.g. moderate."),
                       holdings: str = Query(..., description="Comma-separated asset_id:rupees, e.g. equity_large:200000,gold:50000,cash:10000.")):
    # Same labelled exception as /advisory/basket: this is arithmetic on the user's own amounts and the stored weights
    # and prices (a unit conversion), not a metric. Nothing is estimated, fitted or forecast.
    raw = store.load_advisory_raw()
    p = next((x for x in raw["profiles"] if x["id"] == profile), None)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile '{profile}'. Choose one of: {', '.join(x['id'] for x in raw['profiles'])}.")
    by_id = {a["id"]: a for a in raw["assets"]}
    current = {k: 0.0 for k in by_id}
    for part in holdings.split(","):
        key, _, value = part.strip().partition(":")
        try:
            amount = float(value)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"'{part}' is not asset_id:rupees.")
        if key not in current:
            raise HTTPException(status_code=422, detail=f"Unknown asset '{key}'. Use: {', '.join(current)}.")
        if not math.isfinite(amount) or amount < 0 or amount > 1_000_000_000:      # 'nan' parses as a float and slips past every comparison
            raise HTTPException(status_code=422, detail=f"The amount for {key} must be between 0 and 100 crore rupees.")
        current[key] += amount
    total = sum(current.values())
    if total < 10_000:
        raise HTTPException(status_code=422, detail="The holdings add up to less than 10,000 rupees; enter at least that much.")
    weight_sum = sum(w["weight_pct"] for w in p["allocation"])           # the stored weights are rounded to 2 decimals and can add to 100.01
    target_pct = {w["asset_id"]: w["weight_pct"] / weight_sum * 100.0 for w in p["allocation"]}
    cost_pct = raw["rule"]["cost_pct_per_side"]
    work = {}                                                          # asset id -> the plan for it, adjusted below until it can be paid for
    for aid, a in by_id.items():
        target = total * target_pct.get(aid, 0.0) / 100.0
        diff = target - current[aid]
        price, units, action, move = a.get("last_price"), None, "HOLD", 0.0
        if aid != "cash" and price and abs(diff) > total * REBALANCE_BAND_PCT / 100.0:
            action = "BUY" if diff > 0 else "SELL"
            units = int(abs(diff) / price * 1_000_000) / 1_000_000 if aid == "crypto" else float(int(abs(diff) // price))
            move = units * price
            if units == 0:
                action, units, move = "HOLD", None, 0.0
        work[aid] = {"target": target, "price": price, "units": units, "action": action, "move": move}

    def cash_after_trades() -> float:
        sells = sum(w["move"] for w in work.values() if w["action"] == "SELL")
        buys = sum(w["move"] for w in work.values() if w["action"] == "BUY")
        return current["cash"] + sells - buys - (sells + buys) * cost_pct / 100.0

    # A plan has to be payable: the purchases come from your cash and the sales, after costs. Assets inside the drift band are
    # not sold, and units are rounded down, so the first draft can ask for more than you would have. Cut the purchases back
    # (rounded down again) until it is affordable, and say so.
    scaled_back = False
    for _ in range(50):
        short = -cash_after_trades()
        buys = [(aid, w) for aid, w in work.items() if w["action"] == "BUY"]
        if short <= 0 or not buys:
            break
        scaled_back = True
        total_buys = sum(w["move"] for _, w in buys)
        scale = max(0.0, 1.0 - short * 1.02 / total_buys)              # a little extra, so the next pass lands on the right side
        for aid, w in buys:
            w["units"] = int(w["units"] * scale * 1_000_000) / 1_000_000 if aid == "crypto" else float(int(w["units"] * scale))
            w["move"] = w["units"] * w["price"]
            if w["units"] == 0:
                w["action"], w["units"], w["move"] = "HOLD", None, 0.0
    traded = sum(w["move"] for w in work.values())
    lines = [schemas.RebalanceLine(
        asset_id=aid, name=by_id[aid]["name"], ticker=by_id[aid].get("ticker"), current_rupees=round(current[aid], 2),
        current_pct=round(current[aid] / total * 100.0, 2), target_pct=round(target_pct.get(aid, 0.0), 2),
        target_rupees=round(w["target"], 2), action=w["action"], rupees_to_trade=round(w["move"], 2), units=w["units"], price=w["price"])
        for aid, w in work.items()]
    notes = [f"An asset within {REBALANCE_BAND_PCT:g}% of the whole portfolio from its target is left alone, so small drifts cost nothing.",
             "The rule itself rebalances every 21 trading days; trading more often than that only adds cost.",
             "Prices are the last close, not live quotes, and units are rounded down. Taxes, brokerage on your own plan and the spread are not included.",
             "This is a list to think with. This project places no orders."]
    if scaled_back:
        notes.insert(0, "Purchases were cut back a little so the list can be paid for from your cash and the sales after costs; the mix lands slightly short of the target.")
    return schemas.RebalanceResponse(
        profile_id=p["id"], profile_name=p["name"], recommended_on=p["recommended_on"], total=round(total, 2), band_pct=REBALANCE_BAND_PCT,
        lines=lines, estimated_cost=round(traded * cost_pct / 100.0, 2), cash_after=round(cash_after_trades(), 2), notes=notes)


@api.get("/advisory/basket", response_model=schemas.BasketResponse,
         summary="An indicative shopping list: the recommended weights of a profile turned into rupees and whole units for a given amount. Not an order.")
def advisory_basket(profile: str = Query(..., description="Profile id, e.g. moderate."),
                    amount: float = Query(..., ge=10_000, le=1_000_000_000, description="Rupees to invest.")):
    # The one place this file does arithmetic, and it is a unit conversion, not a financial metric: the user's amount
    # times the stored weights, divided by the stored last close. Nothing is estimated, fitted or forecast.
    raw = store.load_advisory_raw()
    p = next((x for x in raw["profiles"] if x["id"] == profile), None)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown profile '{profile}'. Choose one of: {', '.join(x['id'] for x in raw['profiles'])}.")
    by_id = {a["id"]: a for a in raw["assets"]}
    lines, spent = [], 0.0
    weight_sum = sum(w["weight_pct"] for w in p["allocation"])           # the stored weights are rounded to 2 decimals and can add to 100.01
    for w in p["allocation"]:
        a = by_id[w["asset_id"]]
        rupees = amount * w["weight_pct"] / weight_sum
        price, units, used = a.get("last_price"), None, 0.0
        if w["asset_id"] == "cash" or not price:
            used = rupees if w["asset_id"] == "cash" else 0.0
        elif w["asset_id"] == "crypto":
            units = int(rupees / price * 1_000_000) / 1_000_000   # Bitcoin can be bought in fractions (rounded down)
            used = units * price
        else:
            units = float(int(rupees // price))          # exchange-traded funds trade in whole units
            used = units * price
        if w["asset_id"] != "cash":
            spent += used
        lines.append(schemas.BasketLine(asset_id=w["asset_id"], name=a["name"], ticker=a.get("ticker"), weight_pct=w["weight_pct"],
                                        rupees=round(rupees, 2), price=price, price_date=a.get("price_date"), units=units,
                                        rupees_used=round(used, 2)))
    return schemas.BasketResponse(
        profile_id=p["id"], profile_name=p["name"], amount=amount, recommended_on=p["recommended_on"], lines=lines,
        cash_left=round(amount - spent, 2),             # the cash weight plus whatever could not buy a whole unit
        notes=["Prices are the last close in the price file, not live quotes; the price when you act will differ, so units are approximate.",
               "Brokerage, taxes, the bid-ask spread and any fund expense ratio are not included.",
               "Bitcoin is not traded on the NSE; it is shown as a fraction of one coin, priced in rupees from a market-data feed.",
               "This is a list to think with. This project places no orders."])


# A price file older than this is "stale": the writer polls every 10 s while the market is open and every
# 5 minutes otherwise, so these leave generous room before the page warns that the feed has stopped.
LIVE_STALE_OPEN_SECONDS = 60
LIVE_STALE_OTHER_SECONDS = 900


@api.get("/live-quotes", response_model=schemas.LiveQuotesResponse,
         summary="Near-live prices of the stocks the paper books hold (a display; written by research/live_quotes.py).")
def live_quotes():
    raw = store.load_live_quotes_raw()
    if raw is None:
        return schemas.LiveQuotesResponse(
            reason="The live price writer has not run yet. Start it from the project root with: "
                   "python research/live_quotes.py --loop")
    age = int((datetime.now(timezone.utc) - datetime.strptime(raw["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=timezone.utc)).total_seconds())
    limit = LIVE_STALE_OPEN_SECONDS if raw["market_status"] == "open" else LIVE_STALE_OTHER_SECONDS
    return schemas.LiveQuotesResponse(
        generated_at=raw["generated_at"], age_seconds=age, is_stale=age > limit, market_status=raw["market_status"],
        market_note=raw["market_note"], available=raw["available"], reason=raw["reason"], n_requested=raw["n_requested"],
        quotes=[schemas.LiveQuote(**q) for q in raw["quotes"]])


@api.get("/forward-test", response_model=schemas.ForwardResponse,
         summary="The pre-registered forward paper-trade log (FORWARD_TEST.md).")
def forward_test():
    return schemas.ForwardResponse(rows=[schemas.ForwardRow(**r) for r in store.load_forward_rows()])


app.include_router(api)


# --- serving the built frontend ---------------------------------------------------------
# After `npm run build` the UI is plain files in webapp/frontend/dist. Serving them from this
# same app means ONE process and ONE port run everything: the browser's request for the page and
# its requests for /api/* go to the same place, so there is no proxy and no CORS at all.
#
# It is deliberately the LAST route, so /api/*, /docs and /openapi.json are matched first.
# Any other path that is not a real file gets index.html, because pages such as
# /stock/RELIANCE are routed by the React app in the browser, not by files on disk.

def _dist_dir() -> Path:
    return Path(os.environ.get("WEBAPP_FRONTEND_DIST", Path(__file__).resolve().parents[1] / "frontend" / "dist"))


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        # an unknown API route must be a JSON 404, never the web page
        return JSONResponse(status_code=404, content={"detail": f"No such API route: /{path}"})
    dist = _dist_dir().resolve()
    index = dist / "index.html"
    if not index.is_file():
        return JSONResponse(status_code=404, content={
            "detail": "The web UI has not been built. From webapp/frontend run: npm install && npm run build "
                      "(or start everything with: python run_webapp.py)"})
    candidate = (dist / path).resolve()
    # Serve a real file only if it really lives inside dist (blocks ../ traversal); otherwise
    # fall back to the app shell.
    # The app shell must always be re-checked, or a browser keeps showing yesterday's page after a rebuild. Files under /assets
    # have a content hash in their name, so they can never change and may be kept for a year.
    revalidate = {"Cache-Control": "no-cache"}
    if path and candidate.is_file() and candidate.is_relative_to(dist):
        hashed = path.startswith("assets/")
        return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"} if hashed else revalidate)
    return FileResponse(index, headers=revalidate)
