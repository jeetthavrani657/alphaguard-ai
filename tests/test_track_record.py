"""
tests/test_track_record.py

research/track_record.py proves the record was not rewritten, from git history. The checks must be able to FAIL: each one is tried on a record that was tampered with in the way it
guards against, as well as on an honest one, first as plain functions and then end to end in a throwaway git repository.
"""

import json
import os
import subprocess

import pytest

import track_record as tr


def run(i, before, n, after=None, **kw):
    return {"run_id": f"r{i}", "timestamp": "2026-01-01T00:00:00+00:00", "context": f"idea {i}", "n_hypotheses_this_run": n,
            "cumulative_hypotheses_before_run": before, "cumulative_hypotheses_after_run": before + n if after is None else after, **kw}


GOOD = {"runs": [run(1, 0, 109), run(2, 109, 3)], "cumulative_hypotheses": 112}


# --- the ledger chain ----------------------------------------------------------------------------------------------------------------------

def test_an_honest_chain_has_no_problems():
    assert tr.ledger_chain_problems(GOOD) == [] and tr.ledger_chain_problems({"runs": [], "cumulative_hypotheses": 0}) == []


def test_a_gap_a_wrong_sum_and_a_wrong_total_are_each_found():
    gap = {"runs": [run(1, 0, 109), run(2, 100, 3)], "cumulative_hypotheses": 103}                  # the second run starts at 100, the first ended at 109
    assert any("starts at 100" in p for p in tr.ledger_chain_problems(gap))
    bad_sum = {"runs": [run(1, 0, 109, after=108)], "cumulative_hypotheses": 108}                    # 0 + 109 is not 108
    assert any("is not 108" in p for p in tr.ledger_chain_problems(bad_sum))
    bad_total = {"runs": [run(1, 0, 109)], "cumulative_hypotheses": 50}
    assert any("stated total 50" in p for p in tr.ledger_chain_problems(bad_total))


# --- the ledger only grows -----------------------------------------------------------------------------------------------------------------

def test_adding_a_run_is_fine_and_removing_or_editing_one_is_not():
    longer = {"runs": GOOD["runs"] + [run(3, 112, 2)], "cumulative_hypotheses": 114}
    assert tr.ledger_growth_problems(GOOD, longer) == [] and tr.ledger_growth_problems(GOOD, GOOD) == []
    assert tr.ledger_growth_problems(longer, GOOD) == ["1 run(s) were removed"]
    edited = {"runs": [run(1, 0, 109, context="a nicer story"), GOOD["runs"][1]], "cumulative_hypotheses": 112}
    assert tr.ledger_growth_problems(GOOD, edited) == ["run 1 (r1) was changed"]


# --- the forward files only grow -----------------------------------------------------------------------------------------------------------

HEAD = "run_date,book_id,return_pct\n"


def test_new_days_may_be_added_and_the_last_day_may_be_run_again():
    old = HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n"
    assert tr.csv_growth_problems(old, old + "2026-10-22,a,3.0\n") == []
    assert tr.csv_growth_problems(old, HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.5\n2026-10-22,a,3.0\n") == []      # the 21st was the last day: re-running it that evening is allowed


def test_an_earlier_day_that_changed_or_vanished_is_found_and_so_is_a_changed_header():
    old = HEAD + "2026-10-20,a,1.0\n2026-10-21,a,2.0\n"
    assert tr.csv_growth_problems(old, HEAD + "2026-10-20,a,9.0\n2026-10-21,a,2.0\n") == ["the row for 2026-10-20 a was changed"]
    assert tr.csv_growth_problems(old, HEAD + "2026-10-21,a,2.0\n") == ["the row for 2026-10-20 a was removed"]
    assert tr.csv_growth_problems(old, "run_date,book,return_pct\n2026-10-20,a,1.0\n2026-10-21,a,2.0\n") == ["the header changed"]
    assert tr.csv_growth_problems("", "anything\n") == []                                                           # nothing earlier to protect


def test_two_books_on_the_same_day_are_told_apart():
    old = HEAD + "2026-10-20,a,1.0\n2026-10-20,b,5.0\n2026-10-21,a,2.0\n"
    assert tr.csv_growth_problems(old, HEAD + "2026-10-20,a,1.0\n2026-10-20,b,6.0\n2026-10-21,a,2.0\n") == ["the row for 2026-10-20 b was changed"]


def test_walking_versions_blames_the_commit_that_made_the_change():
    versions = [("c1", "d1", "x"), ("c2", "d2", "y"), ("c3", "d3", "z")]
    w = tr.walk_versions(versions, lambda a, b: ["changed"] if (a, b) == ("y", "z") else [])
    assert w == {"versions": 3, "problems": [{"commit": "c3", "date": "d3", "what": "changed"}]}


# --- end to end in a throwaway repository --------------------------------------------------------------------------------------------------

def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


def save(cwd, rel, text):
    full = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def commit(cwd, msg):
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    git(str(tmp_path), "init", "-q")
    return str(tmp_path)


def status_of(out, id):
    return next(c for c in out["checks"] if c["id"] == id)


def test_an_honest_history_passes_and_the_design_is_shown_to_precede_the_test(repo):
    save(repo, "FORWARD_BOOKS.md", "design v1\n")
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 5)], "cumulative_hypotheses": 5}))
    commit(repo, "design and first idea")
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 5), run(2, 5, 2)], "cumulative_hypotheses": 7}))
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,data_through,status\n2026-10-20,a,2026-10-20,RUNNING\n")
    commit(repo, "second idea and first forward day")
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,data_through,status\n2026-10-20,a,2026-10-20,RUNNING\n2026-10-21,a,2026-10-21,RUNNING\n")
    commit(repo, "next forward day")
    out = tr.run_checks(repo)
    assert status_of(out, "ledger_chain")["status"] == "PASS" and status_of(out, "ledger_append_only")["status"] == "PASS"
    assert status_of(out, "forward:forward_books.csv")["status"] == "PASS" and status_of(out, "frozen_first")["status"] == "PASS"
    doc = next(d for d in out["documents"] if d["document"] == "FORWARD_BOOKS.md")
    assert doc["edits_since"] == 0 and doc["forward_started"] == "2026-10-20" and doc["before_forward_start"] is True


