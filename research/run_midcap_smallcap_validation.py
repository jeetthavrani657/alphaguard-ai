"""
research/run_midcap_smallcap_validation.py

Stage 1 (load + validate, no strategy yet) for the Midcap150 and
Smallcap250 control universes -- see config.py's MIDCAP150_UNIVERSE /
SMALLCAP250_UNIVERSE for how these were built and verified.

Per the control-comparison design: same rule, same params as the Nifty
50 investigation, only the universe changes. This script only answers
"how much of each universe is even usable" -- no strategy runs here.

Run from the project root: python research/run_midcap_smallcap_validation.py
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from universe import load_universe

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports", "output")


def validate_universe(symbols, label):
    print(f"\n{'=' * 100}\n{label}: {len(symbols)} symbols\n{'=' * 100}")
    data, failed = load_universe(symbols, config.START_DATE, config.END_DATE, verbose=False)

    usable = {t: e for t, e in data.items() if e["report"]["usable"]}
    unusable = {t: e for t, e in data.items() if not e["report"]["usable"]}

    print(f"Attempted: {len(symbols)}")
    print(f"Failed to load (no data / delisted / network): {len(failed)}")
    print(f"Loaded but FAILED hard validation (duplicates/invalid prices/OHLC logic): {len(unusable)}")
    print(f"USABLE: {len(usable)} ({len(usable) / len(symbols) * 100:.1f}% of attempted)")

    if failed:
        print(f"\nFailed to load ({len(failed)}):")
        for symbol, err in failed:
            print(f"  {symbol}: {err[:100]}")

    if unusable:
        print(f"\nFailed validation ({len(unusable)}):")
        for ticker, entry in unusable.items():
            failed_checks = [c["name"] for c in entry["report"]["checks"] if not c["passed"]]
            print(f"  {ticker}: failed checks = {failed_checks}")

    # Row-count / history-length distribution for the usable set --
    # smallcaps in particular may have much shorter usable history.
    row_counts = {t: len(e["df"]) for t, e in usable.items()}
    if row_counts:
        counts = sorted(row_counts.values())
        n = len(counts)
        print(f"\nUsable-set row count: min={counts[0]}, median={counts[n // 2]}, max={counts[-1]}")
        short = {t: c for t, c in row_counts.items() if c < 500}
        if short:
            print(f"Usable but <500 rows (won't clear the pairs/strategy minimum-history bar anyway): {len(short)}")

    return {
        "label": label,
        "attempted": len(symbols),
        "failed_to_load": [s for s, _ in failed],
        "failed_validation": list(unusable.keys()),
        "usable": list(usable.keys()),
        "row_counts": row_counts,
    }


def main():
    results = []
    results.append(validate_universe(config.MIDCAP150_UNIVERSE, "NIFTY MIDCAP 150 (control universe)"))
    results.append(validate_universe(config.SMALLCAP250_UNIVERSE, "NIFTY SMALLCAP 250 (control universe)"))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "midcap_smallcap_validation.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved detailed results to {OUTPUT_DIR}/midcap_smallcap_validation.json")


if __name__ == "__main__":
    main()
