"""
research/overfit_checks.py

A second opinion on the multiple-testing bar. The project's own test is Bonferroni: a result must beat 0.05 / (ideas tried). Two methods from
Bailey and Lopez de Prado look at the same question from other sides:

  Deflated Sharpe Ratio (DSR, 2014). The probability that a strategy's TRUE Sharpe ratio is above the best Sharpe that pure noise would
  have produced after N tries, allowing for the strategy's own skew and fat tails and for how many days it was observed.
  Here N is the ledger count (215). The spread of Sharpe ratios across the N trials is not stored, so it is approximated by the sampling
  variance of one Sharpe estimate under no skill, 1 / (T - 1). The plain probability that the Sharpe is above zero (PSR) is shown beside it.
  The N tries here share the same data and are correlated, so the real effective N is smaller than 215: the DSR is a strict reading.

  Probability of Backtest Overfitting (PBO, 2016), by combinatorially symmetric cross-validation. Cut the days into 8 blocks; for every way of
  taking 4 blocks as "in-sample", find the candidate with the best in-sample Sharpe and see where it ranks on the other 4 blocks. PBO is the
  share of splits in which the in-sample winner lands in the bottom half out of sample. About 50% means picking the winner is no better than a
  coin toss; near 0% means the in-sample winner keeps winning.

A DIAGNOSTIC: it registers nothing, counts no hypothesis and changes no status.

    python research/overfit_checks.py
"""

import itertools
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd
from scipy.stats import norm

EULER_GAMMA = 0.5772156649015329
TRADING_DAYS = 252
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "overfit_checks_latest.json")


# ---- pure formulas -----------------------------------------------------------------------------------------------

def daily_excess(equity: pd.Series, risk_free_annual: float) -> pd.Series:
    """Daily returns of an equity curve minus the daily risk-free rate (the geometric one, as the project's Sharpe uses)."""
    rf_daily = (1.0 + risk_free_annual) ** (1.0 / TRADING_DAYS) - 1.0
    return equity.pct_change().dropna() - rf_daily


def sharpe_stats(excess: pd.Series) -> dict:
    """Per-day Sharpe (mean over standard deviation), its annualised value, and the skew and raw kurtosis of the returns."""
    sr = float(excess.mean() / excess.std(ddof=1))
    return {"sr_daily": sr, "sr_annual": sr * np.sqrt(TRADING_DAYS), "skew": float(excess.skew()),
            "kurtosis": float(excess.kurt()) + 3.0, "n_obs": int(len(excess))}          # pandas gives excess kurtosis; the formula wants raw


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """
    The Sharpe ratio (per day) that the BEST of n_trials strategies with no skill would be expected to show, given the variance
    of a Sharpe estimate (Bailey and Lopez de Prado 2014, eq. 5). One trial expects nothing.
    """
    if n_trials <= 1:
        return 0.0
    return float(np.sqrt(var_sr) * ((1.0 - EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n_trials)
                                    + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * np.e))))


def probabilistic_sharpe(sr: float, sr_benchmark: float, n_obs: int, skew: float, kurtosis: float) -> float:
    """Probability that the true Sharpe is above sr_benchmark, given an estimate sr from n_obs days (all per-day quantities)."""
    denom = np.sqrt(1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr ** 2)
    return float(norm.cdf((sr - sr_benchmark) * np.sqrt(n_obs - 1.0) / denom))


def deflated_sharpe(excess: pd.Series, n_trials: int) -> dict:
    """PSR against zero and the DSR against the best Sharpe n_trials noise strategies would show, for one return series."""
    s = sharpe_stats(excess)
    var_sr = 1.0 / (s["n_obs"] - 1.0)                       # sampling variance of one Sharpe estimate under no skill
    bar = expected_max_sharpe(n_trials, var_sr)
    return {**s, "benchmark_sr_annual": bar * np.sqrt(TRADING_DAYS),
            "psr_vs_zero": probabilistic_sharpe(s["sr_daily"], 0.0, s["n_obs"], s["skew"], s["kurtosis"]),
            "dsr": probabilistic_sharpe(s["sr_daily"], bar, s["n_obs"], s["skew"], s["kurtosis"])}


def years_needed(sr_annual: float, n_trials: int, target: float = 0.95) -> float | None:
    """
    The fewest years of daily data at which a strategy whose TRUE annual Sharpe is `sr_annual` (normal returns, and a sample Sharpe equal to the true one) would reach a Deflated
    Sharpe of `target` after `n_trials` tries; None if it would take more than 300 years. This is how long it takes to tell a real edge from the best of n_trials lucky ones:
    about 2.8 years for a true Sharpe of 1.0 if it was the only idea tried, and about 20 years once 215 were.
    """
    sr = sr_annual / np.sqrt(TRADING_DAYS)
    for tenths in range(2, 3000):
        years = tenths / 10.0
        days = int(years * TRADING_DAYS)
        bar = expected_max_sharpe(n_trials, 1.0 / (days - 1.0))
        if probabilistic_sharpe(sr, bar, days, 0.0, 3.0) >= target:
            return years
    return None


def _sharpe_columns(block: np.ndarray) -> np.ndarray:
    """Per-day Sharpe of every column of a (days x candidates) array."""
    sd = block.std(axis=0, ddof=1)
    return np.where(sd > 0, block.mean(axis=0) / np.where(sd > 0, sd, 1.0), 0.0)


