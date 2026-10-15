"""
research/run_momentum_strategy.py

Cross-sectional momentum, run end to end per MOMENTUM_METHODOLOGY.md
(frozen 2026-09-06, before this script existed) and the mandatory-checks
workflow in README.md:

1. Zero-skill benchmark: Monte Carlo random-selection portfolios, same
   universe/costs/turnover, compared against the actual strategy.
2. Exposure reported alongside every Sharpe.
3. In-sample/out-of-sample verified genuinely disjoint (not assumed).
4. Survivorship quantified specifically for a ranking strategy.
5. Turnover and its cost reported explicitly.
6. Registered through research/harness.py; cumulative count + the
   correction threshold that actually applies are reported.

Run from the project root: python research/run_momentum_strategy.py
"""
import sys
import os
import random

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "strategies"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
from universe import load_universe
from loader import load_price_data
from portfolio_backtest import run_portfolio_backtest, _eligible_symbols
from cross_sectional_momentum import generate_target_weights, _momentum_score, LOOKBACK_DAYS, SKIP_DAYS, TOP_N
from metrics import compute_metrics
from harness import evaluate_strategy, run_harness, print_harness_report

N_MONTE_CARLO = 200
RANDOM_SEED = 20260906  # fixed, disclosed -- not re-rolled after seeing a result

MOMENTUM_RATIONALE = (
    "Stocks that have outperformed their peers over the trailing 9-12 months tend to keep "
    "outperforming for several more months because the market underreacts to information -- "
    "analysts revise estimates in stages rather than all at once, institutional capital "
    "reallocates slowly, and the disposition effect means good news gets priced in gradually. "
    "This is a claim about RELATIVE mispricing across stocks (Jegadeesh & Titman 1993), "
    "mechanically distinct from MA crossover's own-trend-persistence rationale and RSI's "
    "own-overreaction-fading rationale already tested in this project. Long-only, single-market "
    "test -- see MOMENTUM_METHODOLOGY.md Section 0 for why this is expected to capture less than "
    "the full academic long-short premium."
)


def _metrics_for(result: dict, initial_capital: float) -> dict:
    equity = result["equity_curve"]
    # position is passed as a constant 1.0 series purely to satisfy
    # compute_metrics()'s signature -- momentum has no per-symbol
    # cash/long binary position the way engine/backtest.py does, so
    # market_exposure_pct from this call is meaningless and ignored;
    # exposure is computed separately in _run_window() from the equity
    # curve's own pre/post-first-rebalance behavior instead.
    m = compute_metrics(
        equity, pd.DataFrame(columns=["entry_date", "exit_date", "entry_price", "exit_price",
                                        "quantity", "return_pct", "holding_days", "total_costs"]),
        initial_capital, pd.Series(1.0, index=equity.index), risk_free_rate=config.RISK_FREE_RATE,
    )
    return m


def _run_window(universe_data, target_weights, start, end, label, verbose=True):
    result = run_portfolio_backtest(universe_data, target_weights, start, end, initial_capital=config.INITIAL_CAPITAL)
    m = _metrics_for(result, config.INITIAL_CAPITAL)

    rb = result["rebalance_log"]
    avg_turnover_pct = rb["turnover_pct"].mean() if len(rb) > 0 else float("nan")
    total_costs = result["trade_log"]["costs"].sum() if len(result["trade_log"]) > 0 else 0.0
    n_rebalances = len(rb)

    # Exposure: fraction of window days the portfolio held ANY non-zero
    # position at all (captures the pre-first-rebalance warm-up as 0%
    # exposure, which is real -- momentum cannot rank anyone until
    # LOOKBACK_DAYS+SKIP_DAYS of history exists for at least one symbol).
    equity = result["equity_curve"]
    cash_only_days = 0
    shares_snapshot = {t: 0 for t in result["eligible_symbols"]}
    first_rebalance_date = rb["execution_date"].min() if n_rebalances > 0 else None
    if first_rebalance_date is not None:
        cash_only_days = (equity.index < first_rebalance_date).sum()
    exposure_pct = (1 - cash_only_days / len(equity)) * 100 if len(equity) > 0 else 0.0

    if verbose:
        print(f"\n--- {label} ({start} to {end}) ---")
        print(f"  CAGR: {m['cagr_pct']:.2f}%  Sharpe: {m['sharpe_ratio']:.3f}  MaxDD: {m['max_drawdown_pct']:.2f}%")
        print(f"  Symbols eligible: {len(result['eligible_symbols'])}  Rebalances: {n_rebalances}")
        print(f"  Exposure (non-cash days): {exposure_pct:.1f}%  (first rebalance: {first_rebalance_date})")
        print(f"  Avg monthly turnover: {avg_turnover_pct:.1f}%  Total realized costs: Rs {total_costs:,.0f} "
              f"({total_costs / config.INITIAL_CAPITAL * 100:.2f}% of initial capital)")
        if result["blocked"]:
            print(f"  Blocked by discontinuity gate: {[t for t, _ in result['blocked']]}")

    return {
        "result": result, "metrics": m, "exposure_pct": exposure_pct,
        "avg_turnover_pct": avg_turnover_pct, "total_costs": total_costs,
        "n_rebalances": n_rebalances, "n_obs": len(equity),
    }


