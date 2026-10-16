"""
fundamentals/fund_extract.py

Reads the located financial-statement pages with Claude and turns the answer into a
VERIFIED record, or an honest "needs_review". Nothing the model says is trusted
until the code has checked it against the page it came from.

What the model returns, per field: the figure exactly as printed, the page number,
and the verbatim line. What the code then does, in order:

  1. the line must really appear on that page (whitespace-insensitive);
  2. the printed figure must really appear in that line, and the line must carry a
     label (so a bare number lifted from elsewhere cannot pass);
  3. the code, not the model, parses the figure and converts it to Rs crore;
  4. the column header the model says it used must appear on the page and name the
     period's year (guards against reading the prior-year column);
  5. accounting identities (fund_checks) must hold across the whole record.

A field failing 1-4 is rejected and listed with the reason. A record is "verified"
only if every REQUIRED field survived and no hard identity failed.

"Point in time": `available_from` says when the numbers were public. The annual
audited results are filed within 60 days of year-end; unless the real filing date
is supplied we assume 90 days after the period end, and say it was assumed. A
backtest must not use a figure before that date.
"""

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

import fund_checks
import fund_pdf
import fund_schema

DEFAULT_MODEL = "claude-sonnet-5-5"
ASSUMED_AVAILABILITY_LAG_DAYS = 90
TOOL_NAME = "record_financials"


# --- the question put to the model ---------------------------------------------------------------

def build_tool() -> dict:
    cell = {
        "type": "object",
        "description": "One figure as printed in the filing.",
        "properties": {
            "printed_value": {"type": "string", "description": "Exactly as printed, e.g. '9,15,423.00' or '(1,234.5)'. Do not convert or compute."},
            "page": {"type": "integer", "description": "The page number from the '=== PAGE n ===' marker."},
            "quote": {"type": "string", "description": "The verbatim line from the page containing the label and the figure."},
        },
        "required": ["printed_value", "page", "quote"],
    }
    statement_meta = {
        "type": "object",
        "properties": {
            "unit": {"type": "string", "description": "The unit the statement states its figures in, e.g. 'crore', 'lakh', 'million'. Copy from the statement header."},
            "column_header": {"type": "string", "description": "The verbatim header of the CURRENT-period column you read, e.g. 'As at March 31, 2025'."},
        },
        "required": ["unit", "column_header"],
    }
    return {
        "name": TOOL_NAME,
        "description": "Record the figures found in the statements, exactly as printed, each with its page and verbatim line.",
        "input_schema": {
            "type": "object",
            "properties": {
                "basis": {"type": "string", "enum": ["consolidated", "standalone"]},
                "period_end": {"type": "string", "description": "Fiscal year-end date of the CURRENT period, YYYY-MM-DD."},
                "statements": {"type": "object", "properties": {s: statement_meta for s in fund_schema.STATEMENTS}},
                "fields": {"type": "object", "description": "Only the fields you can find. Omit a field you cannot find; never guess.",
                           "properties": {name: cell for name in fund_schema.FIELDS}},
                "notes": {"type": "string", "description": "Anything unusual (restated, different layout, missing statement)."},
            },
            "required": ["basis", "period_end", "statements", "fields"],
        },
    }


def build_prompt(symbol: str, fiscal_year: str, basis: str, text: str) -> str:
    lines = [f"- {name}: {desc}" for name, (_st, _k, desc) in fund_schema.FIELDS.items()]
    return (
        f"You are reading the {basis} financial statements of {symbol} for fiscal year {fiscal_year} from an annual report.\n"
        "Extract the fields below by calling the record_financials tool.\n\n"
        "Rules, all of them strict:\n"
        "1. READ, do not calculate. Copy each figure exactly as printed (keep commas and brackets). Never add, subtract, convert or round.\n"
        "2. Use ONLY the current-period column. Statements usually also show the previous year; do not use it. Say which column you used in column_header.\n"
        "3. Each figure needs its page number and the verbatim line (label and figure together) it came from.\n"
        "4. If a field is not on these pages, omit it. Do not infer it from other fields.\n"
        "5. Report each statement's stated unit (crore, lakh, million...) exactly as the statement header gives it.\n"
        "6. A figure in brackets is negative: keep the brackets.\n\n"
        "Fields:\n" + "\n".join(lines) + "\n\nPages:\n\n" + text
    )


def call_model(client, model: str, prompt: str, max_tokens: int = 6000) -> dict:
    """
    One forced tool call; returns the tool input. Raises if the model did not use the tool.

    No sampling parameters are sent: this SDK version does not accept them, so two runs on the same
    document can differ. That is why nothing is trusted on the model's word: every figure is checked
    against the page and the accounting identities, and the model's raw answer is stored for audit.
    """
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        tools=[build_tool()], tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
            return block.input
    raise RuntimeError("the model returned no record_financials tool call")


# --- verifying what came back --------------------------------------------------------------------

def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def verify_cell(cell: dict, pages: list) -> str | None:
    """None if the cell checks out against the page text, otherwise the reason it does not."""
    page, quote, printed = cell.get("page"), cell.get("quote") or "", cell.get("printed_value") or ""
    if not isinstance(page, int) or not 1 <= page <= len(pages):
        return f"page {page!r} is outside the document"
    if sum(c.isalpha() for c in quote) < 3:
        return "the quote carries no label (a bare number cannot be traced to its row)"
    if _squash(quote) not in _squash(pages[page - 1]):
        return f"the quoted line is not on page {page}"
    if _squash(printed) not in _squash(quote):
        return "the printed figure is not inside the quoted line"
    if fund_schema.parse_printed_number(printed) is None:
        return f"{printed!r} is not a readable number"
    return None


