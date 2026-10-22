"""
research/midcap_survivorship_check.py

How much can survivorship bias flatter the Midcap 150 momentum idea (FACTOR_IDEAS.md)? The universe is today's index list, so
every stock in it is one that survived and grew into the index. This is a DIAGNOSTIC of an idea that is already registered: it
registers nothing, counts no hypothesis, and its numbers must never be used to change the rule. Three questions:

  A. Add-back bound. Put the four verified casualties that have prices (Jet Airways, Reliance Capital, Reliance Communications,
     Reliance Naval; DHFL has none left) back into the universe, with the SAME unchanged rule and top 30. A hand-picked set of
     known failures is an UPPER bound on the damage, not an estimate; the engine holds a stock at its last price once its
     data ends, so the bound is lenient about the final fall.
  B. Late-listed names. Drop every stock that had no prices when the history starts (listed after 2015-01-31) and rerun the
     rule. If the result collapses, much of it came from names that were not even listed for the early years.
  C. Where the picks come from. The share of holdings that are late-listed names, against their share of the universe.

    python research/midcap_survivorship_check.py
"""

import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd

import config
import factor_ideas as fi
from universe import load_universe
from portfolio_backtest import run_portfolio_backtest, _eligible_symbols
from cross_sectional_momentum import _momentum_score
from run_momentum_strategy import _metrics_for

CASUALTIES = ["JETAIRWAYS", "RCOM", "RELCAPITAL", "RNAVAL"]      # DHFL has no price history left at the source
TOP_N = 30                                                        # the frozen top fifth of the Midcap 150
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "midcap_survivorship_latest.json")
STALE_DAYS = 7                                                    # a stock with no price for a week is no longer trading


def live_momentum_score(close: pd.Series, formation_date: pd.Timestamp) -> float:
    """The registered 12-1 score, but NaN once a stock has stopped trading: otherwise the last 12-1 value would be frozen
    forever and a delisted stock could stay in the top 30 for years."""
    history = close.loc[:formation_date]
    if history.empty or formation_date - history.index[-1] > pd.Timedelta(days=STALE_DAYS):
        return float("nan")
    return _momentum_score(close, formation_date)


def run(universe: dict, start: str, end: str, gate_already_applied: bool) -> dict:
    weights = fi.target_weights(universe, live_momentum_score, TOP_N)
    res = run_portfolio_backtest(universe, weights, start, end, initial_capital=config.INITIAL_CAPITAL,
                                 override_discontinuity_gate=gate_already_applied)
    m = _metrics_for(res, config.INITIAL_CAPITAL)
    return {"sharpe": float(m["sharpe_ratio"]), "cagr_pct": float(m["cagr_pct"]), "max_drawdown_pct": float(m["max_drawdown_pct"]),
            "weights": weights}


def gated(universe: dict, start: str, end: str) -> dict:
    eligible, _ = _eligible_symbols(universe, start, end, override_discontinuity_gate=False)
    return eligible


def main() -> int:
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    windows = {"in-sample": (config.START_DATE, config.IN_SAMPLE_END_DATE), "out-of-sample": (oos_start, config.END_DATE)}
    mid, _ = load_universe(config.MIDCAP150_UNIVERSE, config.START_DATE, config.END_DATE, verbose=False)
    dead, failed = load_universe(CASUALTIES, config.START_DATE, config.END_DATE, verbose=False)
    print(f"[survivorship] midcap {len(mid)} symbols; casualties with prices: {sorted(dead)}" + (f"; failed {failed}" if failed else ""))
    for t, e in dead.items():
        print(f"[survivorship]   {t}: prices {e['df'].index.min().date()} to {e['df'].index.max().date()}")

    late = {t for t, e in mid.items() if e["df"].index.min() > pd.Timestamp(config.START_DATE) + pd.Timedelta(days=30)}
    print(f"[survivorship] late-listed (no price at the start of 2015): {len(late)} of {len(mid)} = {len(late) / len(mid):.1%}")

    rows = []
    payload_rows = []
    for label, (start, end) in windows.items():
        base_universe = gated(mid, start, end)
        base = run(base_universe, start, end, gate_already_applied=True)

        with_dead = dict(base_universe)
        with_dead.update(dead)                                      # casualties added unfiltered: their collapse is the point
        added = run(with_dead, start, end, gate_already_applied=True)

        no_late = {t: e for t, e in base_universe.items() if t not in late}
        trimmed = run(no_late, start, end, gate_already_applied=True)

        held = base["weights"].loc[base["weights"].index <= pd.Timestamp(end)]
        picks = (held > 0)
        total_picks = int(picks.to_numpy().sum())
        late_picks = int(picks[[c for c in picks.columns if c in late]].to_numpy().sum())
        late_share_universe = sum(1 for t in base_universe if t in late) / len(base_universe)
        casualty_picks = int((added["weights"][[c for c in added["weights"].columns if c in dead]] > 0).to_numpy().sum())

        rows.append((label, base, added, trimmed, late_picks / total_picks if total_picks else float("nan"), late_share_universe, casualty_picks))
        slim = lambda r: {k: r[k] for k in ("sharpe", "cagr_pct", "max_drawdown_pct")}
        payload_rows.append({"window": label.replace("-", "_"), "start": start, "end": end, "todays_list": slim(base),
                             "with_casualties": slim(added), "without_late_listed": slim(trimmed), "n_without_late_listed": len(no_late),
                             "late_listed_share_of_universe_pct": round(late_share_universe * 100.0, 1),
                             "late_listed_share_of_picks_pct": round(late_picks / total_picks * 100.0, 1) if total_picks else None,
                             "casualty_picks": casualty_picks})
        print(f"\n[survivorship] {label} ({start} to {end})")
        print(f"[survivorship]   A. today's list      Sharpe {base['sharpe']:.3f}  CAGR {base['cagr_pct']:.1f}%  maxDD {base['max_drawdown_pct']:.1f}%")
        print(f"[survivorship]      + 4 casualties    Sharpe {added['sharpe']:.3f}  CAGR {added['cagr_pct']:.1f}%  maxDD {added['max_drawdown_pct']:.1f}%"
              f"   (casualties picked {casualty_picks} times)")
        print(f"[survivorship]   B. without late-listed Sharpe {trimmed['sharpe']:.3f}  CAGR {trimmed['cagr_pct']:.1f}%  maxDD {trimmed['max_drawdown_pct']:.1f}%"
              f"   ({len(no_late)} stocks)")
        print(f"[survivorship]   C. late-listed names are {late_share_universe:.1%} of the universe and {late_picks / total_picks:.1%} of the picks")
    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "idea_id": "momentum_midcap150",
               "design_document": "FACTOR_IDEAS.md", "casualties": sorted(dead), "n_universe": len(mid), "n_late_listed": len(late),
               "rows": payload_rows}
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    print(f"[survivorship] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