def build_window_inputs(universe_data, start, end, top_n=TOP_N):
    """
    Rank ONLY symbols the discontinuity gate allows for [start, end].

    Before this existed, the ranking ran over all 50 symbols and the
    engine then dropped any gate-blocked one from the portfolio. If a
    blocked symbol ranked in the top 10 (ADANIENT did on 28 of 54
    in-sample rebalances), its slot silently became CASH instead of
    passing to the 11th-ranked name -- so the portfolio was quietly
    under-invested, and exposure was over-reported. Filtering first
    means a blocked symbol can never be selected at all.

    Returns (eligible_universe, target_weights, blocked).
    """
    eligible, blocked = _eligible_symbols(universe_data, start, end, override_discontinuity_gate=False)
    target_weights = generate_target_weights(eligible, top_n=top_n)
    return eligible, target_weights, blocked


def random_selection_sharpes(eligible_universe, target_weights, start, end, n_sims, on_progress=None):
    """
    The zero-skill null: n_sims portfolios that pick TOP_N names by lot
    (not by rank) from the same date-by-date rankable pool momentum
    uses, with the same costs and monthly full rebalance. Uses EVERY
    formation date up to `end` -- exactly the set the momentum run itself
    uses (including a pre-window one that sets day-one holdings). An
    earlier version used only formations after the window start, so the
    random arm sat in cash for the first month while momentum was
    already invested -- a small bias in momentum's favour.
    """
    formations = target_weights.index[target_weights.index <= pd.Timestamp(end)]
    pool = _scoreable_pool_by_date(eligible_universe, formations)
    tickers = list(eligible_universe.keys())
    rng = random.Random(RANDOM_SEED)
    sharpes = []
    for i in range(n_sims):
        random_weights = _random_target_weights(pool, tickers, TOP_N, rng)
        result = run_portfolio_backtest(eligible_universe, random_weights, start, end,
                                        initial_capital=config.INITIAL_CAPITAL)
        sharpe = _metrics_for(result, config.INITIAL_CAPITAL)["sharpe_ratio"]
        if not np.isnan(sharpe):
            sharpes.append(sharpe)
        if on_progress:
            on_progress((i + 1) / n_sims)
    return np.array(sharpes)


def _scoreable_pool_by_date(universe_data: dict, formation_dates) -> dict:
    """
    For each formation date, the list of tickers that COULD have been
    momentum-ranked (i.e. have LOOKBACK_DAYS+SKIP_DAYS of price history
    by then) -- precomputed once and shared by every Monte Carlo draw,
    since it doesn't depend on the random sampling itself. This is what
    makes the random-selection benchmark a FAIR null: it must draw from
    the exact same pool momentum itself draws from, never from a name
    that isn't listed yet (which would silently understate the random
    benchmark relative to momentum, since an unlisted pick just can't be
    bought at all -- not a fair test of "rank vs. lot" if one side is
    sometimes handicapped by picking untradeable names the other side
    would never have picked either).
    """
    pool = {}
    for f_date in formation_dates:
        pool[f_date] = [t for t, entry in universe_data.items()
                         if not pd.isna(_momentum_score(entry["df"]["close"], f_date))]
    return pool


