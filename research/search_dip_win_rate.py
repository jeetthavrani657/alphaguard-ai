"""
research/search_dip_win_rate.py

A BOUNDED search for a dip-buying configuration that reaches a 90% win
rate AFTER COSTS with positive expectancy, at the owner's request ("keep
trying until it happens"). The honest version of "keep trying":

  * ONE grid, declared here before any result: 2 x 3 x 3 x 2 = 36 variants
      RSI entry level     {30, 40}
      take-profit         {2%, 3%, 4%}
      stop-loss           {8%, 12%, 20%}
      max holding days    {30, 60}
    (entry also requires close above its own 200-day average, as in
    run_dip_uptrend_strategy.py). All 36 are counted in the hypothesis
    ledger -- every try raises the bar the result must clear.
  * SEARCH window: 2015-01-01 to 2025-12-31 (data every earlier test has
    already seen -- a variant that looks good here has proven nothing).
  * WIN CONDITION, fixed in advance: all-in win rate >= 90% (net of costs,
    open positions marked to market) AND mean net return per closed trade
    > 0 AND >= 150 closed trades. Among variants meeting it, the one with
    the highest net expectancy is selected; if none meets it, the best
    positive-expectancy variant by win rate is reported as a FAIL.
  * The selected variant is then run ONCE on 2026-01-01 to today -- data
    that did not exist when any earlier strategy in this project was
    tested, and that this search never touches. That number, not the
    search-window number, is the result.

Run from the project root:
    python research/search_dip_win_rate.py
    python research/search_dip_win_rate.py --no-register --n=6      (dry run)
"""
import sys
import os
import itertools
import types

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd
from scipy.stats import binomtest

import config
import buy_and_hold
import dip_target
from rsi_reversion import _wilders_rsi
from universe import load_universe, run_strategy_on_universe
from harness import evaluate_strategy, run_harness, print_harness_report
from run_dip_target_strategy import window_stats

SEARCH_START, SEARCH_END = config.START_DATE, config.END_DATE      # 2015-01-01 .. 2025-12-31
HOLDOUT_START = "2026-01-01"
GRID = {"oversold": [30, 40], "take_profit": [0.02, 0.03, 0.04],
        "stop_loss": [0.08, 0.12, 0.20], "max_hold_days": [30, 60]}
TARGET_WIN_RATE, MIN_TRADES = 90.0, 150

RATIONALE = (
    "Short-term pullbacks in stocks above their 200-day average tend to retrace; a small fixed "
    "target with a hard stop and a time limit realizes every loser. One of a 36-variant grid "
    "searched for a >=90% net win rate at the owner's request -- the result that matters is the "
    "single run of the selected variant on 2026 data the search never saw."
)

_PRECOMPUTED = {}   # id(df) -> (rsi, uptrend gate); RSI is a slow python loop, so compute once per stock


def _signals(df, oversold, take_profit, stop_loss, max_hold_days):
    rsi, gate = _PRECOMPUTED[id(df)]
    return dip_target._stateful_signal(df["close"], rsi, oversold, take_profit, stop_loss,
                                       entry_ok=gate, max_hold_days=max_hold_days)


STRATEGY = types.SimpleNamespace(generate_signals=_signals)


def evaluate(universe_data, params, start, end):
    run = run_strategy_on_universe(universe_data, STRATEGY, params, start, end, verbose=False)
    st = window_stats(run, universe_data, start, end)
    wr = st["win_rate_closed"] / 100
    expectancy = (wr * st["avg_win_pct"] + (1 - wr) * st["avg_loss_pct"]
                  if st["n_closed"] and pd.notna(st["avg_loss_pct"]) else
                  (st["avg_win_pct"] if st["n_closed"] else float("nan")))
    breakeven = (abs(st["avg_loss_pct"]) / (st["avg_win_pct"] + abs(st["avg_loss_pct"])) * 100
                 if pd.notna(st["avg_loss_pct"]) and pd.notna(st["avg_win_pct"]) else float("nan"))
    return run, st, expectancy, breakeven


