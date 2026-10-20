"""
research/multiasset_momentum.py

Dual-momentum trading rules over the advisory's six assets (Nifty 50 ETF, Nifty Midcap 150 ETF, Nasdaq-100 fund, gold ETF,
long government-bond ETF, Bitcoin), with cash as the alternative. Research only: it simulates what a rule would have done, places
no orders and is NOT investment advice.

The design was frozen in MULTIASSET_MOMENTUM.md before this file was ever run. Two hypotheses are registered (once, with
--register) and judged by the same harness as every other strategy:

  momentum_top2               hold the two assets with the best twelve-month return, half each, but only those whose own return is positive
  momentum_top3_risk_managed  the three best with a positive return, weighted by the advisory's moderate-profile risk machinery

Benchmarks (not hypotheses): the same six assets equal-weighted with no selection, and the Nifty 50 ETF. It reuses the advisory's
simulation loop (research/advisory.py `simulate`), so costs, the one-day execution lag, the cash rate and the windows are the same.

    python research/multiasset_momentum.py --register    # ONCE: counts 2 hypotheses in the ledger
    python research/multiasset_momentum.py               # regenerate the file without touching the ledger
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import advisory as adv
import harness
import multiasset_trend as mt

OUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "multiasset_momentum_latest.json")

# ---- FROZEN in MULTIASSET_MOMENTUM.md (2026-10-20). Do not edit. ------------------------------
LOOKBACK_DAYS = 252                         # twelve months of trading days
WARMUP = LOOKBACK_DAYS + 1                  # a return over 252 days needs 253 prices
STRATEGIES = [
    {"id": "momentum_top2", "name": "Momentum: best two assets",
     "blurb": "Every 21 days, hold the two assets with the best twelve-month return, half each, but only an asset whose own twelve-month return is positive; a failing slot sits in cash."},
    {"id": "momentum_top3_risk_managed", "name": "Momentum: best three, risk-managed",
     "blurb": "The three best assets with a positive twelve-month return are eligible. They are weighted by inverse volatility within the moderate profile's caps, volatility-targeted to 10% a year, with the drawdown guard."},
]
STATIC_ID = mt.BENCH_STATIC_ID


# ---- the rules ----------------------------------------------------------------------------------

def twelve_month_returns(prices: pd.DataFrame, date: pd.Timestamp) -> dict:
    """Each risky asset's return over the last LOOKBACK_DAYS trading days up to `date` (nothing after it is used); empty before enough history exists."""
    window = prices.loc[:date].iloc[-(LOOKBACK_DAYS + 1):]
    if len(window) < LOOKBACK_DAYS + 1:
        return {}
    return {k: float(window[k].iloc[-1] / window[k].iloc[0] - 1.0) for k in adv.RISKY_IDS}


def pick(returns_12m: dict, how_many: int) -> dict:
    """Flags for the `how_many` assets with the best return that is also positive. Ties go to the earlier asset in the list."""
    ranked = sorted(adv.RISKY_IDS, key=lambda k: (-returns_12m.get(k, float("-inf")), adv.RISKY_IDS.index(k)))
    chosen = [k for k in ranked[:how_many] if returns_12m.get(k, float("-inf")) > 0]
    return {k: (k in chosen) for k in adv.RISKY_IDS}


def top2_weights(flags: dict) -> pd.Series:
    """Half in each chosen asset; a slot that failed the positive-return test is cash."""
    w = pd.Series(0.0, index=adv.RISKY_IDS + ["cash"])
    for k in adv.RISKY_IDS:
        if flags[k]:
            w[k] = 0.5
    w["cash"] = 1.0 - float(w.sum())
    return w


def make_chooser(prices: pd.DataFrame, returns: pd.DataFrame, strategy_id: str):
    def chooser(i, window, guard_on):
        date = returns.index[i]
        if strategy_id == STATIC_ID:
            return mt.equal_weight_slots({k: True for k in adv.RISKY_IDS})
        r12 = twelve_month_returns(prices, date)
        if strategy_id == "momentum_top2":
            return top2_weights(pick(r12, 2))
        if strategy_id == "momentum_top3_risk_managed":
            return mt.risk_managed_weights(pick(r12, 3), window, guard_on)
        raise ValueError(f"unknown strategy '{strategy_id}'")
    return chooser


def run_all(prices: pd.DataFrame, returns: pd.DataFrame) -> dict:
    profile = adv.PROFILES[mt.RISK_PROFILE_ID]          # only its drawdown limit is used, to track the guard state
    return {sid: adv.simulate(returns, profile, chooser=make_chooser(prices, returns, sid), warmup=WARMUP)
            for sid in [s["id"] for s in STRATEGIES] + [STATIC_ID]}


# ---- the output file ----------------------------------------------------------------------------

