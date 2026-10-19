"""
research/quality_value_control.py

The zero-skill control for the quality + value forward book (criterion 3 in
FUNDAMENTALS_PREREG.md). It answers one question: does choosing the top 10 by
score beat choosing 10 stocks by lot?

A random portfolio uses the SAME formation dates, the SAME pool of stocks that
were scoreable on each date, the SAME ten-name equal weighting and the SAME
engine and costs. Only the choice of names differs, so any gap is the ranking's,
not the exposure's or the calendar's. (Same idea as the momentum control in
run_momentum_strategy.py, which this reuses.)

The book PASSES this criterion only if its forward Sharpe is at or above the
90th percentile of the random portfolios' Sharpes. Seed, number of draws and the
90th-percentile bar are frozen here, before any result exists.

It REFUSES to give a verdict before the book is old enough (504 trading days and
two completed June rebalances, per the pre-registration). `--rehearse` runs the
machinery on whatever data exists so far, labelled as a rehearsal: it prints
nothing that could be mistaken for a result and records nothing.

    python research/quality_value_control.py            # the real thing (refuses until the book is old enough)
    python research/quality_value_control.py --rehearse
"""

import argparse
import contextlib
import io
import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
import forward_books
import fundamentals_snapshot
import quality_value
from portfolio_backtest import _eligible_symbols, run_portfolio_backtest
from run_momentum_strategy import _metrics_for, _random_target_weights, _run_window
from universe import load_universe

# ---- FROZEN in FUNDAMENTALS_PREREG.md (2026-10-16). Do not edit. -----------------------------
N_SIMS = 500                  # random portfolios drawn
SEED = 20261016               # fixed and disclosed; never re-rolled after seeing a result
PASS_PERCENTILE = 90.0        # the book's Sharpe must sit at or above this percentile of the random ones
MIN_TRADING_DAYS = 504        # no verdict before about two years of forward data ...
MIN_JUNE_REBALANCES = 2       # ... and two completed June rebalances (2027 and 2028)


def pool_by_date(universe_data: dict, facts: pd.DataFrame, currency: dict, formation_dates) -> dict:
    """
    For each formation date, the tickers the book could have chosen from (every stock scoreable that day,
    under the same strict point-in-time rules). Fewer than MIN_ELIGIBLE means the book held cash, so the
    random arm holds cash too (an empty pool).
    """
    pool = {}
    for d in formation_dates:
        table = quality_value.score_universe(universe_data, facts, currency, d, strict=True)
        pool[pd.Timestamp(d)] = table["ticker"].tolist() if len(table) >= quality_value.MIN_ELIGIBLE else []
    return pool


def random_sharpes(eligible: dict, pool: dict, start: str, end: str, n_sims: int = N_SIMS, seed: int = SEED) -> np.ndarray:
    """Sharpe of n_sims portfolios that pick top_n names by lot from each date's pool (NaN runs are dropped)."""
    rng = random.Random(seed)
    tickers = list(eligible.keys())
    out = []
    for _ in range(n_sims):
        weights = _random_target_weights(pool, tickers, quality_value.TOP_N, rng)
        result = run_portfolio_backtest(eligible, weights, start, end, initial_capital=config.INITIAL_CAPITAL)
        sharpe = _metrics_for(result, config.INITIAL_CAPITAL)["sharpe_ratio"]
        if not np.isnan(sharpe):
            out.append(sharpe)
    return np.array(out)


def june_rebalances_done(formation_dates, last: pd.Timestamp) -> int:
    """Rebalances after the freeze day that have executed: a later trading day exists, so the trade has happened."""
    return sum(1 for d in formation_dates[1:] if d < last)


def verdict_allowed(n_trading_days: int, formation_dates, last: pd.Timestamp) -> tuple:
    """(allowed, reason). The pre-registered age gate: enough days AND enough completed June rebalances."""
    done = june_rebalances_done(formation_dates, last)
    if n_trading_days < MIN_TRADING_DAYS:
        return False, f"{n_trading_days} of {MIN_TRADING_DAYS} forward trading days"
    if done < MIN_JUNE_REBALANCES:
        return False, f"{done} of {MIN_JUNE_REBALANCES} June rebalances completed"
    return True, "old enough"