def test_rewriting_an_old_idea_and_an_old_forward_row_are_both_caught_and_blamed_on_their_commit(repo):
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 5)], "cumulative_hypotheses": 5}))
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,return_pct\n2026-10-20,a,-4.0\n2026-10-21,a,-3.0\n")
    commit(repo, "honest start")
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 5, context="never mind that one")], "cumulative_hypotheses": 5}))
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,return_pct\n2026-10-20,a,+4.0\n2026-10-21,a,-3.0\n2026-10-22,a,1.0\n")
    commit(repo, "tidy up")
    bad_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()[:7]
    out = tr.run_checks(repo)
    led, fwd = status_of(out, "ledger_append_only"), status_of(out, "forward:forward_books.csv")
    assert led["status"] == "FAIL" and "run 1 (r1) was changed" in led["detail"] and bad_commit in led["detail"]
    assert fwd["status"] == "FAIL" and "2026-10-20 a was changed" in fwd["detail"] and bad_commit in fwd["detail"]


def test_a_design_committed_after_the_test_began_fails_the_frozen_first_check(repo):
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,data_through,status\n2026-10-01,a,2026-10-01,RUNNING\n")
    commit(repo, "the test starts")
    save(repo, "FORWARD_BOOKS.md", "the rules, written afterwards\n")
    commit(repo, "write the design down")
    out = tr.run_checks(repo)
    assert status_of(out, "frozen_first")["status"] == "FAIL" and "FORWARD_BOOKS.md" in status_of(out, "frozen_first")["detail"]


def test_a_design_and_its_first_results_saved_in_the_same_commit_do_not_count_as_frozen_first(repo):
    save(repo, "FORWARD_BOOKS.md", "design\n")
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,data_through,status\n2026-10-20,a,2026-10-20,RUNNING\n")
    commit(repo, "both at once")
    assert status_of(tr.run_checks(repo), "frozen_first")["status"] == "FAIL"


def test_the_claim_is_judged_by_the_order_of_commits_not_by_dates_that_anyone_can_set(repo):
    env = {**os.environ, "GIT_AUTHOR_DATE": "2020-01-01T00:00:00", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"}       # a design commit given a date long before the test
    save(repo, "reports/output/forward_books.csv", "run_date,book_id,data_through,status\n2026-10-20,a,2026-10-20,RUNNING\n")
    commit(repo, "the test starts")
    save(repo, "FORWARD_BOOKS.md", "written afterwards, back-dated\n")
    git_env = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git_env, "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run([*git_env, "commit", "-q", "-m", "back-dated design"], cwd=repo, check=True, capture_output=True, env=env)
    out = tr.run_checks(repo)
    doc = next(d for d in out["documents"] if d["document"] == "FORWARD_BOOKS.md")
    assert doc["first_committed"].startswith("2020-01-01") and status_of(out, "frozen_first")["status"] == "FAIL"


def test_what_cannot_be_checked_is_never_reported_as_a_pass(repo):
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 5)], "cumulative_hypotheses": 5}))
    commit(repo, "one version only")
    out = tr.run_checks(repo)
    assert status_of(out, "ledger_chain")["status"] == "PASS"                                         # the chain can be checked on one version
    assert status_of(out, "ledger_append_only")["status"] == "CANNOT_CHECK"                           # but growth needs two
    assert status_of(out, "frozen_first")["status"] == "CANNOT_CHECK" and status_of(out, "forward:forward_books.csv")["status"] == "CANNOT_CHECK"