def build(prices: pd.DataFrame, returns: pd.DataFrame, register: bool = False, ledger_total_now: int | None = None) -> dict:
    sims = run_all(prices, returns)
    start = sims[STRATEGIES[0]["id"]]["equity"].index[0]
    nifty = (1.0 + returns[adv.BENCHMARK_ID].loc[start:]).cumprod() * 100.0
    windows = {sid: mt._windows(s["equity"]) for sid, s in sims.items()}
    nifty_windows = mt._windows(nifty)

    results = [harness.evaluate_strategy(
        f"multiasset_{s['id']}", s["blurb"], windows[s["id"]]["in_sample"]["sharpe"], windows[s["id"]]["in_sample"]["n_days"],
        windows[s["id"]]["out_of_sample"]["sharpe"], windows[s["id"]]["out_of_sample"]["n_days"]) for s in STRATEGIES]
    if register:
        out = harness.run_harness(results, "Multi-asset dual momentum: 2 hypotheses (research/multiasset_momentum.py), registered once")
        total, results = int(out["cumulative_hypotheses_all_time"]), out["results"]
    else:
        total = ledger_total_now if ledger_total_now is not None else harness.cumulative_hypotheses()
        harness.classify_results(results, total)

    r12_now = twelve_month_returns(prices, prices.index[-1])
    chosen_now = {s["id"]: pick(r12_now, 2 if s["id"] == "momentum_top2" else 3) for s in STRATEGIES}
    strategies = []
    for s, res in zip(STRATEGIES, results):
        sim = sims[s["id"]]
        eq, last = sim["equity"], sim["rebalances"][-1]
        held = [{"asset_id": k, "weight_pct": round(float(v) * 100.0, 2)} for k, v in last["weights"].sort_values(ascending=False).items() if v > 1e-6]
        strategies.append({
            "id": s["id"], "name": s["name"], "blurb": s["blurb"], "harness_status": str(getattr(res, "status", None) or "UNVALIDATED"),
            "p_value_in_sample": adv._clean(getattr(res, "in_sample_p_value", None)), "p_value_out_of_sample": adv._clean(getattr(res, "out_of_sample_p_value", None)),
            "bonferroni_bar": adv._clean(getattr(res, "bonferroni_alpha", None)),
            "metrics": {w: mt._plain(m) for w, m in windows[s["id"]].items()},
            "growth": adv._series(eq / eq.iloc[0] * 100.0), "drawdown_pct": adv._series(adv.drawdown_series_pct(eq), 2),
            "exposure_pct": adv._series(sim["exposure_pct"], 1), "n_rebalances": len(sim["rebalances"]),
            "cost_paid_pct_of_start": round(sim["cost_paid"] / 100.0 * 100.0, 3),
            "held_now": held, "held_decided_on": last["date"].strftime("%Y-%m-%d"),
        })
    static_eq = sims[STATIC_ID]["equity"]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data_through": returns.index[-1].strftime("%Y-%m-%d"),
        "simulation_start": start.strftime("%Y-%m-%d"), "in_sample_end": adv.IS_END, "out_of_sample_start": adv.OOS_START,
        "ledger_total": int(total), "disclaimer": adv.DISCLAIMER, "lookback_days": LOOKBACK_DAYS, "design_document": "MULTIASSET_MOMENTUM.md",
        "rule": {"rebalance_every_days": adv.REBALANCE_EVERY, "cost_pct_per_side": adv.COST_PCT * 100.0, "cash_rate_pct": adv.CASH_RATE * 100.0,
                 "execution": "decided at the close of day t, carried out one day later"},
        "strategies": strategies,
        "benchmarks": {
            "static": {"id": STATIC_ID, "name": mt.STATIC_NAME, "metrics": {w: mt._plain(m) for w, m in windows[STATIC_ID].items()},
                       "growth": adv._series(static_eq / static_eq.iloc[0] * 100.0), "drawdown_pct": adv._series(adv.drawdown_series_pct(static_eq), 2)},
            "nifty": {"id": "nifty50_etf", "name": "Nifty 50 ETF, buy and hold", "metrics": {w: mt._plain(m) for w, m in nifty_windows.items()},
                      "growth": adv._series(nifty / nifty.iloc[0] * 100.0), "drawdown_pct": adv._series(adv.drawdown_series_pct(nifty), 2)},
        },
        "signals_now": [{"asset_id": k, "return_12m_pct": round(r12_now.get(k, float("nan")) * 100.0, 2),
                         "chosen_by": [sid for sid, flags in chosen_now.items() if flags[k]]} for k in adv.RISKY_IDS] if r12_now else [],
        "stress": adv.stress_tests({**{s["id"]: sims[s["id"]] for s in STRATEGIES}, STATIC_ID: sims[STATIC_ID]}, returns),
        "assets": [{"id": a["id"], "name": a["name"], "ticker": a["ticker"], "asset_class": a["asset_class"], "role": adv.ROLES[a["id"]]}
                   for a in adv.ASSETS if a["risky"]],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Multi-asset dual-momentum rules (research only, no orders).")
    ap.add_argument("--register", action="store_true", help="count the 2 hypotheses in the ledger (do this ONCE)")
    ap.add_argument("--refresh", action="store_true", help="re-download prices")
    args = ap.parse_args(argv)
    prices = adv.load_prices(args.refresh)
    returns = adv.daily_returns(prices)
    payload = build(prices, returns, register=args.register)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False)
    os.replace(tmp, OUT_PATH)
    b = payload["benchmarks"]
    print(f"[momentum] simulation from {payload['simulation_start']} to {payload['data_through']}")
    for s in payload["strategies"]:
        o, i = s["metrics"]["out_of_sample"], s["metrics"]["in_sample"]
        print(f"[momentum] {s['name']:36s} IS sharpe {i['sharpe']:.2f}  OOS sharpe {o['sharpe']:.2f}  OOS CAGR {o['cagr_pct']:.1f}%  OOS max drawdown {o['max_drawdown_pct']:.1f}%  status {s['harness_status']}")
    for k in ("static", "nifty"):
        o, i = b[k]["metrics"]["out_of_sample"], b[k]["metrics"]["in_sample"]
        print(f"[momentum] {b[k]['name'][:36]:36s} IS sharpe {i['sharpe']:.2f}  OOS sharpe {o['sharpe']:.2f}  OOS CAGR {o['cagr_pct']:.1f}%  OOS max drawdown {o['max_drawdown_pct']:.1f}%")
    print(f"[momentum] wrote {OUT_PATH}; ledger now {payload['ledger_total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
