"""
research/extract_fundamentals.py

Extract the primary financial statements from ONE annual-report PDF into a verified
record (see fundamentals/fund_extract.py for how nothing the model says is trusted
until the code has checked it against the page).

    python research/extract_fundamentals.py --pdf ar.pdf --symbol TCS --fy FY2024-25 --dry-run
    python research/extract_fundamentals.py --pdf ar.pdf --symbol TCS --fy FY2024-25

--dry-run needs no API key and makes no model call: it shows which pages hold the
statements and roughly how much text would be sent. The real run needs the
ANTHROPIC_API_KEY environment variable (set it in Windows, not in this project;
the key must never be written into a file that is committed) and costs money per call.

Research only. Version 1 covers non-financial companies on the consolidated basis.
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "fundamentals"))

import fund_extract
import fund_store


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract verified financial statements from an annual-report PDF.")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--fy", required=True, help="label only, e.g. FY2024-25")
    ap.add_argument("--basis", default="consolidated", choices=["consolidated", "standalone"])
    ap.add_argument("--filed-on", help="YYYY-MM-DD the results were actually filed; if omitted, availability is ASSUMED (+90 days)")
    ap.add_argument("--url", help="where the PDF came from, kept in the record")
    ap.add_argument("--model", default=fund_extract.DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="locate the statement pages only; no model call")
    ap.add_argument("--no-save", action="store_true", help="print the result but do not write it to the store")
    args = ap.parse_args()

    try:
        prep = fund_extract.prepare(args.pdf, args.basis)
    except ValueError as e:
        print(f"Cannot use this PDF: {e}")
        return 2
    print(f"{len(prep['pages'])} pages. Statements found ({args.basis} preferred):")
    for st in ("income", "balance", "cashflow"):
        print(f"  {st:9s} pages {prep['located'][st] or 'NOT FOUND'}   basis: {prep['located']['basis_found'][st]}")
    chars = sum(len(prep["pages"][n - 1]) for n in prep["page_numbers"])
    print(f"Would send {len(prep['page_numbers'])} page(s), about {chars:,} characters (roughly {chars // 4:,} tokens).")
    if prep["missing_statements"]:
        print("Missing: " + ", ".join(prep["missing_statements"]) + ". Cannot extract from this file.")
        return 2
    if args.dry_run:
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nANTHROPIC_API_KEY is not set. Set it as a Windows environment variable (never in a project file), "
              "reopen the terminal, and run again. Use --dry-run to check page location without a key.")
        return 3
    import anthropic
    record = fund_extract.extract_pdf(args.pdf, args.symbol, args.fy, anthropic.Anthropic(), args.model,
                                      args.basis, args.filed_on, args.url)

    print(f"\nSTATUS: {record['status'].upper()}   period end {record['period_end']}   "
          f"available from {record['available_from']}{' (ASSUMED)' if record['available_from_assumed'] else ''}")
    print(f"{len(record['values_crore']) + len(record['values_per_share'])} fields verified, "
          f"{len(record['rejected_fields'])} rejected")
    for r in record["rejected_fields"]:
        print(f"  REJECTED {r['field']}: {r['reason']}")
    for c in record["checks"]:
        mark = {True: "pass", False: "FAIL", None: "skip"}[c["passed"]]
        print(f"  [{c['severity']:4s}] {mark}  {c['id']}: {c['detail']}")
    if record["missing_required"]:
        print("  missing required fields: " + ", ".join(record["missing_required"]))
    if not args.no_save:
        print("Saved." if fund_store.append_record(record) else "Already stored for this document; nothing added.")
    return 0 if record["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
