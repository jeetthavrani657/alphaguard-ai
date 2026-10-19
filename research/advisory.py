"""
research/advisory.py

A multi-asset, risk-managed ALLOCATION engine: the "investment advisory" part of AlphaGuard AI.
Research and education only. It recommends a split of money across asset classes for a stated risk
appetite and shows what that split would have done in the past. It places no orders and is NOT
investment advice (see DISCLAIMER; offering advice in India is regulated).

What it does, in plain words
  1. Assets: Nifty 50, Nifty Midcap 150, Nasdaq-100 (in rupees), gold, long-term government bonds, Bitcoin
     (in rupees) and cash. All except cash are exchange-traded funds or a coin price from yfinance.
  2. Three risk profiles (conservative, moderate, aggressive). Each has a TARGET VOLATILITY, a cap on how much
     any one asset may weigh, and a DRAWDOWN GUARD.
  3. Every 21 trading days the rule works out new weights:
       a. weight each allowed asset by 1 / its recent volatility (calm assets get more money), then enforce the caps;
       b. VOLATILITY TARGETING: if that mix would be more volatile than the profile's target, scale it down and
          hold the rest in cash (never leverage, so the scale is at most 1);
       c. DRAWDOWN GUARD: if the portfolio is down more than the profile's limit from its peak, halve the risky
          part until it has recovered half of the way.
  4. The new weights are decided with data up to the close of day t and applied one day later (no look-ahead,
     the same convention as the rest of the project). Each rebalance pays a cost on the amount traded.

Frozen BEFORE any result was looked at (nothing below was tuned): the assets, the three profiles' numbers,
the 63-day look-back, the 21-day rebalance, the 0.10% cost and the 6% cash rate. The simulation is split
only so the application's two-window convention applies unchanged: 2019 to 2022 is "in-sample" and 2023
onwards "out-of-sample"; nothing was fitted on either. The three profiles are three hypotheses and are
registered in the ledger once (`--register`), then judged by the same harness as every strategy.

    python research/advisory.py --register    # ONCE: counts 3 hypotheses in the ledger
    python research/advisory.py               # regenerate the file without touching the ledger
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

import numpy as np
import pandas as pd

import config
import harness
from metrics import compute_metrics

OUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "advisory_latest.json")
CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "advisory")          # git-ignored price cache

DISCLAIMER = ("Educational research prototype. It is not investment advice, it is not a recommendation to buy or sell "
              "anything, and it places no orders. Past simulated results do not predict future results. In India, "
              "giving investment advice is regulated (SEBI); consult a registered adviser before investing.")

# ---- FROZEN design ------------------------------------------------------------------------------------------------
ASSETS = [
    {"id": "equity_large", "name": "Nifty 50 (large-cap equity)", "ticker": "NIFTYBEES.NS", "asset_class": "Equity", "risky": True},
    {"id": "equity_mid", "name": "Nifty Midcap 150 (mid-cap equity)", "ticker": "MID150BEES.NS", "asset_class": "Equity", "risky": True},
    {"id": "intl_equity", "name": "Nasdaq-100 (international equity, in rupees)", "ticker": "MON100.NS", "asset_class": "International equity", "risky": True},
    {"id": "gold", "name": "Gold", "ticker": "GOLDBEES.NS", "asset_class": "Commodity", "risky": True},
    {"id": "debt", "name": "Government bonds (long-term gilt)", "ticker": "LTGILTBEES.NS", "asset_class": "Debt", "risky": True},
    {"id": "crypto", "name": "Bitcoin (in rupees)", "ticker": "BTC-INR", "asset_class": "Crypto", "risky": True},
    {"id": "cash", "name": "Cash / liquid fund (assumed 6% a year)", "ticker": None, "asset_class": "Cash", "risky": False},
]
RISKY_IDS = [a["id"] for a in ASSETS if a["risky"]]
BENCHMARK_ID = "equity_large"
TREND_DAYS = 210                    # about ten months: the trend monitor compares a price with this average
ROLES = {
    "equity_large": "Core growth: large, liquid Indian companies.",
    "equity_mid": "Higher growth and higher risk than large caps.",
    "intl_equity": "Diversifier: US technology shares, in rupees, so it also carries currency risk.",
    "gold": "Hedge: tends to hold its value when equities fall; pays no income.",
    "debt": "Stability: cushions equity falls, but long bonds fall when interest rates rise.",
    "crypto": "High-risk satellite: extremely volatile, so only a small share is ever allowed.",
    "cash": "Safety buffer: the part not placed in risky assets; earns the assumed cash rate.",
}
CASH_RATE = 0.06
VOL_LOOKBACK = 63
REBALANCE_EVERY = 21
COST_PCT = 0.001                    # 0.10% of the amount traded, each way
TRADING_DAYS = 252
IS_END, OOS_START = "2022-12-31", "2023-01-01"
VAR_LEVEL = 0.95

PROFILES = {
    "conservative": {"name": "Conservative", "target_vol": 0.06, "dd_limit": 0.08,
                     "caps": {"equity_large": 0.30, "equity_mid": 0.10, "intl_equity": 0.10, "gold": 0.25, "debt": 0.70, "crypto": 0.0},
                     "blurb": "Protect capital first. Mostly bonds and gold, a small equity share, no crypto."},
    "moderate": {"name": "Moderate", "target_vol": 0.10, "dd_limit": 0.12,
                 "caps": {"equity_large": 0.45, "equity_mid": 0.20, "intl_equity": 0.20, "gold": 0.25, "debt": 0.50, "crypto": 0.05},
                 "blurb": "Balance growth and safety. A broad mix across equity, gold and bonds, a sliver of crypto."},
    "aggressive": {"name": "Aggressive", "target_vol": 0.15, "dd_limit": 0.20,
                   "caps": {"equity_large": 0.55, "equity_mid": 0.30, "intl_equity": 0.30, "gold": 0.20, "debt": 0.30, "crypto": 0.10},
                   "blurb": "Growth first, accepting large swings. Equity-heavy, with room for international equity and crypto."},
}

# A five-question risk questionnaire. Points per answer add up to 0..15; the bands map the total to a profile.
QUESTIONS = [
    {"id": "horizon", "text": "How long can this money stay invested?",
     "options": [{"label": "Under 1 year", "points": 0}, {"label": "1 to 3 years", "points": 1}, {"label": "3 to 7 years", "points": 2}, {"label": "More than 7 years", "points": 3}]},
    {"id": "drop", "text": "Your portfolio falls 20% in a few months. What do you do?",
     "options": [{"label": "Sell everything", "points": 0}, {"label": "Sell some", "points": 1}, {"label": "Do nothing", "points": 2}, {"label": "Buy more", "points": 3}]},
    {"id": "income", "text": "How stable is your income?",
     "options": [{"label": "Uncertain", "points": 0}, {"label": "Somewhat stable", "points": 1}, {"label": "Stable", "points": 2}, {"label": "Very stable, with savings", "points": 3}]},
    {"id": "experience", "text": "How much investing experience do you have?",
     "options": [{"label": "None", "points": 0}, {"label": "Fixed deposits and savings only", "points": 1}, {"label": "Mutual funds", "points": 2}, {"label": "Direct stocks or derivatives", "points": 3}]},
    {"id": "goal", "text": "What matters most?",
     "options": [{"label": "Not losing money", "points": 0}, {"label": "Steady income", "points": 1}, {"label": "Growth with some safety", "points": 2}, {"label": "Maximum growth", "points": 3}]},
]
BANDS = [{"max_points": 5, "profile": "conservative"}, {"max_points": 10, "profile": "moderate"}, {"max_points": 15, "profile": "aggressive"}]


def profile_for_points(points: int) -> str:
    """Questionnaire total -> profile id, using the BANDS above."""
    for band in BANDS:
        if points <= band["max_points"]:
            return band["profile"]
    return BANDS[-1]["profile"]


# ---- data ----------------------------------------------------------------------------------------------------------

BAD_PRINT_MOVE = 0.5            # a one-day move of more than 50% ...
BAD_PRINT_REVERT_DAYS = 3       # ... that is undone within this many trading days is a bad print, not a price move


def clean_prices(prices: pd.DataFrame) -> tuple:
    """
    Remove one-day bad prints. The free source returned, for example, a price one tenth or one hundredth of the
    real one for a day (Nifty and gold ETFs on 2019-12-19) that came back to normal a few days later; left in, it
    shows up as a 90% crash and a 900% rebound. A move is treated as a bad print only if it is huge AND the price
    returns to within 20% of its earlier level within a few days: a real crash does not undo itself. Returns the
    cleaned table (bad days carried forward from the day before) and the list of rows removed, which the web
    application shows so the cleaning is never hidden.
    """
    clean = prices.copy()
    removed = []
    for col in prices.columns:
        s = prices[col]
        change = s.pct_change()
        flagged = set()
        for t in change.index[change.abs() > BAD_PRINT_MOVE]:
            i = s.index.get_loc(t)
            if i == 0 or i in flagged:
                continue
            for k in range(1, BAD_PRINT_REVERT_DAYS + 1):
                if i + k < len(s) and 0.8 <= s.iloc[i + k] / s.iloc[i - 1] <= 1.25:
                    for j in range(i, i + k):
                        flagged.add(j)
                        removed.append({"asset_id": col, "date": s.index[j].strftime("%Y-%m-%d"), "price": float(s.iloc[j]),
                                        "neighbour_price": float(s.iloc[i - 1])})
                    break
        if flagged:
            clean.iloc[sorted(flagged), clean.columns.get_loc(col)] = np.nan
    return clean.ffill(), removed


def merge_fresh(cached: pd.Series, fresh: pd.Series) -> pd.Series:
    """
    Combine a re-download with the cache. The free source publishes the latest day late (its row can exist with no
    close yet), so a plain overwrite would DELETE a day the cache already holds and set the forward test back a
    session. Fresh values win wherever the source has them (so a provisional close is corrected once the final one
    appears); a cached day the source does not have yet is kept.
    """
    return fresh.combine_first(cached).sort_index()


def load_prices(refresh: bool = False) -> pd.DataFrame:
    """Daily closes of every priced asset on the NSE trading calendar, from the day ALL of them exist."""
    import yfinance as yf                              # imported here: the tests never touch the network
    os.makedirs(CACHE_DIR, exist_ok=True)
    series = {}
    for a in ASSETS:
        if a["ticker"] is None:
            continue
        path = os.path.join(CACHE_DIR, a["ticker"].replace("^", "").replace("/", "_") + ".csv")
        if refresh or not os.path.exists(path):
            d = yf.download(a["ticker"], start="2010-01-01", progress=False, auto_adjust=True, multi_level_index=False)
            fresh = d["Close"].dropna().rename("close")
            if os.path.exists(path):
                fresh = merge_fresh(pd.read_csv(path, index_col=0, parse_dates=True)["close"], fresh)
            fresh.to_csv(path, header=True)
        series[a["id"]] = pd.read_csv(path, index_col=0, parse_dates=True)["close"]
    calendar = series[BENCHMARK_ID].index                # the NSE calendar; Bitcoin trades every day, so it is carried onto these dates
    prices = pd.DataFrame({k: v.reindex(v.index.union(calendar)).ffill().reindex(calendar) for k, v in series.items()})
    prices = prices.loc[prices.notna().all(axis=1).idxmax():].dropna()
    prices, removed = clean_prices(prices)
    prices.attrs["removed"] = removed                       # carried along so the output file can list them
    return prices


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    r = prices.pct_change().dropna()
    r["cash"] = (1 + CASH_RATE) ** (1 / TRADING_DAYS) - 1          # cash earns a constant, assumed rate
    return r


# ---- the allocation rule -----------------------------------------------------------------------------------------------

def capped_inverse_vol(vols: pd.Series, caps: pd.Series) -> pd.Series:
    """
    Weights proportional to 1 / volatility, no asset above its cap, an asset with cap 0 gets nothing.
    Money that cannot be placed because every allowed asset is at its cap is simply left out (the weights then
    sum to less than 1; the remainder becomes cash later).
    """
    allowed = caps[caps > 0].index
    inv = (1.0 / vols[allowed]).replace([np.inf, -np.inf], np.nan).dropna()
    w = pd.Series(0.0, index=vols.index)
    free = list(inv.index)
    budget = 1.0
    while free:
        shares = inv[free] / inv[free].sum()
        trial = shares * budget
        over = [k for k in free if trial[k] > caps[k] + 1e-12]
        if not over:
            w[free] = trial
            break
        for k in over:                                   # pin the over-cap assets at their caps, spread the rest again
            w[k] = caps[k]
            budget -= caps[k]
            free.remove(k)
        if budget <= 1e-12:
            break
    return w


def target_weights(window: pd.DataFrame, profile: dict, guard_on: bool) -> pd.Series:
    """Weights for every asset (cash included) from the last VOL_LOOKBACK days of returns. They sum to 1."""
    risky = window[RISKY_IDS]
    vols = risky.std() * np.sqrt(TRADING_DAYS)
    caps = pd.Series({k: profile["caps"].get(k, 0.0) for k in RISKY_IDS})
    base = capped_inverse_vol(vols, caps)
    cov = risky.cov() * TRADING_DAYS
    port_vol = float(np.sqrt(base.values @ cov.values @ base.values)) if base.sum() > 0 else 0.0
    scale = 1.0 if port_vol <= 0 else min(1.0, profile["target_vol"] / port_vol)     # volatility targeting; never leverage
    if guard_on:
        scale *= 0.5                                                                  # drawdown guard
    w = base * scale
    w["cash"] = 1.0 - float(w.sum())
    return w


def simulate(returns: pd.DataFrame, profile: dict, start_equity: float = 100.0) -> dict:
    """
    Run one profile through history. Returns the equity curve, the risky share of the portfolio each day, the
    weights chosen at each rebalance and the total cost paid. Decisions use data up to the close of day t and are
    carried out at the close of day t + 1 (one day later), so nothing sees the future.
    """
    ids = RISKY_IDS + ["cash"]
    rets = returns[ids]
    n = len(rets)
    holdings = pd.Series(0.0, index=ids)
    holdings["cash"] = start_equity
    equity, exposure, peaks = [], [], start_equity
    guard_on, pending, cost_paid = False, None, 0.0
    log = []
    for i in range(n):
        holdings = holdings * (1.0 + rets.iloc[i])                      # the day's return on what is held
        total = float(holdings.sum())
        if pending is not None:                                         # carry out the decision made yesterday
            desired = pending * total
            traded = float((desired - holdings).abs().sum())
            cost = traded * COST_PCT / 2.0                              # COST_PCT is per side; a trade has a buy and a sell side
            cost_paid += cost
            holdings = desired * (1.0 - cost / total) if total > 0 else desired
            total = float(holdings.sum())
            pending = None
        peaks = max(peaks, total)
        dd = total / peaks - 1.0
        if not guard_on and dd < -profile["dd_limit"]:
            guard_on = True
        elif guard_on and dd > -profile["dd_limit"] / 2.0:
            guard_on = False
        equity.append(total)
        exposure.append(float(holdings[RISKY_IDS].sum()) / total * 100.0)
        if i + 1 >= VOL_LOOKBACK and (i + 1 - VOL_LOOKBACK) % REBALANCE_EVERY == 0 and i + 1 < n:
            window = rets.iloc[i + 1 - VOL_LOOKBACK:i + 1]
            pending = target_weights(window, profile, guard_on)
            log.append({"date": rets.index[i], "weights": pending.copy(), "guard_on": guard_on})
    first = VOL_LOOKBACK                                                # earlier days are warm-up, not part of the simulation
    idx = rets.index[first:]
    return {"equity": pd.Series(equity[first:], index=idx), "exposure_pct": pd.Series(exposure[first:], index=idx),
            "rebalances": log, "cost_paid": cost_paid}


def explain_allocation(window: pd.DataFrame, weights: pd.Series, profile: dict) -> tuple:
    """
    Why each asset got its weight, from the same window the rule looked at. For every asset held: its role, its
    recent volatility, its share of the portfolio's RISK (a calm asset can hold much money and little risk, and the
    reverse) and whether it is held at its cap. Also the assets this profile does not use at all.
    Returns (allocation list, excluded asset ids).
    """
    risky = window[RISKY_IDS]
    vols = risky.std() * np.sqrt(TRADING_DAYS)
    cov = (risky.cov() * TRADING_DAYS).values
    w = weights[RISKY_IDS].values.astype(float)
    port_var = float(w @ cov @ w)
    marginal = cov @ w
    contribution = {k: (float(w[i] * marginal[i] / port_var * 100.0) if port_var > 0 else 0.0) for i, k in enumerate(RISKY_IDS)}
    out = []
    for k, wt in weights.sort_values(ascending=False).items():
        if wt <= 1e-6:
            continue
        if k == "cash":
            out.append({"asset_id": k, "weight_pct": round(float(wt) * 100.0, 2), "role": ROLES[k], "volatility_pct": 0.0,
                        "risk_contribution_pct": 0.0, "capped": False,
                        "why": "Volatility targeting and the caps leave this part uninvested; it earns the assumed cash rate and carries no risk."})
            continue
        cap = profile["caps"].get(k, 0.0)
        capped = bool(wt >= cap - 1e-9)
        why = (f"{vols[k] * 100.0:.1f}% volatility over the last {VOL_LOOKBACK} days; it accounts for {contribution[k]:.0f}% of the portfolio's risk."
               + (f" Held at its {cap * 100.0:.0f}% cap." if capped else ""))
        out.append({"asset_id": k, "weight_pct": round(float(wt) * 100.0, 2), "role": ROLES[k],
                    "volatility_pct": round(float(vols[k]) * 100.0, 2), "risk_contribution_pct": round(contribution[k], 1),
                    "capped": capped, "why": why})
    excluded = [k for k in RISKY_IDS if profile["caps"].get(k, 0.0) <= 0]
    return out, excluded


def trend_state(prices: pd.DataFrame) -> list:
    """
    Where each risky asset stands against its own ten-month average. A description of the present, nothing more:
    it makes no claim that the signal predicts anything and was never back-tested (so it is not a hypothesis).
    """
    rows = []
    for a in ASSETS:
        if not a["risky"]:
            continue
        s = prices[a["id"]]
        last, avg = float(s.iloc[-1]), float(s.iloc[-TREND_DAYS:].mean())
        rows.append({"asset_id": a["id"], "last_price": round(last, 2), "average_210d": round(avg, 2),
                     "distance_pct": round((last / avg - 1.0) * 100.0, 2),
                     "return_12m_pct": round((last / float(s.iloc[-TRADING_DAYS - 1]) - 1.0) * 100.0, 2),
                     "signal": "UPTREND" if last > avg else "DOWNTREND"})
    return rows


# ---- measuring it -------------------------------------------------------------------------------------------------------

def var_cvar(daily: pd.Series, level: float = VAR_LEVEL) -> tuple:
    """Historical 1-day Value at Risk and Expected Shortfall at `level`, as positive percentages of the portfolio."""
    cut = np.quantile(daily.values, 1.0 - level)
    tail = daily[daily <= cut]
    return float(-cut * 100.0), float(-tail.mean() * 100.0)


def window_metrics(equity: pd.Series) -> dict:
    """Return and risk numbers for one equity curve. Sharpe, drawdown and CAGR come from the project's own metrics."""
    empty_trades = pd.DataFrame(columns=["entry_date", "exit_date", "entry_price", "exit_price", "quantity", "return_pct", "holding_days", "total_costs"])
    m = compute_metrics(equity, empty_trades, float(equity.iloc[0]), pd.Series(1.0, index=equity.index), risk_free_rate=config.RISK_FREE_RATE)
    daily = equity.pct_change().dropna()
    var, cvar = var_cvar(daily)
    monthly = equity.resample("ME").last().pct_change().dropna()
    cagr, dd = m.get("cagr_pct"), m.get("max_drawdown_pct")
    return {"sharpe": m.get("sharpe_ratio"), "sortino": m.get("sortino_ratio"), "cagr_pct": cagr, "total_return_pct": m.get("total_return_pct"),
            "max_drawdown_pct": dd, "volatility_pct": float(daily.std() * np.sqrt(TRADING_DAYS) * 100.0),
            "var95_pct": var, "cvar95_pct": cvar, "worst_month_pct": float(monthly.min() * 100.0) if len(monthly) else None,
            "calmar": float(cagr / abs(dd)) if cagr is not None and dd not in (None, 0) else None, "n_days": int(len(equity))}


