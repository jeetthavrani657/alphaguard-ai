"""
research/forward_books.py

Forward paper trading for the strategies whose results were the closest to
interesting. Each "book" is a frozen strategy configuration (FORWARD_BOOKS.md)
run on data that did not exist when it was frozen. Research only: it logs what a
book WOULD have done; it places no orders and connects to no broker.

Same discipline as research/forward_log.py, which this complements (that one is
the frozen dip-buying rule and is not touched):
  * Everything is recomputed from raw prices with the same engine, costs and
    benchmark as the backtests, so the report is idempotent: running it twice on
    the same data gives the same answer.
  * No book is added without being counted. The first two were already in the
    ledger when frozen; the quality + value book was registered later
    (FUNDAMENTALS_PREREG.md) and counted when it was. This only collects
    out-of-time evidence for them.
  * Nothing is judged early. Sharpe is withheld until MIN_DAYS_FOR_SHARPE
    trading days of forward data exist; before that the numbers are monitoring.

Outputs (both under reports/output/):
    forward_books.csv          one row per (book, data date): the history of the
                               numbers, so a vendor re-adjustment would show
    forward_books_latest.json  the full current picture per book (series, open
                               positions, pending signals) for the web app

    python research/forward_books.py
"""

import contextlib
import io
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import buy_and_hold
import config
import fundamentals_snapshot
import ma_crossover
import quality_value
from liquidity_costs import build_slippage_map
from metrics import drawdown_series_pct, exposure_series_pct, growth_of_100, non_cash_exposure_series_pct
from portfolio_backtest import _eligible_symbols
from run_momentum_strategy import _run_window, build_window_inputs
from universe import load_universe, run_strategy_on_universe

# ---- FROZEN in FORWARD_BOOKS.md (2026-10-16). Do not edit. ----------------------------------
FORWARD_START = "2026-10-16"          # engine window start (freeze day)
FIRST_COUNTED_DAY = "2026-10-19"      # first session after the freeze-day close
MIN_DAYS_FOR_SHARPE = 252             # no Sharpe, and no verdict, before a year of forward data
HISTORY_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "forward_books.csv")
LATEST_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "forward_books_latest.json")

BOOKS = [
    {
        "id": "momentum_nifty50",
        "name": "Cross-sectional momentum 12-1, top 10, monthly",
        "kind": "portfolio", "universe": "nifty50",
        "params": {"lookback_days": 252, "skip_days": 21, "top_n": 10},
        "rationale": "Stocks that outperformed peers over 9-12 months keep outperforming because the market underreacts.",
        "why_forward_tested": "Beat buy-and-hold out-of-sample (Sharpe 1.41 vs 1.34) but missed its own bar (p 0.00051 vs "
                              "0.000245) and sat below the pre-set 90th percentile of random stock selection.",
    },
    {
        "id": "ma_crossover_smallcap250",
        "name": "MA crossover 50/200 on Smallcap 250",
        "kind": "per_symbol", "universe": "smallcap250", "strategy": "ma_crossover",
        "params": dict(config.MA_CROSSOVER_PARAMS), "liquidity_costs": True,
        "rationale": "Once a trend is established (fast MA above slow MA), price is more likely to continue than reverse.",
        "why_forward_tested": "The only configuration to clear the cumulative bar out-of-sample (by a hair), and only out-of-sample; "
                              "the zero-skill test shows its Sharpe is explained by partial exposure, not timing.",
    },
    {
        # Registered 2026-10-16 in FUNDAMENTALS_PREREG.md, AFTER the two books above (their document is frozen and
        # untouched). This one IS a new hypothesis and was counted in the ledger when it was registered (204 -> 205).
        "id": "quality_value_nifty50",
        "name": "Quality + value (ROE and earnings yield), top 10, yearly",
        "kind": "fundamental", "universe": "nifty50",
        "params": {"top_n": quality_value.TOP_N},
        # this book's own pre-registered verdict gate (the older two use the 252 days in FORWARD_BOOKS.md)
        "verdict_days": 504, "verdict_note": "and two completed June rebalances (2027 and 2028)",
        "criteria_document": "FUNDAMENTALS_PREREG.md",
        "rationale": "Companies that earn high returns on their equity while trading at a low price relative to those earnings "
                     "have historically beaten the market; the two measures guard against each other's traps.",
        "why_forward_tested": "Never backtested: only ~3 usable annual cross-sections exist in free data, too few to test anything. "
                              "Registered as a forward book so the evidence can only come from data that does not exist yet.",
    },
]
STRATEGY_MODULES = {"ma_crossover": ma_crossover}
UNIVERSES = {
    "nifty50": lambda: config.UNIVERSE,
    "midcap150": lambda: config.MIDCAP150_UNIVERSE,
    "smallcap250": lambda: config.SMALLCAP250_UNIVERSE,
}


