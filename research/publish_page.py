"""
research/publish_page.py

Publishes the project's public record to GitHub, once a day at the end of the evening run: the public track-record page (docs/index.html, written by research/public_page.py) and the three
paper-trading files the daily run appends to (the forward-test, paper-book and advisory CSVs). The owner approved the page on 2026-10-26 and, the same day, the CSVs, with their push.

It is built to do ONE job and to refuse in every doubtful case, because an automatic push is the one place this project writes to the outside world on its own:

  * It commits and pushes ONLY those four named files. Everything else in the working folder, staged or not, is left exactly as it is (the commit names the files; it never takes the whole index).
  * A CSV is committed only if it has only GROWN: every row for an earlier day must be exactly as it was in the last committed version (research/track_record.csv_growth_problems). A rewritten
    record is not committed, it is reported, and a person looks. (The page is still published.)
  * It never pushes anyone's other work: it proceeds only when the local branch is main and is exactly level with origin/main (nothing unpushed, nothing behind). If you have commits you have not
    pushed, it does nothing, so a daily job can never publish something you have not approved.
  * It never forces. If the push fails it undoes its own commit, so the next evening starts clean and the failure is in the log, not in the history.
  * It refuses a page that contains a script, a frame, a form, a loaded resource or a link to any host but github.com (public_page.unsafe_parts), whatever produced it.
  * A file named AUTO_PUBLISH_OFF in the project folder switches it all off at once. Delete the file to switch it on again.
  * Nothing that goes wrong stops the evening run: it reports and returns.

    python research/publish_page.py
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import public_page
import track_record

PAGE = "docs/index.html"
RECORDS = ["reports/output/forward_snapshots.csv", "reports/output/forward_books.csv", "reports/output/advisory_forward.csv"]     # the files the daily run only ever appends to
KILL_FILE = "AUTO_PUBLISH_OFF"
MESSAGE_HEAD = "Daily refresh of the public record (automatic)"


def git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def run(cwd: str = PROJECT_ROOT, page: str = PAGE, records: list | None = None, branch: str = "main", remote: str = "origin") -> dict:
    """{"status": "published" | "nothing to publish" | "skipped" | "failed", "detail": why, "files": [what was committed], "refused": [(file, why)]}."""
    records = RECORDS if records is None else records

    def done(status: str, detail: str, files: list | None = None, refused: list | None = None) -> dict:
        return {"status": status, "detail": detail, "files": files or [], "refused": refused or []}

    if os.path.exists(os.path.join(cwd, KILL_FILE)):
        return done("skipped", f"{KILL_FILE} exists: automatic publishing is switched off")
    try:
        here = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
        if here.returncode != 0 or here.stdout.strip() != branch:
            return done("skipped", f"the current branch is {here.stdout.strip() or 'unknown'}, not {branch}")
        fetched = git("fetch", remote, branch, cwd=cwd)
        if fetched.returncode != 0:
            return done("skipped", "could not reach the remote: " + fetched.stderr.strip()[:150])
        count = git("rev-list", "--left-right", "--count", f"HEAD...{remote}/{branch}", cwd=cwd)
        if count.returncode != 0:
            return done("skipped", "could not compare with the remote: " + count.stderr.strip()[:150])
        ahead, behind = (int(x) for x in count.stdout.split())
        if ahead or behind:
            return done("skipped", f"the branch is not level with {remote}/{branch} ({ahead} unpushed, {behind} behind): publishing only ever pushes its own files, so it waits")

        files, refused = [], []
        if git("status", "--porcelain", "--", page, cwd=cwd).stdout.strip():
            if not os.path.exists(os.path.join(cwd, page)):
                bad = ["nothing: the file is missing"]
            else:
                with open(os.path.join(cwd, page), encoding="utf-8") as f:
                    bad = public_page.unsafe_parts(f.read())
            if bad:
                refused.append((page, "it contains " + ", ".join(bad)))
            else:
                files.append(page)
        for rel in records:
            if not git("status", "--porcelain", "--", rel, cwd=cwd).stdout.strip():
                continue
            old = git("show", f"HEAD:{rel}", cwd=cwd)
            full = os.path.join(cwd, rel)
            if old.returncode != 0 or not os.path.exists(full):
                refused.append((rel, "it is not in the last commit, or is gone: a person decides"))
                continue
            with open(full, encoding="utf-8", newline="") as f:
                new_text = f.read()
            problems = track_record.csv_growth_problems(old.stdout, new_text)
            if problems:
                refused.append((rel, "an earlier row changed: " + "; ".join(problems[:3])))
            else:
                files.append(rel)
        if not files:
            if refused:
                return done("skipped", "nothing was committed: " + "; ".join(f"{p} ({why})" for p, why in refused), refused=refused)
            return done("nothing to publish", "the page and the record files are the same as the published ones")
        if git("add", "--", *files, cwd=cwd).returncode != 0:
            return done("failed", "git add failed", refused=refused)
        message = f"{MESSAGE_HEAD}\n\nWritten and pushed by research/publish_page.py at the end of the evening run: only " + ", ".join(files) + "."
        commit = git("commit", "-m", message, "--only", "--", *files, cwd=cwd)             # --only: these files and nothing else that happens to be staged
        if commit.returncode != 0:
            return done("failed", "git commit failed: " + (commit.stderr or commit.stdout).strip()[:150], refused=refused)
        pushed = git("push", remote, branch, cwd=cwd)                                     # never forced
        if pushed.returncode != 0:
            git("reset", "--soft", "HEAD~1", cwd=cwd)                                    # take our own commit back, so tomorrow starts level again
            git("reset", "-q", "--", *files, cwd=cwd)
            return done("failed", "the push was refused or failed, and the commit was undone: " + pushed.stderr.strip()[:200], refused=refused)
        return done("published", f"committed and pushed to {remote}/{branch}: " + ", ".join(files), files=files, refused=refused)
    except OSError as e:                                                                  # git is not installed or not on this run's PATH
        return done("failed", f"git could not be started: {e}")


def main() -> int:
    r = run()
    print(f"[publish] {r['status']}: {r['detail']}")
    for path, why in r["refused"]:
        print(f"[publish] NOT committed: {path}: {why}")
    return 0                                                                              # nothing here may stop the evening run


if __name__ == "__main__":
    sys.exit(main())
