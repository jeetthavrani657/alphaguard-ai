"""
app.py

Web app front-end for the backtesting system (Streamlit). Five pages:

1. "Run a backtest" -- pick a symbol, strategy and parameters, and see the
   strategy vs buy-and-hold: metrics, equity curve, and trade log. It
   calls the SAME engine the run_*.py scripts use (data/, strategies/,
   engine/) -- no separate logic lives here.
2. "Nifty 50 universe" -- MA crossover or RSI run on every Nifty 50 stock and
   pooled, with per-stock results and the zero-skill Sharpe check.
3. "Momentum (Nifty 50)" -- the pre-registered cross-sectional momentum
   strategy, with its turnover/cost drag and an optional zero-skill test.
4. "Forward test" -- paper-trade log of the rule frozen in FORWARD_TEST.md.
5. "Research record" -- the project's findings and the hypothesis ledger.

Research only. There is no broker connection and no order placement.

Run from the project root:  python -m streamlit run app.py
"""

import os
import sys

# Same sibling-import convention the run_*.py scripts use: add each code
# folder to Python's search path so "import loader" etc. work.
ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(ROOT, sub))
sys.path.insert(0, ROOT)

import json

import pandas as pd
import streamlit as st

import config
import buy_and_hold
import ma_crossover
import rsi_reversion
from loader import load_price_data
from validator import validate_price_data
from backtest import run_backtest
from metrics import compute_metrics
from universe import load_universe, run_strategy_on_universe, per_symbol_comparison_table
from run_momentum_strategy import build_window_inputs, _run_window, random_selection_sharpes
from cross_sectional_momentum import LOOKBACK_DAYS, SKIP_DAYS, TOP_N
from forward_log import (build_report, RULE as FORWARD_RULE, FIRST_COUNTED_ENTRY, MIN_POSITIONS,
                         TARGET_WIN_RATE, BREAKEVEN_WIN_RATE, SNAPSHOT_PATH)

st.set_page_config(page_title="NSE Backtesting System", layout="wide")


# --- Cached helpers ---------------------------------------------------
# st.cache_data remembers a function's result so moving a slider does not
# re-download or re-validate the same stock every time.

@st.cache_data(show_spinner=False)
def load_and_validate(symbol: str):
    """Load the symbol's full history (needed so a 200-day moving average
    has its warm-up data) and run the data-quality checks once."""
    df = load_price_data(symbol, config.START_DATE, config.END_DATE)
    report = validate_price_data(df, symbol.upper() + ".NS")
    return df, report


def run_one(df, report, strategy_module, params, start, end, capital):
    """Signal -> backtest -> metrics for one strategy. Signals are built on
    the full history; run_backtest then trades only inside [start, end]."""
    signal = strategy_module.generate_signals(df, **params)
    result = run_backtest(df, signal, report, start, end, initial_capital=capital)
    metrics = compute_metrics(
        result["equity_curve"], result["trade_log"], capital,
        result["position"], risk_free_rate=config.RISK_FREE_RATE,
    )
    return result, metrics


# --- Page 1: run a backtest -------------------------------------------

