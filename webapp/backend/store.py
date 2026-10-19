"""
webapp/backend/store.py

The API's only contact with the disk -- and it only READS.

Three kinds of source:
  1. SNAPSHOT files, written by `python -m webapp.backend.snapshot` (the
     terminal command that runs the library). Strategies, equity curves,
     trade logs, data quality.
  2. The hypothesis ledger, research/hypothesis_ledger.json -- an existing
     file the research harness writes. Read directly.
  3. The forward-test log, reports/output/forward_snapshots.csv -- an
     existing file the daily scheduled run writes. Read directly.

This module imports NO engine, strategy or research code. The API therefore
cannot compute a metric even by accident: every number it serves was
produced by the library at snapshot time and merely read back here.

Security note worth learning once: a URL like /api/strategies/{id} puts
text the CALLER controls into your program. If that text were used to build
a file path ("snapshots/" + id + ".json"), a caller could send
"../../secrets" and read files outside the folder (path traversal). So an id
is never turned into a path until it has been found in the manifest's list
of known ids; anything else is a 404.
"""

import csv
import json
import os
from typing import Optional

from . import schemas

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SnapshotMissing(Exception):
    """No snapshot has been generated yet (or the folder is wrong)."""


class NotFound(Exception):
    """The requested id/symbol/window is not in the snapshot."""


# Resolved on every call (not at import) so tests can point them elsewhere
# with environment variables, and so a new snapshot is picked up without
# restarting the server.
def snapshot_dir() -> str:
    return os.environ.get("WEBAPP_SNAPSHOT_DIR", os.path.join(ROOT, "webapp", "snapshots"))


def ledger_path() -> str:
    return os.environ.get("WEBAPP_LEDGER_PATH", os.path.join(ROOT, "research", "hypothesis_ledger.json"))


def forward_path() -> str:
    return os.environ.get("WEBAPP_FORWARD_CSV", os.path.join(ROOT, "reports", "output", "forward_snapshots.csv"))


def live_quotes_path() -> str:
    return os.environ.get("WEBAPP_LIVE_QUOTES", os.path.join(ROOT, "reports", "output", "live_quotes_latest.json"))


def load_live_quotes_raw() -> Optional[dict]:
    """research/live_quotes.py's latest file, or None if the writer has never run (the page explains that)."""
    path = live_quotes_path()
    return _read_json(path) if os.path.exists(path) else None


def advisory_path() -> str:
    return os.environ.get("WEBAPP_ADVISORY", os.path.join(ROOT, "reports", "output", "advisory_latest.json"))


def load_advisory_raw() -> dict:
    """research/advisory.py's latest file, untouched (the API only labels and validates it)."""
    path = advisory_path()
    if not os.path.exists(path):
        raise NotFound("No advisory results yet. Generate them from the project root with: python research/advisory.py")
    return _read_json(path)


def advisory_forward_path() -> str:
    return os.environ.get("WEBAPP_ADVISORY_FORWARD", os.path.join(ROOT, "reports", "output", "advisory_forward_latest.json"))


def load_advisory_forward_raw() -> dict:
    """research/advisory_forward.py's latest file, untouched."""
    path = advisory_forward_path()
    if not os.path.exists(path):
        raise NotFound("No advisory forward results yet. Generate them from the project root with: python research/advisory_forward.py")
    return _read_json(path)


def health_latest_path() -> str:
    return os.environ.get("WEBAPP_HEALTH_LATEST", os.path.join(ROOT, "reports", "output", "health_latest.json"))


def load_health_latest_raw() -> Optional[dict]:
    """research/health_check.py's latest file, or None if it has never run."""
    path = health_latest_path()
    return _read_json(path) if os.path.exists(path) else None


def forward_books_path() -> str:
    return os.environ.get("WEBAPP_FORWARD_BOOKS", os.path.join(ROOT, "reports", "output", "forward_books_latest.json"))


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# --- snapshot ------------------------------------------------------------

def load_manifest() -> schemas.Manifest:
    path = os.path.join(snapshot_dir(), "manifest.json")
    if not os.path.exists(path):
        raise SnapshotMissing(
            "No snapshot found. Generate one from the project root with: "
            "python -m webapp.backend.snapshot")
    return schemas.Manifest.model_validate(_read_json(path))


