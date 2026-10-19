"""
tests/test_health_check.py

research/health_check.py watches the unattended daily run. A monitor that can only say "OK" is worthless,
so these tests build real little project folders and check that each kind of silent failure is caught:
a missing file, a stale file, a crashed step, a failed task, and that a healthy folder passes.
"""

import json
import os
from datetime import date, datetime, timezone

import pytest

import health_check as hc

MON = date(2026, 10, 19)            # a Monday


# --- counting age in weekdays ----------------------------------------------------------------------------------

@pytest.mark.parametrize("earlier,today,lag", [
    (date(2026, 10, 19), date(2026, 10, 19), 0),
    (date(2026, 10, 16), date(2026, 10, 19), 1),        # Friday's file on Monday: one weekday old, not three days
    (date(2026, 10, 16), date(2026, 10, 17), 0),        # Friday's file on Saturday: still fresh, no session since
    (date(2026, 10, 16), date(2026, 10, 18), 0),
    (date(2026, 10, 19), date(2026, 10, 23), 4),
    (date(2026, 10, 12), date(2026, 10, 19), 5),
    (date(2026, 10, 17), date(2026, 10, 19), 1),        # a Saturday file counts as Friday's
])
def test_age_is_counted_in_weekdays_and_a_weekend_does_not_age_a_file(earlier, today, lag):
    assert hc.weekday_lag(earlier, today) == lag


# --- each check's thresholds ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("newest,status", [
    (date(2026, 10, 19), "OK"), (date(2026, 10, 16), "OK"),            # fresh, and Friday's file on a Monday
    (date(2026, 10, 15), "WARN"),                                      # 2 weekdays: a holiday can explain it
    (date(2026, 10, 14), "FAIL"), (None, "FAIL"),
])
def test_a_daily_file_is_ok_warn_or_fail_by_its_age(newest, status):
    c = hc.check_dated_file("x", "x", newest, MON)
    assert c["status"] == status
    if status == "WARN":
        assert "holiday" in c["detail"]


def test_the_news_archive_is_given_a_little_more_slack_than_the_other_files():
    assert hc.check_dated_file("news", "n", date(2026, 10, 14), MON, ok_max=1, warn_max=3)["status"] == "WARN"   # 3 weekdays
    assert hc.check_dated_file("news", "n", date(2026, 10, 13), MON, ok_max=1, warn_max=3)["status"] == "FAIL"   # 4


@pytest.mark.parametrize("days_ago,status", [(0, "OK"), (8, "OK"), (9, "WARN"), (15, "WARN"), (16, "FAIL")])
def test_the_weekly_archive_is_judged_against_a_seven_day_rhythm(days_ago, status):
    newest = date.fromordinal(MON.toordinal() - days_ago)
    assert hc.check_weekly("f", "f", newest, MON)["status"] == status
    assert hc.check_weekly("f", "f", None, MON)["status"] == "FAIL"


def test_a_traceback_in_a_steps_log_is_a_failure_and_shows_the_last_line():
    log = "starting\nTraceback (most recent call last):\n  File x\nValueError: the feed changed shape\n"
    c = hc.check_log_for_crash("l", "l", log)
    assert c["status"] == "FAIL" and "the feed changed shape" in c["detail"]
    assert hc.check_log_for_crash("l", "l", "[books] ok\n")["status"] == "OK"
    assert hc.check_log_for_crash("l", "l", None)["status"] == "WARN"


def test_the_windows_task_result_is_read_correctly():
    now = datetime(2026, 10, 19, 19, 0)
    assert hc.check_task({"last_run": now, "result": 0}, MON)["status"] == "OK"
    assert hc.check_task({"last_run": now, "result": 1}, MON)["status"] == "FAIL"
    assert hc.check_task({"last_run": now, "result": hc.TASK_RUNNING}, MON)["status"] == "OK"
    assert hc.check_task({"last_run": datetime(2026, 10, 12, 19, 0), "result": 0}, MON)["status"] == "FAIL"   # stopped a week ago
    assert hc.check_task({"last_run": None, "result": 0}, MON)["status"] == "FAIL"
    assert hc.check_task(None, MON)["status"] == "WARN"


