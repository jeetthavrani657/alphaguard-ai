"""
research/run_survivorship_and_exposure_check.py

Two follow-up checks on MIDCAP_SMALLCAP_FINDINGS.md, requested directly
in response to that document's Section 4/5:

PART 1 -- Survivorship magnitude, not just direction.
Take the five named, verified casualties (Jet Airways, DHFL, Reliance
Capital, Reliance Communications, Reliance Naval) -- all solidly
mid-cap-scale in 2015, none in MIDCAP150_UNIVERSE today -- fetch their
price history, run the SAME unchanged MA crossover (config.MA_CROSSOVER_
PARAMS) on them, and add them into the Midcap 150 combined portfolio to
see what including them does to the aggregate Sharpe/CAGR. This is a
biased sample (hand-picked known failures, not a random draw of everyone
who could have failed) -- it is explicitly an UPPER BOUND on the damage
survivorship could do, not an unbiased estimate.

These stocks' entire investment history IS a discontinuity (that's the
finding), so the discontinuity gate is deliberately overridden for this
run rather than reviewed date-by-date like a normal universe symbol --
the crash is not a data artifact to certify away, it's the subject of
the test.

PART 2 -- Is the Smallcap Sharpe win (0.828/0.832 vs 0.792 buy&hold)
genuine timing, or just "lower exposure -> lower volatility -> higher
Sharpe" for free? Built a synthetic, cost-free "same average exposure,
no timing skill" benchmark: buy & hold's own daily return, scaled by the
strategy's realized exposure fraction on days it's out (parked in cash
at the risk-free rate instead of being simply absent). If that
untimed-but-scaled benchmark's Sharpe already matches the strategy's,
the win is mechanical. If the strategy still beats it, that's evidence
of actual timing.

Run from the project root: python research/run_survivorship_and_exposure_check.py
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "strategies"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
from universe import load_universe, run_strategy_on_universe
import ma_crossover
import buy_and_hold
from liquidity_costs import build_slippage_map
from metrics import compute_metrics, TRADING_DAYS_PER_YEAR, _annualized_risk_free_daily


def _combine_two_universe_results(result_a: dict, result_b: dict, initial_capital: float,
                                   risk_free_rate: float) -> dict:
    """
    Merge two independent run_strategy_on_universe() outputs into one
    aggregate -- used instead of building one merged universe_data dict
    and calling run_strategy_on_universe() on it, because that would
    require a single override_discontinuity_gate flag for the WHOLE
    batch. The casualty stocks genuinely need the gate overridden (their
    crash IS the discontinuity, not an artifact to certify away); the
    existing Midcap150 symbols must NOT have their own, unrelated gate
    blocks (several bank/NBFC names, disclosed in MIDCAP_SMALLCAP_FINDINGS.md
    Section 5) silently lifted as a side effect of that -- that would
    change two things at once instead of isolating the one change this
    test is about. Combining two independently-run results (baseline
    with override=False, casualties with override=True) keeps the
    baseline's own inclusion set byte-for-byte identical to
    MIDCAP_SMALLCAP_FINDINGS.md and adds ONLY the casualties on top.
    """
    equity_curves = [r["equity_curve"].rename(t) for t, r in result_a["per_symbol"].items()] + \
                    [r["equity_curve"].rename(t) for t, r in result_b["per_symbol"].items()]
    position_series = [r["position"] for r in result_a["per_symbol"].values()] + \
                       [r["position"] for r in result_b["per_symbol"].values()]
    trade_logs = []
    for t, r in {**result_a["per_symbol"], **result_b["per_symbol"]}.items():
        tl = r["trade_log"].copy()
        tl.insert(0, "symbol", t)
        trade_logs.append(tl)

    combined = pd.concat(equity_curves, axis=1).sort_index().ffill().fillna(initial_capital)
    combined_equity_curve = combined.sum(axis=1)
    pooled_trade_log = pd.concat(trade_logs, ignore_index=True) if trade_logs else pd.DataFrame()
    pooled_position = pd.concat(position_series, ignore_index=True)

    aggregate_metrics = compute_metrics(
        combined_equity_curve, pooled_trade_log,
        initial_capital=initial_capital * len(equity_curves),
        position=pooled_position, risk_free_rate=risk_free_rate,
    )
    aggregate_metrics["n_symbols_included"] = len(equity_curves)
    return {"combined_equity_curve": combined_equity_curve, "aggregate_metrics": aggregate_metrics}

OOS_START = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

# Yahoo/NSE tickers for the five named casualties. Jet Airways, RCom and
# Reliance Capital all stopped trading years before END_DATE (2025-12-31)
# -- load_price_data returns whatever range actually has data, it does
# not require the full window.
CASUALTY_TICKERS = ["JETAIRWAYS", "DHFL", "RCOM", "RELCAPITAL", "RNAVAL"]


def part1_survivorship_magnitude():
    print("=" * 100)
    print("PART 1: SURVIVORSHIP MAGNITUDE -- adding back 5 known casualties")
    print("=" * 100)

    casualty_data, failed = load_universe(CASUALTY_TICKERS, config.START_DATE, config.END_DATE, verbose=False)
    print(f"\nLoaded {len(casualty_data)}/{len(CASUALTY_TICKERS)} casualty tickers.")
    if failed:
        print("Failed to load (excluded from this test, reported not hidden):")
        for t, err in failed:
            print(f"  {t}: {err}")

    for ticker, entry in casualty_data.items():
        df = entry["df"]
        print(f"\n--- {ticker} ---")
        print(f"  Rows: {len(df)}  Range: {df.index.min().date()} to {df.index.max().date()}")
        first_close, last_close = df['close'].iloc[0], df['close'].iloc[-1]
        print(f"  Close: {first_close:.2f} -> {last_close:.2f}  ({(last_close/first_close - 1)*100:+.1f}% over the window)")
        n_discontinuities = len(entry["report"]["discontinuities"])
        if n_discontinuities:
            print(f"  {n_discontinuities} unreviewed/flagged large single-day move(s) -- "
                  f"this IS the collapse, not a data artifact. Gate overridden for this test.")

    if not casualty_data:
        print("\nNo casualty data available -- cannot run this check.")
        return None

    # Reload Midcap150 (cached, no fresh network calls) for the merge.
    mid_data, _ = load_universe(config.MIDCAP150_UNIVERSE, config.START_DATE, config.END_DATE, verbose=False)

    slippage_map_mid = build_slippage_map(mid_data, config.START_DATE, config.END_DATE)
    slippage_map_casualty = build_slippage_map(casualty_data, config.START_DATE, config.END_DATE)

    # Baseline: EXACT same call as MIDCAP_SMALLCAP_FINDINGS.md (override=False)
    # -- its own gate-blocked symbols stay blocked, nothing here changes that.
    base_is = run_strategy_on_universe(
        mid_data, ma_crossover, config.MA_CROSSOVER_PARAMS, config.START_DATE, config.IN_SAMPLE_END_DATE,
        verbose=False, slippage_pct_by_symbol=slippage_map_mid, override_discontinuity_gate=False,
    )
    base_oos = run_strategy_on_universe(
        mid_data, ma_crossover, config.MA_CROSSOVER_PARAMS, OOS_START, config.END_DATE,
        verbose=False, slippage_pct_by_symbol=slippage_map_mid, override_discontinuity_gate=False,
    )

    # Casualties: run in ISOLATION with the gate overridden -- their crash IS
    # the discontinuity being tested, not an artifact. This does not touch
    # the Midcap150 symbols' own gate status at all.
    cas_is = run_strategy_on_universe(
        casualty_data, ma_crossover, config.MA_CROSSOVER_PARAMS, config.START_DATE, config.IN_SAMPLE_END_DATE,
        verbose=False, slippage_pct_by_symbol=slippage_map_casualty, override_discontinuity_gate=True,
    )
    cas_oos = run_strategy_on_universe(
        casualty_data, ma_crossover, config.MA_CROSSOVER_PARAMS, OOS_START, config.END_DATE,
        verbose=False, slippage_pct_by_symbol=slippage_map_casualty, override_discontinuity_gate=True,
    )

    print(f"\n--- Midcap150 ONLY (baseline, matches MIDCAP_SMALLCAP_FINDINGS.md) ---")
    for tag, res in [("IN-SAMPLE", base_is), ("OUT-OF-SAMPLE", base_oos)]:
        m = res["aggregate_metrics"]
        print(f"  {tag}: Sharpe={m['sharpe_ratio']:.3f}  CAGR={m['cagr_pct']:.2f}%  "
              f"MaxDD={m['max_drawdown_pct']:.2f}%  symbols={m['n_symbols_included']}")

    print(f"\n--- 4 casualties ALONE (JETAIRWAYS/RCOM/RELCAPITAL/RNAVAL; DHFL could not be loaded) ---")
    for tag, res in [("IN-SAMPLE", cas_is), ("OUT-OF-SAMPLE", cas_oos)]:
        m = res["aggregate_metrics"]
        print(f"  {tag}: Sharpe={m['sharpe_ratio']:.3f}  CAGR={m['cagr_pct']:.2f}%  "
              f"MaxDD={m['max_drawdown_pct']:.2f}%  symbols={m['n_symbols_included']}  trades={m['total_trades']}")

    stressed_is = _combine_two_universe_results(base_is, cas_is, config.INITIAL_CAPITAL, config.RISK_FREE_RATE)
    stressed_oos = _combine_two_universe_results(base_oos, cas_oos, config.INITIAL_CAPITAL, config.RISK_FREE_RATE)

    print(f"\n--- Midcap150 + 4 casualties (survivorship stress test, isolated gate override) ---")
    for tag, res in [("IN-SAMPLE", stressed_is), ("OUT-OF-SAMPLE", stressed_oos)]:
        m = res["aggregate_metrics"]
        print(f"  {tag}: Sharpe={m['sharpe_ratio']:.3f}  CAGR={m['cagr_pct']:.2f}%  "
              f"MaxDD={m['max_drawdown_pct']:.2f}%  symbols={m['n_symbols_included']}")

    print("\n--- DELTA (stressed minus baseline) ---")
    for tag, base, stressed in [("IN-SAMPLE", base_is, stressed_is), ("OUT-OF-SAMPLE", base_oos, stressed_oos)]:
        b, s = base["aggregate_metrics"], stressed["aggregate_metrics"]
        print(f"  {tag}: Sharpe {b['sharpe_ratio']:.3f} -> {s['sharpe_ratio']:.3f}  "
              f"(delta {s['sharpe_ratio']-b['sharpe_ratio']:+.3f})   "
              f"CAGR {b['cagr_pct']:.2f}% -> {s['cagr_pct']:.2f}%  (delta {s['cagr_pct']-b['cagr_pct']:+.2f}pp)")

    return {"baseline": (base_is, base_oos), "casualties": (cas_is, cas_oos), "stressed": (stressed_is, stressed_oos)}


def _sharpe_and_cagr_from_returns(returns: pd.Series, index: pd.DatetimeIndex, risk_free_rate: float) -> dict:
    """Same formulas as engine/metrics.py's compute_metrics, applied to a raw daily-return series
    instead of an equity curve -- used for the synthetic exposure-scaled benchmark, which has no
    trade log or position series of its own to feed through the real pipeline."""
    equity = (1 + returns).cumprod()
    n_days = (index[-1] - index[0]).days
    cagr = equity.iloc[-1] ** (365.25 / n_days) - 1 if n_days > 0 else float("nan")

    rf_daily = _annualized_risk_free_daily(risk_free_rate)
    excess = returns - rf_daily
    sharpe = (excess.mean() / returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR) if returns.std() > 0 else float("nan")

    running_max = equity.cummax()
    max_dd = (equity / running_max - 1).min()
    return {"sharpe_ratio": sharpe, "cagr_pct": cagr * 100, "max_drawdown_pct": max_dd * 100}


def part2_exposure_check():
    print("\n" + "=" * 100)
    print("PART 2: IS THE SMALLCAP SHARPE WIN JUST LOWER EXPOSURE, OR REAL TIMING?")
    print("=" * 100)

    # Exposure and Sharpe figures below are from the CORRECTED engine
    # (post date-window fix) -- see MIDCAP_SMALLCAP_FINDINGS.md's
    # amendment. The original figures here (56.8%/0.703, 54.2%/0.832)
    # were computed before that fix and are known wrong.
    for label, universe_syms, strat_exposure_oos, strat_sharpe_oos in [
        ("Nifty Midcap 150", config.MIDCAP150_UNIVERSE, 0.6667, 1.4397),
        ("Nifty Smallcap 250", config.SMALLCAP250_UNIVERSE, 0.6359, 1.5048),
    ]:
        data, _ = load_universe(universe_syms, config.START_DATE, config.END_DATE, verbose=False)
        slippage_map = build_slippage_map(data, config.START_DATE, config.END_DATE)

        bh_oos = run_strategy_on_universe(
            data, buy_and_hold, {}, OOS_START, config.END_DATE, verbose=False,
            slippage_pct_by_symbol=slippage_map,
        )
        bh_curve = bh_oos["combined_equity_curve"]
        bh_returns = bh_curve.pct_change().dropna()
        bh_metrics = bh_oos["aggregate_metrics"]

        rf_daily = _annualized_risk_free_daily(config.RISK_FREE_RATE)
        # The "no skill" benchmark: same exposure fraction as the real strategy achieved,
        # but UNTIMED -- every day gets exactly that fraction in the market and the rest
        # in cash at the risk-free rate, regardless of trend. No transaction costs (this
        # is a variance-mechanics diagnostic, not a tradeable strategy).
        scaled_returns = strat_exposure_oos * bh_returns + (1 - strat_exposure_oos) * rf_daily
        scaled_metrics = _sharpe_and_cagr_from_returns(scaled_returns, bh_returns.index, config.RISK_FREE_RATE)

        print(f"\n--- {label} (out-of-sample, {OOS_START} to {config.END_DATE}) ---")
        print(f"  Buy & hold, 100% exposure:                Sharpe={bh_metrics['sharpe_ratio']:.3f}  CAGR={bh_metrics['cagr_pct']:.2f}%")
        print(f"  Untimed, {strat_exposure_oos*100:.1f}% exposure (mechanical benchmark): "
              f"Sharpe={scaled_metrics['sharpe_ratio']:.3f}  CAGR={scaled_metrics['cagr_pct']:.2f}%")
        print(f"  Actual MA-crossover strategy:              Sharpe={strat_sharpe_oos:.3f}")
        gap = strat_sharpe_oos - scaled_metrics['sharpe_ratio']
        verdict = "GENUINE TIMING (beats the same-exposure mechanical benchmark)" if gap > 0.02 else \
                  "MECHANICAL (matches the same-exposure mechanical benchmark -- no real timing evidence)"
        print(f"  Strategy Sharpe minus same-exposure-untimed Sharpe: {gap:+.3f}  -->  {verdict}")


if __name__ == "__main__":
    part1_survivorship_magnitude()
    part2_exposure_check()
