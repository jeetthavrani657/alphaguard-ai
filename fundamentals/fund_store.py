"""
fundamentals/fund_store.py

Where verified (and needs_review) fundamentals records live. Append-only JSON
Lines, one record per (company, period, basis, source document): re-extracting the
same document adds nothing, and nothing is ever silently overwritten. The model's
raw answer for each record is kept in a separate file so any number can be audited
back to what the model actually said.

Data under data/fundamentals/ is derived from public filings for personal research
and is git-ignored.
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS_PATH = os.path.join(PROJECT_ROOT, "data", "fundamentals", "records.jsonl")
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "fundamentals", "raw")


def _key(r: dict) -> tuple:
    return (r.get("symbol"), r.get("period_end"), r.get("basis"), (r.get("source") or {}).get("sha256"))


def load_records(path: str | None = None) -> list:
    path = path or RECORDS_PATH
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_record(record: dict, path: str | None = None, raw_dir: str | None = None) -> bool:
    """Writes the record (and its raw model answer). Returns False if this exact document was already stored."""
    path = path or RECORDS_PATH
    raw_dir = raw_dir or RAW_DIR
    record = dict(record)
    raw = record.pop("_raw_tool_input", None)
    if _key(record) in {_key(r) for r in load_records(path)}:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if raw is not None:
        os.makedirs(raw_dir, exist_ok=True)
        sha8 = ((record.get("source") or {}).get("sha256") or "nosha")[:8]
        raw_name = f"{record.get('symbol')}_{record.get('period_end')}_{sha8}.json"
        with open(os.path.join(raw_dir, raw_name), "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1)
        record["raw_answer_file"] = raw_name
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    return True


def verified(path: str | None = None) -> list:
    """Only records safe to use: status verified."""
    return [r for r in load_records(path) if r.get("status") == "verified"]
