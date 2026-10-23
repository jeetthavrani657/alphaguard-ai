"""
research/factor_ideas.py

Three stock-selection ideas, designed and frozen in FACTOR_IDEAS.md (2026-10-22) before this file was ever run:

    lowvol_nifty50       lowest 252-day volatility, top 10 of the Nifty 50, monthly
    reversal1m_nifty50   biggest 21-day losers, top 10 of the Nifty 50, monthly
    momentum_midcap150   12-1 momentum, top 30 (a fifth) of the Midcap 150, monthly

All three use the same machinery as the existing momentum strategy: month-end formation, equal weights, execution at
the next open through engine/portfolio_backtest.py with the Indian cost model, symbols blocked by the discontinuity gate
removed BEFORE ranking, and the same in-sample / out-of-sample windows. Only the score that ranks the stocks differs.

    python research/factor_ideas.py              # run and print; counts nothing in the ledger
    python research/factor_ideas.py --register   # ONCE: counts the 3 hypotheses (ledger 212 -> 215)
    python research/factor_ideas.py --sims 20    # fewer random portfolios, for a quick look (never used to register)
    python research/factor_ideas.py --rejudge    # re-judge the stored results at today's ledger count; runs nothing and counts nothing
"""

import argparse
import json
import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
import harness
from universe import load_universe
from portfolio_backtest import run_portfolio_backtest, _eligible_symbols
from cross_sectional_momentum import _month_end_dates, _momentum_score
from run_momentum_strategy import _metrics_for

OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "factor_ideas_latest.json")
RANDOM_SEED = 20261022            # fixed in FACTOR_IDEAS.md before any run; never re-rolled
VOL_DAYS = 252                    # low-volatility window
REVERSAL_DAYS = 21                # one-month reversal window


# ---- the three scores: higher = more wanted. NaN = not enough history, so the stock cannot be ranked yet ----

def score_lowvol(close: pd.Series, formation_date: pd.Timestamp) -> float:
    """Minus the standard deviation of the last 252 daily returns (so the calmest stock scores highest)."""
    history = close.loc[:formation_date]
    if len(history) < VOL_DAYS + 1:
        return float("nan")
    daily_returns = history.iloc[-(VOL_DAYS + 1):].pct_change().dropna()      # exactly 252 returns
    return -float(daily_returns.std())


def score_reversal(close: pd.Series, formation_date: pd.Timestamp) -> float:
    """Minus the return over the last 21 trading days (so the month's biggest loser scores highest)."""
    history = close.loc[:formation_date]
    if len(history) < REVERSAL_DAYS + 1:
        return float("nan")
    return -float(history.iloc[-1] / history.iloc[-1 - REVERSAL_DAYS] - 1.0)


IDEAS = [
    {"id": "lowvol_nifty50", "universe": "nifty50", "top_n": 10, "score": score_lowvol,
     "name": "Low volatility (252-day, top 10, monthly, Nifty 50, long-only)",
     "rationale": ("Stocks that swing less have tended to earn at least as much as volatile ones, because many investors reach for "
                   "volatile lottery-like stocks and face leverage limits (the low-volatility anomaly; Frazzini and Pedersen, Ang et al.). "
                   "A claim about the cross-section of stocks, distinct from momentum and from the own-trend moving-average and "
                   "own-overreaction RSI ideas. FACTOR_IDEAS.md.")},
    {"id": "reversal1m_nifty50", "universe": "nifty50", "top_n": 10, "score": score_reversal,
     "name": "One-month reversal (21-day losers, top 10, monthly, Nifty 50, long-only)",
     "rationale": ("A month of heavy selling often pushes a price past what the news justifies and liquidity providers are paid to absorb it, "
                   "so last month's biggest losers tend to bounce (Jegadeesh 1990; Lehmann 1990). The mirror of 12-1 momentum, which "
                   "skips this very month for the same reason. FACTOR_IDEAS.md.")},
    {"id": "momentum_midcap150", "universe": "midcap150", "top_n": 30, "score": _momentum_score,
     "name": "12-1 momentum (top 30, monthly, Midcap 150, long-only)",
     "rationale": ("Momentum is said to be stronger where information travels slowly and fewer analysts look, which describes mid caps "
                   "better than the Nifty 50 (the Nifty 50 result is already in the ledger). The rule is unchanged; the universe and the "
                   "fifth (30 of 150, as 10 of 50) differ. FACTOR_IDEAS.md.")},
]
UNIVERSES = {"nifty50": lambda: config.UNIVERSE, "midcap150": lambda: config.MIDCAP150_UNIVERSE}