def _random_target_weights(scoreable_pool: dict, all_tickers: list, top_n: int, rng: random.Random) -> pd.DataFrame:
    """The zero-skill null: same formation dates, same top_n, same
    equal-weighting and turnover mechanics, drawn from the SAME
    date-by-date eligible pool momentum itself uses -- but names are
    chosen by lot instead of by momentum rank."""
    weights = pd.DataFrame(0.0, index=list(scoreable_pool.keys()), columns=all_tickers)
    for f_date, pool in scoreable_pool.items():
        if not pool:
            continue
        chosen = rng.sample(pool, min(top_n, len(pool)))
        weights.loc[f_date, chosen] = 1.0 / len(chosen)
    return weights


def zero_skill_benchmark(eligible_universe, target_weights, start, end, actual_sharpe, label):
    print(f"\n--- ZERO-SKILL BENCHMARK: {label} ({N_MONTE_CARLO} random-selection portfolios) ---")
    sharpes = random_selection_sharpes(eligible_universe, target_weights, start, end, N_MONTE_CARLO)
    percentile = (sharpes < actual_sharpe).mean() * 100
    print(f"  Random-selection Sharpe: mean={sharpes.mean():.3f}  std={sharpes.std():.3f}  "
          f"5th/50th/95th pct={np.percentile(sharpes, 5):.3f}/{np.percentile(sharpes, 50):.3f}/{np.percentile(sharpes, 95):.3f}")
    print(f"  Actual momentum Sharpe {actual_sharpe:.3f} sits at the {percentile:.1f}th percentile "
          f"of {len(sharpes)} random-selection simulations.")
    verdict = "BEATS the zero-skill benchmark" if percentile >= 95 else               "DOES NOT beat the zero-skill benchmark" if percentile <= 90 else               "is INCONCLUSIVE against the zero-skill benchmark (borderline percentile)"
    print(f"  VERDICT: momentum {verdict}.")
    return {"sharpes": sharpes, "percentile": percentile, "mean": sharpes.mean(), "std": sharpes.std()}