# --- helpers that only reshape engine output (no finance in here) ------------------------------

def _series(s: pd.Series, nd: int = 3) -> dict:
    s = s.dropna()
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), nd) for v in s.values]}


def _num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if f != f or f in (float("inf"), float("-inf")) else f


def _pending_per_symbol(universe_data: dict, module, params: dict) -> list:
    """What the rule would do at the NEXT open: a signal that changed on the last bar."""
    out = []
    for ticker, entry in universe_data.items():
        try:
            sig = module.generate_signals(entry["df"], **params)
        except AssertionError:
            continue                                   # too little history for this rule: cannot trade it yet
        if len(sig) < 2 or pd.isna(sig.iloc[-1]):
            continue
        if sig.iloc[-1] == 1.0 and sig.iloc[-2] != 1.0:
            out.append({"symbol": ticker.replace(".NS", ""), "action": "buy at next open"})
        elif sig.iloc[-1] == 0.0 and sig.iloc[-2] == 1.0:
            out.append({"symbol": ticker.replace(".NS", ""), "action": "sell at next open"})
    return out


def _order_row(date, symbol: str, side: str, shares, price, costs) -> dict:
    return {"date": pd.Timestamp(date).strftime("%Y-%m-%d"), "symbol": symbol.replace(".NS", ""), "side": side.upper(),
            "shares": int(shares), "price": round(float(price), 2), "costs": None if costs is None else round(float(costs), 2)}


def _orders_per_symbol(run: dict) -> list:
    """Every simulated fill of a per-stock book from the first countable day on: closed trades (a buy and a sell) and
    the entries of positions still open. A fill happens at the open after the signal; nothing is sent anywhere."""
    out = []
    first = pd.Timestamp(FIRST_COUNTED_DAY)
    log = run["pooled_trade_log"]
    if len(log):
        for t in log.itertuples():
            if t.entry_date >= first:
                out.append(_order_row(t.entry_date, t.symbol, "buy", t.quantity, t.entry_price, None))
            if t.exit_date >= first:
                out.append(_order_row(t.exit_date, t.symbol, "sell", t.quantity, t.exit_price, None))
    for ticker, r in run["per_symbol"].items():
        op = r["open_position_at_end"]
        if op is not None and op["entry_date"] >= first:
            out.append(_order_row(op["entry_date"], ticker, "buy", op["quantity"], op["entry_price"], op["buy_costs_total"]))
    return out


def _orders_portfolio(trade_log: pd.DataFrame) -> list:
    """Every simulated rebalance leg of a one-account book from the first countable day on, at that day's open."""
    first = pd.Timestamp(FIRST_COUNTED_DAY)
    if trade_log is None or not len(trade_log):
        return []
    return [_order_row(t.date, t.symbol, t.side, t.shares, t.price, t.costs) for t in trade_log.itertuples() if t.date >= first]


def _gate_fields(book: dict) -> dict:
    """Where this book's pass criteria live and when a verdict becomes allowed. Defaults are FORWARD_BOOKS.md's."""
    return {"verdict_gate_days": book.get("verdict_days", MIN_DAYS_FOR_SHARPE), "verdict_note": book.get("verdict_note"),
            "criteria_document": book.get("criteria_document", "FORWARD_BOOKS.md")}


def _report_kind(book: dict) -> str:
    """What the report calls the book. A fundamentals book is a one-account portfolio, and the web app's API
    only knows 'per_symbol' and 'portfolio', so it is reported as 'portfolio' (the dispatch above still sees 'fundamental')."""
    return "portfolio" if book["kind"] == "fundamental" else book["kind"]