# ---- weights --------------------------------------------------------------------------------------------------

def formation_dates(universe_data: dict) -> pd.DatetimeIndex:
    """The last trading day of every month on which any stock in the universe traded."""
    all_dates = sorted(set().union(*(e["df"]["close"].index for e in universe_data.values())))
    return pd.DatetimeIndex(_month_end_dates(pd.DatetimeIndex(all_dates)))


def target_weights(universe_data: dict, score, top_n: int) -> pd.DataFrame:
    """Per formation date: equal weight on the top_n highest-scoring stocks; 0 for everyone else (and for unrankable ones)."""
    closes = {t: e["df"]["close"] for t, e in universe_data.items()}
    dates = formation_dates(universe_data)
    weights = pd.DataFrame(0.0, index=dates, columns=list(closes))
    for date in dates:
        scores = {t: s for t, c in closes.items() if not pd.isna(s := score(c, pd.Timestamp(date)))}
        if not scores:
            continue                                                         # nobody can be ranked yet: stay in cash
        chosen = [t for t, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]]
        weights.loc[date, chosen] = 1.0 / len(chosen)
    return weights


def random_weights(universe_data: dict, score, top_n: int, rng: random.Random) -> pd.DataFrame:
    """The zero-skill null: the same dates and sizes, drawn by lot from the same rankable stocks on each date."""
    closes = {t: e["df"]["close"] for t, e in universe_data.items()}
    dates = formation_dates(universe_data)
    weights = pd.DataFrame(0.0, index=dates, columns=list(closes))
    for date in dates:
        pool = [t for t, c in closes.items() if not pd.isna(score(c, pd.Timestamp(date)))]
        if pool:
            chosen = rng.sample(pool, min(top_n, len(pool)))
            weights.loc[date, chosen] = 1.0 / len(chosen)
    return weights


def equal_weight_all(universe_data: dict, score) -> pd.DataFrame:
    """The universe benchmark: every rankable stock, equal weight, same monthly rebalance and costs (no selection)."""
    return target_weights(universe_data, score, top_n=10 ** 6)


# ---- running one window ----------------------------------------------------------------------------------------

def run_window(universe_data: dict, idea: dict, start: str, end: str, n_sims: int) -> dict:
    eligible, blocked = _eligible_symbols(universe_data, start, end, override_discontinuity_gate=False)
    weights = target_weights(eligible, idea["score"], idea["top_n"])

    def metrics(w):
        res = run_portfolio_backtest(eligible, w, start, end, initial_capital=config.INITIAL_CAPITAL)
        return res, _metrics_for(res, config.INITIAL_CAPITAL)

    result, m = metrics(weights)
    log = result["rebalance_log"]
    held = (weights.loc[weights.index <= pd.Timestamp(end)] > 0).sum(axis=1)
    rng = random.Random(RANDOM_SEED)
    sims = []
    for _ in range(n_sims):
        s = metrics(random_weights(eligible, idea["score"], idea["top_n"], rng))[1]["sharpe_ratio"]
        if not np.isnan(s):
            sims.append(s)
    _, bench = metrics(equal_weight_all(eligible, idea["score"]))
    first_rebalance = log["execution_date"].min() if len(log) else None
    equity = result["equity_curve"]
    return {
        "start": start, "end": end, "n_obs": len(equity), "n_eligible": len(eligible), "blocked": [t for t, _ in blocked],
        "sharpe": float(m["sharpe_ratio"]), "cagr_pct": float(m["cagr_pct"]), "max_drawdown_pct": float(m["max_drawdown_pct"]),
        "exposure_pct": float((equity.index >= first_rebalance).mean() * 100.0) if first_rebalance is not None else 0.0,
        "avg_turnover_pct": float(log["turnover_pct"].mean()) if len(log) else float("nan"),
        "n_rebalances": int(len(log)), "avg_names_held": float(held[held > 0].mean()) if (held > 0).any() else 0.0,
        "universe_sharpe": float(bench["sharpe_ratio"]), "universe_cagr_pct": float(bench["cagr_pct"]),
        "universe_max_drawdown_pct": float(bench["max_drawdown_pct"]),
        "zero_skill": {"n_sims": len(sims), "mean": float(np.mean(sims)) if sims else None,
                       "percentile": float((np.array(sims) < m["sharpe_ratio"]).mean() * 100.0) if sims else None},
    }


