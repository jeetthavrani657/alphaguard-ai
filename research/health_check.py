"""
research/health_check.py

Is the forward test still being recorded? Nothing here judges a strategy. It only checks that the
unattended daily run (run_forward_log.bat, Windows task NSE-ForwardTest-Daily) has really been
producing its files, because the evidence this project is waiting for takes two years to collect and
a silent failure (PC off, network down, a changed data feed, a crashed step) can cost days of it for good.
The news archive in particular cannot be recovered after the fact.

It runs at the START of each daily run, so it judges the previous run's footprints, and writes
reports/output/health_latest.json for the web app's status bar. Each check is OK, WARN or FAIL.

Age is counted in WEEKDAYS (Mon-Fri). Exchange holidays are not known, so one holiday can push a
healthy system to a lag of 2 (a WARN, not a FAIL); the message says so.

    python research/health_check.py
"""

import csv
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PROJECT_ROOT, "reports", "output")
LATEST_PATH = os.path.join(OUT, "health_latest.json")
TASK_NAME = "NSE-ForwardTest-Daily"
TASK_RUNNING = 267009                  # Windows' "the task is running now" result code

import numpy as np

LEVELS = {"OK": 0, "WARN": 1, "FAIL": 2}


def weekday_lag(earlier: date, today: date) -> int:
    """Whole weekdays between two dates, with a weekend today counted as the Friday before it (0 = fresh)."""
    today = np.busday_offset(today.isoformat(), 0, roll="backward").astype(date)
    earlier = np.busday_offset(earlier.isoformat(), 0, roll="backward").astype(date)
    return int(np.busday_count(earlier.isoformat(), today.isoformat()))


def _grade(lag: int, ok_max: int, warn_max: int) -> str:
    return "OK" if lag <= ok_max else "WARN" if lag <= warn_max else "FAIL"


def _check(cid: str, label: str, status: str, detail: str) -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail}


def _missing(cid: str, label: str, what: str) -> dict:
    return _check(cid, label, "FAIL", f"{what} does not exist, so it has never been written")


# --- the individual checks (each takes plain values, so each is testable without a disk) ---------------------------

def check_dated_file(cid: str, label: str, newest: date | None, today: date, ok_max: int = 1, warn_max: int = 2) -> dict:
    if newest is None:
        return _check(cid, label, "FAIL", "no rows or no readable date")
    lag = weekday_lag(newest, today)
    status = _grade(lag, ok_max, warn_max)
    note = " (one exchange holiday can cause a lag of 2)" if status == "WARN" else ""
    return _check(cid, label, status, f"newest entry {newest.isoformat()}, {lag} weekday(s) ago{note}")


def check_weekly(cid: str, label: str, newest: date | None, today: date) -> dict:
    """The fundamentals archive runs weekly (gated to every 7 days)."""
    if newest is None:
        return _check(cid, label, "FAIL", "never ran")
    age = (today - newest).days
    status = "OK" if age <= 8 else "WARN" if age <= 15 else "FAIL"
    return _check(cid, label, status, f"last ran {newest.isoformat()}, {age} day(s) ago (expected every 7)")


def check_log_for_crash(cid: str, label: str, log_text: str | None) -> dict:
    if log_text is None:
        return _check(cid, label, "WARN", "no log from the last run")
    if "Traceback (most recent call last)" in log_text:
        last = [ln for ln in log_text.strip().splitlines() if ln.strip()][-1][:140]
        return _check(cid, label, "FAIL", f"the last run crashed: {last}")
    return _check(cid, label, "OK", "the last run's log shows no crash")


def check_task(info: dict | None, today: date) -> dict:
    """info: {'last_run': datetime-or-None, 'result': int} from Windows, or None if it could not be read."""
    label = f"Windows task {TASK_NAME}"
    if info is None:
        return _check("task", label, "WARN", "could not read the task (not Windows, or it does not exist)")
    if info["result"] == TASK_RUNNING:
        return _check("task", label, "OK", "running right now (its previous result is not visible while it runs)")
    if info["result"] != 0:
        return _check("task", label, "FAIL", f"the last run ended with error code {info['result']}")
    if info["last_run"] is None:
        return _check("task", label, "FAIL", "has never run")
    lag = weekday_lag(info["last_run"].date(), today)
    return _check("task", label, _grade(lag, 1, 2), f"last ran {info['last_run'].date().isoformat()}, {lag} weekday(s) ago, result 0")


