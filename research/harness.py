"""
research/harness.py

A research harness for testing MULTIPLE strategies, not a strategy
scanner. The distinction matters: a scanner runs things and reports
what looked good. This exists specifically to make that easy to do
WRONG hard to do, after this project already produced two false-looking
positives from exactly that pattern -- the 109-cell MA crossover sweep
(best cell: 13.27% CAGR, indistinguishable from the grid's own sampling
noise) and the 51-pair cointegration screen (5 pairs "significant" at
raw p<0.05, 0 survived a fresh out-of-sample test). Both were caught
because a human did the correction and the OOS check by hand, afterward,
carefully. This harness makes that structural instead of a habit:

1. Every run appends to a persistent, cumulative hypothesis-count ledger
   (research/hypothesis_ledger.json) -- the multiple-testing burden this
   project has accumulated is tracked across sessions, not reset each run.
2. Multiple-testing correction (Bonferroni AND Benjamini-Hochberg FDR)
   is computed automatically for every batch -- there is no "raw mode."
   Bonferroni's alpha is divided by the TRUE CUMULATIVE hypothesis count
   (point 1's ledger total after this run), not just this run's own
   batch size -- point 1 tracking a number that never actually fed into
   the correction was itself a real, found-and-fixed bug (a single-
   hypothesis run always got bonferroni_alpha = alpha/1, ignoring
   however large the ledger already was). Benjamini-Hochberg is NOT
   extended the same way -- it needs the full historical p-value vector,
   which the ledger doesn't store (only counts), so BH-FDR here corrects
   within this run's own batch only; see run_harness()'s docstring.
3. Every registered strategy requires a non-empty, non-trivial economic
   rationale string. Missing or trivial rationale is flagged in every
   report as PURE DATA MINING -- not silently accepted.
4. A strategy without an out-of-sample check is always UNVALIDATED.
   UNVALIDATED results cannot outrank VALIDATED ones, structurally --
   the ranking/best-strategy functions enforce this, not just the report
   formatting.
5. print_harness_report() ALWAYS prints the survivor-count summary
   before any per-strategy table -- there is no way to call it and get
   a "top performers" list first.
6. get_best_strategy() refuses to return anything that isn't both
   corrected-significant AND confirmed on out-of-sample data. If nothing
   qualifies, it says so -- it never falls back to ranking by raw
   in-sample number.
7. VALIDATED_CONFIRMED requires in-sample AND out-of-sample to BOTH
   independently clear corrected significance -- not out-of-sample
   alone. A strategy whose in-sample Sharpe was flat or negative but
   whose out-of-sample Sharpe cleared the bar gets a distinct status,
   OOS_ONLY_SIGNIFICANT, instead. This was a real gap, not a
   hypothetical one: after engine/backtest.py's date-window bug was
   fixed (it had been silently backtesting the same full history
   regardless of the requested in-sample/out-of-sample split -- see
   MIDCAP_SMALLCAP_FINDINGS.md's amendment), MA crossover on Nifty 50,
   Midcap 150, and Smallcap 250 ALL showed a negative-or-flat in-sample
   Sharpe with a strongly positive, corrected-significant out-of-sample
   Sharpe (2020-2025 was a broad bull run across every universe tested).
   Under the old logic all three would have printed VALIDATED_CONFIRMED
   -- indistinguishable in the report from a genuinely replicated
   finding, even though "this out-of-sample window happened to suit a
   barely-invested strategy" is a regime effect, not evidence of skill.
   Since both legs of the significance test are one-sided (H1: Sharpe >
   0), requiring both to survive correction also guarantees they agree
   in sign -- no separate direction check is needed.

Significance test: every strategy result is judged on its Sharpe ratio,
using the same asymptotic standard error this project already used to
evaluate the MA crossover sweep (Lo, 2002: SE(Sharpe_annual) =
sqrt(252*(1+0.5*sharpe_period^2)/n_daily_obs)), converted to a ONE-SIDED
p-value against the null of zero-or-negative Sharpe (H1: Sharpe > 0) --
see sharpe_p_value()'s docstring for why two-sided was tried first and
rejected. This is what lets strategies of completely different shapes (a
crossover rule, a mean-reversion rule, anything else) be compared and
corrected on one consistent statistical basis, rather than each strategy
needing its own bespoke significance test.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import numpy as np
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "hypothesis_ledger.json")
TRADING_DAYS_PER_YEAR = 252
DEFAULT_ALPHA = 0.05

# Rationale shorter than this (characters) or matching a known
# placeholder is treated as effectively absent -- a human can still
# type something meaningless to get past a bare "is it empty" check,
# but this stops the laziest version of that (blank string, "n/a", "todo").
MIN_RATIONALE_CHARS = 25
PLACEHOLDER_RATIONALES = {"n/a", "na", "none", "todo", "tbd", "test", "-", "."}


def sharpe_standard_error(sharpe_annual: float, n_daily_obs: int) -> float:
    """
    Lo (2002) asymptotic standard error of an annualized Sharpe ratio,
    estimated from n_daily_obs daily return observations. Already used
    (as a one-off hand calculation) to evaluate the MA crossover sweep
    in this project's chat history -- formalized here as a reusable
    function instead of being redone by hand each time.
    """
    sharpe_period = sharpe_annual / np.sqrt(TRADING_DAYS_PER_YEAR)
    var_period = (1 + 0.5 * sharpe_period ** 2) / n_daily_obs
    se_period = np.sqrt(var_period)
    return se_period * np.sqrt(TRADING_DAYS_PER_YEAR)


def sharpe_p_value(sharpe_annual: float, n_daily_obs: int) -> float:
    """
    ONE-SIDED p-value against the null hypothesis that the true Sharpe
    ratio is zero or negative (H1: true Sharpe > 0).

    Deliberately one-sided, not the textbook-default two-sided test: the
    question this harness exists to answer is "is this a good strategy,"
    not "is this strategy's performance merely distinguishable from
    zero." A two-sided test treats a reliably, significantly NEGATIVE
    Sharpe the same as a reliably positive one -- both come back
    "significant" -- which would let a strategy that loses money with
    statistical confidence get flagged VALIDATED_CONFIRMED and even
    returned as "best." That happened during this module's own first
    real test run (RSI reversion, Sharpe -0.69 both in-sample and
    out-of-sample, two-sided p=0.02) and is exactly the kind of
    plausible-looking-but-wrong result this project has learned to
    catch by actually running real numbers through new code before
    trusting it. A negative Sharpe now returns a high p-value (no
    evidence of the thing we're actually checking for), not a low one.
    """
    se = sharpe_standard_error(sharpe_annual, n_daily_obs)
    if se == 0 or np.isnan(se):
        return float("nan")
    z = sharpe_annual / se
    return 1 - norm.cdf(z)


def _rationale_is_trivial(rationale: str) -> bool:
    if rationale is None:
        return True
    cleaned = rationale.strip()
    if len(cleaned) < MIN_RATIONALE_CHARS:
        return True
    if cleaned.lower() in PLACEHOLDER_RATIONALES:
        return True
    return False


@dataclass
class StrategyResult:
    """
    One strategy's result within a harness run. Construct via
    evaluate_strategy() below rather than directly, so the p-value and
    validation status are always computed consistently.
    """
    name: str
    rationale: str
    in_sample_sharpe: float
    in_sample_n_obs: int
    out_of_sample_sharpe: float = None
    out_of_sample_n_obs: int = None

    # populated by evaluate_strategy()
    in_sample_p_value: float = field(default=None)
    out_of_sample_p_value: float = field(default=None)
    bonferroni_alpha: float = field(default=None)
    in_sample_survives_bonferroni: bool = field(default=None)
    in_sample_survives_bh: bool = field(default=None)
    bh_qvalue: float = field(default=None)
    out_of_sample_survives_correction: bool = field(default=None)
    has_rationale: bool = field(default=None)
    status: str = field(default=None)  # UNVALIDATED / VALIDATED_FAILED / OOS_ONLY_SIGNIFICANT / VALIDATED_CONFIRMED


def evaluate_strategy(name: str, rationale: str, in_sample_sharpe: float, in_sample_n_obs: int,
                       out_of_sample_sharpe: float = None, out_of_sample_n_obs: int = None) -> StrategyResult:
    """
    Registers one strategy's result for a harness run. Requires a
    rationale string (point 3) -- pass an empty/trivial one and the
    result comes back flagged, it isn't rejected outright, since a
    human should be able to see "this was tried with no stated reason"
    in the output rather than have it silently disappear.

    Correction (Bonferroni alpha, BH survival) is filled in by
    run_harness() once the whole batch is known -- a single result's
    significance is only meaningful relative to how many were tested
    alongside it.
    """
    if not name or not name.strip():
        raise ValueError("A strategy result must have a non-empty name.")

    result = StrategyResult(
        name=name, rationale=rationale or "",
        in_sample_sharpe=in_sample_sharpe, in_sample_n_obs=in_sample_n_obs,
        out_of_sample_sharpe=out_of_sample_sharpe, out_of_sample_n_obs=out_of_sample_n_obs,
    )
    result.has_rationale = not _rationale_is_trivial(rationale)
    result.in_sample_p_value = sharpe_p_value(in_sample_sharpe, in_sample_n_obs)
    if out_of_sample_sharpe is not None and out_of_sample_n_obs is not None:
        result.out_of_sample_p_value = sharpe_p_value(out_of_sample_sharpe, out_of_sample_n_obs)
    return result


def classify_results(results: list, cumulative_total: int, alpha: float = DEFAULT_ALPHA) -> dict:
    """
    PURE: decides every result's validation status. Reads and writes no
    files -- in particular it does NOT touch the hypothesis ledger.

    results: list of StrategyResult from evaluate_strategy(); their
        correction fields and `status` are filled in, in place.
    cumulative_total: the TRUE cumulative hypothesis count the Bonferroni
        bar is divided by (see the note below on why that is not just
        len(results)).

    Split out of run_harness() so that a READ-ONLY consumer (the web
    app's snapshot command) can reuse the exact status rules -- not a
    copy of them -- without registering a hypothesis. Extracted verbatim;
    run_harness() calls this and then does the ledger bookkeeping.

    A status is only true AS OF a total: the same p-values can flip from
    one status to another purely because cumulative_total grew (the
    Bonferroni bar alpha/total only ever tightens). Callers that display
    a status must display the total it was computed against.
    """
    if not results:
        raise ValueError("classify_results() called with no strategy results.")

    n_tested = len(results)
    in_sample_pvals = np.array([r.in_sample_p_value for r in results])

    # Bonferroni is corrected against the TRUE CUMULATIVE hypothesis count
    # (this run's own n_tested PLUS everything the ledger already
    # recorded before it) -- not just this run's own batch size. This
    # was a real bug, not a design choice: before this fix, a single-
    # hypothesis run always got bonferroni_alpha = alpha/1 = alpha,
    # completely ignoring however many hypotheses the ledger already
    # showed (the whole point of a persistent, cumulative ledger is
    # defeated if the number it tracks never actually feeds into the
    # correction applied). Bonferroni only needs a COUNT to correct
    # against, which the ledger always has -- see the note on
    # Benjamini-Hochberg below for why that correction is NOT extended
    # the same way.
    bonferroni_alpha = alpha / cumulative_total

    # BH-FDR, by contrast, genuinely needs the FULL set of p-values
    # together to compute its step-up q-values correctly -- it is not a
    # simple function of a count the way Bonferroni is. The ledger only
    # ever stored hypothesis COUNTS for historical runs (the 109-cell
    # sweep and 51-pair screen were backfilled as counts, not as
    # individual p-values), so there is no historical p-value vector to
    # extend this with. bh_reject/bh_qvalue below are therefore computed
    # WITHIN THIS RUN'S BATCH ONLY, same as before this fix -- disclosed
    # as a known limitation (see README.md's Technical Debt), not
    # silently presented as a true cumulative correction the way
    # Bonferroni now is. With n_tested=1 (a single new hypothesis
    # registered alone), BH-FDR degenerates to the raw uncorrected
    # p-value -- Bonferroni against the cumulative count is the
    # meaningful bar in that case, not BH.
    bh_reject, bh_qvalues, _, _ = multipletests(in_sample_pvals, alpha=alpha, method="fdr_bh")

    for i, r in enumerate(results):
        r.bonferroni_alpha = bonferroni_alpha
        r.in_sample_survives_bonferroni = bool(in_sample_pvals[i] < bonferroni_alpha)
        r.in_sample_survives_bh = bool(bh_reject[i])
        r.bh_qvalue = float(bh_qvalues[i])

        # Out-of-sample correction uses the SAME alpha/n as in-sample --
        # both are being judged under the same "n hypotheses were tried"
        # umbrella, not a fresh, smaller comparison (point 2 + point 4
        # together: correction is mandatory, and OOS doesn't get a
        # weaker bar just because fewer things "made it" that far).
        if r.out_of_sample_p_value is not None:
            r.out_of_sample_survives_correction = bool(r.out_of_sample_p_value < bonferroni_alpha)
        else:
            r.out_of_sample_survives_correction = None

        if r.out_of_sample_sharpe is None:
            r.status = "UNVALIDATED"
        elif r.in_sample_survives_bonferroni and r.out_of_sample_survives_correction:
            # A real in-sample finding (Sharpe significantly > 0) that
            # ALSO holds up out-of-sample -- this is what "confirmed"
            # should mean: replication, not just a second independent
            # significance test. Both legs use the same one-sided test
            # (H1: Sharpe > 0), so requiring both to survive already
            # guarantees they agree in sign -- no separate direction
            # check needed.
            r.status = "VALIDATED_CONFIRMED"
        elif r.out_of_sample_survives_correction and not r.in_sample_survives_bonferroni:
            # THE gap this branch exists to close: out-of-sample alone
            # clearing the bar, with nothing resembling a finding
            # in-sample, is NOT a replication -- there was no in-sample
            # signal to replicate. Found for real on this project's own
            # data: MA crossover on Nifty 50 (in-sample Sharpe -0.19)
            # and on Midcap150/Smallcap250 (in-sample Sharpe -0.22/+0.03)
            # all cleared out-of-sample significance during 2020-2025's
            # broad bull run and would have been stamped
            # VALIDATED_CONFIRMED under the old logic -- indistinguishable
            # from a genuinely replicated finding in the report, even
            # though "the whole market went up and this barely-invested
            # strategy caught some of it" is a regime effect, not
            # evidence of skill. Flagged separately so it can't hide
            # inside VALIDATED_CONFIRMED, but it isn't VALIDATED_FAILED
            # either (failure implies a real attempt at replication that
            # didn't hold -- this is a different failure mode, deserving
            # more suspicion, not less).
            r.status = "OOS_ONLY_SIGNIFICANT"
        else:
            r.status = "VALIDATED_FAILED"

    expected_by_chance = alpha * n_tested
    n_raw_significant = int((in_sample_pvals < alpha).sum())
    n_survive_bonferroni = sum(1 for r in results if r.in_sample_survives_bonferroni)
    n_survive_bh = sum(1 for r in results if r.in_sample_survives_bh)
    n_confirmed = sum(1 for r in results if r.status == "VALIDATED_CONFIRMED")
    n_oos_only = sum(1 for r in results if r.status == "OOS_ONLY_SIGNIFICANT")
    n_unvalidated = sum(1 for r in results if r.status == "UNVALIDATED")
    n_no_rationale = sum(1 for r in results if not r.has_rationale)

    return {
        "n_tested": n_tested,
        "bonferroni_alpha": bonferroni_alpha,
        "expected_by_chance": expected_by_chance,
        "n_raw_significant": n_raw_significant,
        "n_survive_bonferroni": n_survive_bonferroni,
        "n_survive_bh_fdr": n_survive_bh,
        "n_validated_confirmed": n_confirmed,
        "n_oos_only_significant": n_oos_only,
        "n_unvalidated": n_unvalidated,
        "n_no_rationale": n_no_rationale,
        "results": results,
    }


def run_harness(results: list, context: str, alpha: float = DEFAULT_ALPHA) -> dict:
    """
    The mandatory pipeline every batch of strategy results goes through.
    Not optional, not a flag -- point 2 and point 4 are enforced HERE,
    not left to whoever calls the reporting function to remember.

    results: list of StrategyResult from evaluate_strategy().
    context: a short human description of this run, stored in the ledger.

    Returns a dict with the corrected results, the survivor counts
    (point 5's required lead numbers), and the ledger entry that was
    just appended to disk.
    """
    if not results:
        raise ValueError("run_harness() called with no strategy results.")

    n_tested = len(results)

    # Bonferroni is corrected against the TRUE CUMULATIVE hypothesis count
    # (this run's own n_tested PLUS everything the ledger already recorded
    # before it) -- not just this run's own batch size. See
    # classify_results() and FINDINGS.md Section 6, Bug 3.
    cumulative_before = _load_ledger()["cumulative_hypotheses"]
    cumulative_after = cumulative_before + n_tested

    summary = classify_results(results, cumulative_after, alpha)

    ledger_entry = _append_to_ledger(context, n_tested)
    assert ledger_entry["cumulative_hypotheses_after_run"] == cumulative_after, (
        "Ledger cumulative count changed between the peek and the append -- "
        "should be impossible in a single-process run; bonferroni_alpha above "
        "would no longer match the ledger's own recorded total."
    )

    return {
        "context": context,
        "n_tested": n_tested,
        "cumulative_hypotheses_before_run": cumulative_before,
        "cumulative_hypotheses_all_time": cumulative_after,
        "bonferroni_alpha": summary["bonferroni_alpha"],
        "expected_by_chance": summary["expected_by_chance"],
        "n_raw_significant": summary["n_raw_significant"],
        "n_survive_bonferroni": summary["n_survive_bonferroni"],
        "n_survive_bh_fdr": summary["n_survive_bh_fdr"],
        "n_validated_confirmed": summary["n_validated_confirmed"],
        "n_oos_only_significant": summary["n_oos_only_significant"],
        "n_unvalidated": summary["n_unvalidated"],
        "n_no_rationale": summary["n_no_rationale"],
        "results": results,
    }


# --- Persistent ledger (point 1) ---

def _load_ledger() -> dict:
    if not os.path.exists(LEDGER_PATH):
        return {"runs": [], "cumulative_hypotheses": 0}
    with open(LEDGER_PATH, "r") as f:
        return json.load(f)


def _append_to_ledger(context: str, n_hypotheses: int) -> dict:
    ledger = _load_ledger()
    before = ledger["cumulative_hypotheses"]
    after = before + n_hypotheses
    entry = {
        "run_id": f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{len(ledger['runs'])}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "n_hypotheses_this_run": n_hypotheses,
        "cumulative_hypotheses_before_run": before,
        "cumulative_hypotheses_after_run": after,
    }
    ledger["runs"].append(entry)
    ledger["cumulative_hypotheses"] = after
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)
    return entry


def cumulative_hypotheses() -> int:
    """The running total, read from disk -- what point 1 asks to keep visible."""
    return _load_ledger()["cumulative_hypotheses"]


# --- Reporting (point 5) and the "best" query (point 6) ---

def print_harness_report(run_output: dict) -> None:
    """
    Enforces the required lead-with-survivor-counts ordering. There is
    no code path in this module that prints a per-strategy table before
    this block -- the ordering is structural, not a formatting choice
    made by whoever calls this.
    """
    print("=" * 100)
    print(f"RESEARCH HARNESS RUN: {run_output['context']}")
    print("=" * 100)
    print(f"Strategies tested this run: {run_output['n_tested']}")
    print(f"Cumulative hypotheses BEFORE this run: {run_output['cumulative_hypotheses_before_run']}")
    print(f"Cumulative hypotheses tested, all runs, all time: {run_output['cumulative_hypotheses_all_time']}")
    print(f"Bonferroni alpha applied (={DEFAULT_ALPHA}/{run_output['cumulative_hypotheses_all_time']} cumulative, "
          f"NOT just this run's {run_output['n_tested']}): {run_output['bonferroni_alpha']:.6f}")
    print(f"Expected to look significant by chance alone at alpha={DEFAULT_ALPHA}, this run's batch: "
          f"{run_output['expected_by_chance']:.2f}")
    print(f"Raw in-sample 'significant' (uncorrected p<{DEFAULT_ALPHA}): {run_output['n_raw_significant']}")
    print(f"Survive Bonferroni correction (against the cumulative count): {run_output['n_survive_bonferroni']}")
    print(f"Survive Benjamini-Hochberg FDR (WITHIN THIS RUN'S BATCH ONLY -- see run_harness()'s docstring "
          f"for why this is not yet extended cumulatively): {run_output['n_survive_bh_fdr']}")
    print(f"UNVALIDATED (no out-of-sample check performed): {run_output['n_unvalidated']}")
    print(f"OOS_ONLY_SIGNIFICANT (out-of-sample cleared the bar with NO real in-sample finding to "
          f"replicate -- a regime-dependent red flag, not a confirmation): {run_output['n_oos_only_significant']}")
    print(f"VALIDATED_CONFIRMED (in-sample AND out-of-sample both corrected-significant -- a real "
          f"replication): {run_output['n_validated_confirmed']}")
    if run_output["n_oos_only_significant"] > 0:
        print(f"*** {run_output['n_oos_only_significant']} strategy(ies) cleared out-of-sample "
              f"significance with no significant in-sample result behind them -- see OOS_ONLY_SIGNIFICANT "
              f"below. Likely explanation: the out-of-sample window happened to suit this strategy "
              f"(e.g. a broad bull market), not that the strategy has skill. Treat with MORE suspicion "
              f"than VALIDATED_FAILED, not less. ***")
    if run_output["n_no_rationale"] > 0:
        print(f"*** {run_output['n_no_rationale']} strategy(ies) tested with NO stated economic "
              f"rationale -- flagged PURE DATA MINING below, regardless of performance. ***")
    print()

    print("-" * 100)
    print("PER-STRATEGY DETAIL (sorted by status, then in-sample Sharpe -- NOT a ranking, a listing)")
    print("-" * 100)
    status_order = {"VALIDATED_CONFIRMED": 0, "OOS_ONLY_SIGNIFICANT": 1, "VALIDATED_FAILED": 2, "UNVALIDATED": 3}
    ordered = sorted(run_output["results"], key=lambda r: (status_order[r.status], -r.in_sample_sharpe))
    for r in ordered:
        rationale_flag = "" if r.has_rationale else "  [[ NO STATED RATIONALE -- PURE DATA MINING ]]"
        print(f"\n{r.name}{rationale_flag}")
        print(f"  Rationale: {r.rationale if r.rationale else '(none given)'}")
        print(f"  In-sample:  Sharpe={r.in_sample_sharpe:+.3f}  raw p={r.in_sample_p_value:.4f}  "
              f"Bonferroni(survives={r.in_sample_survives_bonferroni}, alpha={r.bonferroni_alpha:.5f})  "
              f"BH(survives={r.in_sample_survives_bh}, q={r.bh_qvalue:.4f})")
        if r.out_of_sample_sharpe is not None:
            print(f"  Out-of-sample: Sharpe={r.out_of_sample_sharpe:+.3f}  p={r.out_of_sample_p_value:.4f}  "
                  f"survives same correction={r.out_of_sample_survives_correction}")
        else:
            print("  Out-of-sample: NOT CHECKED")
        print(f"  STATUS: {r.status}")


def get_best_strategy(run_output: dict):
    """
    Point 6: refuses to rank by in-sample return. Returns the
    VALIDATED_CONFIRMED result with the highest out-of-sample Sharpe,
    or None (with an explanatory message) if nothing qualifies -- it
    never falls back to "well, the best raw number was X." An
    OOS_ONLY_SIGNIFICANT result never qualifies as VALIDATED_CONFIRMED
    (see run_harness()) -- clearing the out-of-sample bar alone, with no
    real in-sample finding behind it, is exactly the "looks confirmed
    but isn't" case this function must not fall back to either.
    """
    confirmed = [r for r in run_output["results"] if r.status == "VALIDATED_CONFIRMED"]
    if not confirmed:
        oos_only = sum(1 for r in run_output["results"] if r.status == "OOS_ONLY_SIGNIFICANT")
        oos_only_note = (
            f" ({oos_only} strategy(ies) cleared out-of-sample significance with no significant "
            f"in-sample finding behind them -- see OOS_ONLY_SIGNIFICANT in the report. That is a "
            f"red flag, not a near-miss; it is deliberately NOT treated as 'almost best.')"
            if oos_only > 0 else ""
        )
        print("No strategy survived multiple-testing correction AND out-of-sample validation "
              "in this run. There is no 'best' to report. Reporting the highest in-sample number "
              f"anyway would be exactly the mistake this harness exists to prevent.{oos_only_note}")
        return None
    best = max(confirmed, key=lambda r: r.out_of_sample_sharpe)
    print(f"Best VALIDATED_CONFIRMED strategy: {best.name} "
          f"(out-of-sample Sharpe={best.out_of_sample_sharpe:+.3f}, p={best.out_of_sample_p_value:.4f}, "
          f"survives correction at alpha={best.bonferroni_alpha:.5f})")
    return best