def load_strategy_file(strategy_id: str) -> schemas.StrategyFile:
    manifest = load_manifest()
    if strategy_id not in manifest.strategy_ids:       # the path-traversal guard
        raise NotFound(f"Unknown strategy id {strategy_id!r}. Known: {manifest.strategy_ids}")
    path = os.path.join(snapshot_dir(), "strategies", f"{strategy_id}.json")
    return schemas.StrategyFile.model_validate(_read_json(path))


def load_all_strategy_files() -> list[schemas.StrategyFile]:
    manifest = load_manifest()
    return [load_strategy_file(i) for i in manifest.strategy_ids]


def load_data_quality() -> schemas.DataQualityResponse:
    load_manifest()  # raises SnapshotMissing with the helpful message if absent
    path = os.path.join(snapshot_dir(), "data_quality.json")
    if not os.path.exists(path):
        raise SnapshotMissing("The snapshot has no data_quality.json; re-run the snapshot command.")
    return schemas.DataQualityResponse.model_validate(_read_json(path))


def load_screener() -> schemas.ScreenerResponse:
    load_manifest()
    path = os.path.join(snapshot_dir(), "screener.json")
    if not os.path.exists(path):
        raise SnapshotMissing("The snapshot has no screener.json; re-run the snapshot command.")
    return schemas.ScreenerResponse.model_validate(_read_json(path))


def known_symbol(symbol: str) -> schemas.ScreenerRow:
    """
    The symbol guard, same idea as the strategy-id guard: a symbol is only
    turned into a file path after being found in the screener's own list.
    """
    for row in load_screener().rows:
        if row.symbol == symbol:
            return row
    raise NotFound(f"Unknown symbol {symbol!r}.")


def load_prices(symbol: str) -> schemas.PriceSeries:
    known_symbol(symbol)
    path = os.path.join(snapshot_dir(), "symbols", f"{symbol}.json")
    if not os.path.exists(path):
        raise NotFound(f"No price file for {symbol!r}; re-run the snapshot command.")
    return schemas.PriceSeries.model_validate(_read_json(path))


def load_symbol_slices(strategy_id: str) -> Optional[schemas.SymbolSlices]:
    """Per-stock results for a per-symbol strategy; None for portfolio strategies (no such file)."""
    if strategy_id not in load_manifest().strategy_ids:
        raise NotFound(f"Unknown strategy id {strategy_id!r}.")
    path = os.path.join(snapshot_dir(), "strategies", f"{strategy_id}.symbols.json")
    if not os.path.exists(path):
        return None
    return schemas.SymbolSlices.model_validate(_read_json(path))


# --- existing result files -----------------------------------------------

def load_ledger() -> dict:
    path = ledger_path()
    if not os.path.exists(path):
        raise NotFound("hypothesis_ledger.json not found.")
    return _read_json(path)


def ledger_total_now() -> Optional[int]:
    try:
        return int(load_ledger()["cumulative_hypotheses"])
    except (NotFound, KeyError, ValueError):
        return None


def load_forward_rows() -> list[dict]:
    path = forward_path()
    if not os.path.exists(path):
        return []

    def num(x: str) -> Optional[float]:
        return float(x) if x not in ("", None) else None

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "run_date": r["run_date"], "data_through": r["data_through"], "status": r["status"],
                "n_closed": num(r["n_closed"]), "n_open": num(r["n_open"]),
                "win_rate_all_in": num(r["win_rate_all_in"]), "win_rate_closed": num(r["win_rate_closed"]),
                "expectancy_pct": num(r["expectancy_pct"]), "pooled_return_pct": num(r["pooled_return_pct"]),
                "buy_hold_return_pct": num(r["buy_hold_return_pct"]),
            })
    return rows


def load_forward_books_raw() -> dict:
    """research/forward_books.py's latest output, untouched (the API only labels and validates it)."""
    path = forward_books_path()
    if not os.path.exists(path):
        raise NotFound("No forward paper books yet. Generate them from the project root with: "
                       "python research/forward_books.py")
    return _read_json(path)