def drawdown_series_pct(equity: pd.Series) -> pd.Series:
    return (equity / equity.cummax() - 1.0) * 100.0


def _series(s: pd.Series, nd: int = 3) -> dict:
    return {"dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), nd) for v in s.values]}


def _clean(x):
    return None if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))) else float(x)


# ---- putting the file together --------------------------------------------------------------------------------------------

def build(returns: pd.DataFrame, prices: pd.DataFrame, register: bool = False, ledger_total_now: int | None = None) -> dict:
    """The whole advisory file. `register=True` counts the three profiles in the hypothesis ledger (do it once)."""
    sims = {pid: simulate(returns, p) for pid, p in PROFILES.items()}
    start = next(iter(sims.values()))["equity"].index[0]
    bench = (1.0 + returns[BENCHMARK_ID].loc[start:]).cumprod() * 100.0       # buy-and-hold of the Nifty 50 ETF over the same days

    results = []
    windows = {}
    for pid, s in sims.items():
        e = s["equity"]
        is_e, oos_e = e.loc[:IS_END], e.loc[OOS_START:]
        windows[pid] = {"full": window_metrics(e), "in_sample": window_metrics(is_e), "out_of_sample": window_metrics(oos_e)}
        results.append(harness.evaluate_strategy(
            f"advisory_{pid}", f"{PROFILES[pid]['name']} risk-managed multi-asset allocation (inverse volatility, volatility target {PROFILES[pid]['target_vol']:.0%}, drawdown guard).",
            windows[pid]["in_sample"]["sharpe"], windows[pid]["in_sample"]["n_days"], windows[pid]["out_of_sample"]["sharpe"], windows[pid]["out_of_sample"]["n_days"]))
    if register:
        out = harness.run_harness(results, "Advisory engine: 3 risk-profile allocations (research/advisory.py), registered once")
        total = int(out["cumulative_hypotheses_all_time"])
        results = out["results"]
    else:
        total = ledger_total_now if ledger_total_now is not None else harness.cumulative_hypotheses()
        harness.classify_results(results, total)

    bench_win = {w: window_metrics(bench.loc[:IS_END] if w == "in_sample" else bench.loc[OOS_START:] if w == "out_of_sample" else bench)
                 for w in ("full", "in_sample", "out_of_sample")}
    corr = returns[RISKY_IDS].corr()
    asset_rows = []
    for a in ASSETS:
        if not a["risky"]:
            continue
        eq = (1.0 + returns[a["id"]].loc[start:]).cumprod() * 100.0
        m = window_metrics(eq)
        asset_rows.append({"id": a["id"], "name": a["name"], "ticker": a["ticker"], "asset_class": a["asset_class"], "role": ROLES[a["id"]],
                           "cagr_pct": _clean(m["cagr_pct"]), "volatility_pct": _clean(m["volatility_pct"]),
                           "max_drawdown_pct": _clean(m["max_drawdown_pct"]),
                           "last_price": round(float(prices[a["id"]].iloc[-1]), 4) if prices is not None else None,
                           "price_date": prices.index[-1].strftime("%Y-%m-%d") if prices is not None else None})
    asset_rows.append({"id": "cash", "name": ASSETS[-1]["name"], "ticker": None, "asset_class": "Cash", "role": ROLES["cash"], "cagr_pct": CASH_RATE * 100,
                       "volatility_pct": 0.0, "max_drawdown_pct": 0.0, "last_price": None, "price_date": None})

    profiles = []
    for (pid, p), res in zip(PROFILES.items(), results):
        s = sims[pid]
        last = s["rebalances"][-1]
        window = returns.loc[:last["date"]].iloc[-VOL_LOOKBACK:]
        alloc, excluded = explain_allocation(window, last["weights"], p)
        status = getattr(res, "status", None) or "UNVALIDATED"
        profiles.append({
            "id": pid, "name": p["name"], "blurb": p["blurb"], "target_volatility_pct": p["target_vol"] * 100.0,
            "drawdown_limit_pct": p["dd_limit"] * 100.0, "caps_pct": {k: v * 100.0 for k, v in p["caps"].items()},
            "recommended_on": last["date"].strftime("%Y-%m-%d"), "guard_on": bool(last["guard_on"]), "allocation": alloc, "excluded": excluded,
            "harness_status": str(status),
            "p_value_in_sample": _clean(getattr(res, "in_sample_p_value", None)), "p_value_out_of_sample": _clean(getattr(res, "out_of_sample_p_value", None)),
            "bonferroni_bar": _clean(getattr(res, "bonferroni_alpha", None)),
            "metrics": {w: {k: _clean(v) if k != "n_days" else v for k, v in windows[pid][w].items()} for w in windows[pid]},
            "benchmark_metrics": {w: {k: _clean(v) if k != "n_days" else v for k, v in bench_win[w].items()} for w in bench_win},
            "growth_strategy": _series(s["equity"] / s["equity"].iloc[0] * 100.0), "growth_benchmark": _series(bench / bench.iloc[0] * 100.0),
            "drawdown_strategy_pct": _series(drawdown_series_pct(s["equity"]), 2), "drawdown_benchmark_pct": _series(drawdown_series_pct(bench), 2),
            "exposure_pct": _series(s["exposure_pct"], 1), "n_rebalances": len(s["rebalances"]), "cost_paid_pct_of_start": round(s["cost_paid"] / 100.0 * 100.0, 3),
        })
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data_through": returns.index[-1].strftime("%Y-%m-%d"),
        "simulation_start": start.strftime("%Y-%m-%d"), "in_sample_end": IS_END, "out_of_sample_start": OOS_START, "ledger_total": int(total),
        "disclaimer": DISCLAIMER, "benchmark": "Nifty 50 ETF buy-and-hold",
        "data_cleaning": {"rule": f"a one-day move above {BAD_PRINT_MOVE:.0%} that is undone within {BAD_PRINT_REVERT_DAYS} trading days is treated as a bad print and carried forward",
                          "removed": (prices.attrs.get("removed", []) if prices is not None else [])},
        "rule": {"vol_lookback_days": VOL_LOOKBACK, "rebalance_every_days": REBALANCE_EVERY, "cost_pct_per_side": COST_PCT * 100.0,
                 "cash_rate_pct": CASH_RATE * 100.0, "execution": "decided at the close of day t, carried out one day later"},
        "trend": trend_state(prices) if prices is not None else [],
        "assets": asset_rows, "correlation": {"labels": list(corr.index), "matrix": [[round(float(x), 2) for x in row] for row in corr.values]},
        "questionnaire": {"questions": QUESTIONS, "bands": BANDS}, "profiles": profiles,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the multi-asset advisory file for the web app (read-only research).")
    ap.add_argument("--register", action="store_true", help="count the 3 profiles in the hypothesis ledger (do this ONCE)")
    ap.add_argument("--refresh", action="store_true", help="re-download prices")
    args = ap.parse_args(argv)
    prices = load_prices(args.refresh)
    returns = daily_returns(prices)
    payload = build(returns, prices, register=args.register)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, allow_nan=False)
    os.replace(tmp, OUT_PATH)
    for p in payload["profiles"]:
        o, b = p["metrics"]["out_of_sample"], p["benchmark_metrics"]["out_of_sample"]
        print(f"[advisory] {p['name']:12s} OOS sharpe {o['sharpe']:.2f} (Nifty 50 {b['sharpe']:.2f})  max drawdown {o['max_drawdown_pct']:.1f}% (Nifty 50 {b['max_drawdown_pct']:.1f}%)  status {p['harness_status']}")
    print(f"[advisory] wrote {OUT_PATH}; ledger now {payload['ledger_total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