def page_backtest():
    st.title("Run a backtest")
    st.caption("Daily NSE data, after realistic Indian delivery costs. Research only.")

    with st.sidebar:
        st.header("Inputs")
        symbol = st.text_input("NSE symbol (no .NS)", value="RELIANCE").strip().upper()
        strategy_name = st.selectbox("Strategy", ["MA crossover", "RSI reversion"])

        if strategy_name == "MA crossover":
            fast = st.number_input("Fast MA (days)", 5, 200, config.MA_CROSSOVER_PARAMS["fast"])
            slow = st.number_input("Slow MA (days)", 20, 400, config.MA_CROSSOVER_PARAMS["slow"])
            strategy_module, params = ma_crossover, {"fast": int(fast), "slow": int(slow)}
        else:
            period = st.number_input("RSI period", 2, 50, config.RSI_REVERSION_PARAMS["period"])
            oversold = st.number_input("Enter below RSI", 5, 50, config.RSI_REVERSION_PARAMS["oversold"])
            exit_level = st.number_input("Exit above RSI", 30, 90, config.RSI_REVERSION_PARAMS["exit_level"])
            strategy_module = rsi_reversion
            params = {"period": int(period), "oversold": float(oversold), "exit_level": float(exit_level)}

        start = st.date_input("Start", pd.Timestamp("2015-01-01"),
                              min_value=pd.Timestamp(config.START_DATE), max_value=pd.Timestamp(config.END_DATE))
        end = st.date_input("End", pd.Timestamp(config.END_DATE),
                            min_value=pd.Timestamp(config.START_DATE), max_value=pd.Timestamp(config.END_DATE))
        capital = st.number_input("Starting capital (Rs)", 100_000, 100_000_000, config.INITIAL_CAPITAL, step=100_000)
        go = st.button("Run backtest", type="primary")

    if not go:
        st.info("Choose a symbol and strategy in the sidebar, then click **Run backtest**.")
        return
    if start >= end:
        st.error("Start date must be before end date.")
        return

    try:
        with st.spinner(f"Loading and validating {symbol}..."):
            df, report = load_and_validate(symbol)
    except Exception as e:
        # loader.py raises a clear message for an invalid or delisted symbol.
        st.error(f"Could not load {symbol}: {e}")
        return

    start_s, end_s = str(start), str(end)
    try:
        strat_result, strat_m = run_one(df, report, strategy_module, params, start_s, end_s, capital)
        bh_result, bh_m = run_one(df, report, buy_and_hold, {}, start_s, end_s, capital)
    except RuntimeError as e:
        # The discontinuity gate refuses to run across an unreviewed or
        # artifact price move. That is the safety net working, so show
        # the reason instead of overriding it.
        st.error("Backtest blocked by the data-safety gate.")
        st.code(str(e))
        return
    except (AssertionError, ValueError) as e:
        st.error(f"This configuration can't run on {symbol}: {e}")
        return

    # Metrics table: strategy next to buy-and-hold.
    rows = [
        ("Total return (%)", "total_return_pct", "{:.2f}"),
        ("CAGR (%)", "cagr_pct", "{:.2f}"),
        ("Max drawdown (%)", "max_drawdown_pct", "{:.2f}"),
        ("Sharpe", "sharpe_ratio", "{:.2f}"),
        ("Sortino", "sortino_ratio", "{:.2f}"),
        ("Trades", "total_trades", "{:.0f}"),
        ("Win rate (%)", "win_rate_pct", "{:.1f}"),
        ("Market exposure (%)", "market_exposure_pct", "{:.1f}"),
        ("Final equity (Rs)", "final_equity", "{:,.0f}"),
    ]
    table = pd.DataFrame({
        "Metric": [label for label, _, _ in rows],
        strategy_name: [fmt.format(strat_m[key]) if pd.notna(strat_m[key]) else "n/a" for _, key, fmt in rows],
        "Buy & hold": [fmt.format(bh_m[key]) if pd.notna(bh_m[key]) else "n/a" for _, key, fmt in rows],
    })
    st.subheader(f"{symbol}: {strategy_name} vs buy & hold  ({start_s} to {end_s})")
    st.dataframe(table, hide_index=True, width="stretch")

    n_trades = int(strat_m["total_trades"])
    if n_trades < 30:
        st.warning(
            f"Only {n_trades} closed trades. That is too few to say anything about "
            "the strategy -- one lucky trade can drive the whole result. See the "
            "Research record page for how the multi-symbol tests handle this."
        )
    if strat_m["market_exposure_pct"] < 95:
        st.info(
            f"The strategy was invested only {strat_m['market_exposure_pct']:.0f}% of the time, "
            "so its Sharpe is not directly comparable to buy & hold's. "
            "See the zero-skill benchmark in the Research record."
        )

    st.subheader("Equity curve")
    curves = pd.DataFrame({
        strategy_name: strat_result["equity_curve"],
        "Buy & hold": bh_result["equity_curve"],
    })
    st.line_chart(curves)

    st.subheader("Trade log")
    if len(strat_result["trade_log"]) == 0:
        st.write("No closed trades in this window.")
    else:
        # Round only the number columns (rounding a date column raises a warning).
        trades = strat_result["trade_log"].copy()
        num_cols = trades.select_dtypes("number").columns
        trades[num_cols] = trades[num_cols].round(2)
        st.dataframe(trades, hide_index=True, width="stretch")

    with st.expander("Data-quality notes for this symbol"):
        for check in report["checks"]:
            st.write(f"{'PASS' if check['passed'] else 'NOTE'}: {check['name']} "
                     f"(affected rows: {check['count']})")


