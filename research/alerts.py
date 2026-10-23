"""
research/alerts.py

Tells the owner, on their phone, what they would otherwise have to open the app to find out. It reads the files the daily run already wrote
and sends a short Telegram message to the owner's OWN bot chat. Nothing here trades, reads an account, or touches a broker.

What it sends:
  * a PROBLEM alert when the daily health check is not OK, when the Upstox token was rejected in tonight's run, or when the paper execution layer is
    stopped (a kill switch or a reconciliation halt). A problem is repeated once a day while it lasts, and a "resolved" note is sent when it clears.
  * ONE digest per trading day: how each paper book and advisory profile stands against its benchmark, with the reminder that it is not evidence yet.

It needs two values in WINDOWS ENVIRONMENT VARIABLES (never in a file, the repository or chat):
    ALPHAGUARD_TELEGRAM_TOKEN     the token of a bot the owner created with Telegram's BotFather
    ALPHAGUARD_TELEGRAM_CHAT_ID   the owner's own chat id with that bot
Without them nothing is sent: what would have been sent is written to reports/output/alerts_log.txt instead, so the check can be seen working.

    python research/alerts.py --test       send one test message (needs the two variables)
    python research/alerts.py --dry-run    print what would be sent, change nothing
    python research/alerts.py              what the daily run does, last
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))

OUT_DIR = os.path.join("reports", "output")
STATE_NAME = "alerts_state.json"
LOG_NAME = "alerts_log.txt"
TELEGRAM_LIMIT = 3800                      # Telegram refuses messages over 4096 characters; stay well inside
HEALTH_STALE_HOURS = 36


# ---- reading what the daily run left ---------------------------------------------------------------------------------------------------

def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _pct(x) -> str:
    return "n/a" if x is None else f"{x:+.2f}%"


def collect_alerts(root: str, now: datetime, state_dir: str | None = None) -> list:
    """Every alert that applies right now, each {key, level, text}. `level` is PROBLEM or INFO. Nothing is sent here."""
    out = os.path.join(root, OUT_DIR)
    alerts = []

    health = _read_json(os.path.join(out, "health_latest.json"))
    if health is None:
        alerts.append({"key": "health:missing", "level": "PROBLEM", "text": "The daily health check has not written its file. Is the daily run working?"})
    else:
        age_h = (now - datetime.strptime(health["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        bad = [c for c in health["checks"] if c["status"] != "OK"]
        if age_h > HEALTH_STALE_HOURS:
            alerts.append({"key": "health:stale", "level": "PROBLEM", "text": f"The daily health check last ran {age_h:.0f} hours ago. The daily run may have stopped."})
        elif health["overall"] != "OK":
            alerts.append({"key": "health:" + ",".join(sorted(c["id"] for c in bad)), "level": "PROBLEM",
                           "text": f"Health check {health['overall']}:\n" + "\n".join(f"- {c['label']}: {c['detail']}" for c in bad)})

    if "token was rejected" in _read_text(os.path.join(out, "forward_books_last_run.log")):
        alerts.append({"key": "upstox:token", "level": "PROBLEM",
                       "text": "The Upstox token was rejected in the last run, which fell back to Yahoo alone. Regenerate the token if you want the newest day without waiting for Yahoo."})

    if "blocked this address" in _read_text(os.path.join(out, "forward_books_last_run.log")):
        alerts.append({"key": "upstox:blocked", "level": "PROBLEM",
                       "text": "Upstox's network (Cloudflare) blocked this computer's address in the last run, which fell back to Yahoo alone. A new token will not fix this; it usually clears by itself."})

    folder = state_dir or os.path.join(root, "execution", "state")
    for name, text in (("HALT_RECON", "Paper execution is HALTED after a reconciliation difference"), ("KILL", "The paper execution kill switch is engaged")):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            alerts.append({"key": "execution:" + name, "level": "PROBLEM", "text": f"{text}: {_read_text(path).strip()[:400]}"})

    digest = _digest(out)
    if digest:
        alerts.append(digest)
    return alerts


def _digest(out_dir: str) -> dict | None:
    books = _read_json(os.path.join(out_dir, "forward_books_latest.json"))
    adv = _read_json(os.path.join(out_dir, "advisory_forward_latest.json"))
    lines, dates = [], []
    for b in (books or {}).get("books", []):
        s = b.get("summary")
        dates.append(b.get("data_through"))
        lines.append(f"- {b['name']}: day {b.get('n_trading_days', 0)}, {_pct(s['return_pct']) if s else 'not started'}"
                     + (f" vs {_pct(s['benchmark_return_pct'])} holding" if s else ""))
    for p in (adv or {}).get("profiles", []):
        s = p.get("summary")
        dates.append(p.get("data_through"))
        lines.append(f"- {p['name']}: day {p.get('n_trading_days', 0)}, {_pct(s.get('return_pct')) if s and s.get('return_pct') is not None else 'not started'}"
                     + (f" vs {_pct(s['benchmark_return_pct'])} Nifty ETF" if s and s.get('return_pct') is not None else ""))
    dates = [d for d in dates if d]
    if not lines or not dates:
        return None
    day = max(dates)
    return {"key": f"digest:{day}", "level": "INFO",
            "text": f"Paper tests through {day}\n" + "\n".join(lines) + "\nThese are daily moves, not evidence: a verdict needs 252 trading days."}


# ---- not repeating itself -------------------------------------------------------------------------------------------------------------------

def plan(alerts: list, state: dict, today: date) -> tuple:
    """
    (to_send, new_state_if_all_sent). A digest goes out once. A problem goes out when it first appears and again once a day while it lasts. A problem
    that was active and is no longer present is reported once as resolved.
    """
    sent, active = dict(state.get("sent", {})), dict(state.get("active", {}))
    to_send, now_active = [], {}
    for a in alerts:
        if a["level"] == "PROBLEM":
            now_active[a["key"]] = a["text"]
            last = sent.get(a["key"])
            if last is None or (today - date.fromisoformat(last)).days >= 1:
                to_send.append(a)
        elif a["key"] not in sent:
            to_send.append(a)
    for key, text in active.items():
        if key not in now_active:
            to_send.append({"key": "resolved:" + key, "level": "INFO", "text": "Resolved: " + text.splitlines()[0]})
    return to_send, {"active": now_active, "sent": sent}


# ---- sending -----------------------------------------------------------------------------------------------------------------------------------

def get_credentials():
    """(token, chat_id) from the environment, or None. The token is only ever used to build the request and is never printed or logged."""
    from upstox_client import get_credential              # the same "this process, then Windows user variables" lookup the project already uses
    token, chat = get_credential("ALPHAGUARD_TELEGRAM_TOKEN"), get_credential("ALPHAGUARD_TELEGRAM_CHAT_ID")
    return (token, chat) if token and chat else None


def send_telegram(text: str, credentials: tuple, post=None) -> tuple:
    """(ok, detail). The detail never contains the token, even on an error."""
    token, chat_id = credentials
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:TELEGRAM_LIMIT], "disable_web_page_preview": "true"}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        if post is not None:
            status = post(url, body)
        else:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=20) as r:
                status = r.status
        return (status == 200), f"HTTP {status}"
    except urllib.error.HTTPError as e:
        return False, f"Telegram answered HTTP {e.code}"                       # not str(e): that can carry the address, which contains the token
    except Exception as e:
        return False, f"could not send ({type(e).__name__})"


def _log(root: str, line: str) -> None:
    os.makedirs(os.path.join(root, OUT_DIR), exist_ok=True)
    with open(os.path.join(root, OUT_DIR, LOG_NAME), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {line}\n")


def run(root: str = PROJECT_ROOT, now: datetime | None = None, credentials=None, post=None, dry_run: bool = False, state_dir: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    state_path = os.path.join(root, OUT_DIR, STATE_NAME)
    state = _read_json(state_path) or {}
    to_send, new_state = plan(collect_alerts(root, now, state_dir), state, now.date())
    result = {"to_send": [a["key"] for a in to_send], "sent": [], "not_sent": []}
    if dry_run:
        for a in to_send:
            print(f"--- would send [{a['level']}] {a['key']}\n{a['text']}")
        return result
    for a in to_send:
        if credentials is None:
            _log(root, f"NOT SENT (no Telegram credentials) [{a['level']}] {a['key']}: {a['text'][:200].replace(chr(10), ' | ')}")
            result["not_sent"].append(a["key"])
            continue
        ok, detail = send_telegram(a["text"], credentials, post)
        _log(root, f"{'SENT' if ok else 'FAILED'} [{a['level']}] {a['key']} ({detail})")
        (result["sent"] if ok else result["not_sent"]).append(a["key"])
        if ok:
            new_state["sent"][a["key"]] = now.date().isoformat()
    for key in [k for k in list(new_state["active"]) if k in result["not_sent"]]:       # a problem that could not be sent stays unsent, so it is tried again
        new_state["sent"].pop(key, None)
    os.makedirs(os.path.join(root, OUT_DIR), exist_ok=True)
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new_state, f, indent=1)
    os.replace(tmp, state_path)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phone alerts from the daily run's files (read-only; sends to the owner's own Telegram bot).")
    ap.add_argument("--test", action="store_true", help="send one test message")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent and change nothing")
    args = ap.parse_args(argv)
    creds = get_credentials()
    if args.test:
        if creds is None:
            print("No credentials: set ALPHAGUARD_TELEGRAM_TOKEN and ALPHAGUARD_TELEGRAM_CHAT_ID as Windows environment variables first.")
            return 1
        ok, detail = send_telegram("AlphaGuard alerts are working.", creds)
        print(("Test message sent." if ok else "The test message was not sent: ") + ("" if ok else detail))
        return 0 if ok else 1
    result = run(credentials=creds, dry_run=args.dry_run)
    print(f"[alerts] to send: {result['to_send']}; sent: {result['sent']}; not sent: {result['not_sent']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
