"""
tests/test_alerts.py

research/alerts.py reads the files the daily run wrote and sends a short message to the owner's own Telegram bot. What must hold: a problem is reported when
it appears and is not repeated more than once a day, a digest goes out once, nothing is marked sent unless it was, the token never appears in a log or an error,
and without credentials nothing leaves the computer. No network: the transport is a fake.
"""

import json
import os
import urllib.error
from datetime import date, datetime, timezone

import pytest

import alerts

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
SECRET = "123456:SECRET-TOKEN-VALUE"
CREDS = (SECRET, "999")


@pytest.fixture
def root(tmp_path):
    out = tmp_path / "reports" / "output"
    out.mkdir(parents=True)
    write(out / "health_latest.json", {"generated_at": "2026-10-23T13:30:00Z", "overall": "OK", "checks": [{"id": "task", "label": "Windows task", "status": "OK", "detail": "fine"}]})
    write(out / "forward_books_latest.json", {"books": [
        {"id": "m", "name": "Momentum", "data_through": "2026-10-22", "n_trading_days": 3, "summary": {"return_pct": -2.0, "benchmark_return_pct": -1.75}},
        {"id": "n", "name": "Not started", "data_through": "2026-10-22", "n_trading_days": 0, "summary": None}]})
    write(out / "advisory_forward_latest.json", {"profiles": [{"id": "c", "name": "Conservative", "data_through": "2026-10-22", "n_trading_days": 2,
                                                              "summary": {"return_pct": -0.99, "benchmark_return_pct": -0.86}}]})
    return str(tmp_path)


def write(path, data):
    path.write_text(json.dumps(data))


def out_dir(root):
    return os.path.join(root, "reports", "output")


# ---- what applies right now --------------------------------------------------------------------------------------------------------------

def test_a_healthy_day_gives_just_the_digest_with_every_book_and_the_reminder(root):
    found = alerts.collect_alerts(root, NOW)
    assert [a["key"] for a in found] == ["digest:2026-10-22"] and found[0]["level"] == "INFO"
    text = found[0]["text"]
    assert "Momentum: -2.00% vs buy-and-hold -1.75% (-0.25 pts), day 3 of 252" in text and "Not started: not started" in text
    assert "Conservative: -0.99% vs Nifty ETF -0.86% (-0.13 pts), day 2 of 252" in text
    assert "Stock books" in text and "Advisory profiles" in text and text.index("Stock books") < text.index("Advisory profiles")
    assert "not evidence" in text and "252" in text


def test_the_digest_shows_ahead_as_plus_behind_as_minus_and_reads_the_days_needed_from_the_file(root):
    write(open_path(root, "forward_books_latest.json"), {"min_days_for_sharpe": 200, "books": [
        {"id": "a", "name": "Ahead", "data_through": "2026-10-22", "n_trading_days": 5, "summary": {"return_pct": 1.5, "benchmark_return_pct": 0.5}},
        {"id": "b", "name": "No benchmark", "data_through": "2026-10-22", "n_trading_days": 5, "summary": {"return_pct": 1.5, "benchmark_return_pct": None}}]})
    text = alerts.collect_alerts(root, NOW)[0]["text"]
    assert "Ahead: +1.50% vs buy-and-hold +0.50% (+1.00 pts), day 5 of 200" in text
    assert "No benchmark: +1.50% vs buy-and-hold n/a, day 5 of 200" in text and "a verdict needs 200 trading days" in text


def test_a_digest_with_only_one_kind_of_result_still_reads_cleanly(root):
    os.remove(open_path(root, "advisory_forward_latest.json"))
    text = alerts.collect_alerts(root, NOW)[0]["text"]
    assert "Stock books" in text and "Advisory profiles" not in text and "Conservative" not in text


def test_a_health_problem_names_every_check_that_is_not_ok(root):
    write(open_path(root, "health_latest.json"), {"generated_at": "2026-10-23T13:30:00Z", "overall": "FAIL", "checks": [
        {"id": "task", "label": "Windows task", "status": "OK", "detail": "fine"},
        {"id": "price_data", "label": "Price data", "status": "FAIL", "detail": "3 weekdays old"},
        {"id": "news", "label": "News archive", "status": "WARN", "detail": "2 weekdays old"}]})
    problem = [a for a in alerts.collect_alerts(root, NOW) if a["level"] == "PROBLEM"]
    assert len(problem) == 1 and problem[0]["key"] == "health:news,price_data"
    assert "Price data: 3 weekdays old" in problem[0]["text"] and "News archive: 2 weekdays old" in problem[0]["text"] and "Windows task" not in problem[0]["text"]


