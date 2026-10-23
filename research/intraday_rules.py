"""
research/intraday_rules.py

Runs the three rules frozen in INTRADAY_IDEAS.md on the cached 15-minute candles of the Nifty 50 and judges them with the project's usual harness:

    orb_30           opening-range breakout: buy a close above the first 30 minutes' range, sell short a close below it
    gap_fade         trade against an overnight gap of 1% or more
    late_momentum    trade the last 30 minutes in the direction of a first-half-hour move of 1% or more

    python research/intraday_rules.py              # run and print; counts nothing in the ledger
    python research/intraday_rules.py --register   # ONCE: counts the 3 hypotheses (ledger 217 -> 220)
    python research/intraday_rules.py --rejudge    # re-judge the stored results at today's ledger count; runs nothing and counts nothing

Every entry is at the OPEN of a candle after the signal candle has closed; every exit is at the CLOSE of the 15:15 candle. Costs come from research/intraday_costs.py.
The account is split equally over the day's trades, so each trade's cost percentage depends on its size. Windows: in-sample 2022-01-03 to 2024-06-30, out-of-sample 2024-07-01 on.
The slippage sensitivity (0.03% and 0.10% a side instead of 0.05%) is a DIAGNOSTIC and registers nothing.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import numpy as np
import pandas as pd

import intraday_costs as ic

OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "intraday_rules_latest.json")
IS_END, OOS_START = "2024-06-30", "2024-07-01"
ACCOUNT = 1_000_000.0                    # split equally over the day's trades, no leverage
MIN_CANDLES = 23                         # a session with fewer than 90% of the 25 candles is not traded
GAP_THRESHOLD = 0.01                     # gap_fade and late_momentum act on a move of 1% or more
BAR_PCT = 0.2                            # the break-even bar of INTRADAY_COSTS.md, in percent of the trade's value
SLIPPAGE_LEVELS = [0.0003, 0.0010]
LAST_CANDLE = "15:15"
RULES = [
    {"id": "orb_30", "name": "Opening-range breakout (first 30 minutes), exit at the close"},
    {"id": "gap_fade", "name": "Fade an overnight gap of 1% or more, exit at the close"},
    {"id": "late_momentum", "name": "First half-hour move of 1% or more predicts the last 30 minutes"},
]
RATIONALE = ("Three well-known intraday ideas, each registered before any return was looked at (INTRADAY_IDEAS.md). An early move out of the opening range is said to show which side has won the day; "
             "overnight gaps in liquid stocks are said to be partly overreaction; the first half-hour is said to predict the last. The prior is that each fails the cost bar of about 0.2% per round trip.")


def _plus(hhmm: str, minutes: int) -> str:
    """'09:45' plus 15 minutes is '10:00'."""
    t = int(hhmm[:2]) * 60 + int(hhmm[3:]) + minutes
    return f"{t // 60:02d}:{t % 60:02d}"


SIGNAL_STARTS = [_plus("09:45", 15 * k) for k in range(20)]                       # signal candles 09:45, 10:00, ..., 14:30 (entry at the next candle's open, 10:00 ... 14:45)


# --- one session, one rule -> a trade or nothing -------------------------------------------------------------------------

class _Day:
    """The candles of one session, looked up by their start time ('09:15', '09:30', ..., '15:15')."""

    def __init__(self, frame: pd.DataFrame):
        keys = frame.index.strftime("%H:%M")
        self.at = {k: i for i, k in enumerate(keys)}
        self.open, self.high = frame["open"].to_numpy(), frame["high"].to_numpy()
        self.low, self.close = frame["low"].to_numpy(), frame["close"].to_numpy()


def _trade(day: _Day, side: int, entry_key: str):
    """(side, entry_key, entry_price, exit_price) or None when the entry candle or the final candle is missing."""
    j, last = day.at.get(entry_key), day.at.get(LAST_CANDLE)
    if j is None or last is None:
        return None
    return side, entry_key, float(day.open[j]), float(day.close[last])


def orb_30(day: _Day, prior_close):
    a, b = day.at.get("09:15"), day.at.get("09:30")
    if a is None or b is None:
        return None
    top, bottom = max(day.high[a], day.high[b]), min(day.low[a], day.low[b])      # the first 30 minutes' range
    for start in SIGNAL_STARTS:
        i = day.at.get(start)
        if i is None:
            continue
        if day.close[i] > top:
            return _trade(day, +1, _plus(start, 15))
        if day.close[i] < bottom:
            return _trade(day, -1, _plus(start, 15))
    return None


def gap_fade(day: _Day, prior_close):
    first = day.at.get("09:15")
    if prior_close is None or first is None:
        return None
    gap = day.open[first] / prior_close - 1.0
    if gap >= GAP_THRESHOLD:
        return _trade(day, -1, "09:30")                                            # a gap up is faded: sell short
    if gap <= -GAP_THRESHOLD:
        return _trade(day, +1, "09:30")
    return None


def late_momentum(day: _Day, prior_close):
    second = day.at.get("09:30")
    if prior_close is None or second is None:
        return None
    first_half_hour = day.close[second] / prior_close - 1.0                        # includes the overnight gap
    if first_half_hour >= GAP_THRESHOLD:
        return _trade(day, +1, "15:00")
    if first_half_hour <= -GAP_THRESHOLD:
        return _trade(day, -1, "15:00")
    return None


RULE_FUNCTIONS = {"orb_30": orb_30, "gap_fade": gap_fade, "late_momentum": late_momentum}


def trades_for_symbol(frame: pd.DataFrame, rule_id: str, symbol: str = "") -> pd.DataFrame:
    """One row per trade: date, symbol, side (+1 long, -1 short), entry time, entry and exit price, gross return (before any cost)."""
    rule = RULE_FUNCTIONS[rule_id]
    rows, prior_close, prior_day = [], None, None
    for date, session in frame.groupby(frame.index.normalize()):
        if len(session) < MIN_CANDLES:                                             # a short session is not traded and gives no prior close to the next day
            prior_close, prior_day = None, None
            continue
        day = _Day(session)
        usable_prior = prior_close if prior_day is not None and (date - prior_day).days <= 5 else None     # a prior close from before a long gap is not trusted
        trade = rule(day, usable_prior)
        if trade is not None:
            side, entry_key, entry, exit_ = trade
            rows.append({"date": date, "symbol": symbol, "side": side, "entry_time": entry_key, "entry_price": entry, "exit_price": exit_,
                         "gross_return": side * (exit_ / entry - 1.0)})
        last = day.at.get(LAST_CANDLE)
        prior_close, prior_day = (float(day.close[last]), date) if last is not None else (None, None)
    return pd.DataFrame(rows, columns=["date", "symbol", "side", "entry_time", "entry_price", "exit_price", "gross_return"])


# --- from trades to a daily return and an equity curve -----------------------------------------------------------------

def add_net_returns(trades: pd.DataFrame, account: float = ACCOUNT, slippage_pct: float = ic.SLIPPAGE_PCT) -> pd.DataFrame:
    """Each trade's return after costs. The account is split equally over that day's trades, so a busy day means small trades and a larger cost percentage."""
    out = trades.copy()
    n = out.groupby("date")["symbol"].transform("size")
    cost_by_n = {int(k): ic.round_trip_cost(account / k, slippage_pct)["pct_of_value"] / 100.0 for k in n.unique()}
    out["cost_return"] = n.map(lambda k: cost_by_n[int(k)])
    out["net_return"] = out["gross_return"] - out["cost_return"]
    return out


def daily_equity(trades_net: pd.DataFrame, sessions: pd.DatetimeIndex, account: float = ACCOUNT) -> pd.Series:
    """The account's value at each session's end: the day's return is the equal-weighted net return of its trades (zero on a day with none; no interest on idle cash, which is stricter than the other rules)."""
    daily = trades_net.groupby("date")["net_return"].mean().reindex(sessions).fillna(0.0)
    equity = account * (1.0 + daily).cumprod()
    start = pd.Series([account], index=[sessions[0] - pd.Timedelta(days=1)])
    return pd.concat([start, equity])


