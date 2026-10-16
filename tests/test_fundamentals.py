"""
tests/test_fundamentals.py

The fundamentals extractor must never let a wrong number into a record. These tests
build a REAL PDF (with a text layer) and replace the language model with a fake that
answers the way a real model can go wrong: a made-up quote, a number lifted from the
wrong row, the prior-year column, a misread unit. Each failure mode must be caught
by the code, not by luck. No network, no API key, no cost.
"""

import json
import re
from types import SimpleNamespace

import matplotlib
import pytest

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42                     # real, extractable text
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import fund_checks
import fund_extract
import fund_pdf
import fund_schema
import fund_store

# --- a synthetic annual report -----------------------------------------------------------------

BALANCE = [
    "Total assets 1,20,000.00", "Equity share capital 365.00", "Equity attributable to owners 80,000.00",
    "Non-controlling interests 2,000.00", "Total equity 82,000.00", "Non-current borrowings 10,000.00",
    "Current borrowings 5,000.00", "Total current liabilities 20,000.00", "Total current assets 50,000.00",
    "Cash and cash equivalents 4,000.00", "Total equity and liabilities 1,20,000.00",
]
INCOME = [
    "Revenue from operations 2,40,000.00", "Other income 4,000.00", "Total income 2,44,000.00",
    "Total expenses 2,00,000.00", "Finance costs 1,500.00", "Depreciation and amortisation expense 6,000.00",
    "Profit before tax 44,000.00", "Tax expenses 11,000.00", "Profit for the year 33,000.00",
    "Attributable to owners 32,500.00", "Earnings per equity share (basic) 90.12",
]
CASHFLOW = [
    "Net cash from operating activities 30,000.00", "Net cash used in investing activities (12,000.00)",
    "Net cash used in financing activities (15,000.00)", "Net increase in cash and cash equivalents 3,000.00",
    "Cash and cash equivalents at end of year 4,000.00",
]
NARRATIVE = ["Chairman's letter. We had a good year with strong growth across all our businesses and markets."] * 3


def _page(pdf, title, header, rows):
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.08, 0.95, title, fontsize=11)
    fig.text(0.08, 0.92, header, fontsize=9)
    for i, row in enumerate(rows):
        label, _, number = row.rpartition(" ")
        fig.text(0.08, 0.86 - i * 0.035, label, fontsize=9)
        fig.text(0.70, 0.86 - i * 0.035, number, fontsize=9)
    pdf.savefig(fig)
    plt.close(fig)


@pytest.fixture(scope="module")
def report_pdf(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("ar") / "annual_report.pdf")
    cols = "As at March 31, 2025    As at March 31, 2024    (Rs in crore)"
    with PdfPages(path) as pdf:
        _page(pdf, "Annual Report 2024-25", "Letter to shareholders", NARRATIVE)                         # 1
        _page(pdf, "Standalone Balance Sheet", cols, [r.replace("1,20,000", "70,000").replace("82,000", "40,000")
                                                       .replace("80,000", "39,000").replace("2,000.00", "1,000.00") for r in BALANCE])  # 2
        _page(pdf, "Consolidated Balance Sheet", cols, BALANCE)                                          # 3
        _page(pdf, "Consolidated Statement of Profit and Loss", "For the year ended March 31, 2025    March 31, 2024    (Rs in crore)", INCOME)  # 4
        _page(pdf, "Consolidated Statement of Cash Flows", "For the year ended March 31, 2025    March 31, 2024    (Rs in crore)", CASHFLOW)  # 5
        _page(pdf, "Notes to the accounts", "Note 1", NARRATIVE)                                         # 6
    return path


@pytest.fixture(scope="module")
def pages(report_pdf):
    return fund_pdf.read_pages(report_pdf)


def _line(pages, page_no, label):
    """The verbatim extracted line on a page containing `label` (PDF extraction can split words: 'T otal')."""
    flat = lambda x: re.sub(r"\s+", "", x).lower()
    for line in pages[page_no - 1].splitlines():
        if flat(label) in flat(line) and re.search(r"\d", line):
            return line.strip()
    raise AssertionError(f"{label!r} not found on page {page_no}: {pages[page_no - 1]!r}")


def _cell(pages, page_no, label, printed):
    return {"printed_value": printed, "page": page_no, "quote": _line(pages, page_no, label)}


