"""
research/cost_sensitivity.py

How much of each portfolio rule's result survives worse trading costs? The engine charges the statutory Indian costs (STT, stamp duty,
exchange fee, SEBI fee, GST) plus a flat 0.05% slippage per side, which is a modelling assumption, not a fact; real fills for a
rule that replaces most of its portfolio every month can be worse. This reruns the four monthly stock-selection rules at higher
slippage and shows, beside each, what holding the whole universe earns at the same slippage.

A DIAGNOSTIC of rules that are already registered: it registers nothing, counts no hypothesis, and cannot change any status. It only
shows how fragile a result is to a cost assumption the project cannot measure.

    python research/cost_sensitivity.py
"""

import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import pandas as pd

import config
import factor_ideas as fi
from universe import load_universe
from portfolio_backtest import run_portfolio_backtest, _eligible_symbols
from cross_sectional_momentum import _momentum_score
from run_momentum_strategy import _metrics_for

OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "cost_sensitivity_latest.json")
SLIPPAGES = [0.0005, 0.0010, 0.0020, 0.0030]          # per side, as a fraction: 0.05% (the engine's assumption) up to 0.30%

# The registered rules. The first is the Nifty 50 momentum strategy already in the ledger (same score, top 10, monthly).
RULES = [
    {"id": "momentum_nifty50", "universe": "nifty50", "top_n": 10, "score": _momentum_score, "label": "12-1 momentum, Nifty 50, top 10"},
    {"id": "lowvol_nifty50", "universe": "nifty50", "top_n": 10, "score": fi.score_lowvol, "label": "Low volatility, Nifty 50, top 10"},
    {"id": "reversal1m_nifty50", "universe": "nifty50", "top_n": 10, "score": fi.score_reversal, "label": "One-month reversal, Nifty 50, top 10"},
    {"id": "momentum_midcap150", "universe": "midcap150", "top_n": 30, "score": _momentum_score, "label": "12-1 momentum, Midcap 150, top 30"},
]


def run_at(universe: dict, weights: pd.DataFrame, start: str, end: str, slippage: float) -> dict:
    """One window at one slippage level: headline numbers and the costs paid."""
    res = run_portfolio_backtest(universe, weights, start, end, initial_capital=config.INITIAL_CAPITAL, slippage_pct_override=slippage)
    m = _metrics_for(res, config.INITIAL_CAPITAL)
    trades = res["trade_log"]
    cost_paid = float(trades["costs"].sum()) if len(trades) else 0.0
    years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1e-9)
    return {"sharpe": float(m["sharpe_ratio"]), "cagr_pct": float(m["cagr_pct"]), "max_drawdown_pct": float(m["max_drawdown_pct"]),
            "cost_paid_pct_of_start_per_year": round(cost_paid / config.INITIAL_CAPITAL * 100.0 / years, 2)}


def main() -> int:
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    windows = {"in_sample": (config.START_DATE, config.IN_SAMPLE_END_DATE), "out_of_sample": (oos_start, config.END_DATE)}
    loaded, out = {}, {}
    for rule in RULES:
        key = rule["universe"]
        if key not in loaded:
            loaded[key], _ = load_universe(fi.UNIVERSES[key](), config.START_DATE, config.END_DATE, verbose=False)
        out[rule["id"]] = {"label": rule["label"], "windows": {}}
        for wname, (start, end) in windows.items():
            eligible, _ = _eligible_symbols(loaded[key], start, end, override_discontinuity_gate=False)
            picks = fi.target_weights(eligible, rule["score"], rule["top_n"])
            hold_all = fi.equal_weight_all(eligible, rule["score"])
            rows = []
            for slip in SLIPPAGES:
                s, u = run_at(eligible, picks, start, end, slip), run_at(eligible, hold_all, start, end, slip)
                rows.append({"slippage_pct": round(slip * 100.0, 2), "rule": s, "hold_all": u, "cagr_edge_over_hold_all_pct": round(s["cagr_pct"] - u["cagr_pct"], 2)})
                print(f"[costs] {rule['id']:<20} {wname:<13} slip {slip * 100:.2f}%  CAGR {s['cagr_pct']:6.1f}%  Sharpe {s['sharpe']:5.2f}  "
                      f"holding all {u['cagr_pct']:6.1f}%  edge {s['cagr_pct'] - u['cagr_pct']:+6.1f} pts  costs {s['cost_paid_pct_of_start_per_year']:.1f}%/yr", flush=True)
            out[rule["id"]]["windows"][wname] = {"start": start, "end": end, "rows": rows}
    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "slippage_levels_pct": [round(x * 100, 2) for x in SLIPPAGES],
               "note": "Diagnostic of registered rules; registers nothing.", "rules": out}
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"[costs] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