def percentile_of(book_sharpe: float, random_sharpes_: np.ndarray) -> float:
    """Share of random portfolios the book beats, in percent (strictly below, as in the momentum control)."""
    return float((random_sharpes_ < book_sharpe).mean() * 100)


def run_control(universe_data: dict, facts: pd.DataFrame, currency: dict, rehearse: bool = False,
                n_sims: int = N_SIMS) -> dict:
    """Run the control on the book as it stands. Returns a dict; 'verdict' is None unless the age gate is passed."""
    last = max(e["df"].index.max() for e in universe_data.values())
    start, end = forward_books.FORWARD_START, last.strftime("%Y-%m-%d")
    eligible, _ = _eligible_symbols(universe_data, start, end, override_discontinuity_gate=False)
    formations = forward_books._fundamental_formation_dates(eligible, last)
    weights = quality_value.generate_target_weights(eligible, facts, currency, formations,
                                                    top_n=quality_value.TOP_N, strict=True)
    book = _run_window(eligible, weights, start, end, "quality_value", verbose=False)
    # forward trading days = sessions from the first countable day (the freeze day is the curve's base, not a day)
    n_days = int((book["result"]["equity_curve"].index >= pd.Timestamp(forward_books.FIRST_COUNTED_DAY)).sum())
    allowed, reason = verdict_allowed(n_days, formations, last)
    out = {"n_trading_days": n_days, "allowed": allowed, "reason": reason, "verdict": None,
           "book_sharpe": book["metrics"]["sharpe_ratio"], "percentile": None, "random_sharpes": None}
    if not allowed and not rehearse:
        return out                                          # too early: no simulations, no number to over-read
    pool = pool_by_date(eligible, facts, currency, formations)
    sims = random_sharpes(eligible, pool, start, end, n_sims)
    out["random_sharpes"] = sims
    out["percentile"] = percentile_of(out["book_sharpe"], sims)
    if allowed:
        out["verdict"] = "PASS" if out["percentile"] >= PASS_PERCENTILE else "FAIL"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Zero-skill control for the quality + value forward book.")
    ap.add_argument("--rehearse", action="store_true", help="run the machinery before the book is old enough; not a result")
    args = ap.parse_args(argv)

    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    with contextlib.redirect_stdout(io.StringIO()):
        universe, _ = load_universe(config.UNIVERSE, config.START_DATE, today, verbose=False)
    if max(e["df"].index.max() for e in universe.values()) < pd.Timestamp(forward_books.FIRST_COUNTED_DAY):
        print("[control] the book has no countable day yet; nothing to do")
        return 0
    r = run_control(universe, fundamentals_snapshot.load_snapshot(), fundamentals_snapshot.load_currency(), args.rehearse)
    if not r["allowed"] and not args.rehearse:
        print(f"[control] no verdict yet: {r['reason']} (pre-registered age gate). Use --rehearse to test the machinery.")
        return 0
    sims = r["random_sharpes"]
    tag = "" if r["allowed"] else "REHEARSAL, NOT A RESULT: "
    print(f"[control] {tag}book Sharpe {r['book_sharpe']:.3f} vs {len(sims)} random portfolios "
          f"(5th/50th/95th pct {np.percentile(sims, 5):.3f}/{np.percentile(sims, 50):.3f}/{np.percentile(sims, 95):.3f}); "
          f"book sits at the {r['percentile']:.1f}th percentile")
    if r["allowed"]:
        print(f"[control] criterion 3 (>= {PASS_PERCENTILE:.0f}th percentile): {r['verdict']}. "
              "Criteria 1 and 2 (Sharpe vs buy-and-hold, p < 0.0125) are judged separately.")
    else:
        print(f"[control] a verdict would still be refused: {r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
