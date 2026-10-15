"""
tests/test_harness.py

Regression tests for research/harness.py's validation status logic,
specifically the OOS_ONLY_SIGNIFICANT fix: VALIDATED_CONFIRMED must
require in-sample AND out-of-sample to BOTH independently clear
corrected significance, not out-of-sample alone.

Before this fix, run_harness() granted VALIDATED_CONFIRMED to any
strategy whose out-of-sample Sharpe cleared the bar, regardless of what
in-sample showed. That gap had real teeth on this project's own data:
after engine/backtest.py's date-window bug was fixed, MA crossover on
Nifty 50, Midcap 150, and Smallcap 250 each showed a flat-or-negative
in-sample Sharpe paired with a strongly positive, significant
out-of-sample Sharpe (2020-2025 was a broad bull run) -- and all three
would have printed VALIDATED_CONFIRMED, indistinguishable from a
genuinely replicated finding. See MIDCAP_SMALLCAP_FINDINGS.md's
amendment.

No file previously existed for this module -- these are the first
tests for research/harness.py at all, not just for this fix.
"""

import json

import pytest

import harness
from harness import evaluate_strategy, run_harness, get_best_strategy

RATIONALE = "A rationale long enough to not be flagged as trivial or a placeholder string."


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    """Every test gets its own empty ledger file -- these tests must not
    read or write the project's real research/hypothesis_ledger.json."""
    monkeypatch.setattr(harness, "LEDGER_PATH", str(tmp_path / "test_ledger.json"))


def _n_obs_for_sharpe(target_sharpe: float, want_significant: bool) -> int:
    """
    Picks a sample size that makes a given Sharpe land on the wanted
    side of the one-sided p<0.05 threshold (every test below registers
    exactly ONE strategy per run_harness() call, so bonferroni_alpha =
    DEFAULT_ALPHA/n_tested = 0.05/1 = 0.05) -- lets these tests state
    their intent ("this should be significant") directly instead of
    hand-solving the Lo(2002) formula for each fixture.
    """
    for n in [50, 100, 252, 500, 1000, 2000, 5000, 10000, 20000]:
        p = harness.sharpe_p_value(target_sharpe, n)
        if want_significant and p < 0.05:
            return n
        if not want_significant and p >= 0.05:
            return n
    raise AssertionError(f"Could not find n_obs making Sharpe={target_sharpe} "
                          f"{'significant' if want_significant else 'insignificant'}.")


def test_genuine_replication_is_validated_confirmed():
    """Both legs significant and positive -- this is what CONFIRMED should mean."""
    n_sig = _n_obs_for_sharpe(1.0, want_significant=True)
    r = evaluate_strategy("Genuine", RATIONALE,
                           in_sample_sharpe=1.0, in_sample_n_obs=n_sig,
                           out_of_sample_sharpe=1.0, out_of_sample_n_obs=n_sig)
    out = run_harness([r], context="test")
    assert out["results"][0].status == "VALIDATED_CONFIRMED"
    assert out["n_validated_confirmed"] == 1
    assert out["n_oos_only_significant"] == 0


def test_out_of_sample_only_significant_is_not_validated_confirmed():
    """
    THE regression this file exists to lock in: a negative/insignificant
    in-sample Sharpe paired with a strongly significant out-of-sample
    Sharpe must NOT be VALIDATED_CONFIRMED -- there was no in-sample
    finding to replicate. This is the exact real-data shape (MA
    crossover on Nifty 50/Midcap150/Smallcap250 post date-window fix).
    """
    n_insig = _n_obs_for_sharpe(-0.2, want_significant=False)
    n_sig = _n_obs_for_sharpe(1.0, want_significant=True)
    r = evaluate_strategy("OOS-only", RATIONALE,
                           in_sample_sharpe=-0.2, in_sample_n_obs=n_insig,
                           out_of_sample_sharpe=1.0, out_of_sample_n_obs=n_sig)
    out = run_harness([r], context="test")

    assert out["results"][0].status == "OOS_ONLY_SIGNIFICANT"
    assert out["n_validated_confirmed"] == 0
    assert out["n_oos_only_significant"] == 1