def trade_summary(trades_net: pd.DataFrame, start=None, end=None) -> dict:
    """What the trades looked like in a window, with the average gross gain per trade set against the 0.2% break-even bar."""
    t = trades_net
    if start is not None:
        t = t[t["date"] >= pd.Timestamp(start)]
    if end is not None:
        t = t[t["date"] <= pd.Timestamp(end)]
    if t.empty:
        return {"n_trades": 0}
    gross, net = float(t["gross_return"].mean() * 100), float(t["net_return"].mean() * 100)
    trimmed = t["net_return"].sort_values().iloc[: int(np.ceil(len(t) * 0.95))]          # without the best 5% of trades
    return {"n_trades": int(len(t)), "n_days_traded": int(t["date"].nunique()), "trades_per_day": float(len(t) / t["date"].nunique()),
            "mean_gross_pct": gross, "mean_net_pct": net, "bar_pct": BAR_PCT, "gross_minus_bar_pct": gross - BAR_PCT,
            "mean_cost_pct": float(t["cost_return"].mean() * 100), "win_rate_pct": float((t["net_return"] > 0).mean() * 100),
            "long_share_pct": float((t["side"] > 0).mean() * 100), "mean_net_pct_without_best_5pct": float(trimmed.mean() * 100)}


def windows_of(equity: pd.Series) -> dict:
    return {"in_sample": equity.loc[:IS_END], "out_of_sample": equity.loc[OOS_START:]}