# --- Page 2: cross-sectional momentum ---------------------------------

def choose_window():
    """Sidebar widgets for picking the test window. Call inside `with st.sidebar:`.
    Returns (start, end) as 'YYYY-MM-DD' strings. The presets are the project's
    fixed in-sample / out-of-sample split."""
    window = st.selectbox("Window", ["Out-of-sample (2020-07 to 2025)", "In-sample (2015 to 2020-06)",
                                      "Full period", "Custom"])
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    presets = {
        "Out-of-sample (2020-07 to 2025)": (oos_start, config.END_DATE),
        "In-sample (2015 to 2020-06)": (config.START_DATE, config.IN_SAMPLE_END_DATE),
        "Full period": (config.START_DATE, config.END_DATE),
    }
    if window == "Custom":
        c_start = st.date_input("Start", pd.Timestamp("2018-01-01"),
                                min_value=pd.Timestamp(config.START_DATE), max_value=pd.Timestamp(config.END_DATE))
        c_end = st.date_input("End", pd.Timestamp(config.END_DATE),
                              min_value=pd.Timestamp(config.START_DATE), max_value=pd.Timestamp(config.END_DATE))
        return str(c_start), str(c_end)
    return presets[window]


def fmt(value, spec):
    """Format a metric for display; NaN or infinity (e.g. a profit factor with no losing trade) shows as n/a."""
    if value is None or pd.isna(value) or value in (float("inf"), float("-inf")):
        return "n/a"
    return spec.format(value)


@st.cache_resource(show_spinner=False)
def load_nifty50():
    """Load and validate the whole Nifty 50 universe once per app session."""
    universe_data, _failed = load_universe(config.UNIVERSE, config.START_DATE, config.END_DATE, verbose=False)
    return universe_data