def _good_tool_input(pages, unit="crore"):
    meta = lambda header: {"unit": unit, "column_header": header}
    return {
        "basis": "consolidated", "period_end": "2025-03-31",
        "statements": {"income": meta("For the year ended March 31, 2025"), "balance": meta("As at March 31, 2025"),
                       "cashflow": meta("For the year ended March 31, 2025")},
        "fields": {
            "revenue_from_operations": _cell(pages, 4, "Revenue from operations", "2,40,000.00"),
            "other_income": _cell(pages, 4, "Other income", "4,000.00"),
            "total_income": _cell(pages, 4, "Total income", "2,44,000.00"),
            "profit_before_tax": _cell(pages, 4, "Profit before tax", "44,000.00"),
            "tax_expense": _cell(pages, 4, "Tax expenses", "11,000.00"),
            "profit_after_tax": _cell(pages, 4, "Profit for the year", "33,000.00"),
            "eps_basic": _cell(pages, 4, "Earnings per equity share", "90.12"),
            "total_assets": _cell(pages, 3, "Total assets", "1,20,000.00"),
            "total_equity_and_liabilities": _cell(pages, 3, "Total equity and liabilities", "1,20,000.00"),
            "total_equity": _cell(pages, 3, "Total equity 82", "82,000.00"),
            "equity_attributable_to_owners": _cell(pages, 3, "Equity attributable", "80,000.00"),
            "non_controlling_interests": _cell(pages, 3, "Non-controlling", "2,000.00"),
            "cash_from_operations": _cell(pages, 5, "operating activities", "30,000.00"),
            "cash_from_investing": _cell(pages, 5, "investing activities", "(12,000.00)"),
            "cash_from_financing": _cell(pages, 5, "financing activities", "(15,000.00)"),
            "net_change_in_cash": _cell(pages, 5, "Net increase", "3,000.00"),
        },
    }


SRC = {"file": "annual_report.pdf", "sha256": "ab" * 32}


def _record(pages, tool_input, **kw):
    return fund_extract.build_record("TEST", "FY2024-25", SRC, tool_input, pages, "fake-model", **kw)


# --- parsing and units (the code, not the model, does this arithmetic) ---------------------------------

@pytest.mark.parametrize("printed,expected", [
    ("9,15,423.00", 915423.0), ("1,20,000.00", 120000.0), ("(1,234.5)", -1234.5), ("( 12 )", -12.0), ("-12", -12.0),
    ("−12.5", -12.5), ("Rs. 3,400", 3400.0), ("0.00", 0.0), ("90.12", 90.12),
    ("--", None), ("Nil", None), ("", None), (None, None), ("12.5%", None), ("1,2x4", None), ("1 000", 1000.0),
])
def test_printed_numbers_parse_exactly(printed, expected):
    assert fund_schema.parse_printed_number(printed) == expected


@pytest.mark.parametrize("unit,expected", [("crore", 5.0), ("lakh", 0.05), ("Million", 0.5), ("billion", 500.0),
                                           ("thousand", 0.0005), ("rupees", 5e-7)])
def test_units_convert_to_crore(unit, expected):
    assert fund_schema.to_crore(5.0, unit) == pytest.approx(expected)


def test_an_unknown_unit_is_an_error_never_a_guess():
    with pytest.raises(ValueError):
        fund_schema.to_crore(5.0, "myriad")


# --- finding the statements -----------------------------------------------------------------------------

def test_the_statements_are_found_and_consolidated_is_preferred(pages):
    found = fund_pdf.find_statement_pages(pages, "consolidated")
    assert found["income"] == [4] and found["cashflow"] == [5]
    assert found["balance"] == [3]                                    # not the standalone balance sheet on page 2
    assert found["basis_found"]["balance"] == "consolidated"
    assert 1 not in sum((found[s] for s in ("income", "balance", "cashflow")), [])   # narrative never sent


def test_standalone_can_be_requested_and_a_missing_basis_falls_back_and_says_so(pages):
    assert fund_pdf.find_statement_pages(pages, "standalone")["balance"] == [2]
    only_cons = [pages[i] for i in (0, 2, 3, 4, 5)]                  # drop the standalone balance sheet
    f = fund_pdf.find_statement_pages(only_cons, "standalone")
    assert f["basis_found"]["balance"] == "consolidated"             # fell back, and reported it


def test_a_scanned_pdf_is_refused_not_guessed(tmp_path):
    path = str(tmp_path / "scan.pdf")
    with PdfPages(path) as pdf:
        pdf.savefig(plt.figure(figsize=(4, 4)))                      # a page with no text at all
        plt.close("all")
    assert not fund_pdf.has_text_layer(fund_pdf.read_pages(path))
    with pytest.raises(ValueError, match="no text layer"):
        fund_extract.prepare(path)


