"""
tests/test_try_idea.py

research/try_idea.py is the honest builder. What must hold, each tried against the mistake it exists to prevent: an idea that was not committed first is refused; every combination
of the grid is counted, together, in the ledger; a run that crashes counts nothing; an idea cannot be run twice or overwritten; a grid is checked against the strategy's real
parameters; and the file's fingerprint changes if the idea does.
"""

import json
import os
import subprocess

import pytest

import harness
import try_idea as ti


SPEC = {"id": "ma_fast_nifty50", "name": "Faster moving average", "strategy": "ma_crossover", "universe": "nifty50",
        "rationale": "A faster crossover should react sooner to a new trend and so keep more of the move.", "grid": {"fast": [20, 30], "slow": [100, 150]}}


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A throwaway git repository and a throwaway ledger holding 100 earlier ideas."""
    repo = str(tmp_path / "repo")
    os.makedirs(os.path.join(repo, "ideas"))
    git(repo, "init", "-q")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"runs": [{"run_id": "run_0", "timestamp": "t", "context": "earlier", "n_hypotheses_this_run": 100,
                                            "cumulative_hypotheses_before_run": 0, "cumulative_hypotheses_after_run": 100}], "cumulative_hypotheses": 100}))
    monkeypatch.setattr(harness, "LEDGER_PATH", str(ledger))
    return {"repo": repo, "ledger": ledger, "results": str(tmp_path / "results")}


def write_spec(world, spec=None, commit=True, name="ma_fast_nifty50.json"):
    path = os.path.join(world["repo"], "ideas", name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec or SPEC, f)
    if commit:
        git(world["repo"], "add", "-A")
        git(world["repo"], "commit", "-q", "-m", "freeze the idea")
    return path


def fake_runner(calls=None, crash_on=None):
    def run(params):
        if calls is not None:
            calls.append(dict(params))
        if crash_on is not None and len(calls) == crash_on:
            raise RuntimeError("the data broke halfway")
        return (0.9, 1000, 0.4, 1400)
    return run


def ledger_total(world):
    return json.loads(world["ledger"].read_text())["cumulative_hypotheses"]


# --- the idea file -------------------------------------------------------------------------------------------------------------------------

def test_a_complete_idea_is_valid_and_each_missing_or_wrong_part_is_named():
    assert ti.validate_spec(SPEC) == []
    assert ti.validate_spec({k: v for k, v in SPEC.items() if k != "rationale"}) == ["missing 'rationale'"]
    assert any("underscore" in p for p in ti.validate_spec({**SPEC, "id": "_example"}))
    assert any("id must be" in p for p in ti.validate_spec({**SPEC, "id": "Bad ID"}))
    assert any("rationale" in p for p in ti.validate_spec({**SPEC, "rationale": "todo"}))
    assert any("strategy must be" in p for p in ti.validate_spec({**SPEC, "strategy": "magic"}))
    assert any("universe must be" in p for p in ti.validate_spec({**SPEC, "universe": "nasdaq"}))


def test_the_grid_may_only_use_the_strategys_own_parameters_and_must_have_values():
    assert any("not parameters of ma_crossover" in p and "period" in p for p in ti.validate_spec({**SPEC, "grid": {"period": [14]}}))
    assert any("grid must be" in p for p in ti.validate_spec({**SPEC, "grid": {}}))
    assert any("grid must be" in p for p in ti.validate_spec({**SPEC, "grid": {"fast": []}}))
    assert any("grid must be" in p for p in ti.validate_spec({**SPEC, "grid": {"fast": 20}}))
    assert ti.validate_spec({**SPEC, "strategy": "rsi_reversion", "grid": {"oversold": [25, 30]}}) == []
    assert ti.validate_spec({**SPEC, "strategy": "dip_target", "grid": {"take_profit": [0.03], "stop_loss": [0.1]}}) == []


def test_the_grid_is_every_combination_in_a_fixed_order_and_one_combination_is_one_hypothesis():
    combos = ti.expand_grid({"slow": [100, 150], "fast": [20, 30]})
    assert combos == [{"fast": 20, "slow": 100}, {"fast": 20, "slow": 150}, {"fast": 30, "slow": 100}, {"fast": 30, "slow": 150}]
    assert len(ti.expand_grid({"a": [1, 2, 3], "b": [1, 2], "c": [5]})) == 6 and ti.expand_grid({"fast": [20]}) == [{"fast": 20}]


def test_the_fingerprint_ignores_layout_and_changes_with_any_change_of_content():
    a = ti.spec_hash(SPEC)
    assert a == ti.spec_hash(dict(reversed(list(SPEC.items())))) and len(a) == 12
    assert a != ti.spec_hash({**SPEC, "grid": {"fast": [20, 30], "slow": [100, 151]}}) and a != ti.spec_hash({**SPEC, "rationale": SPEC["rationale"] + " "})


# --- frozen first --------------------------------------------------------------------------------------------------------------------------

def test_a_file_that_is_not_in_git_or_has_uncommitted_changes_is_not_frozen(world):
    path = write_spec(world, commit=False)
    commit, why = ti.check_frozen(path, world["repo"])
    assert commit is None and "not in git yet" in why
    git(world["repo"], "add", "-A")
    git(world["repo"], "commit", "-q", "-m", "freeze")
    commit, why = ti.check_frozen(path, world["repo"])
    assert commit and len(commit) == 40 and why == ""
    with open(path, "a", encoding="utf-8") as f:
        f.write(" ")
    commit, why = ti.check_frozen(path, world["repo"])
    assert commit is None and "not committed" in why


# --- running -------------------------------------------------------------------------------------------------------------------------------

def test_every_combination_is_run_and_all_are_counted_together_in_one_ledger_entry(world):
    path, calls = write_spec(world), []
    done = ti.try_idea(path, runner=fake_runner(calls), results_dir=world["results"], cwd=world["repo"])
    assert calls == ti.expand_grid(SPEC["grid"]) and len(calls) == 4                                     # nothing skipped, nothing chosen
    ledger = json.loads(world["ledger"].read_text())
    assert ledger["cumulative_hypotheses"] == 104 and len(ledger["runs"]) == 2                           # one new entry, four hypotheses
    entry = ledger["runs"][-1]
    m = ti.CONTEXT.match(entry["context"])
    assert entry["n_hypotheses_this_run"] == 4 and m.group("id") == "ma_fast_nifty50" and m.group("hash") == ti.spec_hash(SPEC)
    rec = done["record"]
    assert rec["ledger_before"] == 100 and rec["ledger_after"] == 104 and rec["bonferroni_alpha"] == pytest.approx(0.05 / 104)      # judged at the NEW total
    assert [r["params"] for r in rec["results"]] == calls and rec["spec_commit"] and os.path.exists(done["result_path"])


def test_an_idea_that_was_not_committed_first_is_refused_and_nothing_is_run_or_counted(world):
    path, calls = write_spec(world, commit=False), []
    with pytest.raises(ValueError, match="not in git yet"):
        ti.try_idea(path, runner=fake_runner(calls), results_dir=world["results"], cwd=world["repo"])
    assert calls == [] and ledger_total(world) == 100 and not os.path.exists(world["results"])


def test_a_run_that_crashes_counts_nothing_and_leaves_no_result(world):
    path, calls = write_spec(world), []
    with pytest.raises(RuntimeError, match="broke halfway"):
        ti.try_idea(path, runner=fake_runner(calls, crash_on=3), results_dir=world["results"], cwd=world["repo"])
    assert len(calls) == 3 and ledger_total(world) == 100 and not os.path.exists(world["results"])


def test_an_idea_cannot_be_run_twice_and_a_changed_idea_needs_a_new_id(world):
    path = write_spec(world)
    ti.try_idea(path, runner=fake_runner([]), results_dir=world["results"], cwd=world["repo"])
    with pytest.raises(ValueError, match="already been run"):
        ti.try_idea(path, runner=fake_runner([]), results_dir=world["results"], cwd=world["repo"])
    assert ledger_total(world) == 104                                                                      # the refused second run counted nothing
    tweaked = {**SPEC, "grid": {"fast": [20, 30], "slow": [100, 150, 200]}}                               # same id, new grid: still the same idea, still refused
    write_spec(world, tweaked)
    with pytest.raises(ValueError, match="already been run"):
        ti.try_idea(path, runner=fake_runner([]), results_dir=world["results"], cwd=world["repo"])


def test_a_result_file_is_never_overwritten(world):
    path = write_spec(world)
    os.makedirs(world["results"])
    with open(os.path.join(world["results"], "ma_fast_nifty50_result.json"), "w") as f:
        f.write("{}")
    with pytest.raises(ValueError, match="never overwritten"):
        ti.try_idea(path, runner=fake_runner([]), results_dir=world["results"], cwd=world["repo"])
    assert ledger_total(world) == 100


def test_a_big_grid_must_be_asked_for_on_purpose(world):
    big = {**SPEC, "id": "big_grid", "grid": {"fast": list(range(10, 100, 10)), "slow": list(range(100, 300, 20))}}        # 9 x 10 = 90
    path = write_spec(world, big, name="big_grid.json")
    with pytest.raises(ValueError, match="more than 60"):
        ti.try_idea(path, runner=fake_runner([]), results_dir=world["results"], cwd=world["repo"])
    assert ledger_total(world) == 100
    done = ti.try_idea(path, runner=fake_runner([]), allow_large=True, results_dir=world["results"], cwd=world["repo"])
    assert done["record"]["combinations"] == 90 and ledger_total(world) == 190


def test_an_invalid_idea_is_refused_before_anything_else(world):
    path = write_spec(world, {**SPEC, "rationale": "tbd"})
    with pytest.raises(ValueError, match="not valid"):
        ti.try_idea(path, runner=fake_runner([]), results_dir=world["results"], cwd=world["repo"])
    assert ledger_total(world) == 100


def test_the_plan_says_what_would_be_counted_and_counts_nothing(world):
    p = ti.plan(SPEC)
    assert p == {"combinations": 4, "ledger_before": 100, "ledger_after": 104, "bonferroni_bar_after": pytest.approx(0.05 / 104)}
    assert ledger_total(world) == 100


def test_the_ledger_context_names_the_idea_the_count_and_the_fingerprint():
    c = ti.context_for(SPEC, 4)
    assert c.startswith(f"idea:ma_fast_nifty50 [spec {ti.spec_hash(SPEC)}]") and "4 combinations" in c and "before any result was shown" in c
    assert "1 combination " in ti.context_for(SPEC, 1)
    assert ti.already_tried("ma_fast_nifty50", {"runs": [{"context": c}]}) and not ti.already_tried("other", {"runs": [{"context": c}]})
    assert not ti.already_tried("ma_fast_nifty50", {"runs": [{"context": "MA crossover parameter sweep"}]})