def survivorship_check(universe_data, target_weights, formation_dates):
    print("\n" + "=" * 100)
    print("CHECK 4: SURVIVORSHIP, QUANTIFIED FOR A RANKING STRATEGY SPECIFICALLY")
    print("=" * 100)

    # (a) Eligible-pool-size-over-time -- a ranking strategy's opportunity
    # set shrinks whenever fewer CURRENT constituents had enough history
    # yet, which is a channel MA crossover (a per-symbol strategy) never
    # has to care about.
    n_eligible_by_date = (target_weights > 0).any(axis=1)  # a formation date is "usable" if ANYONE was rankable
    pool_sizes = (target_weights > 0).sum(axis=1)  # actual number HELD (== TOP_N once enough symbols are eligible)
    scoreable = pd.Series(index=target_weights.index, dtype=int)
    for f_date in target_weights.index:
        count = sum(1 for ticker, entry in universe_data.items()
                    if not pd.isna(_momentum_score(entry["df"]["close"], f_date)))
        scoreable.loc[f_date] = count
    thin_pool_dates = scoreable[scoreable < len(universe_data)]
    print(f"Formation dates where fewer than all {len(universe_data)} current constituents were "
          f"rankable (not listed long enough yet): {len(thin_pool_dates)} of {len(scoreable)} "
          f"({len(thin_pool_dates) / len(scoreable) * 100:.1f}%).")
    if len(thin_pool_dates) > 0:
        print(f"  Thinnest pool: {scoreable.min()} of {len(universe_data)} rankable, on {scoreable.idxmin().date()}.")
        print(f"  This shrinks toward {len(universe_data)} over time as more current constituents "
              f"accumulate the required {LOOKBACK_DAYS + SKIP_DAYS}-day history -- an artifact of "
              f"using today's constituent list from day one of the backtest, not a real liquidity event.")

    # (b) The momentum-specific mechanism: would a since-collapsed casualty
    # have RANKED into the top 10 shortly before its collapse, using the
    # SAME formula this backtest applies to today's survivors? If so, this
    # backtest's clean run is invisible to exactly the risk (buying a
    # since-vanished high-flyer right before it craters) the literature
    # calls "momentum crash risk."
    print("\nMomentum-crash mechanism check -- named casualties from FINDINGS.md Section 5:")
    casualty_tickers = ["JETAIRWAYS", "DHFL", "RCOM", "RELCAPITAL", "RNAVAL"]
    cutoff_scores = {}
    for f_date in target_weights.index:
        held = target_weights.loc[f_date]
        held_scores = [
            _momentum_score(universe_data[t]["df"]["close"], f_date)
            for t in held.index if held[t] > 0 and t in universe_data
        ]
        cutoff_scores[f_date] = min(held_scores) if held_scores else float("nan")
    cutoff_series = pd.Series(cutoff_scores)

    for ticker in casualty_tickers:
        try:
            df = load_price_data(ticker, config.START_DATE, config.END_DATE)
        except Exception as e:
            print(f"  {ticker}: could not load ({e}) -- skipped, same as FINDINGS.md Section 7.")
            continue
        close = df["close"]
        scores = pd.Series({f_date: _momentum_score(close, f_date) for f_date in target_weights.index
                             if f_date <= close.index.max()})
        scores = scores.dropna()
        if scores.empty:
            print(f"  {ticker}: never had enough history for a 12-1 score in its available window.")
            continue
        would_qualify = scores[scores >= cutoff_series.reindex(scores.index)]
        peak_date = scores.idxmax()
        peak_score = scores.max()
        last_price_date = close.index.max()
        print(f"  {ticker}: peak trailing 12-1 return = {peak_score:+.1%} on {peak_date.date()} "
              f"(last available price data: {last_price_date.date()}, close={close.iloc[-1]:.2f}). "
              f"Would have cleared the ACTUAL top-10 cutoff on {len(would_qualify)} of {len(scores)} "
              f"formation dates in its available history.")
    print("\nThese formation dates are exactly where this backtest's current-constituent-only "
          "universe is structurally blind: had a point-in-time-correct universe been used, the "
          "strategy could have selected these names during their run-up and held them into the "
          "collapse. That risk is real and not measured by anything else in this report -- see "
          "MOMENTUM_METHODOLOGY.md Section 5 and FINDINGS.md Section 5's disclosed data limitation "
          "(no point-in-time constituent history exists for this project to build a corrected test).")