def page_momentum():
    st.title("Cross-sectional momentum (Nifty 50)")
    st.caption("Ranks stocks against each other, not against their own history. "
               "Pre-registered in MOMENTUM_METHODOLOGY.md before any result existed.")

    st.warning(
        "**Pre-registered result: not a validated strategy.** Picking the same number of stocks at "
        "random, with the same costs, does about as well: out-of-sample momentum's Sharpe ranked at the "
        "**87.5th percentile** of 200 random-selection portfolios (in-sample: 88th). The bar set in "
        "advance was the 95th percentile to count as a win, and 90th or lower counts as not beating "
        "random. Full detail in MOMENTUM_FINDINGS.md (Research record page)."
    )

    st.info(
        f"**Frozen parameters -- deliberately not editable:** rank by the {LOOKBACK_DAYS}-day return "
        f"skipping the most recent {SKIP_DAYS} days (the standard 12-1 convention), hold the top {TOP_N} "
        "of the eligible stocks equal-weight, rebalance monthly (full rebalance), long-only, "
        "same cost model as the other Nifty 50 tests. They are fixed because they were registered before "
        "any result was seen; sliders would turn one registered hypothesis into a parameter search, "
        "and every extra try makes the next result harder to trust."
    )

    with st.sidebar:
        st.header("Inputs")
        start_s, end_s = choose_window()

        do_zero_skill = st.checkbox("Also run the zero-skill benchmark", value=False,
                                    help="Runs many portfolios that pick the same number of stocks at random. "
                                         "Slow: about 1-2 seconds per simulation.")
        n_sims = st.slider("Simulations", 20, 200, 30, step=10, disabled=not do_zero_skill)
        go = st.button("Run momentum", type="primary")

    if not go:
        st.info("Choose a window in the sidebar, then click **Run momentum**. "
                "The first run loads all 50 stocks and takes a minute.")
        return
    if start_s >= end_s:
        st.error("Start date must be before end date.")
        return

    with st.spinner("Loading Nifty 50 (first time only)..."):
        universe_data = load_nifty50()

    try:
        with st.spinner("Ranking and backtesting..."):
            eligible, weights, blocked = build_window_inputs(universe_data, start_s, end_s)
            mom = _run_window(eligible, weights, start_s, end_s, "momentum", verbose=False)
            bh = run_strategy_on_universe(eligible, buy_and_hold, {}, start_s, end_s, verbose=False)
    except (ValueError, RuntimeError, AssertionError) as e:
        st.error(f"Could not run this window: {e}")
        return

    m, bm = mom["metrics"], bh["aggregate_metrics"]
    st.subheader(f"Momentum vs buy & hold  ({start_s} to {end_s})")
    table = pd.DataFrame({
        "Metric": ["CAGR (%)", "Sharpe", "Max drawdown (%)", "Time invested (%)"],
        "Momentum": [f"{m['cagr_pct']:.2f}", f"{m['sharpe_ratio']:.2f}", f"{m['max_drawdown_pct']:.2f}",
                     f"{mom['exposure_pct']:.1f}"],
        "Buy & hold (same stocks)": [f"{bm['cagr_pct']:.2f}", f"{bm['sharpe_ratio']:.2f}",
                                     f"{bm['max_drawdown_pct']:.2f}", f"{bm['market_exposure_pct']:.1f}"],
    })
    st.dataframe(table, hide_index=True, width="stretch")

    st.subheader("What it costs to trade this")
    costs_pct = mom["total_costs"] / config.INITIAL_CAPITAL * 100
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rebalances", mom["n_rebalances"])
    c2.metric("Avg turnover / month", f"{mom['avg_turnover_pct']:.0f}%")
    c3.metric("Total costs", f"Rs {mom['total_costs']:,.0f}")
    c4.metric("Costs / starting capital", f"{costs_pct:.1f}%")
    st.caption("Turnover is the share of the portfolio traded at each monthly rebalance. "
               "Momentum trades far more than the moving-average strategies, and every trade pays "
               "brokerage, STT, exchange charges, GST, stamp duty and slippage.")

    if mom["n_rebalances"] < 24:
        st.warning(f"Only {mom['n_rebalances']} monthly rebalances. The pre-registered rule treats fewer "
                   "than 24 as inconclusive.")
    st.caption(f"Ranked over {len(eligible)} eligible stocks. Excluded by the data-safety gate for this "
               f"window: {', '.join(t for t, _ in blocked) or 'none'}.")

    st.subheader("Growth of 100")
    curves = pd.DataFrame({
        "Momentum": mom["result"]["equity_curve"] / mom["result"]["equity_curve"].iloc[0] * 100,
        "Buy & hold": bh["combined_equity_curve"] / bh["combined_equity_curve"].iloc[0] * 100,
    })
    st.line_chart(curves)

    if do_zero_skill:
        st.subheader("Zero-skill benchmark: random picks, same stocks, same costs")
        bar = st.progress(0.0, text="Running random-selection portfolios...")
        sharpes = random_selection_sharpes(eligible, weights, start_s, end_s, n_sims,
                                           on_progress=lambda f: bar.progress(f))
        bar.empty()
        pct = float((sharpes < m["sharpe_ratio"]).mean() * 100)
        verdict = ("beats the zero-skill benchmark" if pct >= 95 else
                   "does NOT beat the zero-skill benchmark" if pct <= 90 else
                   "is INCONCLUSIVE against the zero-skill benchmark (borderline)")
        a, b, c = st.columns(3)
        a.metric("Momentum Sharpe", f"{m['sharpe_ratio']:.2f}")
        b.metric("Random-pick Sharpe (mean)", f"{sharpes.mean():.2f}")
        c.metric("Momentum's percentile", f"{pct:.0f}th")
        if n_sims >= 100:
            (st.success if pct >= 95 else st.error if pct <= 90 else st.warning)(f"Momentum {verdict}.")
        else:
            # With few simulations the percentile moves in coarse steps and a lucky small
            # sample can look like a win (20 simulations once gave "95th" here when 200 give
            # 87.5th) -- so no verdict is issued below 100 simulations.
            st.info(f"Only {len(sharpes)} simulations, so no verdict: the percentile is too coarse and "
                    "noisy to call. Use 100 or more. The registered result, from 200 simulations, "
                    "is 87.5th percentile out-of-sample (does not beat random selection).")
        st.caption("Bar set in advance: 95th percentile or higher to count as a win, 90th or lower as a "
                   "loss, in between is inconclusive. Even with 200 simulations a percentile is uncertain "
                   "by roughly +/-2-3 points.")
        counts = pd.cut(pd.Series(sharpes), bins=15).value_counts().sort_index()
        counts.index = [f"{iv.mid:.2f}" for iv in counts.index]
        st.bar_chart(counts)
        st.caption("Distribution of Sharpe ratios from random stock selection. Momentum's own Sharpe is the "
                   "number to compare against this spread.")

    st.subheader("Holdings at the end of the window")
    last_day = mom["result"]["equity_curve"].index[-1]
    rows = []
    for ticker, n in mom["result"]["final_shares"].items():
        if n > 0:
            price = float(eligible[ticker]["df"]["close"].loc[:last_day].iloc[-1])
            rows.append({"Symbol": ticker.replace(".NS", ""), "Shares": n, "Value (Rs)": round(n * price)})
    holdings = pd.DataFrame(rows).sort_values("Value (Rs)", ascending=False) if rows else pd.DataFrame()
    st.dataframe(holdings, hide_index=True, width="stretch")
    st.caption("Research output showing what the rule held at the end of the test window, not a recommendation.")

    with st.expander("Rebalance log"):
        st.dataframe(mom["result"]["rebalance_log"].round(2), hide_index=True, width="stretch")


