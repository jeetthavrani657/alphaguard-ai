"""
fundamentals/fund_checks.py

Accounting identities a correctly read statement must satisfy. A record that fails
a HARD check is never used (status needs_review). These checks are what turn "a
language model read a PDF" into "a number you can put in a backtest": a misread
digit, a prior-year column, or a wrong unit breaks an identity almost every time.

All inputs are Rs crore (per-share excluded). Tolerance allows for the rounding
that printed statements carry: 0.2% of the larger figure, never less than Rs 0.05 crore.
"""

REL_TOL = 0.002
ABS_TOL_CRORE = 0.05


def _close(a, b):
    return abs(a - b) <= max(REL_TOL * max(abs(a), abs(b)), ABS_TOL_CRORE)


def _check(check_id, severity, values, needed, test, describe):
    """Skipped (passed=None) when a needed field is absent; otherwise runs `test` on them."""
    missing = [n for n in needed if values.get(n) is None]
    if missing:
        return {"id": check_id, "severity": severity, "passed": None,
                "detail": "skipped: " + ", ".join(missing) + " not available"}
    args = [values[n] for n in needed]
    ok = bool(test(*args))
    return {"id": check_id, "severity": severity, "passed": ok,
            "detail": describe(*args) + ("" if ok else "  <-- does not hold")}


def run_checks(values: dict) -> list:
    """values: {field: Rs crore}. Returns a list of {id, severity, passed, detail}."""
    return [
        _check("balance_sheet_balances", "hard", values, ("total_assets", "total_equity_and_liabilities"),
               _close, lambda a, b: f"total assets {a:,.2f} vs total equity and liabilities {b:,.2f}"),
        _check("equity_parts_add_up", "hard", values,
               ("equity_attributable_to_owners", "non_controlling_interests", "total_equity"),
               lambda o, n, t: _close(o + n, t),
               lambda o, n, t: f"owners {o:,.2f} + minorities {n:,.2f} vs total equity {t:,.2f}"),
        _check("cash_flow_reconciles", "hard", values,
               ("cash_from_operations", "cash_from_investing", "cash_from_financing", "net_change_in_cash"),
               lambda o, i, f, n: _close(o + i + f, n),
               lambda o, i, f, n: f"operating {o:,.2f} + investing {i:,.2f} + financing {f:,.2f} vs net change {n:,.2f}"),
        _check("total_income_adds_up", "hard", values, ("revenue_from_operations", "other_income", "total_income"),
               lambda r, o, t: _close(r + o, t),
               lambda r, o, t: f"revenue {r:,.2f} + other income {o:,.2f} vs total income {t:,.2f}"),
        # Warnings only: legitimate statements can break these (associates' profit, discontinued operations).
        _check("profit_chain", "warn", values, ("profit_before_tax", "tax_expense", "profit_after_tax"),
               lambda p, t, a: _close(p - t, a),
               lambda p, t, a: f"PBT {p:,.2f} - tax {t:,.2f} vs profit after tax {a:,.2f}"),
        _check("equity_not_above_assets", "warn", values, ("total_equity", "total_assets"),
               lambda e, a: e <= a + ABS_TOL_CRORE,
               lambda e, a: f"total equity {e:,.2f} vs total assets {a:,.2f}"),
        _check("revenue_positive", "warn", values, ("revenue_from_operations",),
               lambda r: r > 0, lambda r: f"revenue {r:,.2f}"),
    ]


def hard_failures(checks: list) -> list:
    return [c for c in checks if c["severity"] == "hard" and c["passed"] is False]