def main():
    register = "--no-register" not in sys.argv
    n_limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--n=")), None)
    symbols = config.UNIVERSE[:n_limit] if n_limit else config.UNIVERSE
    today = pd.Timestamp.today().strftime("%Y-%m-%d")

    print(f"Loading {len(symbols)} symbols through {today} (extends the cache past 2025 for the holdout)...")
    universe_data, failed = load_universe(symbols, SEARCH_START, today, verbose=False)
    if failed:
        print("Failed to load:", failed)
    for ticker, entry in universe_data.items():
        close = entry["df"]["close"]
        rsi = _wilders_rsi(close, 14)
        gate = (close > close.rolling(200).mean()).fillna(False)
        _PRECOMPUTED[id(entry["df"])] = (rsi, gate)
    last_date = max(e["df"].index.max() for e in universe_data.values())
    print(f"Data through {last_date.date()}. Holdout window: {HOLDOUT_START} to {last_date.date()}.")

    # ---- the search (2015-2025 only) ----
    rows, runs = [], {}
    keys = list(GRID)
    for combo in itertools.product(*(GRID[k] for k in keys)):
        params = dict(zip(keys, combo))
        run, st, expectancy, breakeven = evaluate(universe_data, params, SEARCH_START, SEARCH_END)
        a = run["aggregate_metrics"]
        rows.append({**params, "n_trades": st["n_closed"], "win_closed": st["win_rate_closed"],
                     "win_all_in": st["win_rate_all_in"], "avg_win": st["avg_win_pct"], "avg_loss": st["avg_loss_pct"],
                     "breakeven": breakeven, "expectancy": expectancy, "cagr": a["cagr_pct"],
                     "sharpe": a["sharpe_ratio"], "invested": a["market_exposure_pct"], "n_obs": len(run["combined_equity_curve"])})
        runs[combo] = run
    table = pd.DataFrame(rows)

    pd.set_option("display.width", 220)
    shown = table.sort_values("win_all_in", ascending=False)[
        ["oversold", "take_profit", "stop_loss", "max_hold_days", "n_trades", "win_all_in",
         "avg_win", "avg_loss", "breakeven", "expectancy", "cagr", "invested"]].round(2)
    print("\n" + "=" * 110)
    print("SEARCH WINDOW 2015-2025 -- all 36 variants, sorted by all-in win rate (net of costs)")
    print("=" * 110)
    print(shown.to_string(index=False))

    meets = table[(table["win_all_in"] >= TARGET_WIN_RATE) & (table["expectancy"] > 0) & (table["n_trades"] >= MIN_TRADES)]
    print(f"\nVariants meeting the pre-registered bar (>= {TARGET_WIN_RATE:.0f}% all-in win rate, positive net "
          f"expectancy, >= {MIN_TRADES} trades): {len(meets)} of {len(table)}")
    if len(meets):
        pick = meets.sort_values("expectancy", ascending=False).iloc[0]
        print("-> SELECTED (highest net expectancy among those meeting the bar):")
    else:
        # Fallbacks, in order: positive expectancy with enough trades; positive
        # expectancy at any trade count; anything. (Only a small dry-run universe
        # ever reaches the last two -- the full universe has enough trades.)
        pool = table[(table["expectancy"] > 0) & (table["n_trades"] >= MIN_TRADES)]
        if pool.empty:
            pool = table[table["expectancy"] > 0]
        if pool.empty:
            pool = table
        pick = pool.sort_values("win_all_in", ascending=False).iloc[0]
        print("-> NONE MEETS THE BAR. Best remaining variant by win rate (reported as a FAIL, run on the holdout for the record):")
    sel_params = {k: (int(pick[k]) if k in ("oversold", "max_hold_days") else float(pick[k])) for k in keys}
    print("  ", sel_params, f"| search-window all-in win rate {pick['win_all_in']:.1f}%, "
          f"net expectancy {pick['expectancy']:+.2f}%/trade, {int(pick['n_trades'])} trades")

    # ---- the single untouched-data test ----
    run_h, st_h, exp_h, be_h = evaluate(universe_data, sel_params, HOLDOUT_START, last_date.strftime("%Y-%m-%d"))
    same = {t: universe_data[t] for t in run_h["per_symbol"]}
    bh = run_strategy_on_universe(same, buy_and_hold, {}, HOLDOUT_START, last_date.strftime("%Y-%m-%d"), verbose=False)
    a_h, b_h = run_h["aggregate_metrics"], bh["aggregate_metrics"]
    print("\n" + "=" * 110)
    print(f"HOLDOUT {HOLDOUT_START} to {last_date.date()} -- ONE run of the selected variant, data never used in the search")
    print("=" * 110)
    print(f"  Stocks run: {a_h['n_symbols_included']}   closed trades: {st_h['n_closed']}   still open: {st_h['n_open']}")
    print(f"  WIN RATE closed: {st_h['win_rate_closed']:.1f}%   counting open positions: {st_h['win_rate_all_in']:.1f}%")
    print(f"  Avg win {st_h['avg_win_pct']:+.2f}%   avg loss {st_h['avg_loss_pct']:+.2f}%   net expectancy {exp_h:+.2f}%/trade")
    se_breakeven = pick["breakeven"]
    if st_h["n_closed"] > 0 and pd.notna(se_breakeven):
        wins = int(round(st_h["win_rate_closed"] / 100 * st_h["n_closed"]))
        p = binomtest(wins, st_h["n_closed"], se_breakeven / 100, alternative="greater").pvalue
        print(f"  Win rate vs the {se_breakeven:.1f}% break-even rate: {wins}/{st_h['n_closed']} wins, one-sided p = {p:.3f}")
    print(f"  Strategy:   CAGR {a_h['cagr_pct']:.2f}%  Sharpe {a_h['sharpe_ratio']:.2f}  invested {a_h['market_exposure_pct']:.1f}%")
    print(f"  Buy & hold: CAGR {b_h['cagr_pct']:.2f}%  Sharpe {b_h['sharpe_ratio']:.2f}")

    if register:
        batch = []
        for combo, run in runs.items():
            row = table.iloc[list(runs).index(combo)]
            is_sel = all(abs(float(row[k]) - float(sel_params[k])) < 1e-12 for k in keys)
            oos_sharpe = a_h["sharpe_ratio"] if (is_sel and pd.notna(a_h["sharpe_ratio"])) else None
            batch.append(evaluate_strategy(
                name=f"Dip-win-rate grid: RSI<{int(row['oversold'])}, +{row['take_profit']:.0%}/-{row['stop_loss']:.0%}, "
                     f"{int(row['max_hold_days'])}d" + (" [SELECTED]" if is_sel else ""),
                rationale=RATIONALE, in_sample_sharpe=row["sharpe"], in_sample_n_obs=int(row["n_obs"]),
                out_of_sample_sharpe=oos_sharpe,
                out_of_sample_n_obs=len(run_h["combined_equity_curve"]) if oos_sharpe is not None else None))
        h = run_harness(batch, context="Bounded 36-variant dip-buying search for >=90% net win rate (search 2015-2025, "
                                        "single holdout run on 2026 data) at the owner's request")
        print()
        print_harness_report(h)
    else:
        print("\n(--no-register: harness/ledger NOT touched)")


if __name__ == "__main__":
    main()
