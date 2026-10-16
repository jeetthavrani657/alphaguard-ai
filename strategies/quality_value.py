"""
strategies/quality_value.py

Quality + value ranking for a universe, using ANNUAL fundamentals. Frozen in
FUNDAMENTALS_PREREG.md before any return was looked at: none of the numbers
below are free, so change none of them without a new, separately registered
hypothesis.

The idea: buy companies that earn a high return on their equity (quality) AND
are cheap relative to those earnings (value). Either alone is a well-known
factor; the average of the two ranks avoids "cheap because it is broken" and
"great but priced for perfection".

  quality = ROE         = net income / shareholders' equity   (higher is better)
  value   = earn. yield = net income / market cap             (higher is better)
  score   = average of each stock's percentile rank on the two measures

Same boundary as every strategies/*.py file: a pure function. Prices and
fundamentals in, target weights out. It knows nothing about money, costs or
execution; engine/portfolio_backtest.py trades the weights at the NEXT open.
"""

import pandas as pd

TOP_N = 10                # hold the 10 best-scoring stocks, equal weight (a fifth of a 50-stock universe)
MIN_ELIGIBLE = 20         # fewer scoreable stocks than this and the ranking means little: hold cash instead
MAX_STALENESS_DAYS = 456  # newest annual statement must end within ~15 months of the formation date
NET_INCOME_ITEMS = ("Net Income Common Stockholders", "Net Income")   # first one present is used
EQUITY_ITEM = "Stockholders Equity"
SHARES_ITEM = "Ordinary Shares Number"
EPS_ITEM = "Basic EPS"
EPS_TOLERANCE = 0.15      # net income / shares must be within 15% of the company's own reported EPS
# Two data-sanity rules, both found on real data BEFORE the rule was frozen (see FUNDAMENTALS_PREREG.md):
#  1. only statements served in rupees are used (Infosys and HCLTech come back in US dollars);
#  2. net income / share count must agree with the reported EPS (Tata Motors Passenger Vehicles after
#     its demerger shows net income of Rs 82,390 crore against an EPS of -0.61: the inputs do not belong together).


def _latest_facts(facts: pd.DataFrame, formation_date: pd.Timestamp, strict: bool = False) -> dict:
    """
    For each symbol, the newest ANNUAL statement that was public on formation_date, as
    {symbol: {"period_end": ..., "net_income": ..., "equity": ..., "shares": ...}}.

    "Public" means assumed_available_from <= formation_date (period end + 90 days, set when the
    archive stored the row). A statement that ended after the lag window is invisible, which is
    what stops the rule peeking at results the market had not seen yet.

    strict=True adds a second condition: the archive must also have SEEN the figure by formation_date
    (first_seen_date <= formation_date). Forward paper books use it, because they recompute every
    formation date on every run and a later restatement must not leak back into an earlier date.
    Retrospective research leaves it off (everything was first seen "today", so strict would see nothing).

    facts: the fundamentals archive (research/fundamentals_snapshot.load_snapshot()) with columns
    symbol, freq, period_end, item, value, assumed_available_from, first_seen_date.
    """
    if facts.empty:
        return {}                                                 # nothing archived yet: nothing can be scored
    visible = facts[(facts["freq"] == "annual") & (facts["assumed_available_from"] <= formation_date)]
    if strict:
        visible = visible[visible["first_seen_date"] <= formation_date]
    out = {}
    for symbol, rows in visible.groupby("symbol"):
        newest = rows["period_end"].max()                         # the latest statement already public
        latest = rows[rows["period_end"] == newest]
        # if the archive stored several values for one item (a restatement), the last one wins
        values = latest.sort_values("first_seen_date").groupby("item")["value"].last()
        net_income = next((values[i] for i in NET_INCOME_ITEMS if i in values.index), None)
        if net_income is None or any(i not in values.index for i in (EQUITY_ITEM, SHARES_ITEM, EPS_ITEM)):
            continue                                              # an incomplete statement is skipped, never guessed
        shares, eps = float(values[SHARES_ITEM]), float(values[EPS_ITEM])
        if shares <= 0 or abs(float(net_income) / shares - eps) > EPS_TOLERANCE * abs(eps):
            continue                                              # rule 2: the inputs contradict the company's own EPS
        out[symbol] = {"period_end": newest, "net_income": float(net_income),
                       "equity": float(values[EQUITY_ITEM]), "shares": shares}
    return out


def score_universe(universe_data: dict, facts: pd.DataFrame, currency: dict, formation_date,
                   strict: bool = False) -> pd.DataFrame:
    """
    One row per scoreable stock on formation_date, best score first:
    columns ticker, roe, earnings_yield, score, period_end. Empty if nothing can be scored.

    currency: {symbol: reporting currency} from the archive. Only "INR" is scored; a symbol whose
    currency is unknown is skipped too (unverified is not the same as fine).
    """
    formation_date = pd.Timestamp(formation_date)
    latest = _latest_facts(facts, formation_date, strict)
    rows = []
    for ticker, entry in universe_data.items():
        symbol = ticker.replace(".NS", "")                        # the archive stores RELIANCE, the price files RELIANCE.NS
        info = latest.get(symbol)
        if info is None or currency.get(symbol) != "INR":         # rule 1
            continue
        if (formation_date - info["period_end"]).days > MAX_STALENESS_DAYS:
            continue                                              # the company stopped reporting or the archive lacks a year
        closes = entry["df"]["close"].loc[:formation_date]        # prices up to and including the formation date only
        if closes.empty or info["equity"] <= 0 or info["shares"] <= 0:
            continue                                              # ROE is meaningless on negative equity
        market_cap = float(closes.iloc[-1]) * info["shares"]
        rows.append({"ticker": ticker, "roe": info["net_income"] / info["equity"],
                     "earnings_yield": info["net_income"] / market_cap, "period_end": info["period_end"]})
    if not rows:
        return pd.DataFrame(columns=["ticker", "roe", "earnings_yield", "score", "period_end"])
    table = pd.DataFrame(rows)
    # percentile rank within today's eligible stocks (1.0 = best); the score is the average of the two
    table["score"] = (table["roe"].rank(pct=True) + table["earnings_yield"].rank(pct=True)) / 2
    # ties are broken by ticker so the result never depends on dict order
    return table.sort_values(["score", "ticker"], ascending=[False, True]).reset_index(drop=True)


def generate_target_weights(universe_data: dict, facts: pd.DataFrame, currency: dict, formation_dates,
                            top_n: int = TOP_N, strict: bool = False) -> pd.DataFrame:
    """
    Target weights indexed by formation date, one column per ticker: 1/top_n for the top-scoring stocks,
    0.0 for everything else (all zero = cash when fewer than MIN_ELIGIBLE stocks can be scored).
    Same shape the momentum strategy returns, so engine/portfolio_backtest.py runs it unchanged.
    """
    formation_dates = [pd.Timestamp(d) for d in formation_dates]
    weights = pd.DataFrame(0.0, index=pd.DatetimeIndex(formation_dates), columns=list(universe_data.keys()))
    for d in formation_dates:
        table = score_universe(universe_data, facts, currency, d, strict)
        if len(table) < MIN_ELIGIBLE:
            continue
        chosen = table["ticker"].head(top_n).tolist()
        weights.loc[d, chosen] = 1.0 / len(chosen)
    return weights
