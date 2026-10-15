"""
webapp/backend/snapshot.py

THE ONLY PLACE THE WEB APP RUNS STRATEGIES. A terminal command, run by you:

    python -m webapp.backend.snapshot                 # everything (slow: ~20-30 min)
    python -m webapp.backend.snapshot --only ma_crossover_nifty50,rsi_reversion_nifty50
    python -m webapp.backend.snapshot --list

It calls the existing library exactly as the research scripts and the
Streamlit app do -- run_strategy_on_universe, the portfolio engine, the
validator's reports, the harness -- and writes the results to JSON files
under webapp/snapshots/. The API then only reads those files.

Why a separate step, rather than the API computing on demand:
  * The browser can never trigger a strategy run (your constraint 3 holds
    by construction -- there is no code path from an HTTP request to the
    engine, not merely a rule against using one).
  * Every number shown is stamped with when, from which code version, and
    against which hypothesis total it was produced.
  * Pages load instantly: no 76-second backtest behind a click.

What this file deliberately does NOT contain: any financial calculation.
Metrics come from engine/metrics.py via compute_metrics (inside the
library's own aggregate_metrics), statuses from research/harness.py's
classify_results(). The only arithmetic here is presentation: NaN -> null,
dates -> text, a fraction -> percent for discontinuity magnitudes.
"""

import argparse
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(ROOT, _sub))
sys.path.insert(0, ROOT)

import pandas as pd

import buy_and_hold
import config
import dip_target
import harness
import ma_crossover
import rsi_reversion
from liquidity_costs import build_slippage_map
from metrics import drawdown_series_pct, exposure_series_pct, growth_of_100, non_cash_exposure_series_pct
from run_momentum_strategy import _run_window, build_window_inputs
from universe import load_universe, per_symbol_comparison_table, run_strategy_on_universe

from webapp.backend import schemas

DEFAULT_OUT = os.path.join(ROOT, "webapp", "snapshots")

UNIVERSES = {
    "nifty50": lambda: config.UNIVERSE,
    "midcap150": lambda: config.MIDCAP150_UNIVERSE,
    "smallcap250": lambda: config.SMALLCAP250_UNIVERSE,
}

# One entry per registered strategy configuration. Parameters come from
# config.py or are the values fixed in advance in the research scripts
# (research/run_dip_target_strategy.py, run_dip_uptrend_strategy.py).
RECIPES = [
    dict(id="ma_crossover_nifty50", name="MA crossover 50/200", family="Trend following",
         universe="nifty50", kind="per_symbol", module=ma_crossover, params=dict(config.MA_CROSSOVER_PARAMS),
         liquidity_costs=False,
         rationale="Once a trend is established (fast MA above slow MA), price is more likely to continue than reverse."),
    dict(id="ma_crossover_midcap150", name="MA crossover 50/200", family="Trend following",
         universe="midcap150", kind="per_symbol", module=ma_crossover, params=dict(config.MA_CROSSOVER_PARAMS),
         liquidity_costs=True,
         rationale="Same rule, unchanged, as a control comparison of the universe (not a new hypothesis about mid caps)."),
    dict(id="ma_crossover_smallcap250", name="MA crossover 50/200", family="Trend following",
         universe="smallcap250", kind="per_symbol", module=ma_crossover, params=dict(config.MA_CROSSOVER_PARAMS),
         liquidity_costs=True,
         rationale="Same rule, unchanged, as a control comparison of the universe (not a new hypothesis about small caps)."),
    dict(id="rsi_reversion_nifty50", name="RSI reversion 14/30/50", family="Mean reversion",
         universe="nifty50", kind="per_symbol", module=rsi_reversion, params=dict(config.RSI_REVERSION_PARAMS),
         liquidity_costs=False,
         rationale="After a sharp short-term move, prices tend to partially revert as the overreaction fades."),
    dict(id="momentum_nifty50", name="Cross-sectional momentum 12-1, top 10, monthly", family="Momentum",
         universe="nifty50", kind="portfolio", module=None, params={"lookback_days": 252, "skip_days": 21, "top_n": 10},
         liquidity_costs=False,
         rationale="Stocks that outperformed peers over 9-12 months keep outperforming because the market underreacts."),
    dict(id="dip_a_nifty50", name="Dip buy +3% target, no stop", family="Dip buying",
         universe="nifty50", kind="per_symbol", module=dip_target,
         params={"take_profit": 0.03, "stop_loss": None}, liquidity_costs=False,
         rationale="Oversold bounce with a small profit target and no stop-loss (built to maximize win rate)."),
    dict(id="dip_b_nifty50", name="Dip buy +3% target, 10% stop", family="Dip buying",
         universe="nifty50", kind="per_symbol", module=dip_target,
         params={"take_profit": 0.03, "stop_loss": 0.10}, liquidity_costs=False,
         rationale="The same dip rule with losses realized by a 10% stop."),
    dict(id="dip_uptrend_nifty50", name="Dip in uptrend +4% / -12% stop / 60d", family="Dip buying",
         universe="nifty50", kind="per_symbol", module=dip_target,
         params={"oversold": 30, "take_profit": 0.04, "stop_loss": 0.12, "trend_window": 200, "max_hold_days": 60},
         liquidity_costs=False,
         rationale="Pullbacks in stocks above their 200-day average retrace; a stop and time limit realize every loser."),
]