def rejudge(path: str = OUTPUT_PATH) -> dict:
    """
    The registered results judged again at the CURRENT ledger count (the bar tightens as ideas are added), from the Sharpe ratios already stored: nothing is run, nothing is
    counted, and no number but the status, the bar and the ledger count changes.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    results = [harness.evaluate_strategy(i["name"], i["rationale"], data["ideas"][i["id"]]["in_sample"]["sharpe"], data["ideas"][i["id"]]["in_sample"]["n_obs"],
                                         data["ideas"][i["id"]]["out_of_sample"]["sharpe"], data["ideas"][i["id"]]["out_of_sample"]["n_obs"]) for i in IDEAS]
    total = harness.cumulative_hypotheses()
    harness.classify_results(results, total)
    for i, res in zip(IDEAS, results):
        data["ideas"][i["id"]].update({"harness_status": str(getattr(res, "status", None) or "UNVALIDATED"), "p_in_sample": getattr(res, "in_sample_p_value", None),
                                       "p_out_of_sample": getattr(res, "out_of_sample_p_value", None), "bonferroni_bar": getattr(res, "bonferroni_alpha", None)})
    data["ledger_total"] = total
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=str)
    os.replace(tmp, path)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--register", action="store_true", help="count the 3 hypotheses in the ledger (do this ONCE)")
    ap.add_argument("--sims", type=int, default=200, help="random zero-skill portfolios per window (200 is the frozen number)")
    ap.add_argument("--rejudge", action="store_true", help="judge the stored results again at the current ledger count; runs nothing")
    args = ap.parse_args()
    if args.rejudge:
        d = rejudge()
        print(f"[factor] re-judged at {d['ledger_total']}: " + ", ".join(f"{k} {v['harness_status']}" for k, v in d["ideas"].items()))
        return 0
    if args.register and args.sims != 200:
        raise SystemExit("Register only with the frozen 200 random portfolios (FACTOR_IDEAS.md).")

    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    loaded = {}
    out = {}
    for idea in IDEAS:
        key = idea["universe"]
        if key not in loaded:
            loaded[key], failed = load_universe(UNIVERSES[key](), config.START_DATE, config.END_DATE, verbose=False)
            print(f"[factor] {key}: loaded {len(loaded[key])}/{len(UNIVERSES[key]())} symbols" + (f", failed {failed}" if failed else ""))
        print(f"[factor] running {idea['id']} ...", flush=True)
        ins = run_window(loaded[key], idea, config.START_DATE, config.IN_SAMPLE_END_DATE, args.sims)
        oos = run_window(loaded[key], idea, oos_start, config.END_DATE, args.sims)
        out[idea["id"]] = {"in_sample": ins, "out_of_sample": oos}
        for label, w in (("IS ", ins), ("OOS", oos)):
            print(f"[factor]   {label} Sharpe {w['sharpe']:.3f}  CAGR {w['cagr_pct']:.1f}%  maxDD {w['max_drawdown_pct']:.1f}%  "
                  f"universe Sharpe {w['universe_sharpe']:.3f}  zero-skill pct {w['zero_skill']['percentile']}")

    results = [harness.evaluate_strategy(i["name"], i["rationale"], out[i["id"]]["in_sample"]["sharpe"], out[i["id"]]["in_sample"]["n_obs"],
                                         out[i["id"]]["out_of_sample"]["sharpe"], out[i["id"]]["out_of_sample"]["n_obs"]) for i in IDEAS]
    if args.register:
        run = harness.run_harness(results, "Three stock-selection ideas: 3 hypotheses (research/factor_ideas.py, FACTOR_IDEAS.md), registered once")
        total, results = int(run["cumulative_hypotheses_all_time"]), run["results"]
    else:
        total = harness.cumulative_hypotheses()
        harness.classify_results(results, total)
        total_after = total + len(IDEAS)
        print(f"[factor] NOT registered: judged at the current count {total}; registering would make it {total_after}")
    for i, res in zip(IDEAS, results):
        out[i["id"]].update({"name": i["name"], "rationale": i["rationale"], "universe": i["universe"], "top_n": i["top_n"],
                             "harness_status": str(getattr(res, "status", None) or "UNVALIDATED"),
                             "p_in_sample": getattr(res, "in_sample_p_value", None), "p_out_of_sample": getattr(res, "out_of_sample_p_value", None),
                             "bonferroni_bar": getattr(res, "bonferroni_alpha", None)})
        print(f"[factor] {i['id']}: {out[i['id']]['harness_status']}  p IS {out[i['id']]['p_in_sample']}  p OOS {out[i['id']]['p_out_of_sample']}")
    if args.register:
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"ledger_total": total, "registered": True, "ideas": out}, f, indent=1, default=str)
        print(f"[factor] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