# --- verifying what the model says ------------------------------------------------------------------------

def test_a_correct_cell_verifies(pages):
    assert fund_extract.verify_cell(_cell(pages, 3, "Total assets", "1,20,000.00"), pages) is None


@pytest.mark.parametrize("mutate,reason", [
    (lambda c: dict(c, quote="Total assets 9,99,999.00"), "not on page"),                    # a made-up line
    (lambda c: dict(c, printed_value="1,00,000.00"), "not inside the quoted line"),          # figure not in the line
    (lambda c: dict(c, quote="1,20,000.00"), "no label"),                                    # a bare number
    (lambda c: dict(c, page=99), "outside the document"),
    (lambda c: dict(c, page=4), "not on page 4"),                                            # right text, wrong page
])
def test_each_way_a_model_can_misquote_is_caught(pages, mutate, reason):
    problem = fund_extract.verify_cell(mutate(_cell(pages, 3, "Total assets", "1,20,000.00")), pages)
    assert problem is not None and reason in problem


# --- whole records ------------------------------------------------------------------------------------------

def test_a_correctly_read_report_becomes_a_verified_record_in_crore(pages):
    r = _record(pages, _good_tool_input(pages))
    assert r["status"] == "verified" and r["missing_required"] == [] and r["rejected_fields"] == []
    v = r["values_crore"]
    assert v["total_assets"] == 120000.0 and v["cash_from_investing"] == -12000.0 and v["revenue_from_operations"] == 240000.0
    assert r["values_per_share"] == {"eps_basic": 90.12}
    assert {c["id"] for c in r["checks"] if c["passed"] is True} >= {"balance_sheet_balances", "cash_flow_reconciles",
                                                                       "total_income_adds_up", "equity_parts_add_up"}
    assert r["provenance"]["total_assets"]["page"] == 3 and "1,20,000.00" in r["provenance"]["total_assets"]["quote"]


def test_lakh_statements_are_converted_by_the_code(pages):
    r = _record(pages, _good_tool_input(pages, unit="lakh"))
    assert r["values_crore"]["total_assets"] == pytest.approx(1200.0)         # 1,20,000 lakh = 1,200 crore
    assert r["status"] == "verified"


def test_a_number_from_the_wrong_row_passes_the_quote_check_but_not_the_balance_sheet(pages):
    ti = _good_tool_input(pages)
    ti["fields"]["total_equity_and_liabilities"] = _cell(pages, 3, "Total equity 82", "82,000.00")   # real line, wrong field
    r = _record(pages, ti)
    assert r["rejected_fields"] == []                                          # it IS on the page
    assert r["status"] == "needs_review"
    bad = [c for c in r["checks"] if c["passed"] is False]
    assert [c["id"] for c in bad] == ["balance_sheet_balances"] and "does not hold" in bad[0]["detail"]


def test_the_prior_year_column_is_caught(pages):
    ti = _good_tool_input(pages)
    ti["statements"]["balance"]["column_header"] = "As at March 31, 2024"      # it IS on the page, but it is last year
    r = _record(pages, ti)
    assert r["status"] == "needs_review"
    hdr = next(c for c in r["checks"] if c["id"] == "column_header_names_the_period")
    assert hdr["passed"] is False and "does not name the period" in hdr["detail"]


def test_an_invented_column_header_is_caught(pages):
    ti = _good_tool_input(pages)
    ti["statements"]["income"]["column_header"] = "Fiscal 2025 (restated)"
    r = _record(pages, ti)
    assert r["status"] == "needs_review"
    assert "not on any page" in next(c for c in r["checks"] if c["id"] == "column_header_names_the_period")["detail"]


def test_a_rejected_required_field_makes_the_record_needs_review_with_the_reason(pages):
    ti = _good_tool_input(pages)
    ti["fields"]["profit_after_tax"]["quote"] = "Profit for the year 99,999.00"   # invented
    r = _record(pages, ti)
    assert r["status"] == "needs_review" and "profit_after_tax" in r["missing_required"]
    assert r["rejected_fields"] == [{"field": "profit_after_tax", "reason": "the quoted line is not on page 4"}]
    assert "profit_after_tax" not in r["values_crore"]                          # a rejected figure never enters the values


def test_an_unrequested_field_and_an_unknown_unit_are_rejected(pages):
    ti = _good_tool_input(pages)
    ti["fields"]["favourite_number"] = _cell(pages, 3, "Total assets", "1,20,000.00")
    ti["statements"]["cashflow"]["unit"] = "myriad"
    r = _record(pages, ti)
    assert {"field": "favourite_number", "reason": "not a requested field"} in r["rejected_fields"]
    assert "cash_from_operations" not in r["values_crore"] and r["status"] == "needs_review"


