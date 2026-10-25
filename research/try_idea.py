"""
research/try_idea.py

The HONEST BUILDER: the one way to try a new rule on the existing strategy families, built so that the two ways a researcher fools themselves are not available.

  * No try goes uncounted. Every combination in the idea's grid is run and every one goes into the hypothesis ledger, together, before any result is shown. There is no flag to
    run "just to look", and no way to keep the best cell and forget the rest.
  * No idea is rewritten after its result is known. The idea is a small file in ideas/ that must already be COMMITTED and unchanged before the tool will run it; the tool writes the
    file's fingerprint into the ledger, and research/track_record.py later checks the file was saved before the run and never edited since. Each idea runs once.

An idea file (ideas/<id>.json):

    {"id": "ma_20_100_nifty50", "name": "Faster MA crossover", "rationale": "why this should work, in your own words (at least a sentence)",
     "strategy": "ma_crossover", "universe": "nifty50", "grid": {"fast": [20, 30], "slow": [100, 150]}}

    strategy: ma_crossover | rsi_reversion | dip_target        universe: nifty50 | midcap150 | smallcap250
    grid:     every combination is one hypothesis (the example above is 4). Names must be the strategy's own parameters; any you leave out keep the strategy's defaults.

    python research/try_idea.py ideas/my_idea.json --plan     # shows what it would count and the stricter bar that results; runs nothing, counts nothing
    python research/try_idea.py ideas/my_idea.json --run      # commit the file first; then runs every combination, counts them all, prints the verdicts

The tool cannot stop someone running a backtest by hand outside it. What it does is make the honest route the easy one, and make the record show which route each result came from.
"""

import hashlib
import inspect
import itertools
import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("data", "strategies", "engine", "research", ""):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, sub) if sub else PROJECT_ROOT)

import harness

IDEAS_DIR = os.path.join(PROJECT_ROOT, "ideas")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "reports", "output", "ideas")
STRATEGIES = ("ma_crossover", "rsi_reversion", "dip_target")
UNIVERSES = {"nifty50": "UNIVERSE", "midcap150": "MIDCAP150_UNIVERSE", "smallcap250": "SMALLCAP250_UNIVERSE"}
MAX_COMBINATIONS = 60              # a bigger grid is a bigger fishing trip: it must be asked for on purpose with --allow-large
REQUIRED = ("id", "name", "rationale", "strategy", "universe", "grid")
CONTEXT = re.compile(r"^idea:(?P<id>[a-z0-9_]+) \[spec (?P<hash>[0-9a-f]{12})\]")


# --- the idea file -------------------------------------------------------------------------------------------------------------------------

def strategy_parameters(name: str) -> list:
    """The parameter names the strategy's own signal function accepts."""
    module = __import__(name)
    return [p for p in inspect.signature(module.generate_signals).parameters if p != "df"]


def validate_spec(spec: dict, params_of=strategy_parameters) -> list:
    """Everything wrong with an idea file, in plain words; an empty list means it can be run."""
    problems = [f"missing '{k}'" for k in REQUIRED if k not in spec]
    if problems:
        return problems
    if not re.fullmatch(r"[a-z0-9_]+", str(spec["id"])) or str(spec["id"]).startswith("_"):
        problems.append("id must be lower-case letters, digits and underscores, and must not start with an underscore")
    if harness._rationale_is_trivial(str(spec["rationale"])):
        problems.append(f"the rationale is missing or too short (at least {harness.MIN_RATIONALE_CHARS} characters): say why this should work before it is tried")
    if spec["strategy"] not in STRATEGIES:
        problems.append(f"strategy must be one of {', '.join(STRATEGIES)}")
    if spec["universe"] not in UNIVERSES:
        problems.append(f"universe must be one of {', '.join(UNIVERSES)}")
    grid = spec["grid"]
    if not isinstance(grid, dict) or not grid or not all(isinstance(v, list) and v for v in grid.values()):
        problems.append("grid must be a non-empty object whose every value is a non-empty list")
        return problems
    if spec["strategy"] in STRATEGIES:
        allowed = params_of(spec["strategy"])
        unknown = [k for k in grid if k not in allowed]
        if unknown:
            problems.append(f"{', '.join(unknown)} are not parameters of {spec['strategy']} (it takes: {', '.join(allowed)})")
    return problems