def open_path(root, name):
    import pathlib
    return pathlib.Path(out_dir(root)) / name


def test_a_missing_or_old_health_file_is_itself_a_problem(root):
    os.remove(open_path(root, "health_latest.json"))
    assert [a["key"] for a in alerts.collect_alerts(root, NOW) if a["level"] == "PROBLEM"] == ["health:missing"]
    write(open_path(root, "health_latest.json"), {"generated_at": "2026-10-20T13:30:00Z", "overall": "OK", "checks": []})
    old = [a for a in alerts.collect_alerts(root, NOW) if a["level"] == "PROBLEM"]
    assert old[0]["key"] == "health:stale" and "hours ago" in old[0]["text"]


def test_a_rejected_upstox_token_in_the_last_run_is_reported_and_its_absence_is_not(root):
    assert not any(a["key"] == "upstox:token" for a in alerts.collect_alerts(root, NOW))
    open_path(root, "forward_books_last_run.log").write_text("[upstox-tail] the token was rejected; the newest sessions will come from Yahoo alone\n")
    assert any(a["key"] == "upstox:token" and "Regenerate" in a["text"] for a in alerts.collect_alerts(root, NOW))


def test_a_stopped_paper_execution_layer_is_reported_with_its_reason_and_reading_creates_nothing(root):
    state = os.path.join(root, "execution", "state")
    assert not os.path.exists(state) and not [a for a in alerts.collect_alerts(root, NOW) if a["key"].startswith("execution")]
    assert not os.path.exists(state)                                           # looking did not create the folder
    os.makedirs(state)
    open(os.path.join(state, "HALT_RECON"), "w").write("positions differ: A expected 100, actual 107\n")
    open(os.path.join(state, "KILL"), "w").write("manual stop\n")
    found = {a["key"]: a for a in alerts.collect_alerts(root, NOW)}
    assert "actual 107" in found["execution:HALT_RECON"]["text"] and "manual stop" in found["execution:KILL"]["text"]


# ---- not repeating itself ---------------------------------------------------------------------------------------------------------------------------

def _problem(key="health:x", text="Health FAIL\n- a: b"):
    return {"key": key, "level": "PROBLEM", "text": text}


def test_a_problem_goes_out_once_a_day_while_it_lasts_and_a_digest_goes_out_once():
    digest = {"key": "digest:2026-10-22", "level": "INFO", "text": "d"}
    first, state = alerts.plan([_problem(), digest], {}, date(2026, 10, 23))
    assert [a["key"] for a in first] == ["health:x", "digest:2026-10-22"]
    state["sent"].update({"health:x": "2026-10-23", "digest:2026-10-22": "2026-10-23"})
    same_day, state2 = alerts.plan([_problem(), digest], state, date(2026, 10, 23))
    assert same_day == []
    next_day, _ = alerts.plan([_problem(), digest], state2, date(2026, 10, 24))
    assert [a["key"] for a in next_day] == ["health:x"]                         # reminded again; the digest is not


def test_a_problem_that_clears_is_reported_once_as_resolved():
    state = {"sent": {"health:x": "2026-10-23"}, "active": {"health:x": "Health FAIL\n- a: b"}}
    to_send, new = alerts.plan([], state, date(2026, 10, 24))
    assert [a["text"] for a in to_send] == ["Resolved: Health FAIL"] and new["active"] == {}
    again, _ = alerts.plan([], new, date(2026, 10, 25))
    assert again == []


# ---- sending ---------------------------------------------------------------------------------------------------------------------------------------------

class Post:
    def __init__(self, status=200, boom=None):
        self.calls, self.status, self.boom = [], status, boom

    def __call__(self, url, body):
        self.calls.append((url, body))
        if self.boom:
            raise self.boom
        return self.status