def pbo_cscv(returns: pd.DataFrame, n_splits: int = 8) -> dict:
    """
    Probability of backtest overfitting by combinatorially symmetric cross-validation. `returns` is days x candidates (daily excess
    returns on the same days). Returns the PBO, the mean logit of the in-sample winner's out-of-sample relative rank, the share of splits
    in which that winner lost money out of sample, and how many splits were used.
    """
    if n_splits % 2 or n_splits < 4:
        raise ValueError("n_splits must be an even number, at least 4")
    m = returns.shape[1]
    if m < 3:
        raise ValueError("PBO needs at least three candidates")
    n = (len(returns) // n_splits) * n_splits
    data = returns.to_numpy(dtype=float)[len(returns) - n:]            # drop the oldest days so the blocks are equal
    blocks = np.split(data, n_splits)
    logits, lost = [], 0
    combos = list(itertools.combinations(range(n_splits), n_splits // 2))
    for ins in combos:
        outs = [b for b in range(n_splits) if b not in ins]
        sr_in = _sharpe_columns(np.vstack([blocks[b] for b in ins]))
        sr_out = _sharpe_columns(np.vstack([blocks[b] for b in outs]))
        winner = int(np.argmax(sr_in))
        rank = 1 + int((sr_out < sr_out[winner]).sum())               # 1 = worst, m = best, out of sample
        omega = rank / (m + 1.0)
        logits.append(float(np.log(omega / (1.0 - omega))))
        lost += int(sr_out[winner] < 0)
    logits_arr = np.array(logits)
    return {"pbo": float((logits_arr <= 0).mean()), "mean_logit": float(logits_arr.mean()),
            "share_of_splits_where_the_winner_lost_money": lost / len(combos), "n_splits_used": len(combos),
            "n_candidates": m, "n_days": int(n)}


# ---- gathering the real return series -------------------------------------------------------------------------------

def collect_series() -> dict:
    """
    {name: {"windows": {"in_sample": excess, "out_of_sample": excess}, "common": excess on the shared out-of-sample days}} for every
    portfolio-type rule whose daily returns can be rebuilt: the four monthly stock rules, the three advisory profiles, the two
    trend rules and the two dual-momentum rules.
    """
    import config
    import advisory as adv
    import multiasset_trend as mt
    import multiasset_momentum as mm
    import cost_sensitivity as cs
    import factor_ideas as fi
    from universe import load_universe
    from portfolio_backtest import run_portfolio_backtest, _eligible_symbols

    rf = config.RISK_FREE_RATE
    common_start, common_end = pd.Timestamp("2020-07-01"), pd.Timestamp(config.END_DATE)
    stock_windows = {"in_sample": (config.START_DATE, config.IN_SAMPLE_END_DATE),
                     "out_of_sample": ((pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), config.END_DATE)}
    out, loaded = {}, {}
    for rule in cs.RULES:
        key = rule["universe"]
        if key not in loaded:
            loaded[key], _ = load_universe(fi.UNIVERSES[key](), config.START_DATE, config.END_DATE, verbose=False)
        wins = {}
        for wname, (start, end) in stock_windows.items():
            eligible, _ = _eligible_symbols(loaded[key], start, end, override_discontinuity_gate=False)
            weights = fi.target_weights(eligible, rule["score"], rule["top_n"])
            res = run_portfolio_backtest(eligible, weights, start, end, initial_capital=config.INITIAL_CAPITAL)
            wins[wname] = daily_excess(res["equity_curve"], rf)
        out[rule["id"]] = {"label": rule["label"], "windows": wins, "common": wins["out_of_sample"]}

    prices = adv.load_prices()
    returns = adv.daily_returns(prices)
    sims = {pid: adv.simulate(returns, p) for pid, p in adv.PROFILES.items()}
    sims.update({sid: s for sid, s in mt.run_all(prices, returns).items() if sid != mt.BENCH_STATIC_ID})
    sims.update({sid: s for sid, s in mm.run_all(prices, returns).items() if sid != mm.STATIC_ID})
    for sid, sim in sims.items():
        eq = sim["equity"]
        out[sid] = {"label": sid.replace("_", " "),
                    "windows": {"in_sample": daily_excess(eq.loc[:adv.IS_END], rf), "out_of_sample": daily_excess(eq.loc[adv.OOS_START:], rf)},
                    "common": daily_excess(eq.loc[common_start:common_end], rf)}
    return out


def main() -> int:
    import harness
    n_trials = harness.cumulative_hypotheses()
    series = collect_series()
    rows = {}
    print(f"[overfit] ledger {n_trials}: the bar a strategy's Sharpe must beat is the best of {n_trials} no-skill tries")
    for name, s in series.items():
        rows[name] = {"label": s["label"], "windows": {w: deflated_sharpe(x, n_trials) for w, x in s["windows"].items()}}
        o, i = rows[name]["windows"]["out_of_sample"], rows[name]["windows"]["in_sample"]
        print(f"[overfit] {name:<28} IS Sharpe {i['sr_annual']:5.2f} PSR {i['psr_vs_zero']:.3f} DSR {i['dsr']:.3f} | "
              f"OOS Sharpe {o['sr_annual']:5.2f} (noise bar {o['benchmark_sr_annual']:.2f}) PSR {o['psr_vs_zero']:.3f} DSR {o['dsr']:.3f}")
    common = pd.DataFrame({k: v["common"] for k, v in series.items()}).dropna()
    pbo = pbo_cscv(common)
    print(f"[overfit] PBO over {pbo['n_candidates']} candidates on {pbo['n_days']} common days "
          f"({common.index.min().date()} to {common.index.max().date()}): {pbo['pbo']:.0%}; "
          f"the in-sample winner lost money out of sample in {pbo['share_of_splits_where_the_winner_lost_money']:.0%} of {pbo['n_splits_used']} splits")
    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ledger_total": n_trials,
               "note": "Diagnostic; registers nothing.", "series": rows, "pbo": pbo,
               "pbo_days": [common.index.min().strftime("%Y-%m-%d"), common.index.max().strftime("%Y-%m-%d")]}
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False)
    print(f"[overfit] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