NOTES = {
    "per_symbol": [],
    "portfolio": [
        "A rebalanced portfolio has no per-trade win rate or profit factor; those are null by design.",
        "market_exposure_pct is the share of days capital was deployed (cash before the first rebalance counts as not invested).",
        "Trading activity is shown as executions (buy/sell legs) and rebalances, not closed trades.",
    ],
}


# --- tiny presentation helpers (no finance in here) ----------------------------

def _clean(x):
    """NaN / infinity / None -> None; anything numeric -> a plain float. JSON has no NaN."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _int(x):
    v = _clean(x)
    return None if v is None else int(round(v))


def _iso(d) -> str:
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def _windows() -> dict:
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return {"in_sample": (config.START_DATE, config.IN_SAMPLE_END_DATE),
            "out_of_sample": (oos_start, config.END_DATE)}


def _git_state() -> tuple:
    """(short commit, dirty?). 'Dirty' ignores generated outputs so a snapshot doesn't make itself look modified."""
    def run(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    try:
        commit = run("rev-parse", "--short", "HEAD")
        if commit.returncode != 0:
            return None, None
        status = run("status", "--porcelain", "--", ".", ":(exclude)webapp/snapshots",
                     ":(exclude)reports/output/forward_snapshots.csv", ":(exclude)reports/output/forward_last_run.log")
        return commit.stdout.strip(), bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None, None


def _write_json(path: str, model) -> None:
    """Validated, atomic write: never leaves a half-written file for the API to trip on."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(model.model_dump_json(indent=None))
    os.replace(tmp, path)


# --- running the library -------------------------------------------------------

_universe_cache: dict = {}


def get_universe(key: str) -> dict:
    if key not in _universe_cache:
        buffer = io.StringIO()  # the validator prints a long report per stock; keep the console readable
        with contextlib.redirect_stdout(buffer):
            data, failed = load_universe(UNIVERSES[key](), config.START_DATE, config.END_DATE, verbose=False)
        print(f"    loaded {key}: {len(data)} symbols" + (f" ({len(failed)} failed)" if failed else ""))
        _universe_cache[key] = data
    return _universe_cache[key]


_slippage_cache: dict = {}


def get_slippage(key: str):
    """Liquidity-adjusted slippage map for Midcap/Smallcap (as the research scripts use); None for Nifty 50."""
    if key == "nifty50":
        return None
    if key not in _slippage_cache:
        _slippage_cache[key] = build_slippage_map(get_universe(key), config.START_DATE, config.END_DATE)
    return _slippage_cache[key]


def _run_per_symbol(universe_data, recipe, start, end, slippage_map):
    run = run_strategy_on_universe(universe_data, recipe["module"], recipe["params"], start, end,
                                   verbose=False, slippage_pct_by_symbol=slippage_map)
    if not run["per_symbol"]:
        raise RuntimeError(f"{recipe['id']}: no symbol could run in {start}..{end}")
    same = {t: universe_data[t] for t in run["per_symbol"]}   # benchmark on exactly the stocks the strategy ran on
    bh = run_strategy_on_universe(same, buy_and_hold, {}, start, end, verbose=False,
                                  slippage_pct_by_symbol=slippage_map)
    return dict(metrics=run["aggregate_metrics"], bench=bh["aggregate_metrics"],
                curve=run["combined_equity_curve"], bench_curve=bh["combined_equity_curve"],
                trades=run["pooled_trade_log"], executions=None, rebalances=None,
                # each stock's own metrics, straight from the engine's existing per-symbol table
                table=per_symbol_comparison_table(run), bench_table=per_symbol_comparison_table(bh),
                blocked=dict(run["blocked"]),
                # each curve is the sum of one INITIAL_CAPITAL book per stock it ran on
                init_strategy=config.INITIAL_CAPITAL * run["aggregate_metrics"]["n_symbols_included"],
                init_bench=config.INITIAL_CAPITAL * bh["aggregate_metrics"]["n_symbols_included"],
                exposure=exposure_series_pct({t: v["position"] for t, v in run["per_symbol"].items()}),
                exposure_definition="Share of the universe's books that are long on each date (stocks not yet "
                                    "listed are absent, not counted as cash). From engine/metrics.py "
                                    "exposure_series_pct.")


def _run_portfolio(universe_data, start, end):
    eligible, weights, _blocked = build_window_inputs(universe_data, start, end)
    mom = _run_window(eligible, weights, start, end, "momentum", verbose=False)
    bh = run_strategy_on_universe(eligible, buy_and_hold, {}, start, end, verbose=False)
    metrics = dict(mom["metrics"])
    metrics["market_exposure_pct"] = mom["exposure_pct"]       # compute_metrics' own value is meaningless here
    for undefined in ("win_rate_pct", "avg_win_pct", "avg_loss_pct", "profit_factor", "avg_holding_days", "total_trades"):
        metrics[undefined] = None
    metrics["n_symbols_included"] = len(eligible)
    return dict(metrics=metrics, bench=bh["aggregate_metrics"],
                curve=mom["result"]["equity_curve"], bench_curve=bh["combined_equity_curve"],
                trades=None, executions=mom["result"]["trade_log"], rebalances=mom["result"]["rebalance_log"],
                table=None, bench_table=None, blocked={},
                # ONE account for the strategy; the benchmark is one book per stock
                init_strategy=float(config.INITIAL_CAPITAL),
                init_bench=config.INITIAL_CAPITAL * bh["aggregate_metrics"]["n_symbols_included"],
                exposure=non_cash_exposure_series_pct(
                    mom["result"]["equity_curve"].index,
                    mom["result"]["rebalance_log"]["execution_date"].min()
                    if len(mom["result"]["rebalance_log"]) else None),
                exposure_definition="The engine's momentum definition: 0% until the first rebalance executes, "
                                    "100% after. It does not measure how much cash is held once invested. "
                                    "From engine/metrics.py non_cash_exposure_series_pct.")


# --- assembling validated models -----------------------------------------------

def _ratio(kind, value, window, status, total, result=None):
    p = bar = clears = None
    if result is not None and kind == "sharpe":
        p = _clean(result.in_sample_p_value if window == "in_sample" else result.out_of_sample_p_value)
        bar = _clean(result.bonferroni_alpha)
        clears = None if p is None or bar is None else bool(p < bar)
    return schemas.RiskAdjustedRatio(kind=kind, value=_clean(value), window=window, status=status,
                                     as_of_hypotheses=total, p_value=p, bonferroni_bar=bar, clears_bar=clears)


def _window_metrics(m: dict, window: str, status: str, total: int, result=None) -> schemas.WindowMetrics:
    return schemas.WindowMetrics(
        sharpe=_ratio("sharpe", m.get("sharpe_ratio"), window, status, total, result),
        sortino=_ratio("sortino", m.get("sortino_ratio"), window, status, total, result),
        total_return_pct=_clean(m.get("total_return_pct")), cagr_pct=_clean(m.get("cagr_pct")),
        max_drawdown_pct=_clean(m.get("max_drawdown_pct")),
        max_drawdown_duration_days=_clean(m.get("max_drawdown_duration_days")),
        win_rate_pct=_clean(m.get("win_rate_pct")), avg_win_pct=_clean(m.get("avg_win_pct")),
        avg_loss_pct=_clean(m.get("avg_loss_pct")), profit_factor=_clean(m.get("profit_factor")),
        total_trades=_int(m.get("total_trades")), avg_holding_days=_clean(m.get("avg_holding_days")),
        market_exposure_pct=_clean(m.get("market_exposure_pct")), final_equity=_clean(m.get("final_equity")),
        n_symbols_included=_int(m.get("n_symbols_included")),
    )


def _curve(series: pd.Series, nd: int = 2) -> schemas.EquityCurve:
    s = series.dropna()
    return schemas.EquityCurve(dates=[_iso(d) for d in s.index], values=[round(float(v), nd) for v in s.values])


def _closed_trades(df) -> list:
    if df is None or len(df) == 0:
        return []
    return [schemas.ClosedTrade(
        symbol=str(r.symbol).replace(".NS", ""), entry_date=_iso(r.entry_date), exit_date=_iso(r.exit_date),
        entry_price=round(float(r.entry_price), 4), exit_price=round(float(r.exit_price), 4),
        quantity=int(r.quantity), return_pct=round(float(r.return_pct), 4),
        holding_days=int(r.holding_days), total_costs=round(float(r.total_costs), 2))
        for r in df.itertuples()]


def _executions(df) -> list:
    if df is None or len(df) == 0:
        return []
    return [schemas.Execution(date=_iso(r.date), symbol=str(r.symbol).replace(".NS", ""), side=r.side,
                              shares=int(r.shares), price=round(float(r.price), 4), costs=round(float(r.costs), 2))
            for r in df.itertuples()]


def _rebalances(df) -> list:
    if df is None or len(df) == 0:
        return []
    return [schemas.Rebalance(
        formation_date=_iso(r.formation_date), execution_date=_iso(r.execution_date), n_held=int(r.n_held),
        turnover_value=round(float(r.turnover_value), 2),
        portfolio_value_pre_rebalance=round(float(r.portfolio_value_pre_rebalance), 2),
        turnover_pct=round(float(r.turnover_pct), 4)) for r in df.itertuples()]


def build_strategy(recipe: dict, total_now: int, provenance: schemas.Provenance) -> schemas.StrategyFile:
    windows = _windows()
    universe_data = get_universe(recipe["universe"])
    slippage_map = get_slippage(recipe["universe"]) if recipe["liquidity_costs"] else None

    runs = {}
    for window, (start, end) in windows.items():
        t0 = time.time()
        if recipe["kind"] == "portfolio":
            runs[window] = _run_portfolio(universe_data, start, end)
        else:
            runs[window] = _run_per_symbol(universe_data, recipe, start, end, slippage_map)
        print(f"    {window}: {time.time() - t0:.0f}s")

    # Status: the harness's own rules, via the pure function extracted for exactly this use.
    result = harness.evaluate_strategy(
        name=recipe["id"], rationale=recipe["rationale"],
        in_sample_sharpe=runs["in_sample"]["metrics"]["sharpe_ratio"],
        in_sample_n_obs=len(runs["in_sample"]["curve"]),
        out_of_sample_sharpe=runs["out_of_sample"]["metrics"]["sharpe_ratio"],
        out_of_sample_n_obs=len(runs["out_of_sample"]["curve"]))
    summary = harness.classify_results([result], cumulative_total=total_now)
    status = result.status

    infos, data = {}, {}
    for window, (start, end) in windows.items():
        r = runs[window]
        infos[window] = schemas.WindowInfo(
            window=window, start=start, end=end, n_observations=len(r["curve"]),
            strategy=_window_metrics(r["metrics"], window, status, total_now, result),
            benchmark=_window_metrics(r["bench"], window, "BENCHMARK_NOT_A_HYPOTHESIS", total_now, None))
        dd_s, dd_b = drawdown_series_pct(r["curve"]), drawdown_series_pct(r["bench_curve"])
        # Integrity check at generation time: the charted series must reproduce the headline numbers.
        for label, series, headline in (("strategy", dd_s, r["metrics"]["max_drawdown_pct"]),
                                        ("benchmark", dd_b, r["bench"]["max_drawdown_pct"])):
            if abs(series.min() - headline) > 1e-6:
                raise RuntimeError(f"{recipe['id']} {window} {label}: drawdown series minimum {series.min()} "
                                   f"does not match max_drawdown_pct {headline}")
        g_s = growth_of_100(r["curve"], r["init_strategy"])
        g_b = growth_of_100(r["bench_curve"], r["init_bench"])
        for label, series, headline in (("strategy", g_s, r["metrics"]["total_return_pct"]),
                                        ("benchmark", g_b, r["bench"]["total_return_pct"])):
            if abs((series.iloc[-1] - 100) - headline) > 1e-6:
                raise RuntimeError(f"{recipe['id']} {window} {label}: growth-of-100 ends at {series.iloc[-1]} "
                                   f"but total_return_pct is {headline}")
        data[window] = schemas.StoredWindowData(
            growth_strategy=_curve(g_s, 3), growth_benchmark=_curve(g_b, 3),
            equity_strategy=_curve(r["curve"]), equity_benchmark=_curve(r["bench_curve"]),
            drawdown_strategy_pct=_curve(dd_s, 3), drawdown_benchmark_pct=_curve(dd_b, 3),
            exposure_strategy_pct=_curve(r["exposure"], 2), exposure_definition=r["exposure_definition"],
            closed_trades=_closed_trades(r["trades"]), executions=_executions(r["executions"]),
            rebalances=_rebalances(r["rebalances"]))

    notes = list(NOTES[recipe["kind"]])
    if recipe["liquidity_costs"]:
        notes.append("Costs are liquidity-adjusted per symbol (research/liquidity_costs.py), not the flat 0.05% rate.")
        notes.append("The benchmark covers the same stocks the strategy ran on; FINDINGS.md Section 3b's benchmark "
                     "covered every eligible stock, so benchmark figures can differ slightly.")
    if recipe["id"] == "dip_a_nifty50":
        notes.append("win_rate_pct counts CLOSED trades only. This rule never closes a loser, so open positions and "
                     "their unrealized losses are not in it -- see FINDINGS.md Section 3f.")
    if recipe["family"] == "Trend following":
        notes.append("Max drawdown is the smaller number for the strategy than for buy-and-hold, in every window, "
                     "at the cost of return -- see FINDINGS.md Section 7.")

    # Read from the already-computed exposure figures (no arithmetic): idle cash earns nothing in the
    # engine's equity curve (engine/backtest.py has no interest accrual) while Sharpe subtracts the
    # risk-free rate, so a strategy that is rarely invested shows a very negative Sharpe by construction.
    exposures = [infos[w].strategy.market_exposure_pct for w in infos]
    if any(e is not None and e < 25 for e in exposures):
        notes.append("Low market exposure: idle cash earns nothing in the engine's equity curve, while Sharpe "
                     f"subtracts the {config.RISK_FREE_RATE:.1%} risk-free rate. A rarely-invested strategy therefore "
                     "shows a very negative Sharpe by construction -- read it together with total return and exposure.")

    detail = schemas.StrategyDetail(
        id=recipe["id"], name=recipe["name"], family=recipe["family"], universe=recipe["universe"],
        kind=recipe["kind"], params=recipe["params"], rationale=recipe["rationale"], status=status,
        as_of_hypotheses=total_now, stale=False, notes=notes,
        in_sample=infos["in_sample"], out_of_sample=infos["out_of_sample"],
        provenance=provenance.model_copy(update={"bonferroni_bar_at_snapshot": summary["bonferroni_alpha"]}))
    return schemas.StrategyFile(detail=detail, data=data), _build_slices(recipe, runs, status, total_now)


def _slice_ratio(value, window, recipe_id, parent_status, total):
    return schemas.RiskAdjustedRatio(
        kind="sharpe", value=_clean(value), window=window, status="SLICE_OF_POOLED_HYPOTHESIS",
        as_of_hypotheses=total, parent_strategy_id=recipe_id, parent_status=parent_status)


def _build_slices(recipe, runs, parent_status, total):
    """Each stock's own result per window, for per-symbol strategies (None for a portfolio strategy)."""
    if recipe["kind"] != "per_symbol":
        return None
    windows, excluded = {}, {}
    for window, r in runs.items():
        table, bench = r["table"], r["bench_table"]
        windows[window] = {}
        for ticker, row in table.iterrows():
            bench_ret = _clean(bench.loc[ticker, "total_return_pct"]) if ticker in bench.index else None
            windows[window][ticker.replace(".NS", "")] = schemas.SliceMetrics(
                sharpe=_slice_ratio(row.get("sharpe_ratio"), window, recipe["id"], parent_status, total),
                total_return_pct=_clean(row.get("total_return_pct")), cagr_pct=_clean(row.get("cagr_pct")),
                max_drawdown_pct=_clean(row.get("max_drawdown_pct")), win_rate_pct=_clean(row.get("win_rate_pct")),
                total_trades=_int(row.get("total_trades")), market_exposure_pct=_clean(row.get("market_exposure_pct")),
                buy_hold_return_pct=bench_ret)
        excluded[window] = {t.replace(".NS", ""): str(why)[:240] for t, why in r["blocked"].items()}
    return schemas.SymbolSlices(strategy_id=recipe["id"], parent_status=parent_status, as_of_hypotheses=total,
                                windows=windows, excluded=excluded)


def build_data_quality(universes: dict) -> list:
    out = []
    for key, data in universes.items():
        for ticker, entry in data.items():
            df, rep = entry["df"], entry["report"]
            out.append(schemas.SymbolQuality(
                symbol=ticker.replace(".NS", ""), universe=key, rows=int(len(df)),
                first_date=_iso(df.index.min()), last_date=_iso(df.index.max()), usable=bool(rep["usable"]),
                checks=[schemas.QualityCheck(name=c["name"], passed=bool(c["passed"]), affected_rows=int(c["count"]))
                        for c in rep["checks"]],
                discontinuities=[schemas.Discontinuity(
                    date=_iso(d["date"]), magnitude_pct=round(float(d["magnitude"]) * 100, 2),   # fraction -> percent
                    status=str(d["status"]), reason=d.get("reason")) for d in rep["discontinuities"]]))
    return out


def _series(s: pd.Series, nd: int) -> list:
    """Series -> JSON list; NaN -> null (warm-up periods)."""
    return [None if pd.isna(v) else round(float(v), nd) for v in s.values]


def build_symbol_files(universe_key: str, out_dir: str, generated_at: str) -> list:
    """
    Writes symbols/<SYMBOL>.json (prices + indicator series) for every stock in a loaded universe
    and returns its ScreenerRow list. Indicator series are read from the strategy modules'
    own functions (ma_crossover.moving_average, rsi_reversion.rsi) so the line on the chart is,
    by construction, the line the strategy traded on. Buy-and-hold returns come from the engine's
    per-symbol table, same costs as the strategy files use.
    """
    data = get_universe(universe_key)
    slippage_map = get_slippage(universe_key)
    bh = {}
    for window, (start, end) in _windows().items():
        run = run_strategy_on_universe(data, buy_and_hold, {}, start, end, verbose=False,
                                       slippage_pct_by_symbol=slippage_map)
        bh[window] = per_symbol_comparison_table(run) if run["per_symbol"] else pd.DataFrame()

    fast, slow = config.MA_CROSSOVER_PARAMS["fast"], config.MA_CROSSOVER_PARAMS["slow"]
    rsi_period = config.RSI_REVERSION_PARAMS["period"]
    sym_dir = os.path.join(out_dir, "symbols")
    os.makedirs(sym_dir, exist_ok=True)

    rows = []
    for ticker, entry in data.items():
        df, rep = entry["df"], entry["report"]
        sym = ticker.replace(".NS", "")
        close = df["close"]
        # A stock listed days ago has too little history for an RSI at all (the library needs
        # period + 1 closes to seed it and raises otherwise). The indicator is then simply
        # undefined for every date: all null, never a crash and never a made-up value.
        rsi_series = (_series(rsi_reversion.rsi(close, rsi_period), 2)
                      if len(close) > rsi_period else [None] * len(close))
        ind = {f"sma_{fast}": _series(ma_crossover.moving_average(close, fast), 2),
               f"sma_{slow}": _series(ma_crossover.moving_average(close, slow), 2),
               f"rsi_{rsi_period}": rsi_series}
        src = {f"sma_{fast}": "strategies/ma_crossover.py moving_average", f"sma_{slow}": "strategies/ma_crossover.py moving_average",
               f"rsi_{rsi_period}": "strategies/rsi_reversion.py rsi (Wilder smoothing)"}
        ps = schemas.PriceSeries(
            symbol=sym, dates=[_iso(d) for d in df.index], open=_series(df["open"], 2), high=_series(df["high"], 2),
            low=_series(df["low"], 2), close=_series(close, 2), volume=_series(df["volume"], 0),
            indicators=ind, indicator_sources=src)
        _write_json(os.path.join(sym_dir, f"{sym}.json"), ps)

        def bh_val(window, col):
            t = bh[window]
            return _clean(t.loc[ticker, col]) if (len(t) and ticker in t.index) else None

        rows.append(schemas.ScreenerRow(
            symbol=sym, universe=universe_key, sector=config.SECTOR_MAP.get(sym), rows=int(len(df)),
            first_date=_iso(df.index.min()), last_date=_iso(df.index.max()), last_close=round(float(close.iloc[-1]), 2),
            usable=bool(rep["usable"]),
            has_unresolved_discontinuity=any(str(d["status"]) != "GENUINE" for d in rep["discontinuities"]),
            buy_hold_return_in_sample_pct=bh_val("in_sample", "total_return_pct"),
            buy_hold_return_out_of_sample_pct=bh_val("out_of_sample", "total_return_pct"),
            buy_hold_max_drawdown_out_of_sample_pct=bh_val("out_of_sample", "max_drawdown_pct")))
    print(f"    wrote {len(rows)} price files + screener rows for {universe_key}")
    return rows


def manifest_provenance(provs: list) -> schemas.Provenance:
    """
    The provenance the WHOLE snapshot is allowed to claim: that of its OLDEST strategy result.
    A manifest stamped with "now" would be wrong after a --prices-only run (the strategies were
    computed earlier, possibly on older data) and the status strip would overstate freshness.
      generated_at / git_commit / bar : from the oldest strategy file
      data_through, ledger_total      : the minimum across strategies (the weakest link)
      git_dirty                       : true if ANY strategy was produced from uncommitted code
    """
    oldest = min(provs, key=lambda p: p.generated_at)
    known_dirty = [p.git_dirty for p in provs if p.git_dirty is not None]
    return oldest.model_copy(update={
        "data_through": min(p.data_through for p in provs),
        "ledger_total_at_snapshot": min(p.ledger_total_at_snapshot for p in provs),
        "git_dirty": any(known_dirty) if known_dirty else None,
    })


def write_manifest(out_dir: str, known: list) -> schemas.Manifest:
    """Manifest of every strategy file on disk (so partial runs never hide earlier results)."""
    sdir = os.path.join(out_dir, "strategies")
    present = sorted(f[:-5] for f in os.listdir(sdir) if f.endswith(".json") and not f.endswith(".symbols.json"))
    if not present:
        raise RuntimeError(f"No strategy files in {sdir}; run the snapshot command first.")
    ordered = [i for i in known if i in present] + [i for i in present if i not in known]
    provs = [schemas.StrategyFile.model_validate_json(open(os.path.join(sdir, f"{i}.json"), encoding="utf-8").read())
             .detail.provenance for i in ordered]
    manifest = schemas.Manifest(
        provenance=manifest_provenance(provs), strategy_ids=ordered,
        notes=["Generated by python -m webapp.backend.snapshot. The provenance here is that of the OLDEST strategy "
               "result; each strategy file carries its own, and a status is 'as of' the ledger total in its own file."])
    _write_json(os.path.join(out_dir, "manifest.json"), manifest)
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the web app's result snapshots (runs the library).")
    ap.add_argument("--only", help="comma-separated strategy ids")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--prices-only", action="store_true",
                    help="run NO strategies: rebuild price files, screener, data quality and the manifest "
                         "for all three universes (strategy files already on disk are kept as they are)")
    ap.add_argument("--manifest-only", action="store_true",
                    help="rewrite manifest.json from the strategy files already on disk (instant; runs nothing)")
    args = ap.parse_args(argv)

    known = [r["id"] for r in RECIPES]
    if args.list:
        print("\n".join(known))
        return 0
    if args.manifest_only:
        m = write_manifest(args.out, known)
        print(f"Wrote manifest.json: {len(m.strategy_ids)} strategies, generated {m.provenance.generated_at}, "
              f"data through {m.provenance.data_through}, ledger {m.provenance.ledger_total_at_snapshot}")
        return 0
    chosen = known if not args.only else [i.strip() for i in args.only.split(",")]
    if args.prices_only:
        chosen = []
        for key in UNIVERSES:
            get_universe(key)
    unknown = [i for i in chosen if i not in known]
    if unknown:
        print(f"Unknown id(s): {unknown}. Known: {known}")
        return 2

    total_now = harness.cumulative_hypotheses()
    commit, dirty = _git_state()
    provenance = schemas.Provenance(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), git_commit=commit, git_dirty=dirty,
        ledger_total_at_snapshot=total_now, bonferroni_bar_at_snapshot=0.0,   # replaced per strategy from the harness
        data_through="", in_sample_end=config.IN_SAMPLE_END_DATE,
        risk_free_rate=config.RISK_FREE_RATE, initial_capital=float(config.INITIAL_CAPITAL))

    print(f"Snapshot: {len(chosen)} strategies | ledger total {total_now} | commit {commit} dirty={dirty}")
    os.makedirs(os.path.join(args.out, "strategies"), exist_ok=True)
    for i, rid in enumerate(chosen, 1):
        recipe = next(r for r in RECIPES if r["id"] == rid)
        t0 = time.time()
        print(f"[{i}/{len(chosen)}] {rid}")
        universe_data = get_universe(recipe["universe"])
        data_through = max(e["df"].index.max() for e in universe_data.values())
        prov = provenance.model_copy(update={"data_through": _iso(data_through)})
        sf, slices = build_strategy(recipe, total_now, prov)
        _write_json(os.path.join(args.out, "strategies", f"{rid}.json"), sf)
        slices_path = os.path.join(args.out, "strategies", f"{rid}.symbols.json")
        if slices is not None:
            _write_json(slices_path, slices)
        elif os.path.exists(slices_path):
            os.remove(slices_path)
        print(f"    -> {sf.detail.status} (as of {total_now}) in {time.time() - t0:.0f}s")

    # Data-quality report for every universe loaded in this run (merged with earlier runs).
    dq_path = os.path.join(args.out, "data_quality.json")
    kept = []
    if os.path.exists(dq_path):
        old = schemas.DataQualityResponse.model_validate_json(open(dq_path, encoding="utf-8").read())
        kept = [s for s in old.symbols if s.universe not in _universe_cache]
    symbols = kept + build_data_quality(_universe_cache)
    unresolved = sum(1 for s in symbols if any(d.status != "GENUINE" for d in s.discontinuities))
    _write_json(dq_path, schemas.DataQualityResponse(
        generated_at=provenance.generated_at, n_symbols=len(symbols), n_usable=sum(1 for s in symbols if s.usable),
        n_with_unresolved_discontinuity=unresolved, symbols=symbols))

    # Screener rows + per-stock price files for every universe loaded in this run (merged like data quality).
    sc_path = os.path.join(args.out, "screener.json")
    kept_rows = []
    if os.path.exists(sc_path):
        old_sc = schemas.ScreenerResponse.model_validate_json(open(sc_path, encoding="utf-8").read())
        kept_rows = [r for r in old_sc.rows if r.universe not in _universe_cache]
    new_rows = []
    for key in list(_universe_cache):
        new_rows += build_symbol_files(key, args.out, provenance.generated_at)
    all_rows = kept_rows + new_rows
    dupes = sorted({r.symbol for r in all_rows if sum(1 for x in all_rows if x.symbol == r.symbol) > 1})
    if dupes:
        raise RuntimeError(f"Symbols appear in more than one universe (price files would collide): {dupes}")
    win = _windows()
    _write_json(sc_path, schemas.ScreenerResponse(
        generated_at=provenance.generated_at, data_through=max(r.last_date for r in all_rows),
        in_sample=f"{win['in_sample'][0]} to {win['in_sample'][1]}",
        out_of_sample=f"{win['out_of_sample'][0]} to {win['out_of_sample'][1]}", rows=all_rows))

    write_manifest(args.out, known)
    print(f"Done. Wrote {len(chosen)} strategy file(s), data_quality.json, manifest.json to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
