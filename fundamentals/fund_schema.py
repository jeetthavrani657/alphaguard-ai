"""
fundamentals/fund_schema.py

What the extractor is asked to find, and the small amount of arithmetic the CODE
(never the language model) does on what it returns: parsing a printed number and
converting units.

Design rule for the whole package: the model READS, the code COMPUTES. The model
returns each figure exactly as printed in the filing (e.g. "9,15,423.00" or
"(1,234.5)") together with the page and the verbatim line it came from. Parsing,
sign handling and the lakh/crore/million conversion happen here, where they can be
tested. A model that is asked to do that arithmetic will sometimes get it wrong
and will never say so.

Scope of version 1: non-financial companies, consolidated statements. Banks, NBFCs
and insurers publish differently shaped statements (no "revenue from operations",
a different balance-sheet layout) and need their own schema; they are out.
"""

import re

# field name -> (statement, kind, plain-English description for the model)
#   kind "money": converted to Rs crore; "per_share": kept in Rs as printed.
FIELDS = {
    # --- statement of profit and loss ---
    "revenue_from_operations": ("income", "money", "Revenue from operations (net sales / total operating revenue)."),
    "other_income": ("income", "money", "Other income."),
    "total_income": ("income", "money", "Total income (revenue from operations plus other income)."),
    "total_expenses": ("income", "money", "Total expenses."),
    "finance_costs": ("income", "money", "Finance costs / interest expense."),
    "depreciation_amortisation": ("income", "money", "Depreciation and amortisation expense."),
    "profit_before_tax": ("income", "money", "Profit before tax (the final PBT line, after exceptional items if shown)."),
    "tax_expense": ("income", "money", "Total tax expense (current plus deferred)."),
    "profit_after_tax": ("income", "money", "Profit for the year, total (before splitting between owners and minorities)."),
    "profit_attributable_to_owners": ("income", "money", "Profit for the year attributable to owners of the company."),
    "eps_basic": ("income", "per_share", "Basic earnings per equity share, in rupees."),
    # --- balance sheet ---
    "total_assets": ("balance", "money", "Total assets."),
    "total_equity_and_liabilities": ("balance", "money", "Total equity and liabilities (the balancing total)."),
    "total_equity": ("balance", "money", "Total equity (including non-controlling interests)."),
    "equity_attributable_to_owners": ("balance", "money", "Equity attributable to owners of the company."),
    "non_controlling_interests": ("balance", "money", "Non-controlling interests."),
    "share_capital": ("balance", "money", "Equity share capital."),
    "borrowings_non_current": ("balance", "money", "Non-current borrowings."),
    "borrowings_current": ("balance", "money", "Current borrowings."),
    "cash_and_equivalents": ("balance", "money", "Cash and cash equivalents."),
    "current_assets": ("balance", "money", "Total current assets."),
    "current_liabilities": ("balance", "money", "Total current liabilities."),
    # --- cash flow ---
    "cash_from_operations": ("cashflow", "money", "Net cash from / (used in) operating activities."),
    "cash_from_investing": ("cashflow", "money", "Net cash from / (used in) investing activities."),
    "cash_from_financing": ("cashflow", "money", "Net cash from / (used in) financing activities."),
    "net_change_in_cash": ("cashflow", "money", "Net increase / (decrease) in cash and cash equivalents."),
}
STATEMENTS = ("income", "balance", "cashflow")

# A record is only "verified" if all of these were found AND verified against the page.
REQUIRED = ("revenue_from_operations", "profit_after_tax", "total_assets", "total_equity_and_liabilities", "total_equity")

# How many Rs crore one printed unit is worth. (1 crore = 10 million = 100 lakh = 1e7 rupees.)
UNIT_TO_CRORE = {
    "crore": 1.0, "crores": 1.0, "cr": 1.0,
    "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01,
    "million": 0.1, "millions": 0.1, "mn": 0.1,
    "billion": 100.0, "billions": 100.0, "bn": 100.0,
    "thousand": 1e-4, "thousands": 1e-4,
    "rupees": 1e-7, "inr": 1e-7,
}

_NIL = {"", "-", "--", "—", "–", "nil", "n.a.", "na", "n/a"}


def parse_printed_number(text):
    """
    '9,15,423.00' -> 915423.0 ; '(1,234.5)' -> -1234.5 ; '-12' -> -12.0 ; '--' or 'Nil' -> None.
    Handles Indian digit grouping (commas anywhere) and accounting brackets for negatives.
    Returns None for anything that is not a single number: the caller treats that as "not found".
    """
    if text is None:
        return None
    t = str(text).replace(" ", " ").strip()
    for junk in ("₹", "Rs.", "Rs", "INR"):
        t = t.replace(junk, "")
    t = t.strip().replace("−", "-")                    # unicode minus sign
    if t.lower() in _NIL:
        return None
    negative = False
    m = re.fullmatch(r"\(\s*(.*?)\s*\)", t)
    if m:
        negative, t = True, m.group(1)
    if t.startswith("-"):
        negative, t = True, t[1:].strip()
    t = t.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    value = float(t)
    return -value if negative else value


def to_crore(value, unit):
    """Convert a figure printed in `unit` to Rs crore. Unknown unit -> ValueError (never guess)."""
    factor = UNIT_TO_CRORE.get(str(unit).strip().lower())
    if factor is None:
        raise ValueError(f"unknown unit {unit!r}; known: {sorted(UNIT_TO_CRORE)}")
    return value * factor
