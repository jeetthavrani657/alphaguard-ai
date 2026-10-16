"""
research/fundamentals_snapshot.py

A point-in-time archive of company fundamentals for the Nifty 50, built from the
free structured statements yfinance serves (annual and quarterly income statement,
balance sheet and cash flow). No PDFs, no paid API.

Why an archive and not just a download: yfinance shows today's numbers, including
any later restatement, with no record of when each figure first appeared. A backtest
on such data quietly sees the future. So every run records what it sees, when it
first saw it, and keeps a NEW row (never an overwrite) when a figure changes. From
today onward the archive is genuinely point-in-time.

Two ways to read it (see `known_as_of`):
  * strict:         only what this logger had actually seen by the date. Honest, but
                    it starts today, so it is empty for the past.
  * retrospective:  assume each period's figures became public a fixed lag after the
                    period end (annual +90 days, quarterly +60), and use the latest
                    values. Gives ~4-5 years of history now, but with restated, not
                    as-first-reported, numbers. Every retrospective result must say so.

Each row is tagged `pit_quality`: "observed" if the logger first saw the period soon
after it should have become public (that figure is trustworthy as point-in-time),
"backfilled" if it was already old on first sight (it is not).

Raw values are stored exactly as served (Indian rupees, not crore). Nothing here
computes a ratio or a signal: factor definitions are strategy design, and every
strategy is a hypothesis that must be pre-registered and counted first.

    python research/fundamentals_snapshot.py             # weekly gate: skips if run in the last 7 days
    python research/fundamentals_snapshot.py --force
    python research/fundamentals_snapshot.py --quality   # data-quality report on what is stored
    python research/fundamentals_snapshot.py --status
"""

import argparse
import csv
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import config

SNAPSHOT_PATH = os.path.join(PROJECT_ROOT, "data", "fundamentals", "yf_snapshot.csv")
LAST_RUN_PATH = os.path.join(PROJECT_ROOT, "data", "fundamentals", "yf_last_run.txt")
CURRENCY_PATH = os.path.join(PROJECT_ROOT, "data", "fundamentals", "yf_currency.csv")
COLUMNS = ["symbol", "statement", "freq", "period_end", "item", "value", "first_seen_utc",
           "assumed_available_from", "pit_quality"]
# (statement, freq) -> the yfinance Ticker attribute that serves it
SOURCES = {
    ("income", "annual"): "financials", ("income", "quarterly"): "quarterly_financials",
    ("balance", "annual"): "balance_sheet", ("balance", "quarterly"): "quarterly_balance_sheet",
    ("cashflow", "annual"): "cashflow", ("cashflow", "quarterly"): "quarterly_cashflow",
}
ASSUMED_LAG_DAYS = {"annual": 90, "quarterly": 60}   # SEBI: audited annual results within 60 days, quarterly within 45
OBSERVED_SLACK_DAYS = 14                             # first seen within this long after it should be public => "observed"
RUN_EVERY_DAYS = 7
SLEEP_SECONDS = 0.6


# --- turning what yfinance serves into archive rows (pure) -------------------------------------------

def pit_quality(first_seen: str, assumed_available_from: str) -> str:
    seen = datetime.strptime(first_seen[:10], "%Y-%m-%d").date()
    ready = datetime.strptime(assumed_available_from, "%Y-%m-%d").date()
    return "observed" if seen <= ready + timedelta(days=OBSERVED_SLACK_DAYS) else "backfilled"


def tidy(df, symbol: str, statement: str, freq: str, seen_at: str) -> list:
    """One yfinance statement (line items x periods) -> archive rows. Missing (NaN) cells are not stored."""
    rows = []
    if df is None or getattr(df, "empty", True):
        return rows
    for period in df.columns:
        period_end = pd.Timestamp(period).strftime("%Y-%m-%d")
        ready = (pd.Timestamp(period) + timedelta(days=ASSUMED_LAG_DAYS[freq])).strftime("%Y-%m-%d")
        quality = pit_quality(seen_at, ready)
        for item, value in df[period].items():
            if pd.isna(value):
                continue
            rows.append({"symbol": symbol, "statement": statement, "freq": freq, "period_end": period_end,
                         "item": str(item), "value": repr(float(value)), "first_seen_utc": seen_at,
                         "assumed_available_from": ready, "pit_quality": quality})
    return rows


def _key(r: dict) -> tuple:
    return (r["symbol"], r["statement"], r["freq"], r["period_end"], r["item"], r["value"])


def existing_keys(path: str | None = None) -> set:
    path = path or SNAPSHOT_PATH
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {_key(r) for r in csv.DictReader(f)}