def test_garbage_from_the_model_never_raises(pages):
    r = _record(pages, {"basis": "consolidated", "period_end": "not a date", "statements": None, "fields": None})
    assert r["status"] == "needs_review" and r["period_end"] is None and r["available_from"] is None


def test_availability_is_assumed_conservatively_unless_the_filing_date_is_given(pages):
    r = _record(pages, _good_tool_input(pages))
    assert r["available_from"] == "2025-06-29" and r["available_from_assumed"] is True       # 2025-03-31 + 90 days
    r2 = _record(pages, _good_tool_input(pages), filed_on="2025-05-10")
    assert r2["available_from"] == "2025-05-10" and r2["available_from_assumed"] is False


# --- identities on their own ---------------------------------------------------------------------------------

def test_identities_pass_fail_and_skip_correctly():
    ok = {c["id"]: c for c in fund_checks.run_checks({"total_assets": 100.0, "total_equity_and_liabilities": 100.1})}
    assert ok["balance_sheet_balances"]["passed"] is True                     # within rounding tolerance
    assert ok["cash_flow_reconciles"]["passed"] is None                       # fields absent: skipped, not passed
    bad = {c["id"]: c for c in fund_checks.run_checks({"total_assets": 100.0, "total_equity_and_liabilities": 110.0})}
    assert bad["balance_sheet_balances"]["passed"] is False
    assert fund_checks.hard_failures(list(bad.values()))[0]["id"] == "balance_sheet_balances"


def test_warnings_do_not_block_a_record():
    checks = fund_checks.run_checks({"profit_before_tax": 100.0, "tax_expense": 25.0, "profit_after_tax": 60.0})
    chain = next(c for c in checks if c["id"] == "profit_chain")
    assert chain["passed"] is False and chain["severity"] == "warn"
    assert fund_checks.hard_failures(checks) == []


# --- the model call and the pipeline ---------------------------------------------------------------------------

class FakeClient:
    def __init__(self, tool_input=None, text_only=False):
        self.calls, self._ti, self._text = [], tool_input, text_only
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._text:
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="I cannot do that")])
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=fund_extract.TOOL_NAME, input=self._ti)])


def test_the_model_is_forced_to_use_the_tool_and_sent_only_arguments_the_sdk_accepts(pages):
    client = FakeClient(_good_tool_input(pages))
    out = fund_extract.call_model(client, "some-model", "prompt")
    kw = client.calls[0]
    assert out["basis"] == "consolidated"
    assert kw["tool_choice"] == {"type": "tool", "name": fund_extract.TOOL_NAME}
    assert kw["model"] == "some-model" and kw["tools"][0]["name"] == fund_extract.TOOL_NAME
    assert "temperature" not in kw                      # this SDK version has no such argument (checked, see below)


def test_every_argument_the_extractor_sends_is_one_the_real_sdk_accepts(pages):
    """Catches an SDK/code mismatch before the first paid call, without a key or a network call."""
    import inspect
    import anthropic
    accepted = set(inspect.signature(anthropic.Anthropic(api_key="not-a-real-key").messages.create).parameters)
    client = FakeClient(_good_tool_input(pages))
    fund_extract.call_model(client, "some-model", "prompt")
    assert set(client.calls[0]) <= accepted, f"not accepted by the SDK: {set(client.calls[0]) - accepted}"


def test_a_model_that_does_not_use_the_tool_is_an_error():
    with pytest.raises(RuntimeError, match="no record_financials"):
        fund_extract.call_model(FakeClient(text_only=True), "m", "p")


def test_the_tool_schema_covers_every_field_and_demands_page_and_quote():
    tool = fund_extract.build_tool()
    props = tool["input_schema"]["properties"]["fields"]["properties"]
    assert set(props) == set(fund_schema.FIELDS)
    assert set(props["total_assets"]["required"]) == {"printed_value", "page", "quote"}
    assert "fields" in tool["input_schema"]["required"]