def test_in_sample_significant_but_out_of_sample_fails_is_validated_failed():
    """A real-looking in-sample finding that does NOT replicate -- unchanged from before this fix."""
    n_sig = _n_obs_for_sharpe(1.0, want_significant=True)
    n_insig = _n_obs_for_sharpe(0.0, want_significant=False)
    r = evaluate_strategy("Failed replication", RATIONALE,
                           in_sample_sharpe=1.0, in_sample_n_obs=n_sig,
                           out_of_sample_sharpe=0.0, out_of_sample_n_obs=n_insig)
    out = run_harness([r], context="test")
    assert out["results"][0].status == "VALIDATED_FAILED"


def test_neither_significant_is_validated_failed_not_oos_only():
    n_insig = _n_obs_for_sharpe(0.0, want_significant=False)
    r = evaluate_strategy("Nothing here", RATIONALE,
                           in_sample_sharpe=0.0, in_sample_n_obs=n_insig,
                           out_of_sample_sharpe=0.0, out_of_sample_n_obs=n_insig)
    out = run_harness([r], context="test")
    assert out["results"][0].status == "VALIDATED_FAILED"


def test_no_out_of_sample_check_is_unvalidated():
    r = evaluate_strategy("Untested", RATIONALE, in_sample_sharpe=1.0, in_sample_n_obs=500)
    out = run_harness([r], context="test")
    assert out["results"][0].status == "UNVALIDATED"


def test_get_best_strategy_never_returns_an_oos_only_significant_result():
    """
    The exact failure mode this fix targets: get_best_strategy() must
    not treat OOS_ONLY_SIGNIFICANT as "close enough" and return it when
    nothing is genuinely VALIDATED_CONFIRMED.
    """
    n_insig = _n_obs_for_sharpe(-0.2, want_significant=False)
    n_sig = _n_obs_for_sharpe(1.0, want_significant=True)
    r = evaluate_strategy("OOS-only", RATIONALE,
                           in_sample_sharpe=-0.2, in_sample_n_obs=n_insig,
                           out_of_sample_sharpe=1.0, out_of_sample_n_obs=n_sig)
    out = run_harness([r], context="test")

    best = get_best_strategy(out)
    assert best is None


def test_get_best_strategy_returns_a_genuine_confirmation():
    n_sig = _n_obs_for_sharpe(1.0, want_significant=True)
    r = evaluate_strategy("Genuine", RATIONALE,
                           in_sample_sharpe=1.0, in_sample_n_obs=n_sig,
                           out_of_sample_sharpe=1.0, out_of_sample_n_obs=n_sig)
    out = run_harness([r], context="test")
    best = get_best_strategy(out)
    assert best is not None
    assert best.name == "Genuine"


def test_bonferroni_alpha_uses_the_cumulative_ledger_total_not_just_this_batch():
    """
    Regression test for a real bug: bonferroni_alpha was computed as
    alpha/n_tested using only THIS RUN's batch size, completely ignoring
    however many hypotheses the ledger already recorded -- which meant a
    single-hypothesis run always got bonferroni_alpha = 0.05/1 = 0.05,
    no matter whether it was hypothesis #1 or #165. Seed the ledger with
    163 prior hypotheses, register one new one, and confirm the
    correction reflects 164 (163 + 1), not 1.
    """
    for i in range(3):
        harness._append_to_ledger(f"seed run {i}", 50 if i < 2 else 63)  # 50+50+63 = 163
    assert harness.cumulative_hypotheses() == 163

    n_sig = _n_obs_for_sharpe(1.0, want_significant=True)
    r = evaluate_strategy("New hypothesis #164", RATIONALE,
                           in_sample_sharpe=1.0, in_sample_n_obs=n_sig,
                           out_of_sample_sharpe=1.0, out_of_sample_n_obs=n_sig)
    out = run_harness([r], context="test")

    assert out["cumulative_hypotheses_before_run"] == 163
    assert out["cumulative_hypotheses_all_time"] == 164
    assert out["bonferroni_alpha"] == pytest.approx(0.05 / 164)
    assert out["results"][0].bonferroni_alpha == pytest.approx(0.05 / 164)