def expand_grid(grid: dict) -> list:
    """Every combination of the grid, in a fixed order: [{"fast": 20, "slow": 100}, ...]."""
    keys = sorted(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def spec_hash(spec: dict) -> str:
    """A fingerprint of the idea's content (not its formatting), 12 hex characters, written into the ledger so a later edit of the file is visible."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def check_frozen(path: str, cwd: str = PROJECT_ROOT) -> tuple:
    """(commit hash that last saved the file, "") when the file is committed and unchanged since; (None, reason) otherwise."""
    rel = os.path.relpath(os.path.abspath(path), cwd).replace("\\", "/")
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=cwd, capture_output=True, text=True)
        if tracked.returncode != 0:
            return None, f"{rel} is not in git yet: commit it first, so it is provable that it was written before it was run"
        dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=cwd, capture_output=True, text=True).stdout.strip()
        if dirty:
            return None, f"{rel} has changes that are not committed: commit it (or undo the change) so the file that runs is the file that was saved"
        head = subprocess.run(["git", "log", "-1", "--format=%H", "--", rel], cwd=cwd, capture_output=True, text=True).stdout.strip()
        return head, ""
    except OSError as e:
        return None, f"git could not be started: {e}"


def already_tried(spec_id: str, ledger: dict) -> bool:
    for r in ledger.get("runs", []):
        m = CONTEXT.match(r.get("context", ""))
        if m and m.group("id") == spec_id:
            return True
    return False


def context_for(spec: dict, n: int) -> str:
    return (f"idea:{spec['id']} [spec {spec_hash(spec)}] {spec['name']}: {n} combination{'s' if n != 1 else ''} of {spec['strategy']} on {spec['universe']} "
            f"(research/try_idea.py), all counted before any result was shown")


def plan(spec: dict) -> dict:
    """What running the idea would count and the bar that would then apply. Runs nothing."""
    n = len(expand_grid(spec["grid"]))
    before = harness.cumulative_hypotheses()
    return {"combinations": n, "ledger_before": before, "ledger_after": before + n, "bonferroni_bar_after": harness.DEFAULT_ALPHA / (before + n)}


# --- running ------------------------------------------------------------------------------------------------------------------------------

def make_runner(spec: dict):
    """A function params -> (in-sample Sharpe, in-sample days, out-of-sample Sharpe, out-of-sample days), on the real data. The universe is loaded once."""
    import pandas as pd
    import config
    from universe import load_universe, run_strategy_on_universe
    module = __import__(spec["strategy"])
    symbols = getattr(config, UNIVERSES[spec["universe"]])
    data, _ = load_universe(symbols, config.START_DATE, config.END_DATE, verbose=False)
    oos_start = (pd.Timestamp(config.IN_SAMPLE_END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    def run(params: dict) -> tuple:
        a = run_strategy_on_universe(data, module, params, config.START_DATE, config.IN_SAMPLE_END_DATE, verbose=False)
        b = run_strategy_on_universe(data, module, params, oos_start, config.END_DATE, verbose=False)
        return (a["aggregate_metrics"]["sharpe_ratio"], len(a["combined_equity_curve"]), b["aggregate_metrics"]["sharpe_ratio"], len(b["combined_equity_curve"]))

    return run


def try_idea(path: str, runner=None, allow_large: bool = False, results_dir: str = RESULTS_DIR, cwd: str = PROJECT_ROOT) -> dict:
    """
    Run an idea file through the whole pipeline. Raises ValueError, before anything is run or counted, if the file is invalid, not committed, already run, or too large.
    Every combination is run first and nothing is shown; then ALL of them are counted in the ledger in one step; only then is the result written and returned.
    """
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    problems = validate_spec(spec)
    if problems:
        raise ValueError("the idea file is not valid: " + "; ".join(problems))
    combos = expand_grid(spec["grid"])
    if len(combos) > MAX_COMBINATIONS and not allow_large:
        raise ValueError(f"{len(combos)} combinations is more than {MAX_COMBINATIONS}: a grid this big mostly finds luck. Cut it down, or pass --allow-large and accept the count.")
    commit, reason = check_frozen(path, cwd)
    if commit is None:
        raise ValueError(reason)
    if already_tried(spec["id"], harness._load_ledger()):
        raise ValueError(f"idea '{spec['id']}' has already been run and counted. A changed idea is a new idea: give it a new id and a new file.")
    out_path = os.path.join(results_dir, f"{spec['id']}_result.json")
    if os.path.exists(out_path):
        raise ValueError(f"{out_path} already exists; it is never overwritten")

    runner = runner or make_runner(spec)
    results = []
    for params in combos:                                                    # all of it runs; nothing has been printed and nothing is counted yet
        i_sh, i_n, o_sh, o_n = runner(params)
        label = ", ".join(f"{k} {v}" for k, v in params.items())
        results.append(harness.evaluate_strategy(f"{spec['name']} ({label})", spec["rationale"], i_sh, i_n, o_sh, o_n))
    run_output = harness.run_harness(results, context_for(spec, len(combos)))      # every combination counted at once, then judged at the new total

    record = {"id": spec["id"], "spec": spec, "spec_hash": spec_hash(spec), "spec_commit": commit, "combinations": len(combos), "ledger_before": run_output["cumulative_hypotheses_before_run"],
              "ledger_after": run_output["cumulative_hypotheses_all_time"], "bonferroni_alpha": run_output["bonferroni_alpha"],
              "results": [{"params": p, "name": r.name, "status": str(r.status), "in_sample_sharpe": r.in_sample_sharpe, "out_of_sample_sharpe": r.out_of_sample_sharpe,
                           "in_sample_p": getattr(r, "in_sample_p_value", None), "out_of_sample_p": getattr(r, "out_of_sample_p_value", None)} for p, r in zip(combos, results)]}
    os.makedirs(results_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1, default=float)
    return {"record": record, "run_output": run_output, "result_path": out_path}


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or not ({"--plan", "--run"} & set(argv)):
        print(__doc__)
        return 2
    path = args[0]
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
        problems = validate_spec(spec)
        if problems:
            print("[idea] not valid: " + "; ".join(problems))
            return 1
        p = plan(spec)
        print(f"[idea] '{spec['id']}': {p['combinations']} combination(s) would be counted: the ledger goes {p['ledger_before']} -> {p['ledger_after']}, and a result then has to beat "
              f"p < {p['bonferroni_bar_after']:.6f}.")
        if "--plan" in argv:
            print("[idea] --plan only: nothing was run and nothing was counted.")
            return 0
        done = try_idea(path, allow_large="--allow-large" in argv)
    except ValueError as e:
        print(f"[idea] refused: {e}")
        return 1
    harness.print_harness_report(done["run_output"])
    print(f"\n[idea] counted {done['record']['combinations']} hypotheses (ledger now {done['record']['ledger_after']}); result saved to {done['result_path']}")
    print("[idea] commit the ledger and that result file: the record only helps if it is kept.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