def _fundamental_formation_dates(universe_data: dict, last: pd.Timestamp) -> list:
    """
    Freeze day, then the last trading day of each June after it, up to the data end (FUNDAMENTALS_PREREG.md).
    June, because the annual statements to 31 March are assumed public by 29 June (period end + 90 days).
    """
    calendar = sorted(set().union(*(e["df"].index for e in universe_data.values())))
    dates = [pd.Timestamp(FORWARD_START)]
    for year in range(pd.Timestamp(FORWARD_START).year + 1, last.year + 1):
        june = [d for d in calendar if d.year == year and d.month == 6]
        if june and june[-1] <= last:
            dates.append(june[-1])
    return dates


def _fundamental_weights(universe_data: dict, last: pd.Timestamp) -> pd.DataFrame:
    """Target weights of the quality + value book on every formation date so far, as known on each date (strict)."""
    return quality_value.generate_target_weights(
        universe_data, fundamentals_snapshot.load_snapshot(), fundamentals_snapshot.load_currency(),
        _fundamental_formation_dates(universe_data, last), top_n=quality_value.TOP_N, strict=True)


def _empty_report(book: dict, last: pd.Timestamp, pending: list, note: str, holdings: list | None = None) -> dict:
    return {
        "id": book["id"], "name": book["name"], "kind": _report_kind(book), "universe": book["universe"], **_gate_fields(book),
        "rationale": book["rationale"], "why_forward_tested": book["why_forward_tested"],
        "status": "NOT_STARTED", "data_through": last.strftime("%Y-%m-%d"), "start": FORWARD_START,
        "first_counted_day": FIRST_COUNTED_DAY, "n_trading_days": 0, "sharpe_withheld_until_days": MIN_DAYS_FOR_SHARPE,
        "summary": None, "growth_book": None, "growth_benchmark": None, "drawdown_book": None,
        "drawdown_benchmark": None, "exposure": None, "holdings": holdings or [], "pending": pending, "orders": [], "notes": [note],
    }


def _summary(book_metrics: dict, bench_metrics: dict, n_days: int, n_open: int, n_closed) -> dict:
    gate = n_days >= MIN_DAYS_FOR_SHARPE
    return {
        "return_pct": _num(book_metrics.get("total_return_pct")),
        "benchmark_return_pct": _num(bench_metrics.get("total_return_pct")),
        "max_drawdown_pct": _num(book_metrics.get("max_drawdown_pct")),
        "benchmark_max_drawdown_pct": _num(bench_metrics.get("max_drawdown_pct")),
        "market_exposure_pct": _num(book_metrics.get("market_exposure_pct")),
        "n_open_positions": n_open, "n_closed_trades": n_closed,
        "sharpe": _num(book_metrics.get("sharpe_ratio")) if gate else None,
        "benchmark_sharpe": _num(bench_metrics.get("sharpe_ratio")) if gate else None,
        "sharpe_note": ("" if gate else f"withheld: {n_days} of {MIN_DAYS_FOR_SHARPE} trading days of forward data"),
    }