# --- Page: Nifty 50 universe ---------------------------------------------

def page_universe():
    st.title("Nifty 50 universe")
    st.caption("Runs one strategy on every Nifty 50 stock separately, then pools the results. "
               "One stock's handful of trades is not a sample; a few hundred pooled trades is.")

    with st.sidebar:
        st.header("Inputs")
        strategy_name = st.selectbox("Strategy", ["MA crossover", "RSI reversion"], key="uni_strategy")
        if strategy_name == "MA crossover":
            fast = st.number_input("Fast MA (days)", 5, 200, config.MA_CROSSOVER_PARAMS["fast"], key="uni_fast")
            slow = st.number_input("Slow MA (days)", 20, 400, config.MA_CROSSOVER_PARAMS["slow"], key="uni_slow")
            strategy_module, params = ma_crossover, {"fast": int(fast), "slow": int(slow)}
            is_default = params == config.MA_CROSSOVER_PARAMS
        else:
            period = st.number_input("RSI period", 2, 50, config.RSI_REVERSION_PARAMS["period"], key="uni_period")
            oversold = st.number_input("Enter below RSI", 5, 50, config.RSI_REVERSION_PARAMS["oversold"], key="uni_over")
            exit_level = st.number_input("Exit above RSI", 30, 90, config.RSI_REVERSION_PARAMS["exit_level"], key="uni_exit")
            strategy_module = rsi_reversion
            params = {"period": int(period), "oversold": float(oversold), "exit_level": float(exit_level)}
            is_default = params == {k: float(v) if k != "period" else v for k, v in config.RSI_REVERSION_PARAMS.items()}
        start_s, end_s = choose_window()
        go = st.button("Run on Nifty 50", type="primary", key="uni_go")

    if not is_default:
        st.warning(
            "**Exploratory settings.** These differ from the project's registered defaults. Every different "
            "setting you try is another hypothesis, and this page does not add it to the hypothesis ledger, "
            "so a good-looking number found by trying settings here is expected by chance. The project's "
            "own 109-setting sweep found nothing (Research record page)."
        )

    if not go:
        st.info("Choose a strategy and window in the sidebar, then click **Run on Nifty 50**. "
                "The first run loads all 50 stocks and takes a minute; RSI is slower than MA crossover.")
        return
    if start_s >= end_s:
        st.error("Start date must be before end date.")
        return

    with st.spinner("Loading Nifty 50 (first time only)..."):
        universe_data = load_nifty50()

    try:
        with st.spinner(f"Running {strategy_name} on every stock..."):
            strat = run_strategy_on_universe(universe_data, strategy_module, params, start_s, end_s, verbose=False)
            if not strat["per_symbol"]:
                st.error("No stock could run this strategy in this window.")
                return
            # Buy & hold on exactly the stocks the strategy actually ran on, so the two columns
            # cover the same names (MA crossover skips stocks with too little history to warm up).
            same_stocks = {t: universe_data[t] for t in strat["per_symbol"]}
            bh = run_strategy_on_universe(same_stocks, buy_and_hold, {}, start_s, end_s, verbose=False)
    except (ValueError, RuntimeError, AssertionError) as e:
        st.error(f"Could not run this window: {e}")
        return

    m, bm = strat["aggregate_metrics"], bh["aggregate_metrics"]
    st.subheader(f"{strategy_name} vs buy & hold, pooled across {m['n_symbols_included']} stocks  ({start_s} to {end_s})")
    table = pd.DataFrame({
        "Metric": ["CAGR (%)", "Sharpe", "Sortino", "Max drawdown (%)", "Time invested (%)",
                   "Pooled trades", "Win rate (%)", "Profit factor"],
        strategy_name: [fmt(m["cagr_pct"], "{:.2f}"), fmt(m["sharpe_ratio"], "{:.2f}"),
                        fmt(m["sortino_ratio"], "{:.2f}"), fmt(m["max_drawdown_pct"], "{:.2f}"),
                        fmt(m["market_exposure_pct"], "{:.1f}"), fmt(m["total_trades"], "{:.0f}"),
                        fmt(m["win_rate_pct"], "{:.1f}"), fmt(m["profit_factor"], "{:.2f}")],
        "Buy & hold (same stocks)": [fmt(bm["cagr_pct"], "{:.2f}"), fmt(bm["sharpe_ratio"], "{:.2f}"),
                                     fmt(bm["sortino_ratio"], "{:.2f}"), fmt(bm["max_drawdown_pct"], "{:.2f}"),
                                     fmt(bm["market_exposure_pct"], "{:.1f}"), "-", "-", "-"],
    })
    st.dataframe(table, hide_index=True, width="stretch")

    # The zero-skill check (FINDINGS.md Section 4). A strategy that is only partly invested has
    # lower volatility than buy & hold, and Sharpe is unchanged by diluting with cash -- so a
    # partly-invested strategy with NO timing skill scores the same Sharpe as buy & hold. Only a
    # Sharpe above buy & hold's would suggest skill.
    gap = m["sharpe_ratio"] - bm["sharpe_ratio"]
    c1, c2 = st.columns(2)
    c1.metric("Sharpe minus the zero-skill benchmark", f"{gap:+.2f}",
              help="Zero-skill benchmark = buy & hold's Sharpe (dilution with cash leaves Sharpe unchanged).")
    c2.metric("Time invested", f"{m['market_exposure_pct']:.0f}%")
    if gap <= 0.05:
        st.info(f"A gap at or below zero means no evidence of timing skill: a strategy invested "
                f"{m['market_exposure_pct']:.0f}% of the time, choosing when at random, would score about "
                "buy & hold's Sharpe. (Explained in FINDINGS.md Section 4.)")
    if m["total_trades"] < 30:
        st.warning(f"Only {int(m['total_trades'])} pooled trades -- too few to say anything.")

    st.subheader("Growth of 100")
    curves = pd.DataFrame({
        strategy_name: strat["combined_equity_curve"] / strat["combined_equity_curve"].iloc[0] * 100,
        "Buy & hold": bh["combined_equity_curve"] / bh["combined_equity_curve"].iloc[0] * 100,
    })
    st.line_chart(curves)

    st.subheader("Stock by stock")
    per = per_symbol_comparison_table(strat)
    view = per[["total_return_pct", "cagr_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades",
                "win_rate_pct", "market_exposure_pct"]].copy()
    view.index = [t.replace(".NS", "") for t in view.index]
    view.columns = ["Total return (%)", "CAGR (%)", "Sharpe", "Max drawdown (%)", "Trades", "Win rate (%)",
                    "Time invested (%)"]
    st.dataframe(view.sort_values("Sharpe", ascending=False).round(2), width="stretch")
    st.caption("Each stock is its own Rs 10 lakh book; the pooled figures above sum those books. "
               "Sorted by Sharpe only for readability -- do not read the top of this list as a shortlist: "
               "with 49 stocks, some look good by chance.")

    if strat["blocked"]:
        with st.expander(f"{len(strat['blocked'])} stocks excluded from this window"):
            for ticker, reason in strat["blocked"]:
                st.write(f"**{ticker.replace('.NS', '')}**: {reason[:200]}")
            st.caption("Excluded by the data-safety gate (an unreviewed price jump inside the window), "
                       "for listing too recently for the strategy's warm-up, or for having no data in the window.")