def test_a_run_sends_what_is_new_records_it_and_does_not_send_it_again(root):
    post = Post()
    first = alerts.run(root, NOW, credentials=CREDS, post=post)
    assert first["sent"] == ["digest:2026-10-22"] and len(post.calls) == 1
    url, body = post.calls[0]
    assert url == f"https://api.telegram.org/bot{SECRET}/sendMessage" and b"chat_id=999" in body and b"Paper+tests+through+2026-10-22" in body
    second = alerts.run(root, NOW, credentials=CREDS, post=post)
    assert second["to_send"] == [] and len(post.calls) == 1


def test_nothing_leaves_the_computer_without_credentials_and_what_would_have_gone_is_logged(root, capsys):
    post = Post()
    r = alerts.run(root, NOW, credentials=None, post=post)
    assert r["sent"] == [] and r["not_sent"] == ["digest:2026-10-22"] and post.calls == []
    assert "NOT SENT (no Telegram credentials)" in open(os.path.join(out_dir(root), alerts.LOG_NAME)).read()
    later = alerts.run(root, NOW, credentials=CREDS, post=Post())              # once credentials exist, the unsent digest still goes
    assert later["sent"] == ["digest:2026-10-22"]


def test_a_failed_send_is_not_marked_sent_and_is_tried_again_next_run(root):
    r = alerts.run(root, NOW, credentials=CREDS, post=Post(status=500))
    assert r["sent"] == [] and r["not_sent"] == ["digest:2026-10-22"]
    assert alerts.run(root, NOW, credentials=CREDS, post=Post())["sent"] == ["digest:2026-10-22"]


def test_a_dry_run_prints_and_changes_nothing(root, capsys):
    r = alerts.run(root, NOW, credentials=CREDS, post=Post(), dry_run=True)
    assert r["to_send"] == ["digest:2026-10-22"] and "would send" in capsys.readouterr().out
    assert not os.path.exists(os.path.join(out_dir(root), alerts.STATE_NAME)) and not os.path.exists(os.path.join(out_dir(root), alerts.LOG_NAME))


def test_the_token_never_appears_in_an_error_a_log_or_a_state_file(root):
    boom = urllib.error.URLError(f"cannot reach https://api.telegram.org/bot{SECRET}/sendMessage")
    ok, detail = alerts.send_telegram("hi", CREDS, Post(boom=boom))
    assert not ok and SECRET not in detail and "URLError" in detail
    http = urllib.error.HTTPError(f"https://api.telegram.org/bot{SECRET}/sendMessage", 401, "Unauthorized", {}, None)
    ok, detail = alerts.send_telegram("hi", CREDS, Post(boom=http))
    assert not ok and SECRET not in detail and "401" in detail
    alerts.run(root, NOW, credentials=CREDS, post=Post(boom=boom))
    alerts.run(root, NOW, credentials=CREDS, post=Post())
    for name in (alerts.LOG_NAME, alerts.STATE_NAME):
        assert SECRET not in open(os.path.join(out_dir(root), name)).read()


def test_a_long_message_is_cut_to_what_telegram_accepts():
    post = Post()
    alerts.send_telegram("x" * 10_000, CREDS, post)
    assert len(post.calls[0][1]) < 4096 + 200                                  # the encoded body, with its other fields


def test_credentials_come_only_when_both_variables_are_set(monkeypatch):
    import upstox_client
    values = {"ALPHAGUARD_TELEGRAM_TOKEN": "t", "ALPHAGUARD_TELEGRAM_CHAT_ID": None}
    monkeypatch.setattr(upstox_client, "get_credential", lambda name: values.get(name))
    assert alerts.get_credentials() is None
    values["ALPHAGUARD_TELEGRAM_CHAT_ID"] = "c"
    assert alerts.get_credentials() == ("t", "c")


def test_a_blocked_upstox_address_is_reported_without_telling_the_owner_to_regenerate_the_token(root):
    open_path(root, "forward_books_last_run.log").write_text("[upstox-tail] Upstox blocked this address (Cloudflare); the newest sessions will come from Yahoo alone this run.\n")
    found = {a["key"]: a for a in alerts.collect_alerts(root, NOW)}
    assert "upstox:blocked" in found and "upstox:token" not in found
    assert "token will not fix" in found["upstox:blocked"]["text"] and "Regenerate" not in found["upstox:blocked"]["text"]
