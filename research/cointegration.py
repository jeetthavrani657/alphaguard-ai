"""
research/cointegration.py

Cointegration screening for the pairs-trading RESEARCH question (see
METHODOLOGY.md Section 0): does stable cointegration exist in this
universe, and does it survive out-of-sample and a multiple-testing
correction? This is deliberately NOT wired to any execution/backtest
machinery -- see METHODOLOGY.md Section 0 for why.

Every threshold used here (significance, min history, Z-score window)
comes from config.py, which mirrors METHODOLOGY.md's frozen values --
nothing here is a free parameter chosen after seeing results.

Engle-Granger implementation uses statsmodels.tsa.stattools.coint(),
not a hand-rolled ADF -- verified against synthetic data with known
ground truth before use: a constructed cointegrated pair (known hedge
ratio 2.0) was correctly flagged significant in both directions
(p≈0.0), and two independent random walks were correctly NOT flagged
(p≈0.26). See the session's verification output; not re-run as an
automated test since this is one-off research code, not the trading
engine.
"""

from itertools import combinations

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint
from statsmodels.stats.multitest import multipletests


def generate_candidate_pairs(sector_map: dict, excluded_symbols: list) -> list:
    """
    Every same-sector pair from sector_map, excluding any symbol in
    excluded_symbols. This is the ECONOMIC pre-filter from
    METHODOLOGY.md Section 1, applied before any statistics -- it's
    what shrinks 1,128 possible pairs down to a much smaller,
    justified-in-advance candidate set.
    """
    eligible = {s: sector for s, sector in sector_map.items() if s not in excluded_symbols}
    by_sector = {}
    for symbol, sector in eligible.items():
        by_sector.setdefault(sector, []).append(symbol)

    pairs = []
    for sector, symbols in by_sector.items():
        for a, b in combinations(sorted(symbols), 2):
            pairs.append((a, b, sector))
    return pairs


def test_pair_cointegration(close_a: pd.Series, close_b: pd.Series, symbol_a: str, symbol_b: str,
                             start: str, end: str, alpha: float, min_history_days: int) -> dict:
    """
    Engle-Granger cointegration test, BOTH directions, on the window
    [start, end] only. Per METHODOLOGY.md Section 1: both directions
    must reject the null of no cointegration (p < alpha) for the pair
    to qualify. Hedge ratio is taken from whichever direction has the
    stronger evidence (lower p-value) -- METHODOLOGY.md's "winning
    direction," made concrete here since both directions passing still
    leaves a choice of which regression's slope to use.
    """
    window_a = close_a.loc[start:end]
    window_b = close_b.loc[start:end]
    aligned = pd.concat([window_a.rename("a"), window_b.rename("b")], axis=1).dropna()

    if len(aligned) < min_history_days:
        return {
            "symbol_a": symbol_a, "symbol_b": symbol_b,
            "status": "insufficient_history", "n_obs": len(aligned),
        }

    a, b = aligned["a"].to_numpy(), aligned["b"].to_numpy()

    _, p_a_on_b, _ = coint(a, b)
    _, p_b_on_a, _ = coint(b, a)

    both_pass = (p_a_on_b < alpha) and (p_b_on_a < alpha)
    min_p = min(p_a_on_b, p_b_on_a)

    if p_a_on_b <= p_b_on_a:
        hedge_ratio = float(np.polyfit(b, a, 1)[0])  # a ~ hedge_ratio * b
        direction = "a_on_b"  # spread = a - hedge_ratio * b
    else:
        hedge_ratio = float(np.polyfit(a, b, 1)[0])  # b ~ hedge_ratio * a
        direction = "b_on_a"  # spread = b - hedge_ratio * a

    return {
        "symbol_a": symbol_a, "symbol_b": symbol_b,
        "status": "tested",
        "n_obs": len(aligned),
        "p_value_a_on_b": p_a_on_b, "p_value_b_on_a": p_b_on_a,
        "min_p_value": min_p,
        "both_directions_pass": both_pass,
        "hedge_ratio": hedge_ratio, "hedge_direction": direction,
    }