def build_book_report(book: dict, universe_data: dict) -> dict:
    """One book's full current picture, recomputed from raw prices."""
    last = max(e["df"].index.max() for e in universe_data.values())
    module = STRATEGY_MODULES.get(book.get("strategy"))
    pending = _pending_per_symbol(universe_data, module, book["params"]) if book["kind"] == "per_symbol" else []

    if last < pd.Timestamp(FIRST_COUNTED_DAY):
        note = (f"The first countable session is {FIRST_COUNTED_DAY}; data currently ends {last.date()}. "
                "Nothing to evaluate yet: the clock has started.")
        holdings = None
        if book["kind"] == "fundamental":
            w = _fundamental_weights(universe_data, last).iloc[0]            # the picks frozen on the freeze day
            note += " Frozen picks: " + ", ".join(t.replace(".NS", "") for t in w[w > 0].index) + "."
            holdings = [{"symbol": t.replace(".NS", ""), "target_weight_pct": round(float(v) * 100, 2),
                         "as_of_formation_date": FORWARD_START} for t, v in w[w > 0].sort_values(ascending=False).items()]
        return _empty_report(book, last, pending, note, holdings)

    end = last.strftime("%Y-%m-%d")
    notes = []

    if book["kind"] == "per_symbol":
        slip = build_slippage_map(universe_data, config.START_DATE, config.END_DATE) if book.get("liquidity_costs") else None
        run = run_strategy_on_universe(universe_data, module, book["params"], FORWARD_START, end, verbose=False,
                                       slippage_pct_by_symbol=slip)
        if not run["per_symbol"]:
            return _empty_report(book, last, pending, "No stock could run the rule in the forward window yet.")
        same = {t: universe_data[t] for t in run["per_symbol"]}
        bench = run_strategy_on_universe(same, buy_and_hold, {}, FORWARD_START, end, verbose=False,
                                         slippage_pct_by_symbol=slip)
        curve, bench_curve = run["combined_equity_curve"], bench["combined_equity_curve"]
        initial = config.INITIAL_CAPITAL * run["aggregate_metrics"]["n_symbols_included"]
        bench_initial = config.INITIAL_CAPITAL * bench["aggregate_metrics"]["n_symbols_included"]
        exposure = exposure_series_pct({t: v["position"] for t, v in run["per_symbol"].items()})
        book_metrics, bench_metrics = run["aggregate_metrics"], bench["aggregate_metrics"]
        holdings = []
        for t, r in run["per_symbol"].items():
            op = r["open_position_at_end"]
            if op is not None:
                last_close = float(universe_data[t]["df"]["close"].iloc[-1])
                holdings.append({"symbol": t.replace(".NS", ""), "since": op["entry_date"].strftime("%Y-%m-%d"),
                                 "entry_price": round(float(op["entry_price"]), 2), "last_close": round(last_close, 2)})
        n_open, n_closed = len(holdings), int(len(run["pooled_trade_log"]))
        orders = _orders_per_symbol(run)
        if run["blocked"]:
            notes.append(f"{len(run['blocked'])} stock(s) could not run the rule (data gate or too little history).")
    else:
        if book["kind"] == "fundamental":
            eligible, blocked = _eligible_symbols(universe_data, FORWARD_START, end, override_discontinuity_gate=False)
            weights = _fundamental_weights(eligible, last)                  # ranks only symbols the data gate allows
        else:
            eligible, weights, blocked = build_window_inputs(universe_data, FORWARD_START, end)
        mom = _run_window(eligible, weights, FORWARD_START, end, book["id"], verbose=False)
        curve, bench_curve = mom["result"]["equity_curve"], None
        bench = run_strategy_on_universe(eligible, buy_and_hold, {}, FORWARD_START, end, verbose=False)
        bench_curve = bench["combined_equity_curve"]
        initial = float(config.INITIAL_CAPITAL)                 # one account; the benchmark is one book per stock
        bench_initial = config.INITIAL_CAPITAL * bench["aggregate_metrics"]["n_symbols_included"]
        rb = mom["result"]["rebalance_log"]
        first_exec = rb["execution_date"].min() if len(rb) else None
        exposure = non_cash_exposure_series_pct(curve.index, first_exec)
        book_metrics = dict(mom["metrics"])
        book_metrics["market_exposure_pct"] = mom["exposure_pct"]
        bench_metrics = bench["aggregate_metrics"]
        latest = weights.iloc[-1]
        holdings = [{"symbol": t.replace(".NS", ""), "target_weight_pct": round(float(w) * 100, 2),     # percent here, so no UI has to convert
                     "as_of_formation_date": weights.index[-1].strftime("%Y-%m-%d")}
                    for t, w in latest[latest > 0].sort_values(ascending=False).items()]
        done = rb["formation_date"].max() if len(rb) else None
        if weights.index[-1] <= last and (done is None or weights.index[-1] > done):
            pending = [{"symbol": "(portfolio)", "action": f"rebalance to the {len(holdings)} targets formed "
                                                         f"{weights.index[-1].date()}, at the next open"}]
        n_open, n_closed = len(holdings), None
        orders = _orders_portfolio(mom["result"]["trade_log"])
        notes.append("Holdings shown are the latest formation's targets, executed at the next session's open."
                     + (" Rebalanced once a year, on the last trading day of June." if book["kind"] == "fundamental" else ""))

    # Count only sessions from the first countable day on. The curve also holds the freeze day as its base
    # (day 0, no trade yet), which is not a forward trading day and must not bring the verdict gate closer.
    n_days = int((curve.index >= pd.Timestamp(FIRST_COUNTED_DAY)).sum())
    return {
        "id": book["id"], "name": book["name"], "kind": _report_kind(book), "universe": book["universe"], **_gate_fields(book),
        "rationale": book["rationale"], "why_forward_tested": book["why_forward_tested"],
        "status": "RUNNING", "data_through": last.strftime("%Y-%m-%d"), "start": FORWARD_START,
        "first_counted_day": FIRST_COUNTED_DAY, "n_trading_days": n_days,
        "sharpe_withheld_until_days": MIN_DAYS_FOR_SHARPE,
        "summary": _summary(book_metrics, bench_metrics, n_days, n_open, n_closed),
        # growth of 100: each curve divided by its OWN starting capital (a portfolio is one account,
        # the benchmark is one account per stock), by the same function the strategy pages use
        "growth_book": _series(growth_of_100(curve, initial)),
        "growth_benchmark": _series(growth_of_100(bench_curve, bench_initial)),
        "drawdown_book": _series(drawdown_series_pct(curve)),
        "drawdown_benchmark": _series(drawdown_series_pct(bench_curve)),
        "exposure": _series(exposure, 2),
        "holdings": holdings, "pending": pending, "orders": sorted(orders, key=lambda o: (o["date"], o["symbol"]), reverse=True), "notes": notes,
    }