# --- the whole thing on a real folder -------------------------------------------------------------------------------

def _project(tmp_path, books_through="2026-10-19", run_date="2026-10-19", news="2026-10-19T14:00:00Z"):
    out = tmp_path / "reports" / "output"
    out.mkdir(parents=True)
    (tmp_path / "data" / "news").mkdir(parents=True)
    (tmp_path / "data" / "fundamentals").mkdir(parents=True)
    (out / "forward_snapshots.csv").write_text(f"run_date,data_through\n2026-10-15,2026-10-14\n{run_date},{run_date}\n")
    (out / "forward_books.csv").write_text(f"run_date,book_id,data_through\n{run_date},a,{books_through}\n")
    (out / "forward_books_latest.json").write_text(json.dumps({"books": [{"data_through": books_through}]}))
    (tmp_path / "data" / "news" / "news_log.csv").write_text(f"symbol,first_seen_utc\nTCS,{news}\n")
    (tmp_path / "data" / "fundamentals" / "yf_last_run.txt").write_text("2026-10-16T10:28:29Z")
    for log in ("forward_books_last_run.log", "news_last_run.log", "fundamentals_last_run.log", "forward_last_run.log"):
        (out / log).write_text("all good\n")
    return tmp_path


def _task_ok():
    return {"last_run": datetime(2026, 10, 19, 19, 0), "result": 0}


def test_a_healthy_project_passes_every_check(tmp_path):
    checks = hc.run_checks(MON, str(_project(tmp_path)), lambda: _task_ok())
    assert [c["status"] for c in checks] == ["OK"] * 10 and hc.overall(checks) == "OK"


def test_each_kind_of_silent_failure_is_caught(tmp_path):
    root = _project(tmp_path, books_through="2026-10-12", news="2026-10-08T14:00:00Z")           # stale prices, stale news
    out = tmp_path / "reports" / "output"
    (out / "news_last_run.log").write_text("Traceback (most recent call last):\nRuntimeError: feed down\n")
    os.remove(out / "forward_snapshots.csv")                                                      # a file that vanished
    by = {c["id"]: c for c in hc.run_checks(MON, str(root), lambda: {"last_run": datetime(2026, 10, 19, 19, 0), "result": 1})}
    assert by["task"]["status"] == "FAIL" and by["dip_log"]["status"] == "FAIL"
    assert by["price_data"]["status"] == "FAIL" and by["news"]["status"] == "FAIL"
    assert by["log_news"]["status"] == "FAIL" and "feed down" in by["log_news"]["detail"]
    assert by["fundamentals"]["status"] == "OK" and by["log_books"]["status"] == "OK"             # and healthy parts stay green
    assert hc.overall(list(by.values())) == "FAIL"


def test_overall_is_the_worst_single_check():
    ok, warn, fail = {"status": "OK"}, {"status": "WARN"}, {"status": "FAIL"}
    assert hc.overall([ok, ok]) == "OK" and hc.overall([ok, warn]) == "WARN" and hc.overall([ok, warn, fail]) == "FAIL"


def test_bad_rows_in_a_csv_are_skipped_not_fatal(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("run_date,x\nnot-a-date,1\n2026-10-15,2\n,3\n")
    assert hc._newest_csv_date(str(p), "run_date") == date(2026, 10, 15)
    assert hc._newest_csv_date(str(tmp_path / "missing.csv"), "run_date") is None


def test_the_payload_is_written_atomically_and_carries_the_overall_status(tmp_path):
    payload = hc.build_payload([{"id": "a", "label": "A", "status": "WARN", "detail": "d"}],
                               datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc))
    path = str(tmp_path / "out" / "health.json")
    hc.write_latest(payload, path)
    assert json.load(open(path)) == payload and not os.path.exists(path + ".tmp")
    assert payload["overall"] == "WARN" and payload["generated_at"] == "2026-10-19T13:30:00Z"