def compute_spread(close_a: pd.Series, close_b: pd.Series, hedge_ratio: float, direction: str) -> pd.Series:
    """The frozen-hedge-ratio spread: a - hedge_ratio*b, or b - hedge_ratio*a per the winning direction."""
    aligned = pd.concat([close_a.rename("a"), close_b.rename("b")], axis=1).dropna()
    if direction == "a_on_b":
        spread = aligned["a"] - hedge_ratio * aligned["b"]
    else:
        spread = aligned["b"] - hedge_ratio * aligned["a"]
    spread.name = "spread"
    return spread


def compute_zscore(spread: pd.Series, window: int) -> pd.Series:
    """Rolling Z-score of the spread -- METHODOLOGY.md Section 3."""
    rolling_mean = spread.rolling(window).mean()
    rolling_std = spread.rolling(window).std()
    z = (spread - rolling_mean) / rolling_std
    z.name = "zscore"
    return z


def compute_half_life(spread: pd.Series) -> float:
    """
    Half-life of mean reversion, from an Ornstein-Uhlenbeck fit to the
    spread: regress the spread's daily change on its own lagged level,
    delta_S_t = beta * S_{t-1} + noise. The discrete-time AR(1)
    persistence is phi = 1 + beta, the continuous-time mean-reversion
    speed is theta = -ln(phi), and half_life = ln(2) / theta =
    -ln(2) / ln(1 + beta).

    Verified against synthetic OU data with a known true half-life of
    13.86 days (theta=0.05): this formula recovered 13.43 days from a
    2000-point simulated series -- within simulation noise of the true
    value. See the session's verification output.

    Returns None if beta >= 0 (the fitted series is not mean-reverting
    at all -- can happen even for a series that passed the Engle-Granger
    test, since the two are different statistical questions; reported
    as None rather than a nonsensical negative or infinite half-life).
    """
    spread = spread.dropna()
    lagged = spread.shift(1)
    delta = spread.diff()
    valid = pd.concat([lagged.rename("lag"), delta.rename("delta")], axis=1).dropna()

    beta = np.polyfit(valid["lag"], valid["delta"], 1)[0]
    if beta >= 0:
        return None
    return -np.log(2) / np.log(1 + beta)


def apply_multiple_testing_correction(pair_results: list, alpha: float) -> dict:
    """
    pair_results: list of dicts from test_pair_cointegration() with
    status == "tested" (i.e. had enough history to actually run the test).

    Applies both Bonferroni (family-wise error rate control -- the
    conservative "even in the worst case" bar) and Benjamini-Hochberg
    (false discovery rate control -- the standard tool for "many
    hypotheses tested, some real positives plausible" screening, and
    the one actually recommended here) to the min_p_value of each
    tested pair. Both operate on the ACTUAL number of tests run (the
    sector-filtered candidate count), not the theoretical 1,128 -- the
    pre-filter already did its job by the time this runs.
    """
    tested = [r for r in pair_results if r["status"] == "tested"]
    n_tests = len(tested)
    pvalues = np.array([r["min_p_value"] for r in tested])

    bonferroni_alpha = alpha / n_tests if n_tests > 0 else float("nan")
    bonferroni_pass = pvalues < bonferroni_alpha

    if n_tests > 0:
        bh_reject, bh_qvalues, _, _ = multipletests(pvalues, alpha=alpha, method="fdr_bh")
    else:
        bh_reject, bh_qvalues = np.array([]), np.array([])

    for i, r in enumerate(tested):
        r["bonferroni_survives"] = bool(bonferroni_pass[i])
        r["bh_survives"] = bool(bh_reject[i])
        r["bh_qvalue"] = float(bh_qvalues[i])

    return {
        "n_tests": n_tests,
        "bonferroni_alpha": bonferroni_alpha,
        "n_survive_bonferroni": int(bonferroni_pass.sum()),
        "n_survive_bh_fdr": int(bh_reject.sum()) if n_tests > 0 else 0,
        "expected_false_positives_uncorrected": alpha * n_tests,
    }