# --- reading the real files ---------------------------------------------------------------------------------------------

def _newest_csv_date(path: str, column: str) -> date | None:
    if not os.path.exists(path):
        return None
    newest = None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                d = datetime.strptime(row[column][:10], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            newest = d if newest is None or d > newest else newest
    return newest


def _read_text(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_task_info(task_name: str = TASK_NAME) -> dict | None:
    """Last run time and result of the Windows scheduled task, or None when it cannot be read."""
    if os.name != "nt":
        return None
    script = (f"$i = Get-ScheduledTaskInfo -TaskName '{task_name}' -ErrorAction Stop; "
              "Write-Output ('{0}|{1}' -f $i.LastRunTime.ToString('s'), $i.LastTaskResult)")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        stamp, result = out.split("|")
        last = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S")
        return {"last_run": None if last.year < 2000 else last, "result": int(result)}
    except Exception:
        return None


def run_checks(today: date, root: str = PROJECT_ROOT, task_info=read_task_info) -> list:
    out = os.path.join(root, "reports", "output")
    books_file = os.path.join(out, "forward_books_latest.json")
    books_data = None
    if os.path.exists(books_file):
        with open(books_file, encoding="utf-8") as f:
            data_through = [b["data_through"] for b in json.load(f).get("books", [])]
        books_data = datetime.strptime(min(data_through)[:10], "%Y-%m-%d").date() if data_through else None
    fund_run = _read_text(os.path.join(root, "data", "fundamentals", "yf_last_run.txt"))
    fund_date = None
    if fund_run:
        try:
            fund_date = datetime.strptime(fund_run.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    checks = [
        check_task(task_info(), today),
        check_dated_file("dip_log", "Dip-rule forward log (forward_snapshots.csv)",
                         _newest_csv_date(os.path.join(out, "forward_snapshots.csv"), "run_date"), today),
        check_dated_file("books_log", "Paper books history (forward_books.csv)",
                         _newest_csv_date(os.path.join(out, "forward_books.csv"), "run_date"), today),
        check_dated_file("price_data", "Price data behind the books (oldest book's data date)", books_data, today),
        check_dated_file("news", "News archive (news_log.csv)",
                         _newest_csv_date(os.path.join(root, "data", "news", "news_log.csv"), "first_seen_utc"), today,
                         ok_max=1, warn_max=3),
        check_weekly("fundamentals", "Fundamentals archive (weekly)", fund_date, today),
    ]
    for cid, label, log in (("log_books", "Paper books run", "forward_books_last_run.log"),
                            ("log_news", "News logger run", "news_last_run.log"),
                            ("log_fundamentals", "Fundamentals run", "fundamentals_last_run.log"),
                            ("log_dip", "Dip-rule run", "forward_last_run.log")):
        checks.append(check_log_for_crash(cid, label, _read_text(os.path.join(out, log))))
    return checks


def overall(checks: list) -> str:
    return max((c["status"] for c in checks), key=LEVELS.get, default="OK")


def build_payload(checks: list, now: datetime) -> dict:
    return {"generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "overall": overall(checks), "checks": checks}


def write_latest(payload: dict, path: str = LATEST_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, path)


def main() -> int:
    payload = build_payload(run_checks(date.today()), datetime.now(timezone.utc))
    write_latest(payload)
    mark = {"OK": "ok  ", "WARN": "WARN", "FAIL": "FAIL"}
    for c in payload["checks"]:
        print(f"[health] {mark[c['status']]} {c['label']}: {c['detail']}")
    print(f"[health] overall: {payload['overall']}")
    return 1 if payload["overall"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