# --- Page: forward test ----------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def forward_report():
    """Load the Nifty 50 through today and build the forward-test report (cached for an hour)."""
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    universe_data, _ = load_universe(config.UNIVERSE, config.START_DATE, today, verbose=False)
    return build_report(universe_data)


def page_forward():
    st.title("Forward test")
    st.caption("A paper-trade log of one rule frozen before any of this data existed (FORWARD_TEST.md). "
               "It records what the rule WOULD have done. No orders, no broker, not trading advice.")

    st.info(
        f"**Frozen rule:** buy when RSI(14) < {FORWARD_RULE['oversold']} and the stock is above its "
        f"200-day average; exit at +{FORWARD_RULE['take_profit']:.0%}, at a {FORWARD_RULE['stop_loss']:.0%} "
        f"hard stop, or after {FORWARD_RULE['max_hold_days']} trading days. Nifty 50. A win means 'closed above "
        f"zero after costs, or still open and above water' -- an underwater open position counts as a loss. "
        f"Only entries filled on or after {FIRST_COUNTED_ENTRY} count."
    )
    st.warning(
        f"**Expect below {TARGET_WIN_RATE:.0f}%.** The backtest said about 84%, and the nearest relative of this "
        "rule dropped to 60-75% on 2026 data. This test exists to find out by how much, and whether the rule "
        f"makes money. No conclusion is possible before {MIN_POSITIONS} counted positions."
    )

    with st.sidebar:
        st.header("Forward test")
        refresh = st.button("Update forward report", type="primary", key="fwd_go")
    if refresh:
        forward_report.clear()
    if not (refresh or st.session_state.get("fwd_loaded")):
        st.info("Click **Update forward report** in the sidebar. It loads the latest prices for all 50 stocks "
                "(about a minute the first time).")
        return
    st.session_state["fwd_loaded"] = True

    with st.spinner("Loading latest prices and rebuilding the log..."):
        rep = forward_report()
    s = rep["summary"]

    st.subheader(f"Status: {rep['status'].replace('_', ' ').lower()}  (data through {rep['last_date'].date()})")
    if rep["status"] == "NOT_STARTED":
        st.write(f"No counted forward data yet -- the first countable fill is the {FIRST_COUNTED_ENTRY} open. "
                 "Check back after that session.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Counted positions", s["n_all"], help=f"{s['n_closed']} closed, {s['n_open']} open")
        c2.metric("Win rate, all positions", f"{s['win_rate_all_in']:.1f}%",
                  help="Open positions marked to market; underwater counts as a loss.")
        c3.metric("Win rate, closed only", f"{s['win_rate_closed']:.1f}%")
        c4.metric("Net expectancy / closed trade", f"{s['expectancy_pct']:+.2f}%")
        st.write(f"Average win {s['avg_win_pct']:+.2f}%, average loss {s['avg_loss_pct']:+.2f}%, "
                 f"worst closed trade {s['worst_closed_pct']:+.1f}%. Break-even win rate for these payoffs: "
                 f"{BREAKEVEN_WIN_RATE}%. Pooled return since start {rep['pooled_return_pct']:+.2f}% against "
                 f"{rep['buy_hold_return_pct']:+.2f}% for holding the same stocks.")
        if not s["enough_to_conclude"]:
            st.warning(f"**Too few positions to conclude** ({s['n_all']} of {MIN_POSITIONS}). "
                       "These numbers are for monitoring, not evidence.")
        elif s["win_rate_all_in"] >= TARGET_WIN_RATE and s["expectancy_pct"] > 0 and s["p_vs_breakeven"] < 0.05:
            st.success("Passes the pre-registered bar: at or above 90%, positive expectancy, and significant "
                       "against break-even. Evidence for this regime only.")
        else:
            st.error("Does not pass the pre-registered bar (90% all-in win rate, positive expectancy, "
                     "p < 0.05 against break-even).")

        st.subheader("Open positions")
        if len(rep["open"]):
            st.dataframe(rep["open"].round(2), hide_index=True, width="stretch")
        else:
            st.write("None.")
        with st.expander("Closed trades"):
            if len(rep["closed"]):
                st.dataframe(rep["closed"].round(2), hide_index=True, width="stretch")
            else:
                st.write("None yet.")

    st.subheader("Signals at the last close (filled at the next open)")
    if len(rep["pending_entries"]):
        st.dataframe(rep["pending_entries"], hide_index=True, width="stretch")
        st.caption("Research output: what the frozen rule would do next. Not a recommendation.")
    else:
        st.write("No new entry signals at the last close.")
    if len(rep["pending_exits"]):
        st.write("Exits triggered: " + ", ".join(rep["pending_exits"]["symbol"]))

    if os.path.exists(SNAPSHOT_PATH):
        with st.expander("History of this report (one row per data date)"):
            st.dataframe(pd.read_csv(SNAPSHOT_PATH).round(2), hide_index=True, width="stretch")
            st.caption("Written by `python research/forward_log.py`. The page itself does not add rows.")