def append_new(rows: list, path: str | None = None) -> int:
    """
    Append only (symbol, statement, freq, period, item, VALUE) combinations not already stored. The same
    figure seen again adds nothing and keeps its original first_seen; a CHANGED figure (a restatement)
    adds a new row, so the history of what was known when is never lost.
    """
    path = path or SNAPSHOT_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seen = existing_keys(path)
    fresh = []
    for r in rows:
        k = _key(r)
        if k not in seen:
            seen.add(k)
            fresh.append(r)
    if not fresh:
        return 0
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        w.writerows(fresh)
    return len(fresh)


def fetch_currency(symbol: str, ticker_factory=None):
    """
    The currency yfinance reports the statements in ("INR", "USD", ...), or None if it cannot be read.
    It matters: two Nifty 50 names (Infosys, HCLTech) are served in US dollars, which makes any ratio of
    a statement figure to a rupee share price off by ~80x. Raw values are archived as served, so the
    currency has to be archived next to them.
    """
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    try:
        return ticker_factory(f"{symbol}.NS").get_info().get("financialCurrency")
    except Exception:
        return None


def load_currency(path: str | None = None) -> dict:
    """{symbol: currency} using the newest row stored for each symbol (rows are only added when it changes)."""
    path = path or CURRENCY_PATH
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["symbol"]: r["financial_currency"] for r in sorted(rows, key=lambda r: r["first_seen_utc"])}


def append_currency(symbol: str, currency, seen_at: str, path: str | None = None) -> bool:
    """Store a symbol's currency if it is new or changed. Returns True if a row was written."""
    if not currency or load_currency(path).get(symbol) == currency:
        return False
    path = path or CURRENCY_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "financial_currency", "first_seen_utc"])
        if new_file:
            w.writeheader()
        w.writerow({"symbol": symbol, "financial_currency": currency, "first_seen_utc": seen_at})
    return True


def fetch_symbol(symbol: str, seen_at: str, ticker_factory=None) -> tuple:
    """All six statements for one stock. Returns (rows, problems); a failing statement is reported, not fatal."""
    if ticker_factory is None:
        import yfinance as yf
        ticker_factory = yf.Ticker
    ticker = ticker_factory(f"{symbol}.NS")
    rows, problems = [], []
    for (statement, freq), attr in SOURCES.items():
        try:
            rows += tidy(getattr(ticker, attr), symbol, statement, freq, seen_at)
        except Exception as e:
            problems.append(f"{symbol} {attr}: {type(e).__name__}: {str(e)[:80]}")
    return rows, problems


# --- reading the archive back --------------------------------------------------------------------------------

def load_snapshot(path: str | None = None) -> pd.DataFrame:
    path = path or SNAPSHOT_PATH
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path)
    df["value"] = df["value"].astype(float)
    df["first_seen_date"] = pd.to_datetime(df["first_seen_utc"].str[:10])
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["assumed_available_from"] = pd.to_datetime(df["assumed_available_from"])
    return df


def known_as_of(df: pd.DataFrame, as_of, mode: str = "strict") -> pd.DataFrame:
    """
    What could have been known on `as_of`: the latest value of each (symbol, statement, freq, period, item).
      mode="strict":         only rows this logger had already seen by `as_of` (true point-in-time).
      mode="retrospective":  rows whose assumed public date is on or before `as_of`, latest value
                             (restated numbers: use only where the result is labelled non-PIT).
    """
    if mode not in ("strict", "retrospective"):
        raise ValueError("mode must be 'strict' or 'retrospective'")
    as_of = pd.Timestamp(as_of)
    if mode == "strict":
        visible = df[df["first_seen_date"] <= as_of]
    else:
        visible = df[df["assumed_available_from"] <= as_of]
    keys = ["symbol", "statement", "freq", "period_end", "item"]
    return (visible.sort_values("first_seen_date").groupby(keys, as_index=False).tail(1)
            .sort_values(keys).reset_index(drop=True))


# --- is the data any good? ----------------------------------------------------------------------------------

def _close(a, b, rel=0.005, scale=None):
    scale = max(abs(a), abs(b), 1.0) if scale is None else scale
    return abs(a - b) <= rel * scale


