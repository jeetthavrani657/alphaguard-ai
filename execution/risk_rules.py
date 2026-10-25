"""
execution/risk_rules.py

The ACCOUNT-level risk rules of RISK_RULES.md, for the paper layer: what the account does when things go badly, whatever the rule that is trading says. Pure functions on numbers
(no files, no network): the paper layer reads the account, asks these, and halts. They halt; they never sell, never change a rule's decision, and never place anything.

    drawdown breaker   the account's fall from its highest value:  warning, halt (no new orders), review (everything stops until a person has looked)
    daily loss limit   a single day's fall in the account's value:  halt

THE NUMBERS BELOW ARE PROPOSALS from RISK_RULES.md. The owner has not yet answered its five questions, so these are placeholders chosen to be conservative, kept in this one place
so that changing them is a one-line edit, and every one has a test that makes it bite. Nothing real depends on them: the layer is simulated.
"""

RISK = {
    "drawdown_warning": 0.05,       # a visible alert; nothing stops
    "drawdown_halt": 0.10,          # no new orders until a person writes a note (the same 10% as go-live gate 7)
    "drawdown_review": 0.15,        # everything stops until the rule has been re-judged
    "daily_loss_halt": 0.03,        # one day's fall of this much halts new orders: a daily-bar rule should never lose this in a day, so something is wrong
}

OK, WARNING, HALT, REVIEW = "OK", "WARNING", "HALT", "REVIEW"


def drawdown(equity: float, peak: float) -> float:
    """How far the account is below its highest value, as a fraction (0.12 = 12% below). Never negative: a new high is zero."""
    if peak <= 0:
        return 0.0
    return max(0.0, 1.0 - equity / peak)


def breaker_level(dd: float, risk: dict = RISK) -> str:
    if dd >= risk["drawdown_review"]:
        return REVIEW
    if dd >= risk["drawdown_halt"]:
        return HALT
    if dd >= risk["drawdown_warning"]:
        return WARNING
    return OK


def daily_loss(equity: float, previous_equity: float) -> float:
    """The fall since the previous day's value, as a fraction (0.03 = lost 3%). A gain is zero."""
    if previous_equity <= 0:
        return 0.0
    return max(0.0, 1.0 - equity / previous_equity)


def update_marks(account: dict, equity: float, day: str) -> dict:
    """
    Keep the account's highest value and its last two daily values in `account["risk"]`. The highest value starts at the money put in. A second look on the same day replaces that day's
    value (so running the step twice cannot make a day look like two); a new day moves the old value into `prev_equity`, which is what the daily loss is measured against.
    """
    r = account.setdefault("risk", {})
    start = float(account.get("initial_cash", equity))
    r["peak_equity"] = max(float(r.get("peak_equity", start)), equity)                # starts at the money put in; after a resume (rebase_peak) it may legitimately be lower
    if r.get("last_day") != day:
        r["prev_equity"] = float(r.get("last_equity", start))
        r["prev_day"] = r.get("last_day")
        r["last_day"] = day
    r["last_equity"] = float(equity)
    return r


def assess(account: dict, equity: float, day: str, risk: dict = RISK) -> dict:
    """
    Update the marks and judge the account: {"level", "drawdown_pct", "daily_loss_pct", "peak_equity", "halt", "reasons"}. `halt` is True for HALT and REVIEW, or a daily loss at or above its limit.
    """
    marks = update_marks(account, equity, day)
    dd = drawdown(equity, marks["peak_equity"])
    level = breaker_level(dd, risk)
    loss = daily_loss(equity, marks["prev_equity"])
    reasons = []
    if level in (HALT, REVIEW):
        reasons.append(f"the account is {dd * 100:.1f}% below its highest value ({marks['peak_equity']:,.0f}): "
                       + ("everything stops until the rule has been re-judged" if level == REVIEW else "no new orders until a person has looked"))
    if loss >= risk["daily_loss_halt"]:
        reasons.append(f"the account lost {loss * 100:.1f}% in one day (limit {risk['daily_loss_halt'] * 100:.0f}%): something may be wrong with the data or the code")
    return {"level": level, "drawdown_pct": round(dd * 100, 2), "daily_loss_pct": round(loss * 100, 2), "peak_equity": marks["peak_equity"],
            "halt": bool(reasons), "reasons": reasons}


def rebase_peak(account: dict) -> tuple:
    """After a person has looked and written a note: the highest value becomes today's value, so the same fall does not halt the next step again. Returns (old peak, new peak)."""
    r = account.setdefault("risk", {})
    old = float(r.get("peak_equity", account.get("initial_cash", 0.0)))
    new = float(r.get("last_equity", old))
    r["peak_equity"] = new
    return old, new
