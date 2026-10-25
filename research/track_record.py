"""
research/track_record.py

Checks that the project's record has not been rewritten, from the one thing nobody can quietly edit afterwards: the git history of the public repository.

  1. The hypothesis ledger is an unbroken chain (each run starts where the last one ended) and its total is the sum of its runs.
  2. The ledger only ever grew: in every committed version, the runs of the earlier version are still there, unchanged.
  3. The forward paper-trading files only ever grew: a row that was written for an earlier day was never changed in a later version.
  4. Each rule's design document was committed BEFORE the forward test it describes began (the frozen-in-advance claim), judged by the order of the commits and
     not by their dates, which anyone can set; and how often it was edited since.

Anyone with a copy of the repository can run this and get the same answers; nothing here is trusted from the web app. A check that cannot be made (no git history, a
file not in git yet) is reported as such and never as a pass.

    python research/track_record.py        # writes reports/output/track_record_latest.json and prints each check
"""

import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "reports", "output", "track_record_latest.json")
LEDGER = "research/hypothesis_ledger.json"
FORWARD_FILES = ["reports/output/forward_snapshots.csv", "reports/output/forward_books.csv", "reports/output/advisory_forward.csv"]
# design document -> the forward file whose first counted day it must precede (None: only its history is shown)
DESIGN_DOCS = {"FORWARD_TEST.md": "reports/output/forward_snapshots.csv", "FORWARD_BOOKS.md": "reports/output/forward_books.csv", "ADVISORY.md": "reports/output/advisory_forward.csv",
               "GO_LIVE_GATES.md": None, "OPTIONS_IDEAS.md": None, "INTRADAY_IDEAS.md": None}


# --- pure checks ---------------------------------------------------------------------------------------------------------------------------

def ledger_chain_problems(ledger: dict) -> list:
    """What is wrong with the chain of runs: a run that does not start where the one before ended, a run whose total is not before + its own count, a wrong grand total."""
    problems, expected = [], 0
    for r in ledger.get("runs", []):
        if r["cumulative_hypotheses_before_run"] != expected:
            problems.append(f"{r['run_id']} starts at {r['cumulative_hypotheses_before_run']}, the run before it ended at {expected}")
        if r["cumulative_hypotheses_after_run"] != r["cumulative_hypotheses_before_run"] + r["n_hypotheses_this_run"]:
            problems.append(f"{r['run_id']}: {r['cumulative_hypotheses_before_run']} + {r['n_hypotheses_this_run']} is not {r['cumulative_hypotheses_after_run']}")
        expected = r["cumulative_hypotheses_after_run"]
    if ledger.get("cumulative_hypotheses") != expected:
        problems.append(f"the stated total {ledger.get('cumulative_hypotheses')} is not the last run's {expected}")
    return problems


def ledger_growth_problems(old: dict, new: dict) -> list:
    """The ledger may only gain runs at the end: every run of `old` must be in `new`, in the same place, word for word."""
    o, n = old.get("runs", []), new.get("runs", [])
    if len(n) < len(o):
        return [f"{len(o) - len(n)} run(s) were removed"]
    return [f"run {i + 1} ({o[i]['run_id']}) was changed" for i in range(len(o)) if o[i] != n[i]]


def csv_rows(text: str) -> list:
    return [row for row in csv.reader(io.StringIO(text)) if row]


def csv_growth_problems(old_text: str, new_text: str) -> list:
    """
    A forward file may gain rows, and the LAST day of the older version may be rewritten (the daily run can be repeated the same evening). Any row for an EARLIER day must be
    exactly as it was. Rows are matched by their first two fields (the day and, where there is one, the book or profile).
    """
    old, new = csv_rows(old_text), csv_rows(new_text)
    if not old:
        return []
    if not new or old[0] != new[0]:
        return ["the header changed"]
    last_day = max(r[0] for r in old[1:]) if len(old) > 1 else None
    later = {tuple(r[:2]) if len(r) > 1 else (r[0],): r for r in new[1:]}
    out = []
    for r in old[1:]:
        if r[0] == last_day:
            continue
        key = tuple(r[:2])
        if key not in later:
            out.append(f"the row for {key[0]} {key[1] if len(key) > 1 else ''} was removed".replace("  ", " "))
        elif later[key] != r:
            out.append(f"the row for {key[0]} {key[1] if len(key) > 1 else ''} was changed".replace("  ", " "))
    return out


def walk_versions(versions: list, problems_between) -> dict:
    """
    `versions` is a list of (commit hash, date, content) oldest first, the working copy last if it differs. Compares each version with the next.
    Returns {"versions", "problems": [{"commit", "date", "what"}]}.
    """
    found = []
    for (_, _, a), (h, d, b) in zip(versions, versions[1:]):
        found += [{"commit": h, "date": d, "what": w} for w in problems_between(a, b)]
    return {"versions": len(versions), "problems": found}