def test_only_the_statement_pages_reach_the_model_and_the_rules_are_in_the_prompt(report_pdf, pages):
    client = FakeClient(_good_tool_input(pages))
    fund_extract.extract_pdf(report_pdf, "TEST", "FY2024-25", client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert "=== PAGE 3 ===" in prompt and "=== PAGE 4 ===" in prompt and "=== PAGE 5 ===" in prompt
    assert "Chairman's letter" not in prompt and "=== PAGE 1 ===" not in prompt and "=== PAGE 2 ===" not in prompt
    for rule in ("READ, do not calculate", "ONLY the current-period column", "omit it", "brackets"):
        assert rule in prompt


def test_end_to_end_from_pdf_to_a_verified_record(report_pdf, pages):
    r = fund_extract.extract_pdf(report_pdf, "TEST", "FY2024-25", FakeClient(_good_tool_input(pages)),
                                 source_url="https://example.com/ar.pdf")
    assert r["status"] == "verified" and r["source"]["pages_sent"] == [3, 4, 5]
    assert len(r["source"]["sha256"]) == 64 and r["source"]["url"] == "https://example.com/ar.pdf"


def test_a_pdf_without_the_statements_is_refused_with_the_reason(tmp_path):
    path = str(tmp_path / "narrative.pdf")
    with PdfPages(path) as pdf:
        for i in range(3):
            _page(pdf, "Annual Report", "Letter", NARRATIVE)
    with pytest.raises(ValueError, match="could not find the income, balance, cashflow"):
        fund_extract.extract_pdf(path, "TEST", "FY", FakeClient({}))


# --- the store ---------------------------------------------------------------------------------------------------

def test_the_store_is_append_only_and_idempotent_and_keeps_the_raw_answer(report_pdf, pages, tmp_path):
    path, raw_dir = str(tmp_path / "rec.jsonl"), str(tmp_path / "raw")
    r = fund_extract.extract_pdf(report_pdf, "TEST", "FY2024-25", FakeClient(_good_tool_input(pages)))
    assert fund_store.append_record(r, path, raw_dir) is True
    assert fund_store.append_record(r, path, raw_dir) is False                # same document again: nothing added
    stored = fund_store.load_records(path)
    assert len(stored) == 1 and "_raw_tool_input" not in stored[0]
    raw = json.load(open(f"{raw_dir}/{stored[0]['raw_answer_file']}"))
    assert raw["fields"]["total_assets"]["printed_value"] == "1,20,000.00"     # auditable back to what the model said


def test_only_verified_records_are_offered_for_use(pages, tmp_path):
    path = str(tmp_path / "rec.jsonl")
    good = _record(pages, _good_tool_input(pages))
    bad_in = _good_tool_input(pages)
    bad_in["fields"]["total_equity_and_liabilities"] = _cell(pages, 3, "Total equity 82", "82,000.00")
    bad = fund_extract.build_record("OTHER", "FY", dict(SRC, sha256="cd" * 32), bad_in, pages, "m")
    fund_store.append_record(good, path, str(tmp_path / "raw"))
    fund_store.append_record(bad, path, str(tmp_path / "raw"))
    assert len(fund_store.load_records(path)) == 2
    assert [r["symbol"] for r in fund_store.verified(path)] == ["TEST"]


def test_pdf_extraction_artifacts_do_not_hide_a_statement(pages):
    """pypdf really does turn 'Total' into 'T otal' on these pages; the locator and the quote check must not care."""
    assert "T otal assets" in pages[2]                                  # the artifact is present in this very PDF
    assert fund_pdf.find_statement_pages(pages)["balance"] == [3]
    spaced = pages[2].replace("Total equity and liabilities", "T o t a l  equity and  liabilities")
    assert fund_pdf.find_statement_pages([spaced])["balance"] == [1]    # even heavier spacing still finds it


def test_a_file_that_is_not_a_pdf_gives_a_plain_error_not_a_traceback(tmp_path):
    fake = tmp_path / "report.pdf"
    fake.write_text("this is not a pdf at all")
    with pytest.raises(ValueError, match="not a readable PDF"):
        fund_extract.prepare(str(fake))
    with pytest.raises(ValueError, match="not a readable PDF"):
        fund_pdf.read_pages(str(tmp_path / "does_not_exist.pdf"))


def test_cash_flow_rounding_is_judged_against_the_flows_not_the_small_net_change():
    """Regression: a net change of 30 built from flows of ~30,000 carries rounding error from the flows."""
    v = {"cash_from_operations": 30000.4, "cash_from_investing": -12000.5, "cash_from_financing": -17969.6,
         "net_change_in_cash": 30.0}                                  # sum = 30.3, i.e. rounding, not an error
    c = next(x for x in fund_checks.run_checks(v) if x["id"] == "cash_flow_reconciles")
    assert c["passed"] is True
    v["net_change_in_cash"] = 3000.0                                  # a genuinely wrong figure is still caught
    c = next(x for x in fund_checks.run_checks(v) if x["id"] == "cash_flow_reconciles")
    assert c["passed"] is False