def main():
    print("=" * 100)
    print("CROSS-SECTIONAL MOMENTUM -- Nifty 50, per MOMENTUM_METHODOLOGY.md")
    print("=" * 100)

    universe_data, failed = load_universe(config.UNIVERSE, config.START_DATE, config.END_DATE, verbose=False)
    print(f"Loaded {len(universe_data)}/{len(config.UNIVERSE)} symbols.")
    if failed:
        print(f"Failed to load: {failed}")

    eligible, blocked = _eligible_symbols(universe_data, config.START_DATE, config.END_DATE, override_discontinuity_gate=False)
    print(f"Eligible after the discontinuity gate (full period): {len(eligible)}/{len(universe_data)}")
    if blocked:
        print(f"  Blocked: {[t for t, _ in blocked]}")

    # Full-period, gate-eligible weights -- used only by the survivorship
    # diagnostic below. Each window's headline numbers use weights ranked
    # over THAT window's own eligible symbols (see build_window_inputs).
    full_period_weights = generate_target_weights(eligible)
    print(f"Formation dates (monthly, full period): {len(full_period_weights)}")

    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    # --- Check 3: IS/OOS genuinely disjoint, verified directly, not assumed ---
    print("\n" + "=" * 100)
    print("CHECK 3: IN-SAMPLE / OUT-OF-SAMPLE DISJOINTNESS, VERIFIED DIRECTLY")
    print("=" * 100)
    is_universe, is_weights, _ = build_window_inputs(universe_data, config.START_DATE, config.IN_SAMPLE_END_DATE)
    oos_universe, oos_weights, _ = build_window_inputs(universe_data, oos_start, config.END_DATE)
    is_window = _run_window(is_universe, is_weights, config.START_DATE, config.IN_SAMPLE_END_DATE, "IN-SAMPLE", verbose=False)
    oos_window = _run_window(oos_universe, oos_weights, oos_start, config.END_DATE, "OUT-OF-SAMPLE", verbose=False)
    is_curve, oos_curve = is_window["result"]["equity_curve"], oos_window["result"]["equity_curve"]
    overlap = is_curve.index.intersection(oos_curve.index)
    identical = is_curve.equals(oos_curve)
    print(f"IN-SAMPLE date range: {is_curve.index.min().date()} to {is_curve.index.max().date()} ({len(is_curve)} days)")
    print(f"OUT-OF-SAMPLE date range: {oos_curve.index.min().date()} to {oos_curve.index.max().date()} ({len(oos_curve)} days)")
    print(f"Overlapping dates: {len(overlap)}  Equity curves identical: {identical}")
    assert len(overlap) == 0 and not identical, (
        "IN-SAMPLE and OUT-OF-SAMPLE windows are not genuinely disjoint -- refusing to report "
        "results until this is fixed. This exact failure mode is why this check is mandatory "
        "now (see FINDINGS.md Section 6, Bug 1)."
    )
    print("CONFIRMED genuinely disjoint -- not assumed.")

    print("\n" + "=" * 100)
    print("RESULTS")
    print("=" * 100)
    is_window = _run_window(is_universe, is_weights, config.START_DATE, config.IN_SAMPLE_END_DATE, "IN-SAMPLE")
    oos_window = _run_window(oos_universe, oos_weights, oos_start, config.END_DATE, "OUT-OF-SAMPLE")

    # --- Check 1: zero-skill benchmark ---
    print("\n" + "=" * 100)
    print("CHECK 1: ZERO-SKILL BENCHMARK (random-selection Monte Carlo)")
    print("=" * 100)
    is_zero_skill = zero_skill_benchmark(is_universe, is_weights, config.START_DATE, config.IN_SAMPLE_END_DATE,
                                          is_window["metrics"]["sharpe_ratio"], "IN-SAMPLE")
    oos_zero_skill = zero_skill_benchmark(oos_universe, oos_weights, oos_start, config.END_DATE,
                                           oos_window["metrics"]["sharpe_ratio"], "OUT-OF-SAMPLE")

    # --- Check 4: survivorship, quantified ---
    survivorship_check(eligible, full_period_weights, full_period_weights.index)

    # --- Check 6: harness ---
    print("\n" + "=" * 100)
    print("CHECK 6: RESEARCH HARNESS")
    print("=" * 100)
    momentum_result = evaluate_strategy(
        name="Cross-Sectional Momentum (12-1, top-10, monthly, Nifty 50, long-only)",
        rationale=MOMENTUM_RATIONALE,
        in_sample_sharpe=is_window["metrics"]["sharpe_ratio"], in_sample_n_obs=is_window["n_obs"],
        out_of_sample_sharpe=oos_window["metrics"]["sharpe_ratio"], out_of_sample_n_obs=oos_window["n_obs"],
    )
    run_output = run_harness([momentum_result], context="Cross-sectional momentum (12-1, top-10, monthly, Nifty 50, "
                                                          "long-only) -- new strategy family, pre-registered in "
                                                          "MOMENTUM_METHODOLOGY.md before any result existed")
    print()
    print_harness_report(run_output)

    print("\n" + "=" * 100)
    print("SUMMARY FOR THE REPORT")
    print("=" * 100)
    print(f"IS  Sharpe={is_window['metrics']['sharpe_ratio']:.3f}  CAGR={is_window['metrics']['cagr_pct']:.2f}%  "
          f"exposure={is_window['exposure_pct']:.1f}%  turnover={is_window['avg_turnover_pct']:.1f}%/mo  "
          f"vs zero-skill pct={is_zero_skill['percentile']:.1f}")
    print(f"OOS Sharpe={oos_window['metrics']['sharpe_ratio']:.3f}  CAGR={oos_window['metrics']['cagr_pct']:.2f}%  "
          f"exposure={oos_window['exposure_pct']:.1f}%  turnover={oos_window['avg_turnover_pct']:.1f}%/mo  "
          f"vs zero-skill pct={oos_zero_skill['percentile']:.1f}")


if __name__ == "__main__":
    main()