# --- reading git ---------------------------------------------------------------------------------------------------------------------------

def git(*args: str, cwd: str = PROJECT_ROOT) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    except OSError as e:                                                 # git is not installed or not on the PATH (the scheduled run may have a smaller PATH than a terminal)
        raise RuntimeError(f"git could not be started: {e}") from e
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def history(path: str, cwd: str = PROJECT_ROOT) -> list:
    """[(commit, date, file content)] oldest first for every commit that touched `path`; then the working copy if it differs from the last commit."""
    lines = git("log", "--format=%H %aI", "--", path, cwd=cwd).strip().splitlines()
    versions = []
    for line in reversed(lines):
        h, d = line.split(" ", 1)
        versions.append((h, d, git("show", f"{h}:{path}", cwd=cwd)))
    full = os.path.join(cwd, path)
    if os.path.exists(full):
        with open(full, encoding="utf-8", newline="") as f:
            now = f.read()
        if not versions or now.replace("\r\n", "\n") != versions[-1][2].replace("\r\n", "\n"):
            versions.append(("working copy", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"), now))
    return versions


def first_and_edits(path: str, cwd: str = PROJECT_ROOT) -> dict:
    """When a file was first committed, by which commit, and how many commits touched it since. {} if it is not in git."""
    lines = git("log", "--format=%H %aI", "--", path, cwd=cwd).strip().splitlines()
    if not lines:
        return {}
    h, d = lines[-1].split(" ", 1)
    return {"first_commit": h, "first_committed": d, "edits_since": len(lines) - 1}


def is_before(older: str, newer: str, cwd: str = PROJECT_ROOT) -> bool:
    """True if commit `older` is a strict ancestor of commit `newer`: it came earlier in the history, which a commit's own date cannot prove (dates can be set to anything)."""
    if older == newer:
        return False
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=cwd, capture_output=True).returncode == 0
    except OSError:
        return False


def blame(commit: str) -> str:
    """A commit's short name, or a plain statement for a change that has not been committed."""
    return "not yet committed" if commit == "working copy" else commit[:7]


def check(id: str, title: str, status: str, detail: str, **extra) -> dict:
    return {"id": id, "title": title, "status": status, "detail": detail, **extra}


def idea_check(ledger: dict, cwd: str = PROJECT_ROOT) -> dict:
    """
    Every ledger run that came through the honest builder (research/try_idea.py) names its idea file and the file's fingerprint. For each: the file must have been committed in an
    EARLIER commit than the one that first recorded the run, and must still have the fingerprint it had when it was run.
    """
    import re
    context = re.compile(r"^idea:(?P<id>[a-z0-9_]+) \[spec (?P<hash>[0-9a-f]{12})\]")
    title = "Each idea tried through the builder was saved before it was run, and not changed since"
    ideas = [(m.group("id"), m.group("hash"), r["run_id"]) for r in ledger.get("runs", []) if (m := context.match(r.get("context", "")))]
    if not ideas:
        return check("ideas_frozen_first", title, "CANNOT_CHECK", "No idea has gone through the builder yet (research/try_idea.py), so there is nothing to check.")
    try:
        ledger_versions = history(LEDGER, cwd)
    except RuntimeError as e:
        return check("ideas_frozen_first", title, "CANNOT_CHECK", f"git history could not be read: {e}")
    import hashlib
    bad = []
    for idea_id, fingerprint, run_id in ideas:
        rel = f"ideas/{idea_id}.json"
        full = os.path.join(cwd, rel)
        try:
            info = first_and_edits(rel, cwd)
        except RuntimeError:
            info = {}
        if not info:
            bad.append(f"{idea_id}: its file {rel} is not in git")
            continue
        recorded = next((v for v in ledger_versions if run_id in v[2]), None)
        if recorded is not None and recorded[0] != "working copy" and not is_before(info["first_commit"], recorded[0], cwd):
            bad.append(f"{idea_id}: the file was saved in the same commit as, or after, the run it describes")
        if os.path.exists(full):
            with open(full, encoding="utf-8") as f:
                now = hashlib.sha256(json.dumps(json.load(f), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
            if now != fingerprint:
                bad.append(f"{idea_id}: the file was changed after it was run")
        else:
            bad.append(f"{idea_id}: its file {rel} is missing")
    if bad:
        return check("ideas_frozen_first", title, "FAIL", "; ".join(bad))
    return check("ideas_frozen_first", title, "PASS", f"{len(ideas)} idea(s): " + ", ".join(i for i, _, _ in ideas))


def run_checks(cwd: str = PROJECT_ROOT) -> dict:
    checks = []
    ledger_path = os.path.join(cwd, LEDGER)
    ledger = json.load(open(ledger_path, encoding="utf-8")) if os.path.exists(ledger_path) else None

    if ledger is None:
        checks.append(check("ledger_chain", "The idea count is an unbroken chain", "CANNOT_CHECK", "The ledger file was not found."))
    else:
        p = ledger_chain_problems(ledger)
        n = len(ledger["runs"])
        checks.append(check("ledger_chain", "The idea count is an unbroken chain", "FAIL" if p else "PASS",
                            "; ".join(p) if p else f"{n} runs, each starting where the last ended; the total, {ledger['cumulative_hypotheses']}, is the sum of them."))
        try:
            w = walk_versions(history(LEDGER, cwd), lambda a, b: ledger_growth_problems(json.loads(a), json.loads(b)))
            status = "CANNOT_CHECK" if w["versions"] < 2 else ("FAIL" if w["problems"] else "PASS")
            checks.append(check("ledger_append_only", "The list of ideas tried was never edited, only added to", status,
                                f"{w['versions']} saved versions compared; " + ("; ".join(f"{x['what']} ({blame(x['commit'])})" for x in w["problems"]) if w["problems"] else "every earlier run is still there, unchanged."),
                                versions=w["versions"]))
        except RuntimeError as e:
            checks.append(check("ledger_append_only", "The list of ideas tried was never edited, only added to", "CANNOT_CHECK", f"git history could not be read: {e}"))

    for path in FORWARD_FILES:
        title = f"{os.path.basename(path)}: earlier days were never rewritten"
        try:
            w = walk_versions(history(path, cwd), csv_growth_problems)
            status = "CANNOT_CHECK" if w["versions"] < 2 else ("FAIL" if w["problems"] else "PASS")
            detail = ("; ".join(f"{x['what']} ({blame(x['commit'])})" for x in w["problems"]) if w["problems"]
                      else (f"{w['versions']} saved versions compared; no earlier row changed." if w["versions"] >= 2 else "Only one saved version so far: nothing to compare yet."))
            checks.append(check(f"forward:{os.path.basename(path)}", title, status, detail, versions=w["versions"]))
        except RuntimeError as e:
            checks.append(check(f"forward:{os.path.basename(path)}", title, "CANNOT_CHECK", f"git history could not be read: {e}"))

    docs = []
    for doc, forward_file in DESIGN_DOCS.items():
        try:
            info = first_and_edits(doc, cwd)
        except RuntimeError:
            info = {}
        entry = {"document": doc, **info, "forward_started": None, "before_forward_start": None}
        if forward_file and info:
            try:
                versions = history(forward_file, cwd)
                rows = csv_rows(versions[-1][2]) if versions else []
                counted = [r for r in rows[1:] if len(r) > 2 and "NOT_STARTED" not in r]
                entry["forward_started"] = min((r[0] for r in counted), default=None)
                # the first saved version of the forward file that holds a counted day: the design must be an EARLIER commit than that one (order, not dates)
                first_with_days = next((v for v in versions if any(len(r) > 2 and "NOT_STARTED" not in r for r in csv_rows(v[2])[1:])), None)
                if first_with_days is not None:
                    entry["before_forward_start"] = first_with_days[0] == "working copy" or is_before(info["first_commit"], first_with_days[0], cwd)
            except RuntimeError:
                pass
        docs.append(entry)
    judged = [d for d in docs if d["before_forward_start"] is not None]
    if judged:
        bad = [d["document"] for d in judged if not d["before_forward_start"]]
        checks.append(check("frozen_first", "Each design was committed before its forward test began", "FAIL" if bad else "PASS",
                            ("Committed after the start: " + ", ".join(bad)) if bad else "; ".join(f"{d['document']} committed {d['first_committed'][:10]}, first counted day {d['forward_started']}" for d in judged)))
    else:
        checks.append(check("frozen_first", "Each design was committed before its forward test began", "CANNOT_CHECK",
                            "No forward test has produced a counted day yet, so there is nothing to compare the design dates with."))

    if ledger is not None:
        checks.append(idea_check(ledger, cwd))

    try:
        repo = git("remote", "get-url", "origin", cwd=cwd).strip()
        repo = repo[:-4] if repo.endswith(".git") else repo
    except RuntimeError:
        repo = None
    try:
        head = git("rev-parse", "HEAD", cwd=cwd).strip()
    except RuntimeError:
        head = None
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "repo_url": repo, "checked_at_commit": head,
            "ledger_total": None if ledger is None else ledger["cumulative_hypotheses"], "checks": checks, "documents": docs}


def main() -> int:
    out = run_checks()
    tmp = OUTPUT_PATH + ".tmp"
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, OUTPUT_PATH)
    for c in out["checks"]:
        print(f"[track] {c['status']:<12} {c['title']}: {c['detail'][:150]}")
    return 1 if any(c["status"] == "FAIL" for c in out["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
