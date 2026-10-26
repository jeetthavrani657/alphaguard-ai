"""
tests/test_publish_page.py

research/publish_page.py pushes the public page to GitHub by itself every evening, which makes it the one place the project writes to the outside world unattended. Every promise in its docstring is
tried here against real git repositories (a bare "remote" and a working clone, built in a temporary folder): it commits ONLY the page, it never pushes anyone else's unpushed work, it never forces,
it undoes its own commit when a push fails, it refuses an unsafe page, and a switch file stops it.
"""

import os
import subprocess

import pytest

import publish_page as pp

HEAD = "run_date,book_id,return_pct\n"
SNAP = "reports/output/forward_snapshots.csv"
BOOKS = "reports/output/forward_books.csv"
SAFE = '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title></head><body><p>checks made 1</p><a href="https://github.com/x/y">repo</a></body></html>'


def git(cwd, *args, check=True):
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise AssertionError(out.stderr)
    return out.stdout.strip()


def porcelain(cwd):
    """git status in short form, WITHOUT stripping: the first column (staged or not) is a leading space."""
    return subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True).stdout.splitlines()


def write(cwd, rel, text):
    full = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(text)


@pytest.fixture
def world(tmp_path):
    remote = str(tmp_path / "remote.git")
    local = str(tmp_path / "local")
    other = str(tmp_path / "other")
    subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
    os.makedirs(local)
    git(local, "init", "-q")
    git(local, "symbolic-ref", "HEAD", "refs/heads/main")
    git(local, "remote", "add", "origin", remote)
    git(local, "config", "user.name", "t")                                                         # the owner's own repository has an identity; the job's commit needs one
    git(local, "config", "user.email", "t@t")
    git(local, "config", "commit.gpgsign", "false")
    write(local, "docs/index.html", SAFE)
    write(local, "notes.txt", "first\n")
    for name in ("forward_snapshots", "forward_books", "advisory_forward"):
        write(local, f"reports/output/{name}.csv", HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n")
    write(local, "reports/output/other.csv", "x\n1\n")                                              # a CSV the job must never touch
    git(local, "add", "-A")
    git(local, "commit", "-q", "-m", "start")
    git(local, "push", "-q", "origin", "main")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    return {"remote": remote, "local": local, "other": other}


def run(world, **kw):
    return pp.run(cwd=world["local"], **kw)


def remote_log(world):
    return git(world["remote"], "log", "--format=%s", "main").splitlines()


def test_a_changed_page_is_committed_and_pushed_and_nothing_else_goes_with_it(world):
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 2"))
    r = run(world)
    assert r["status"] == "published", r
    assert remote_log(world)[0].startswith("Daily refresh of the public record (automatic)")
    assert git(world["remote"], "show", "--name-only", "--format=", "main").splitlines() == ["docs/index.html"]
    assert git(world["local"], "rev-parse", "HEAD") == git(world["remote"], "rev-parse", "main")


def test_a_page_that_has_not_changed_publishes_nothing(world):
    before = git(world["remote"], "rev-parse", "main")
    r = run(world)
    assert r["status"] == "nothing to publish" and git(world["remote"], "rev-parse", "main") == before


def test_other_work_in_the_folder_is_left_exactly_as_it_was_staged_or_not(world):
    write(world["local"], "notes.txt", "staged change\n")
    git(world["local"], "add", "notes.txt")                                                        # staged for a commit the owner has not made
    write(world["local"], "scratch.txt", "untracked\n")
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 3"))
    assert run(world)["status"] == "published"
    assert git(world["remote"], "show", "--name-only", "--format=", "main").splitlines() == ["docs/index.html"]
    status = porcelain(world["local"])
    assert "M  notes.txt" in status and "?? scratch.txt" in status                                  # still staged, still untracked, not on the remote
    assert git(world["remote"], "show", "main:notes.txt") == "first"


def test_unpushed_work_of_the_owner_is_never_pushed_by_the_job(world):
    write(world["local"], "notes.txt", "second\n")
    git(world["local"], "commit", "-q", "-am", "an owner commit, not yet approved for pushing")
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 4"))
    before = git(world["remote"], "rev-parse", "main")
    r = run(world)
    assert r["status"] == "skipped" and "1 unpushed" in r["detail"]
    assert git(world["remote"], "rev-parse", "main") == before                                       # the owner's commit stayed local
    assert " M docs/index.html" in porcelain(world["local"])                                         # and the page change was left alone, unstaged


def test_a_branch_that_is_behind_the_remote_is_left_alone(world):
    subprocess.run(["git", "clone", "-q", world["remote"], world["other"]], check=True)
    write(world["other"], "notes.txt", "from elsewhere\n")
    git(world["other"], "commit", "-q", "-am", "pushed from another place")
    git(world["other"], "push", "-q", "origin", "HEAD:main")
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 5"))
    r = run(world)
    assert r["status"] == "skipped" and "1 behind" in r["detail"]
    assert remote_log(world)[0] == "pushed from another place"


def test_it_only_ever_publishes_from_main(world):
    git(world["local"], "checkout", "-q", "-b", "feature")
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 6"))
    r = run(world)
    assert r["status"] == "skipped" and "feature" in r["detail"] and remote_log(world) == ["start"]


@pytest.mark.parametrize("bad, word", [('<script>alert(1)</script>', "script"), ('<iframe src="x"></iframe>', "frame"), ('<form></form>', "form"),
                                       ('<a href="https://evil.example/x">x</a>', "evil.example"), ('<img src="a.png">', "loaded resource"), ('<meta http-equiv="refresh" content="0;url=x">', "refresh")])
def test_an_unsafe_page_is_never_pushed_whatever_produced_it(world, bad, word):
    write(world["local"], "docs/index.html", SAFE.replace("</body>", bad + "</body>"))
    r = run(world)
    assert r["status"] == "skipped" and word in r["detail"]
    assert remote_log(world) == ["start"]


def test_the_switch_file_stops_it_and_removing_the_file_starts_it_again(world):
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 7"))
    write(world["local"], pp.KILL_FILE, "")
    r = run(world)
    assert r["status"] == "skipped" and "switched off" in r["detail"] and remote_log(world) == ["start"]
    os.remove(os.path.join(world["local"], pp.KILL_FILE))
    assert run(world)["status"] == "published"


def test_a_refused_push_undoes_its_own_commit_so_tomorrow_starts_level(world):
    hook = os.path.join(world["remote"], "hooks", "pre-receive")
    write(world["remote"], "hooks/pre-receive", "#!/bin/sh\necho refused >&2\nexit 1\n")
    os.chmod(hook, 0o755)
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 8"))
    r = run(world)
    assert r["status"] == "failed" and "commit was undone" in r["detail"]
    assert git(world["local"], "rev-parse", "HEAD") == git(world["remote"], "rev-parse", "main")      # no stray local commit
    assert porcelain(world["local"]) == [" M docs/index.html"]                                       # the page change is still there, unstaged
    os.remove(hook)
    assert run(world)["status"] == "published"                                                       # and the next run works


def test_an_unreachable_remote_is_a_skip_not_a_crash(world):
    git(world["local"], "remote", "set-url", "origin", os.path.join(world["local"], "does_not_exist.git"))
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 9"))
    r = run(world)
    assert r["status"] == "skipped" and "could not reach the remote" in r["detail"]


def test_a_missing_page_is_a_skip(world):
    os.remove(os.path.join(world["local"], "docs", "index.html"))
    assert run(world)["status"] == "skipped"


def test_the_job_never_forces_and_names_no_file_but_the_page():
    source = open(pp.__file__, encoding="utf-8").read()
    for forbidden in ("--force", "-f ", "--force-with-lease", "git add -A", '"add", "-A"', '"add", "."', "--no-verify"):
        assert forbidden not in source, f"publish_page.py contains {forbidden!r}"
    assert source.count('git("push"') == 1 and 'git("push", remote, branch, cwd=cwd)' in source


def test_it_runs_after_the_page_is_rebuilt_and_before_the_alerts_and_cannot_stop_the_run():
    bat = open(os.path.join(os.path.dirname(os.path.dirname(pp.__file__)), "run_forward_log.bat"), encoding="utf-8").read()
    assert bat.index("research\\public_page.py") < bat.index("research\\publish_page.py") < bat.index("research\\alerts.py")
    assert pp.main.__doc__ is None and "return 0" in open(pp.__file__, encoding="utf-8").read().split("def main")[1]


# --- the paper-trading record: committed only if it has only grown ---------------------------------------------------------------------

def test_new_days_in_the_record_files_are_committed_and_pushed_together_with_a_changed_page(world):
    write(world["local"], SNAP, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n2026-10-22,a,3.0\n")
    write(world["local"], BOOKS, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n2026-10-22,a,3.5\n")
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 10"))
    r = run(world)
    assert r["status"] == "published" and sorted(r["files"]) == sorted(["docs/index.html", SNAP, BOOKS]), r
    assert sorted(git(world["remote"], "show", "--name-only", "--format=", "main").splitlines()) == sorted(["docs/index.html", SNAP, BOOKS])
    assert git(world["local"], "rev-parse", "HEAD") == git(world["remote"], "rev-parse", "main")


def test_a_record_file_alone_is_enough_to_publish(world):
    write(world["local"], SNAP, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n2026-10-22,a,3.0\n")
    r = run(world)
    assert r["status"] == "published" and r["files"] == [SNAP]


def test_the_last_day_may_be_run_again_but_an_earlier_day_rewritten_is_refused_and_the_rest_still_goes(world):
    write(world["local"], SNAP, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.5\n")                    # only the LAST day changed: allowed
    write(world["local"], BOOKS, HEAD + "2026-10-20,a,9.9\n2026-10-21,a,2.0\n")                   # an EARLIER day changed: a rewrite
    write(world["local"], "docs/index.html", SAFE.replace("checks made 1", "checks made 11"))
    r = run(world)
    assert r["status"] == "published" and sorted(r["files"]) == sorted(["docs/index.html", SNAP])
    assert [p for p, why in r["refused"]] == [BOOKS] and "2026-10-20" in r["refused"][0][1]
    assert git(world["remote"], "show", f"main:{BOOKS}") == (HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0").strip()      # the rewrite never reached GitHub
    assert f" M {BOOKS}" in porcelain(world["local"])                                                 # it waits in the working folder for a person


def test_when_the_only_change_is_a_rewrite_nothing_is_committed_and_it_says_why(world):
    write(world["local"], BOOKS, HEAD + "2026-10-20,a,9.9\n2026-10-21,a,2.0\n")
    before = git(world["remote"], "rev-parse", "main")
    r = run(world)
    assert r["status"] == "skipped" and "nothing was committed" in r["detail"] and BOOKS in r["detail"]
    assert git(world["remote"], "rev-parse", "main") == before


def test_a_record_file_that_was_never_committed_is_left_for_a_person(world):
    git(world["local"], "rm", "-q", "--cached", SNAP)
    git(world["local"], "commit", "-q", "-m", "stop tracking the snapshot file")
    git(world["local"], "push", "-q", "origin", "main")
    write(world["local"], SNAP, HEAD + "2026-10-20,a,1.0\n")
    r = run(world)
    assert r["status"] == "skipped" and [p for p, why in r["refused"]] == [SNAP]


def test_a_csv_that_is_not_one_of_the_three_is_never_touched(world):
    write(world["local"], "reports/output/other.csv", "x\n2\n")
    write(world["local"], SNAP, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n2026-10-22,a,3.0\n")
    assert run(world)["files"] == [SNAP]
    assert " M reports/output/other.csv" in porcelain(world["local"]) and git(world["remote"], "show", "main:reports/output/other.csv") == "x\n1".strip()


def test_an_unsafe_page_is_refused_but_a_good_record_file_beside_it_is_still_published(world):
    write(world["local"], "docs/index.html", SAFE.replace("</body>", "<script>x</script></body>"))
    write(world["local"], SNAP, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n2026-10-22,a,3.0\n")
    r = run(world)
    assert r["status"] == "published" and r["files"] == [SNAP] and "script" in r["refused"][0][1]
    assert " M docs/index.html" in porcelain(world["local"])


def test_the_four_names_are_exactly_the_files_the_daily_run_writes_and_all_are_tracked():
    root = os.path.dirname(os.path.dirname(pp.__file__))
    assert pp.PAGE == "docs/index.html" and sorted(pp.RECORDS) == sorted(["reports/output/forward_snapshots.csv", "reports/output/forward_books.csv", "reports/output/advisory_forward.csv"])
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    for rel in [pp.PAGE, *pp.RECORDS]:
        assert rel in tracked, f"{rel} is not in git"
