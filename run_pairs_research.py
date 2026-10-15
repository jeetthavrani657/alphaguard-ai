"""
run_pairs_research.py

Cointegration RESEARCH entry point -- see METHODOLOGY.md Section 0.
No execution layer, no trade log, no P&L: this answers "does stable
cointegration exist in this universe and does it survive out-of-sample
and a multiple-testing correction," not "should this be traded."

Run from the project root:  python run_pairs_research.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "data"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "research"))

import pandas as pd

import config
from loader import load_price_data
from cointegration import (
    generate_candidate_pairs, test_pair_cointegration, compute_spread,
    compute_zscore, compute_half_life, apply_multiple_testing_correction,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "reports", "output")


def _load_closes(symbols):
    closes = {}
    failed = []
    for symbol in symbols:
        try:
            df = load_price_data(symbol, config.START_DATE, config.END_DATE)
            closes[symbol] = df["close"]
        except Exception as e:
            failed.append((symbol, str(e)))
    return closes, failed


def main():
    candidates = generate_candidate_pairs(config.SECTOR_MAP, config.PAIRS_EXCLUDED_SYMBOLS)
    symbols_needed = sorted(set(s for a, b, _ in candidates for s in (a, b)))

    print("=" * 100)
    print("PAIRS COINTEGRATION RESEARCH -- see METHODOLOGY.md Section 0 for scope")
    print("=" * 100)
    n_eligible = len(config.UNIVERSE) - len(config.PAIRS_EXCLUDED_SYMBOLS)
    print(f"Sector groups -> {len(candidates)} same-sector candidate pairs "
          f"(out of {n_eligible * (n_eligible - 1) // 2} possible pairs among the "
          f"{n_eligible} eligible symbols, before the sector filter)")
    print(f"Selection window: {config.PAIRS_SELECTION_START} to {config.PAIRS_SELECTION_END}")
    print(f"Holdout window:   {config.PAIRS_HOLDOUT_START} to {config.PAIRS_HOLDOUT_END}")
    print(f"Significance threshold (uncorrected): {config.PAIRS_COINTEGRATION_ALPHA}")
    print()

    closes, failed = _load_closes(symbols_needed)
    if failed:
        print(f"{len(failed)} symbol(s) failed to load and were dropped from candidate pairs:")
        for s, err in failed:
            print(f"  {s}: {err}")
    candidates = [(a, b, sector) for a, b, sector in candidates if a in closes and b in closes]

    # --- Selection-window cointegration testing ---
    selection_results = []
    for a, b, sector in candidates:
        result = test_pair_cointegration(
            closes[a], closes[b], a, b,
            config.PAIRS_SELECTION_START, config.PAIRS_SELECTION_END,
            config.PAIRS_COINTEGRATION_ALPHA, config.PAIRS_MIN_HISTORY_DAYS,
        )
        result["sector"] = sector
        selection_results.append(result)

    tested = [r for r in selection_results if r["status"] == "tested"]
    skipped = [r for r in selection_results if r["status"] != "tested"]
    qualifying = [r for r in tested if r["both_directions_pass"]]

    print(f"Tested (sufficient history in selection window): {len(tested)}")
    if skipped:
        skipped_names = [f"{r['symbol_a']}/{r['symbol_b']}" for r in skipped]
        print(f"Skipped (insufficient history): {len(skipped)} -- {skipped_names}")
    print(f"Qualify at raw p<{config.PAIRS_COINTEGRATION_ALPHA} (both directions): {len(qualifying)}")
    print()

    # --- Multiple-testing correction ---
    correction = apply_multiple_testing_correction(tested, config.PAIRS_COINTEGRATION_ALPHA)
    print("-" * 100)
    print("MULTIPLE-TESTING CORRECTION")
    print("-" * 100)
    print(f"Tests actually run: {correction['n_tests']}")
    print(f"Expected false positives at alpha={config.PAIRS_COINTEGRATION_ALPHA} by chance alone: "
          f"{correction['expected_false_positives_uncorrected']:.2f}")
    print(f"Raw pairs qualifying (uncorrected): {len(qualifying)}")
    print(f"Bonferroni-corrected alpha: {correction['bonferroni_alpha']:.6f}")
    print(f"Pairs surviving Bonferroni: {correction['n_survive_bonferroni']}")
    print(f"Pairs surviving Benjamini-Hochberg FDR (q<{config.PAIRS_COINTEGRATION_ALPHA}): "
          f"{correction['n_survive_bh_fdr']}")
    print()

    qualifying_df = pd.DataFrame(qualifying).sort_values("min_p_value")
    pd.set_option("display.width", 160)
    print("--- Pairs qualifying at raw p<0.05 (both directions), sorted by strength ---")
    if len(qualifying_df) > 0:
        print(qualifying_df[["symbol_a", "symbol_b", "sector", "n_obs", "min_p_value",
                              "bonferroni_survives", "bh_survives", "bh_qvalue", "hedge_ratio"]].to_string(index=False))
    else:
        print("(none)")
    print()

    # --- Out-of-sample stability check, on raw-qualifying pairs ---
    print("-" * 100)
    print("OUT-OF-SAMPLE STABILITY (holdout period, fresh re-test)")
    print("-" * 100)
    stability_rows = []
    for r in qualifying:
        a, b, sector = r["symbol_a"], r["symbol_b"], r["sector"]
        holdout_result = test_pair_cointegration(
            closes[a], closes[b], a, b,
            config.PAIRS_HOLDOUT_START, config.PAIRS_HOLDOUT_END,
            config.PAIRS_COINTEGRATION_ALPHA, config.PAIRS_MIN_HISTORY_DAYS,
        )
        stability_rows.append({
            "symbol_a": a, "symbol_b": b, "sector": sector,
            "in_sample_min_p": r["min_p_value"],
            "in_sample_bh_survives": r["bh_survives"],
            "holdout_status": holdout_result["status"],
            "holdout_min_p": holdout_result.get("min_p_value"),
            "holdout_both_pass": holdout_result.get("both_directions_pass", False),
        })

    stability_df = pd.DataFrame(stability_rows)
    n_qualify_is = len(stability_df)
    n_survive_oos = stability_df["holdout_both_pass"].sum() if n_qualify_is > 0 else 0
    print(f"In-sample qualifying pairs: {n_qualify_is}")
    print(f"Still qualify out-of-sample (fresh test, same alpha): {n_survive_oos}")
    if n_qualify_is > 0:
        print(f"Survival fraction: {n_survive_oos / n_qualify_is:.1%}")
        print()
        print(stability_df.to_string(index=False))
    print()

    # --- Half-life for in-sample qualifying pairs (selection-window spread, frozen hedge ratio) ---
    print("-" * 100)
    print("MEAN-REVERSION HALF-LIFE (selection-window spread, frozen hedge ratio)")
    print("-" * 100)
    half_life_rows = []
    for r in qualifying:
        a, b = r["symbol_a"], r["symbol_b"]
        spread = compute_spread(closes[a], closes[b], r["hedge_ratio"], r["hedge_direction"])
        spread = spread.loc[config.PAIRS_SELECTION_START:config.PAIRS_SELECTION_END]
        hl = compute_half_life(spread)
        half_life_rows.append({"symbol_a": a, "symbol_b": b, "half_life_days": hl})
    half_life_df = pd.DataFrame(half_life_rows)
    if len(half_life_df) > 0:
        print(half_life_df.to_string(index=False))
    else:
        print("(no qualifying pairs)")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pd.DataFrame(selection_results).to_csv(os.path.join(OUTPUT_DIR, "pairs_selection_window_tests.csv"), index=False)
    stability_df.to_csv(os.path.join(OUTPUT_DIR, "pairs_stability_check.csv"), index=False)
    half_life_df.to_csv(os.path.join(OUTPUT_DIR, "pairs_half_life.csv"), index=False)
    print()
    print(f"Saved detailed results to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