def test_a_change_not_yet_committed_is_compared_too(repo):
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 5)], "cumulative_hypotheses": 5}))
    commit(repo, "v1")
    save(repo, tr.LEDGER, json.dumps({"runs": [], "cumulative_hypotheses": 0}))                       # deleted in the working copy, not committed
    out = tr.run_checks(repo)
    assert status_of(out, "ledger_append_only")["status"] == "FAIL" and "not yet committed" in status_of(out, "ledger_append_only")["detail"]


def test_rows_that_say_not_started_do_not_count_as_the_test_having_begun(repo):
    head = "run_date,book_id,data_through,status\n"
    save(repo, "reports/output/forward_books.csv", head + "2026-10-16,a,2026-10-16,NOT_STARTED\n")
    commit(repo, "the file exists, nothing counted yet")
    save(repo, "FORWARD_BOOKS.md", "the rules, written before the first counted day\n")
    commit(repo, "write the design down")
    save(repo, "reports/output/forward_books.csv", head + "2026-10-16,a,2026-10-16,NOT_STARTED\n2026-10-20,a,2026-10-20,RUNNING\n")
    commit(repo, "first counted day")
    out = tr.run_checks(repo)
    doc = next(d for d in out["documents"] if d["document"] == "FORWARD_BOOKS.md")
    assert doc["forward_started"] == "2026-10-20" and status_of(out, "frozen_first")["status"] == "PASS"


def test_without_git_on_the_path_nothing_crashes_and_nothing_that_needs_git_is_called_a_pass(monkeypatch, tmp_path):
    save(str(tmp_path), tr.LEDGER, json.dumps({"runs": [run(1, 0, 5)], "cumulative_hypotheses": 5}))

    def no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(tr.subprocess, "run", no_git)
    out = tr.run_checks(str(tmp_path))
    by_id = {c["id"]: c["status"] for c in out["checks"]}
    assert by_id["ledger_chain"] == "PASS"                                                        # needs only the file
    assert by_id["ledger_append_only"] == "CANNOT_CHECK" and by_id["frozen_first"] == "CANNOT_CHECK"
    assert all(s == "CANNOT_CHECK" for k, s in by_id.items() if k.startswith("forward:"))


# --- ideas tried through the honest builder ------------------------------------------------------------------------------------------------

IDEA = {"id": "ma_fast_nifty50", "name": "Faster moving average", "strategy": "ma_crossover", "universe": "nifty50",
        "rationale": "A faster crossover should react sooner to a new trend.", "grid": {"fast": [20, 30]}}


def idea_ledger(spec=IDEA, n=2):
    import try_idea as ti
    run1 = run(1, 0, 100)
    run2 = run(2, 100, n, context=ti.context_for(spec, n))
    return json.dumps({"runs": [run1, run2], "cumulative_hypotheses": 100 + n})


def test_the_builders_fingerprint_matches_the_one_the_tracker_recomputes(repo):
    import try_idea as ti
    save(repo, "ideas/ma_fast_nifty50.json", json.dumps(IDEA))
    commit(repo, "freeze the idea")
    save(repo, tr.LEDGER, idea_ledger())
    commit(repo, "run it")
    assert status_of(tr.run_checks(repo), "ideas_frozen_first")["status"] == "PASS"
    assert ti.spec_hash(IDEA) in idea_ledger()


def test_an_idea_with_no_run_through_the_builder_is_not_judged(repo):
    save(repo, tr.LEDGER, json.dumps({"runs": [run(1, 0, 100)], "cumulative_hypotheses": 100}))
    commit(repo, "only older ideas")
    assert status_of(tr.run_checks(repo), "ideas_frozen_first")["status"] == "CANNOT_CHECK"


def test_an_idea_file_saved_after_its_run_or_in_the_same_commit_fails(repo):
    save(repo, tr.LEDGER, idea_ledger())
    commit(repo, "the run is recorded")
    save(repo, "ideas/ma_fast_nifty50.json", json.dumps(IDEA))
    commit(repo, "the idea is written down afterwards")
    check_ = status_of(tr.run_checks(repo), "ideas_frozen_first")
    assert check_["status"] == "FAIL" and "same commit as, or after" in check_["detail"]


def test_an_idea_file_edited_after_it_was_run_fails_even_if_it_was_saved_first(repo):
    save(repo, "ideas/ma_fast_nifty50.json", json.dumps(IDEA))
    commit(repo, "freeze the idea")
    save(repo, tr.LEDGER, idea_ledger())
    commit(repo, "run it")
    save(repo, "ideas/ma_fast_nifty50.json", json.dumps({**IDEA, "grid": {"fast": [20]}}))      # the grid is trimmed to the winner after the fact
    commit(repo, "tidy the idea")
    check_ = status_of(tr.run_checks(repo), "ideas_frozen_first")
    assert check_["status"] == "FAIL" and "changed after it was run" in check_["detail"]


def test_an_idea_whose_file_has_gone_missing_fails(repo):
    save(repo, tr.LEDGER, idea_ledger())
    commit(repo, "the run is recorded, the file never was")
    check_ = status_of(tr.run_checks(repo), "ideas_frozen_first")
    assert check_["status"] == "FAIL" and "not in git" in check_["detail"]
