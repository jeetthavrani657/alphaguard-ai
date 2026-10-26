"""
research/publish_page.py

Publishes the public track-record page (docs/index.html, written by research/public_page.py) to GitHub, once a day at the end of the evening run. The owner approved this on 2026-10-26.

It is built to do ONE thing and to refuse in every doubtful case, because an automatic push is the one place this project writes to the outside world on its own:

  * It commits and pushes ONLY docs/index.html. Everything else in the working folder, staged or not, is left exactly as it is (the commit names the file; it never takes the whole index).
  * It never pushes anyone's other work: it proceeds only when the local branch is main and is exactly level with origin/main (nothing unpushed, nothing behind). If you have commits you have not
    pushed, it does nothing, so a daily job can never publish something you have not approved.
  * It never forces. If the push fails it undoes its own commit, so the next evening starts clean and the failure is in the log, not in the history.
  * It refuses a page that contains a script, a frame, a form, a loaded resource or a link to any host but github.com (public_page.unsafe_parts), whatever produced it.
  * A file named AUTO_PUBLISH_OFF in the project folder switches it off at once. Delete the file to switch it on again.
  * Nothing that goes wrong stops the evening run: it reports and returns.

    python research/publish_page.py
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import public_page

PAGE = "docs/index.html"
KILL_FILE = "AUTO_PUBLISH_OFF"
MESSAGE = "Daily refresh of the public track-record page (automatic)\n\nWritten and pushed by research/publish_page.py at the end of the evening run: only docs/index.html, rebuilt from the day's checks."


def git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def run(cwd: str = PROJECT_ROOT, page: str = PAGE, branch: str = "main", remote: str = "origin") -> dict:
    """{"status": "published" | "nothing to publish" | "skipped" | "failed", "detail": why}."""
    def done(status: str, detail: str) -> dict:
        return {"status": status, "detail": detail}

    if os.path.exists(os.path.join(cwd, KILL_FILE)):
        return done("skipped", f"{KILL_FILE} exists: automatic publishing is switched off")
    path = os.path.join(cwd, page)
    if not os.path.exists(path):
        return done("skipped", f"{page} does not exist")
    with open(path, encoding="utf-8") as f:
        bad = public_page.unsafe_parts(f.read())
    if bad:
        return done("skipped", "the page contains " + ", ".join(bad) + ": not published")
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
            return done("skipped", f"the branch is not level with {remote}/{branch} ({ahead} unpushed, {behind} behind): publishing only ever pushes its own page, so it waits")
        changed = git("status", "--porcelain", "--", page, cwd=cwd)
        if not changed.stdout.strip():
            return done("nothing to publish", f"{page} is the same as the published one")
        if git("add", "--", page, cwd=cwd).returncode != 0:
            return done("failed", "git add failed")
        commit = git("commit", "-m", MESSAGE, "--only", "--", page, cwd=cwd)             # --only: this file and nothing else that happens to be staged
        if commit.returncode != 0:
            return done("failed", "git commit failed: " + (commit.stderr or commit.stdout).strip()[:150])
        pushed = git("push", remote, branch, cwd=cwd)                                     # never forced
        if pushed.returncode != 0:
            git("reset", "--soft", "HEAD~1", cwd=cwd)                                    # take our own commit back, so tomorrow starts level again
            git("reset", "-q", "--", page, cwd=cwd)
            return done("failed", "the push was refused or failed, and the commit was undone: " + pushed.stderr.strip()[:200])
        return done("published", f"{page} committed and pushed to {remote}/{branch}")
    except OSError as e:                                                                  # git is not installed or not on this run's PATH
        return done("failed", f"git could not be started: {e}")


def main() -> int:
    r = run()
    print(f"[publish] {r['status']}: {r['detail']}")
    return 0                                                                              # nothing here may stop the evening run


if __name__ == "__main__":
    sys.exit(main())