# --- running -------------------------------------------------------------------------------------------------------------------

def load_candles(symbols=None) -> dict:
    import config
    import intraday
    symbols = symbols or list(config.UNIVERSE)
    out = {}
    for s in symbols:
        frame = intraday._read_cache(intraday._cache_path(s, 15))
        if frame is not None:
            out[s] = frame
    return out


def run_rule(candles: dict, rule_id: str) -> pd.DataFrame:
    parts = [trades_for_symbol(frame, rule_id, symbol) for symbol, frame in candles.items()]
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["date", "symbol", "side", "entry_time", "entry_price", "exit_price", "gross_return"])


def _plain(x):
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def rejudge(path: str = OUTPUT_PATH) -> dict:
    """The registered results judged again at the CURRENT ledger count, from the Sharpe ratios already stored. Nothing is run and nothing is counted."""
    import harness
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    m = lambda r, w: data["rules"][r["id"]]["metrics"][w]
    results = [harness.evaluate_strategy(r["name"], RATIONALE, m(r, "in_sample")["sharpe"], m(r, "in_sample")["n_days"],
                                         m(r, "out_of_sample")["sharpe"], m(r, "out_of_sample")["n_days"]) for r in RULES]
    total = harness.cumulative_hypotheses()
    harness.classify_results(results, total)
    for r, res in zip(RULES, results):
        data["rules"][r["id"]].update({"harness_status": str(getattr(res, "status", None) or "UNVALIDATED"), "p_in_sample": getattr(res, "in_sample_p_value", None),
                                       "p_out_of_sample": getattr(res, "out_of_sample_p_value", None), "bonferroni_bar": getattr(res, "bonferroni_alpha", None)})
    data["ledger_total"] = total
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=_plain)
    os.replace(tmp, path)
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--register", action="store_true", help="count the 3 hypotheses in the ledger (do this ONCE)")
    ap.add_argument("--rejudge", action="store_true", help="judge the stored results again at the current ledger count; runs nothing")
    args = ap.parse_args()
    import advisory as adv
    import harness
    if args.rejudge:
        d = rejudge()
        print(f"[intraday] re-judged at {d['ledger_total']}: " + ", ".join(f"{k} {v['harness_status']}" for k, v in d["rules"].items()))
        return 0

    candles = load_candles()
    if len(candles) < 50:
        print(f"[intraday] only {len(candles)} of 50 symbols have candle files: finish research/backfill_intraday.py first (rules are judged on the full universe only)")
        return 1
    sessions = pd.DatetimeIndex(sorted({d for f in candles.values() for d in f.index.normalize().unique()}))
    print(f"[intraday] {len(candles)} symbols, {len(sessions)} sessions, {sessions[0].date()} to {sessions[-1].date()}")

    results, out = [], {}
    for rule in RULES:
        trades = run_rule(candles, rule["id"])
        net = add_net_returns(trades)
        eq = daily_equity(net, sessions)
        w = {name: adv.window_metrics(e) for name, e in windows_of(eq).items()}
        sens = {}
        for s in SLIPPAGE_LEVELS:
            alt_net = add_net_returns(trades, slippage_pct=s)
            alt_w = windows_of(daily_equity(alt_net, sessions))
            sens[f"{s * 100:.2f}%"] = {"oos_sharpe": adv.window_metrics(alt_w["out_of_sample"])["sharpe"], "oos_mean_net_pct": trade_summary(alt_net, OOS_START)["mean_net_pct"]}
        s_is, s_oos = trade_summary(net, None, IS_END), trade_summary(net, OOS_START)
        print(f"[intraday] {rule['id']}: {s_is['n_trades']} IS / {s_oos['n_trades']} OOS trades; gross per trade IS {s_is.get('mean_gross_pct', float('nan')):.3f}% OOS {s_oos.get('mean_gross_pct', float('nan')):.3f}% "
              f"(bar {BAR_PCT}%); net OOS {s_oos.get('mean_net_pct', float('nan')):.3f}%; Sharpe IS {w['in_sample']['sharpe']:.2f} OOS {w['out_of_sample']['sharpe']:.2f}")
        results.append(harness.evaluate_strategy(rule["name"], RATIONALE, w["in_sample"]["sharpe"], w["in_sample"]["n_days"], w["out_of_sample"]["sharpe"], w["out_of_sample"]["n_days"]))
        out[rule["id"]] = {"name": rule["name"], "metrics": w, "trades_in_sample": s_is, "trades_out_of_sample": s_oos, "slippage_sensitivity": sens}

    nifty = adv.load_prices()["equity_large"]
    bench = {"nifty_etf": {name: adv.window_metrics(e) for name, e in windows_of(nifty.loc[sessions[0]:]).items()}}
    if args.register:
        run_out = harness.run_harness(results, "Three intraday rules on the Nifty 50: orb_30, gap_fade, late_momentum (research/intraday_rules.py, INTRADAY_IDEAS.md), registered once")
        total, results = int(run_out["cumulative_hypotheses_all_time"]), run_out["results"]
    else:
        total = harness.cumulative_hypotheses()
        harness.classify_results(results, total)
        print(f"[intraday] NOT registered: judged at the current count {total}; registering would make it {total + len(RULES)}")
    for rule, res in zip(RULES, results):
        out[rule["id"]].update({"harness_status": str(getattr(res, "status", None) or "UNVALIDATED"), "p_in_sample": getattr(res, "in_sample_p_value", None),
                                "p_out_of_sample": getattr(res, "out_of_sample_p_value", None), "bonferroni_bar": getattr(res, "bonferroni_alpha", None)})
        print(f"[intraday] {rule['id']}: {out[rule['id']]['harness_status']}  p IS {out[rule['id']]['p_in_sample']}  p OOS {out[rule['id']]['p_out_of_sample']}")
    if args.register:
        payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ledger_total": total, "registered": True, "rules": out, "benchmarks": bench}
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, default=_plain)
        print(f"[intraday] wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