# --- persistence ---------------------------------------------------------------------------------

def append_history(report: dict, path: str = HISTORY_PATH) -> None:
    s = report["summary"] or {}
    row = pd.DataFrame([{
        "run_date": pd.Timestamp.today().strftime("%Y-%m-%d"), "book_id": report["id"],
        "data_through": report["data_through"], "status": report["status"], "n_trading_days": report["n_trading_days"],
        "return_pct": s.get("return_pct"), "benchmark_return_pct": s.get("benchmark_return_pct"),
        "max_drawdown_pct": s.get("max_drawdown_pct"), "n_open_positions": s.get("n_open_positions"),
    }])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        old = pd.read_csv(path)
        # one row per (book, data date): re-running on the same data replaces, not duplicates
        keep = ~((old["book_id"] == report["id"]) & (old["data_through"] == report["data_through"]))
        row = pd.concat([old[keep], row], ignore_index=True)
    row.to_csv(path, index=False)


def write_latest(reports: list, path: str = LATEST_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "start": FORWARD_START,
               "first_counted_day": FIRST_COUNTED_DAY, "min_days_for_sharpe": MIN_DAYS_FOR_SHARPE, "books": reports}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False)           # NaN would be invalid JSON: fail loudly, never write it
    os.replace(tmp, path)


def _use_upstox_for_the_newest_sessions() -> None:
    """
    Let the loader take sessions Yahoo has not priced yet from the read-only Upstox client (data/upstox_tail.py), so a day
    Yahoo publishes late does not hold the books back. The candle endpoints need no token; on a normal evening it makes no request.
    """
    import loader
    import upstox_tail
    if upstox_tail.available():
        loader.set_tail_source(upstox_tail.UpstoxTail())
        print("[books] Upstox is on for sessions Yahoo has not priced yet (read-only market data)")
    else:
        print("[books] Upstox is off: using Yahoo alone")


def main() -> int:
    _use_upstox_for_the_newest_sessions()
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    cache = {}
    reports = []
    for book in BOOKS:
        key = book["universe"]
        if key not in cache:
            with contextlib.redirect_stdout(io.StringIO()):        # the validator prints a long report per stock
                cache[key], failed = load_universe(UNIVERSES[key](), config.START_DATE, today, verbose=False)
            if failed:
                print(f"[books] {len(failed)} {key} symbol(s) failed to load and were skipped")
        rep = build_book_report(book, cache[key])
        reports.append(rep)
        append_history(rep)
        s = rep["summary"]
        print(f"[books] {book['id']}: {rep['status']}, data through {rep['data_through']}, {rep['n_trading_days']} forward days"
              + (f", return {s['return_pct']:+.2f}% vs buy&hold {s['benchmark_return_pct']:+.2f}%, "
                 f"drawdown {s['max_drawdown_pct']:.1f}%" if s else "")
              + (f", {len(rep['pending'])} pending action(s)" if rep["pending"] else ""))
        for n in rep["notes"]:
            print(f"[books]   {n}")
    write_latest(reports)
    print(f"[books] wrote {LATEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