def _period_year_in(header: str, period_end: date) -> bool:
    y = period_end.year
    return str(y) in header or f"{y - 1}-{y % 100:02d}" in header or f"{y - 1}-{y}" in header


def _parse_date(s) -> date | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except ValueError:
        return None


def build_record(symbol: str, fiscal_year: str, source: dict, tool_input: dict, pages: list,
                 model: str, filed_on: str | None = None) -> dict:
    """
    Verified record from the model's tool input. `source` = {"file", "sha256", ...}.
    Never raises on bad model output: problems become rejected fields / failed checks.
    """
    period_end = _parse_date(tool_input.get("period_end"))
    statements = tool_input.get("statements") or {}
    rejected, provenance, values_crore, values_per_share = [], {}, {}, {}

    # unit and column header per statement, verified once
    units, header_problems = {}, []
    for st in fund_schema.STATEMENTS:
        meta = statements.get(st) or {}
        unit = (meta.get("unit") or "").strip().lower()
        if unit in fund_schema.UNIT_TO_CRORE:
            units[st] = unit
        elif meta:
            header_problems.append(f"{st}: unknown unit {meta.get('unit')!r}")
        header = meta.get("column_header") or ""
        if meta and period_end is not None:
            on_a_page = any(_squash(header) in _squash(p) for p in pages) if header else False
            if not on_a_page:
                header_problems.append(f"{st}: column header {header!r} is not on any page")
            elif not _period_year_in(header, period_end):
                header_problems.append(f"{st}: column header {header!r} does not name the period {period_end}")

    for name, cell in (tool_input.get("fields") or {}).items():
        if name not in fund_schema.FIELDS:
            rejected.append({"field": name, "reason": "not a requested field"})
            continue
        statement, kind, _desc = fund_schema.FIELDS[name]
        problem = verify_cell(cell, pages)
        if problem:
            rejected.append({"field": name, "reason": problem})
            continue
        number = fund_schema.parse_printed_number(cell["printed_value"])
        try:
            if kind == "money":
                if statement not in units:
                    raise ValueError(f"no verified unit for the {statement} statement")
                values_crore[name] = fund_schema.to_crore(number, units[statement])
            else:
                values_per_share[name] = number
        except ValueError as e:
            rejected.append({"field": name, "reason": str(e)})
            continue
        provenance[name] = {"page": cell["page"], "printed_value": cell["printed_value"], "quote": cell["quote"],
                            "unit": units.get(statement)}

    checks = fund_checks.run_checks(values_crore)
    if header_problems:
        checks.append({"id": "column_header_names_the_period", "severity": "hard", "passed": False,
                       "detail": "; ".join(header_problems)})
    else:
        checks.append({"id": "column_header_names_the_period", "severity": "hard", "passed": True,
                       "detail": "every statement's column header is on its page and names the period"})

    missing_required = [f for f in fund_schema.REQUIRED if f not in values_crore]
    failures = fund_checks.hard_failures(checks)
    status = "verified" if period_end and not missing_required and not failures else "needs_review"

    if filed_on:
        available_from, available_assumed = filed_on, False
    elif period_end:
        available_from = (period_end + timedelta(days=ASSUMED_AVAILABILITY_LAG_DAYS)).isoformat()
        available_assumed = True
    else:
        available_from, available_assumed = None, True

    return {
        "symbol": symbol, "fiscal_year": fiscal_year, "basis": tool_input.get("basis"),
        "period_end": period_end.isoformat() if period_end else None,
        "available_from": available_from, "available_from_assumed": available_assumed,
        "status": status, "missing_required": missing_required,
        "values_crore": values_crore, "values_per_share": values_per_share,
        "provenance": provenance, "rejected_fields": rejected, "checks": checks,
        "model_notes": tool_input.get("notes", ""),
        "source": source, "model": model, "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# --- the whole pipeline for one PDF ----------------------------------------------------------------

def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(pdf_path: str, basis: str = "consolidated") -> dict:
    """Read the PDF and locate the statements (no model call). Raises ValueError with a plain reason if it cannot."""
    pages = fund_pdf.read_pages(pdf_path)
    if not fund_pdf.has_text_layer(pages):
        raise ValueError("this PDF has no text layer (a scan); it needs OCR first, which is not attempted")
    located = fund_pdf.find_statement_pages(pages, basis)
    missing = [st for st in fund_schema.STATEMENTS if not located[st]]
    return {"pages": pages, "located": located, "missing_statements": missing,
            "page_numbers": sorted({n for st in fund_schema.STATEMENTS for n in located[st]})}


def extract_pdf(pdf_path: str, symbol: str, fiscal_year: str, client, model: str = DEFAULT_MODEL,
                basis: str = "consolidated", filed_on: str | None = None, source_url: str | None = None) -> dict:
    prep = prepare(pdf_path, basis)
    if prep["missing_statements"]:
        raise ValueError("could not find the " + ", ".join(prep["missing_statements"]) +
                         " statement(s) in this PDF; check the file or the basis")
    text = fund_pdf.collect_text(prep["pages"], prep["page_numbers"])
    tool_input = call_model(client, model, build_prompt(symbol, fiscal_year, basis, text))
    source = {"file": pdf_path.replace("\\", "/").split("/")[-1], "sha256": sha256_of(pdf_path), "url": source_url,
              "pages_sent": prep["page_numbers"]}
    record = build_record(symbol, fiscal_year, source, tool_input, prep["pages"], model, filed_on)
    record["_raw_tool_input"] = tool_input           # kept for audit; the store writes it to a separate file
    return record