def quality_report(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (symbol, annual period) with accounting-identity results on the latest stored values:
    balance sheet (assets = liabilities + equity) and cash flow (operating + investing + financing + FX =
    net change in cash). Identities that cannot be evaluated are None, never silently passed.
    """
    if df.empty:
        return pd.DataFrame(columns=["symbol", "period_end", "balance_ok", "cashflow_ok"])
    latest = df.sort_values("first_seen_date").groupby(
        ["symbol", "statement", "freq", "period_end", "item"], as_index=False).tail(1)
    annual = latest[latest["freq"] == "annual"]
    out = []
    for (symbol, period), g in annual.groupby(["symbol", "period_end"]):
        v = dict(zip(g["item"], g["value"]))
        need_b = ("Total Assets", "Total Liabilities Net Minority Interest", "Total Equity Gross Minority Interest")
        balance = _close(v[need_b[0]], v[need_b[1]] + v[need_b[2]]) if all(k in v for k in need_b) else None
        need_c = ("Operating Cash Flow", "Investing Cash Flow", "Financing Cash Flow", "Changes In Cash")
        # Tolerance: 2% of the LARGEST flow. Measured on the first archive (191 stock-years): the median residual
        # is 0.08% of the largest flow, 90% are within 2% and 97% within 5%; the rest are real definitional gaps
        # (cash of discontinued operations, restricted cash). A tolerance tied to the small net change instead
        # flagged 106 of 191, nearly all of them rounding.
        flows = [v[k] for k in need_c[:3]] if all(k in v for k in need_c) else []
        cashflow = (_close(sum(flows) + v.get("Effect Of Exchange Rate Changes", 0.0), v["Changes In Cash"],
                           rel=0.02, scale=max(abs(x) for x in flows))
                    if flows else None)
        out.append({"symbol": symbol, "period_end": period.date().isoformat(), "balance_ok": balance, "cashflow_ok": cashflow})
    return pd.DataFrame(out)


def status(path: str | None = None) -> str:
    df = load_snapshot(path)
    if df.empty:
        return "No fundamentals archived yet."
    n_sym = df["symbol"].nunique()
    periods = df.groupby("freq")["period_end"].agg(["min", "max"])
    q = df.drop_duplicates(["symbol", "freq", "period_end"])["pit_quality"].value_counts().to_dict()
    span = lambda f: (f"{periods.loc[f, 'min'].date()}..{periods.loc[f, 'max'].date()}" if f in periods.index else "none")
    return (f"{len(df):,} figures, {n_sym} stocks. First logged {df['first_seen_utc'].min()}, latest {df['first_seen_utc'].max()}. "
            f"Annual periods {span('annual')}, quarterly {span('quarterly')}. "
            f"Point-in-time quality by stock-period: {q}.")


# --- the command ---------------------------------------------------------------------------------------------------

def _ran_recently(days: int = RUN_EVERY_DAYS, path: str | None = None) -> bool:
    path = path or LAST_RUN_PATH
    if not os.path.exists(path):
        return False
    try:
        last = datetime.strptime(open(path).read().strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return (date.today() - last).days < days


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Archive Nifty 50 fundamentals from yfinance, point in time.")
    ap.add_argument("--force", action="store_true", help=f"run even if it already ran in the last {RUN_EVERY_DAYS} days")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--quality", action="store_true", help="accounting-identity report on what is stored; fetches nothing")
    args = ap.parse_args(argv)

    if args.status:
        print(status())
        return 0
    if args.quality:
        q = quality_report(load_snapshot())
        if q.empty:
            print("Nothing stored yet.")
            return 0
        for col in ("balance_ok", "cashflow_ok"):
            vals = q[col]
            print(f"{col}: {int((vals == True).sum())} pass, {int((vals == False).sum())} FAIL, {int(vals.isna().sum())} not evaluable, of {len(q)} stock-years")
        bad = q[(q["balance_ok"] == False) | (q["cashflow_ok"] == False)]
        for _, r in bad.head(25).iterrows():
            print(f"  FAIL {r['symbol']} {r['period_end']}: balance_ok={r['balance_ok']} cashflow_ok={r['cashflow_ok']}")
        return 0
    if not args.force and _ran_recently():
        print(f"[fundamentals] already ran within {RUN_EVERY_DAYS} days; nothing to do (use --force to override)")
        return 0

    seen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_total, problems, stocks_ok = 0, [], 0
    for i, symbol in enumerate(config.UNIVERSE):
        rows, probs = fetch_symbol(symbol, seen_at)
        problems += probs
        ccy = fetch_currency(symbol)
        if ccy is None:
            problems.append(f"{symbol}: reporting currency unavailable")
        else:
            append_currency(symbol, ccy, seen_at)
        if rows:
            stocks_ok += 1
            new_total += append_new(rows)
        if i < len(config.UNIVERSE) - 1:
            time.sleep(SLEEP_SECONDS)
    print(f"[fundamentals] {new_total:,} new figures archived at {seen_at}; {stocks_ok} of {len(config.UNIVERSE)} stocks returned data")
    for p in problems[:15]:
        print(f"[fundamentals]   problem: {p}")
    if len(problems) > 15:
        print(f"[fundamentals]   ... and {len(problems) - 15} more")
    print("[fundamentals] " + status())
    if stocks_ok:
        os.makedirs(os.path.dirname(LAST_RUN_PATH), exist_ok=True)
        with open(LAST_RUN_PATH, "w") as f:
            f.write(seen_at)
    return 0 if stocks_ok else 1


if __name__ == "__main__":
    sys.exit(main())
