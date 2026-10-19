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
    arithmetic on financial values.
"""

import os
from datetime import datetime, timezone
from bisect import bisect_left, bisect_right
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

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
        snapshot_generated_at=prov.generated_at if prov else None,
        git_commit=prov.git_commit if prov else None, git_dirty=prov.git_dirty if prov else None,
        ledger_total_now=now, snapshot_ledger_total=prov.ledger_total_at_snapshot if prov else None,
        snapshot_stale=(now != prov.ledger_total_at_snapshot) if (prov and ledger) else None)


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
    return data.model_copy(update={"rows": rows})


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
        last_date=row.last_date, last_close=row.last_close, quality=quality, results=results, markers=markers,
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
            exposure=b.get("exposure"), holdings=b.get("holdings", []), pending=b.get("pending", []),
            notes=b.get("notes", [])))
    return schemas.ForwardBooksResponse(generated_at=raw["generated_at"], start=raw["start"],
                                        first_counted_day=raw["first_counted_day"], books=books)


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
    if path and candidate.is_file() and candidate.is_relative_to(dist):
        return FileResponse(candidate)
    return FileResponse(index)