# --- Page 3: research record ------------------------------------------

def page_research():
    st.title("Research record")
    st.caption("What this project has actually found, and the running count of everything tested.")

    ledger_path = os.path.join(ROOT, "research", "hypothesis_ledger.json")
    if os.path.exists(ledger_path):
        with open(ledger_path) as f:
            ledger = json.load(f)
        st.metric("Hypotheses tested to date", ledger["cumulative_hypotheses"])
        st.caption("Every hypothesis raises the bar the next result must clear "
                   "(Bonferroni: 0.05 divided by this count).")
        runs = pd.DataFrame(ledger["runs"])[["timestamp", "n_hypotheses_this_run", "context"]]
        st.dataframe(runs, hide_index=True, width="stretch")

    for label, filename in [("Main findings", "FINDINGS.md"),
                            ("Momentum", "MOMENTUM_FINDINGS.md"),
                            ("Midcap / Smallcap", "MIDCAP_SMALLCAP_FINDINGS.md")]:
        path = os.path.join(ROOT, filename)
        if os.path.exists(path):
            with st.expander(label):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())


page = st.sidebar.radio("Page", ["Run a backtest", "Nifty 50 universe", "Momentum (Nifty 50)",
                                 "Forward test", "Research record"])
if page == "Run a backtest":
    page_backtest()
elif page == "Nifty 50 universe":
    page_universe()
elif page == "Momentum (Nifty 50)":
    page_momentum()
elif page == "Forward test":
    page_forward()
else:
    page_research()
