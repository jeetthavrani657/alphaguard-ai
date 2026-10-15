"""
reports/plots.py

Saves PNG charts from a backtest result: equity curve vs benchmarks, an
underwater (drawdown) plot, a monthly returns heatmap, a histogram of
individual trade returns, and (Stage 5) a parameter-sweep heatmap.

Uses the "Agg" backend explicitly -- this environment has no display,
and Agg renders straight to a file without needing one.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_equity_curves(curves: dict, save_path: str) -> None:
    """
    curves: {label: equity_curve_series}, e.g.
        {"MA Crossover": strategy_equity, "RELIANCE Buy & Hold": bh_equity,
         "Nifty 50 Buy & Hold": nifty_equity}
    All curves are plotted on the same rupee axis -- they're comparable
    because every curve here was produced by the same run_backtest(),
    starting from the same initial capital and cost model.
    """
    fig, ax = plt.subplots(figsize=(11, 6))
    for label, curve in curves.items():
        ax.plot(curve.index, curve.values, label=label, linewidth=1.3)
    ax.set_title("Equity Curve: Strategy vs Benchmarks")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity (Rs)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def plot_underwater(equity_curve: pd.Series, save_path: str) -> None:
    """Drawdown (%) over time: how far below the running peak equity is, every day."""
    running_max = equity_curve.cummax()
    drawdown_pct = (equity_curve / running_max - 1) * 100

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.fill_between(drawdown_pct.index, drawdown_pct.values, 0, color="firebrick", alpha=0.5)
    ax.plot(drawdown_pct.index, drawdown_pct.values, color="firebrick", linewidth=0.8)
    ax.set_title("Underwater Plot (Drawdown from Running Peak)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def plot_monthly_returns_heatmap(equity_curve: pd.Series, save_path: str) -> None:
    """Year x month grid of monthly returns (%), color-coded (red = loss, green = gain)."""
    monthly_equity = equity_curve.resample("ME").last()
    # Prepend the curve's own starting value so the FIRST calendar month
    # (which may be partial) still gets a return relative to day one,
    # instead of being dropped by pct_change()'s leading NaN.
    monthly_equity = pd.concat([pd.Series([equity_curve.iloc[0]], index=[equity_curve.index[0]]), monthly_equity])
    monthly_returns = monthly_equity.pct_change().dropna() * 100

    table = monthly_returns.to_frame("ret")
    table["year"] = table.index.year
    table["month"] = table.index.month
    pivot = table.pivot(index="year", columns="month", values="ret")
    pivot = pivot.reindex(columns=range(1, 13))  # ensure all 12 months appear, even if empty

    fig, ax = plt.subplots(figsize=(11, max(3, 0.5 * len(pivot))))
    limit = np.nanmax(np.abs(pivot.values)) if not np.isnan(pivot.values).all() else 1
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=-limit, vmax=limit, aspect="auto")

    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_yticks(range(len(pivot)))
    ax.set_yticklabels(pivot.index)

    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.values[i, j]
            if not np.isnan(value):
                ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=7)

    ax.set_title("Monthly Returns (%)")
    fig.colorbar(im, ax=ax, label="Return (%)")
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def plot_sweep_heatmap(sweep_df: pd.DataFrame, metric_col: str, metric_label: str, save_path: str) -> None:
    """
    sweep_df: one row per (fast, slow) combination (from
        engine.sweep.run_ma_crossover_sweep), with a `metric_col` column.
    Rows = fast MA window, columns = slow MA window. A diverging
    colormap centered on the metric's mean makes it easy to see at a
    glance whether "good" cells form a contiguous region or are
    scattered isolated points.
    """
    pivot = sweep_df.pivot(index="fast", columns="slow", values=metric_col)

    fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(pivot.columns)), max(5, 0.5 * len(pivot.index))))
    center = np.nanmean(pivot.values)
    limit = np.nanmax(np.abs(pivot.values - center)) if not np.isnan(pivot.values).all() else 1
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=center - limit, vmax=center + limit, aspect="auto", origin="lower")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("Slow MA window")
    ax.set_ylabel("Fast MA window")

    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.values[i, j]
            if not np.isnan(value):
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=7)

    ax.set_title(f"Parameter Sweep: {metric_label} (pooled across universe)")
    fig.colorbar(im, ax=ax, label=metric_label)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def plot_trade_return_histogram(trade_log: pd.DataFrame, save_path: str) -> None:
    """Distribution of individual (closed) trade returns (%)."""
    fig, ax = plt.subplots(figsize=(8, 5))
    if len(trade_log) > 0:
        ax.hist(trade_log["return_pct"], bins=min(20, max(5, len(trade_log))), color="steelblue", edgecolor="white")
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("Distribution of Individual Trade Returns")
    ax.set_xlabel("Trade Return (%)")
    ax.set_ylabel("Number of Trades")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
