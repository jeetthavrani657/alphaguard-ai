# NSE Backtesting System

A backtesting system for NSE (India) equities research, daily timeframe.
**Research only — no live order placement, no broker integration, ever.**

It exists to answer one kind of question honestly: "if I had traded this
rule on these stocks over this period, after realistic costs, would it
have beaten just holding the stocks?" The whole design — the look-ahead
lag, the cost model, the data-quality gate, the multi-symbol validation,
and (since Stage 6) the research harness — is built around not letting
that answer come out wrong by accident, and around catching it quickly
when it does anyway.

See [FINDINGS.md](FINDINGS.md) for the complete research record: six
strategies, three universes, 204 tracked hypotheses, no validated edge —
and four of this project's own apparent positives that turned out to be
bugs in its measurement code, documented in detail because that's as
important a result as the trading conclusion itself.

## What it does

1. Downloads, caches, and validates NSE daily OHLCV data, gated against
   known price discontinuities (`data/`)
2. Turns a price series into a long/cash signal via a strategy rule
   (`strategies/`)
3. Turns that signal into trades, a cost-adjusted trade log, and an
   equity curve, with a hard look-ahead-prevention guarantee (`engine/`)
4. Computes performance metrics and compares against buy-and-hold,
   single-symbol or pooled across a universe of many symbols
   (`engine/`, `reports/`)
5. Runs any strategy result through a research harness that tracks the
   cumulative multiple-testing burden, requires a genuine in-sample AND
   out-of-sample confirmation before calling anything "validated," and
   structurally refuses to rank by raw in-sample return (`research/`)

## Architecture

```
data/          Load, cache, and validate price data. Nothing above this
                layer touches yfinance directly.
strategies/    Pure functions: price data in, a position signal out.
                No knowledge of money, costs, or execution.
engine/        Turns a signal into trades: enforces the look-ahead lag,
                restricts execution to a requested date window, applies
                costs, sizes positions, computes metrics, aggregates
                across symbols, sweeps parameters.
research/      Cross-strategy research tooling: pairs cointegration
                screening, liquidity-based cost modeling, and the
                validation harness (multiple-testing correction,
                in-sample/out-of-sample confirmation, the hypothesis
                ledger). Sits ABOVE engine/ -- everything here calls
                engine/universe.py, nothing in engine/ knows research/
                exists.
reports/       Renders results (equity curves, drawdown, heatmaps) to PNG.
tests/         pytest suite -- see "Test coverage" below for exactly
                what is and isn't covered.
config.py      Every tunable value lives here. Nothing is hardcoded
                inside a module.
run_*.py       Entry-point scripts that wire the layers together for a
                specific task (single backtest, multi-symbol validation,
                parameter sweep, pairs research).
```

### Why the boundaries are where they are

**`data/` is the only layer that talks to Yahoo Finance**, and it does
three things no other layer is allowed to skip:

- **Caches** every symbol to a local CSV (`data/cache/`) so re-running
  anything doesn't re-download, and so a flaky network call doesn't
  silently produce a shorter series than last time.
- **Validates** every series (`data/validator.py`) for the specific
  failure modes real NSE data actually has: missing trading days,
  duplicate rows, impossible OHLC values (with an explicit floating-
  point tolerance — see `data/known_issues.md`), single-day moves too
  large to be an ordinary split/dividend, zero-volume days, and long
  flat stretches.
- **Gates** the engine (`assert_backtest_safe()`) against known price
  discontinuities that aren't real trading history — a demerger, a bad
  data print — classified GENUINE / ARTIFACT / UNREVIEWED in
  `data/discontinuity_registry.py` (full review log in
  `data/known_issues.md`). UNREVIEWED blocks by default, a hard
  `RuntimeError`; nothing silently overrides it — `override=True` is
  explicit, every time, at the call site.

**`strategies/` only ever sees price data and returns a signal.** No
strategy function knows what capital is, what a trade costs, or when an
order actually fills — execution realism is enforced in exactly one
place (`engine/`) instead of being re-implemented per strategy.

**`engine/` is where a signal becomes money, and where the things that
most commonly make a backtest lie are enforced structurally:**

- **Look-ahead**: `position = signal.shift(1)`, one line, with an
  independent runtime assertion that re-derives the same invariant a
  different way and fails loudly if it's ever violated
  (`tests/test_backtest_lookahead.py`).
- **Date-window integrity**: `run_backtest(df, signal, report, start,
  end, ...)` restricts the actual trading loop, equity curve, and trade
  log to `[start, end]` — every call is an independent, freshly-
  capitalized deployment starting flat, though the signal itself still
  uses full history so indicator warm-up and an already-established
  trend are correctly respected on day one. This was NOT always true —
  see `engine/backtest.py`'s docstring and `FINDINGS.md` Section 6 for a
  real bug this project shipped and found the hard way.
- **Costs**: brokerage, STT, exchange charges, SEBI fees, GST, stamp
  duty, and slippage, at rates verified against currently-published
  broker rates (`engine/costs.py`) — and, for `research/`'s Midcap/
  Smallcap work, re-estimated per-symbol from liquidity rather than
  inherited flat (`research/liquidity_costs.py`).

`engine/universe.py` and `engine/sweep.py` exist because one symbol's
trade count is not a sample — they run `run_backtest()` across many
symbols and pool the results.

**`research/` is where cross-strategy rigor lives, deliberately separate
from the single-strategy engine:**

- `research/harness.py` — every strategy result registered here gets:
  a mandatory entry in the persistent hypothesis ledger
  (`research/hypothesis_ledger.json`, tracked across sessions, never
  reset); mandatory Bonferroni + Benjamini-Hochberg correction against
  the CUMULATIVE hypothesis count; a mandatory non-trivial economic
  rationale (a missing one is flagged PURE DATA MINING in the report,
  not silently accepted); and a status — `UNVALIDATED` /
  `VALIDATED_FAILED` / `OOS_ONLY_SIGNIFICANT` / `VALIDATED_CONFIRMED` —
  where `VALIDATED_CONFIRMED` requires BOTH in-sample and out-of-sample
  to independently clear corrected significance, not out-of-sample
  alone (see `FINDINGS.md` Section 6, Bug 2, for why that distinction
  exists and what it caught). `get_best_strategy()` refuses to fall back
  to ranking by raw in-sample number if nothing genuinely qualifies.
- `research/cointegration.py` — Engle-Granger pairs screening for the
  cointegration research question (`METHODOLOGY.md`), independent of
  `engine/backtest.py` entirely (no execution layer by design).
- `research/liquidity_costs.py` — square-root market-impact slippage
  model, calibrated so a Nifty-50-liquid stock reproduces the flat
  0.05% rate exactly.

## Setup

```bash
pip install -r requirements.txt
```

Pinned versions (verified against this environment, 2026-09-06):

```
pandas==3.0.5
numpy==2.5.2
yfinance==1.6.0
matplotlib==3.11.1
pytest==9.1.1
statsmodels==0.15.0
scipy==1.18.1
streamlit==1.64.0
```

If you're tempted to add a dependency (a TA-lib, a market calendar
library), check `config.py`'s tech-stack comment and `CLAUDE.md` first —
several were deliberately avoided in favor of a few extra lines of plain
pandas.

## Web app

```bash
python -m streamlit run app.py
```

Opens in your browser (default http://localhost:8501). Five pages:

- **Run a backtest** — pick an NSE symbol, a strategy (MA crossover or RSI
  reversion), its parameters, a date range and starting capital. Shows the
  strategy next to buy-and-hold: metrics, equity curve, trade log, and the
  data-quality notes for that symbol. It calls the same `data/`,
  `strategies/`, `engine/` code as the `run_*.py` scripts — there is no
  separate logic in `app.py`. If the discontinuity gate blocks a symbol
  (for example ADANIENT over the full period), the app shows the reason
  and does not offer an override. It also warns when a result rests on
  fewer than 30 trades or on a strategy that is mostly out of the market.
- **Nifty 50 universe** — MA crossover or RSI reversion run on every Nifty 50
  stock separately and pooled (the test behind `FINDINGS.md` Sections 3a
  and 3c), over the in-sample, out-of-sample, full or a custom window.
  Shows pooled strategy vs buy-and-hold on the same stocks, the zero-skill
  Sharpe check (`FINDINGS.md` Section 4), an equity curve, a stock-by-stock
  table, and which stocks were excluded and why. Defaults are the registered
  parameters; changing them shows a warning, because each different setting
  tried is another hypothesis this page does not add to the ledger.
- **Momentum (Nifty 50)** — the pre-registered cross-sectional momentum
  strategy over the in-sample, out-of-sample, full or a custom window:
  momentum vs buy-and-hold, turnover and trading costs, an equity curve,
  end-of-window holdings, and an optional zero-skill benchmark (random
  stock selection, with a progress bar). The parameters are shown but
  deliberately not editable — they were registered before any result
  existed, and sliders would turn one hypothesis into a parameter search.
- **Forward test** — a paper-trade log of one dip-buying rule frozen before
  any of its data existed (`FORWARD_TEST.md`). Shows win rate counting open
  positions marked to market (an underwater open position is a loss),
  expectancy, results against buy-and-hold, and the signals at the last
  close. Refuses to conclude before 100 counted positions. Same report as
  `python research/forward_log.py`, which also appends a dated row to
  `reports/output/forward_snapshots.csv`. It logs what the rule would have
  done; it places no orders.
  A Windows scheduled task (`NSE-ForwardTest-Daily`, Mon-Fri 7 PM IST) runs
  it automatically via `run_forward_log.bat`; see `FORWARD_TEST.md`.
- **Research record** — the hypothesis ledger (running count of everything
  tested) and the findings documents.

Use the same Python that has the project's packages installed (the one
`pip install -r requirements.txt` went into). The app is research-only:
no broker connection, no order placement.

### Web app v2: the research terminal (FastAPI + React)

A dark, dense research terminal that replaces the Streamlit app: a stock
screener with a sector heatmap, a per-stock cockpit (candles, SMA/RSI, the
strategies' own trades), every strategy with its validation status, and the
research record (hypothesis ledger, forward test, data quality). The
Streamlit app above still works and is untouched; retire it when you are
satisfied with this one.

It is **read-only by construction**: it never runs a strategy and never
places an order. Strategies run from the terminal, where the harness
discipline applies; the app only displays what they already produced.

#### Quick start

```bash
# 1. Once, or whenever results are out of date: run the library and write the results (about 20 min).
python -m webapp.backend.snapshot
#    one strategy while experimenting (about 1 minute):
python -m webapp.backend.snapshot --only ma_crossover_nifty50

# 2. Start the app. Builds the UI the first time (needs Node.js 22+ and internet, once).
python run_webapp.py --open          # -> http://127.0.0.1:8000     (Ctrl+C to stop)
```

Or double-click `run_webapp.bat`. Always use the Python that has the
project's packages installed (see "Setup"); the `.bat` hard-codes that path
the same way `run_forward_log.bat` does.

| Command | What it does |
|---|---|
| `python run_webapp.py` | Serves the UI **and** the API from one process on port 8000. Rebuilds the UI first if its source changed. |
| `python run_webapp.py --dev` | Two processes with hot reload for editing the UI: API on 8000, Vite dev server on 5173. |
| `python run_webapp.py --rebuild` | Force a fresh UI build. |
| `python run_webapp.py --port 8010` | Use another port (default mode). |
| `python -m webapp.backend.snapshot --list` | Show the strategy ids the snapshot knows. |
| `python webapp/smoke_check.py` | Smoke test: starts the app on a spare port and sweeps every route, every strategy and window, and all 441 stocks against the real results (about 1 minute). Run it after regenerating results or changing the backend. |
| `python -m webapp.backend.snapshot --manifest-only` | Rewrite `manifest.json` from the strategy files already on disk (instant). Its provenance is always that of the OLDEST strategy result. |
| `python -m webapp.backend.snapshot --prices-only` | Run no strategies: rebuild price files, screener, data quality and the manifest (about 5 min). Use it after a data refresh, or to finish a snapshot that stopped in its last step. |

**After refreshing prices:** `python data/refresh_cache.py` re-downloads every symbol in one pass (about 7 minutes). Do it, not an ad-hoc append, whenever you want newer data: Yahoo re-scales adjusted history after every dividend, so a cache patched from downloads made on different days carries fake one-day moves at the seams. Then regenerate the results below.

**When to regenerate results (step 1):** after any change to the data, the
engine, a strategy or its parameters; after new hypotheses are registered in
the ledger. The status strip at the top of every page tells you when you
need to: it turns to a **STALE** warning when the ledger has grown since the
results were generated, and it always shows the commit the results came from
(with "+uncommitted changes" if the code was dirty).

#### How it fits together

```
 python -m webapp.backend.snapshot          the ONLY thing that runs strategies (terminal, by you)
   imports data/ engine/ strategies/ research/ as a library
   writes webapp/snapshots/*.json           provenance-stamped, validated against schemas.py
            |
            v
 FastAPI  (webapp/backend/main.py)          read-only: every route is GET, imports no calculation code
            |  JSON, validated again by the same schemas
            v
 React + TypeScript  (webapp/frontend/)     draws what it is given; computes nothing
```

A number therefore exists in exactly one place: where the library computed
it. The brief's five rules, and what enforces each:

| Rule | Enforced by |
|---|---|
| Tested modules untouched (all tests pass) | Only three small, behaviour-preserving additions were made, each proven identical on real data first: `harness.classify_results`, `ma_crossover.moving_average` / `rsi_reversion.rsi`, and four series functions in `engine/metrics.py`. |
| No duplicated calculation | A test imports the API in a fresh interpreter and fails if any engine/strategy/research/pandas module loads; a source-level test fails on arithmetic in the UI; the snapshot refuses to write a series that disagrees with its headline figure. |
| Read-only | A test fails if any route is not GET; the UI is checked for non-GET requests. Starting the app never triggers a backtest. |
| Streamlit keeps working | `app.py` is untouched; both can run at once. |
| No bare Sharpe | `RiskAdjustedRatio` has a required `status`; the UI can only render it through `<Ratio>`; a test fails if any other file reads a ratio's value. |

#### What each page shows

- **Screener** (`/`): all 441 stocks with buy-and-hold returns per window,
  filters, and a sector heatmap. It deliberately shows no Sharpe: ranking
  441 stocks by Sharpe is a multiple comparison.
- **Stock cockpit** (`/stock/RELIANCE`): candles with SMA 50/200 and the
  strategies' trade markers over volume and RSI 14; each strategy's result
  on this stock; the stock's data-quality record and reviewed discontinuities.
- **Strategies** (`/strategies`, `/strategies/ID`): every strategy with its
  status and "as of N hypotheses"; both windows against buy-and-hold; growth,
  drawdown and exposure charts; the paginated trade log.
- **Research record** (`/research`): the hypothesis ledger, the forward test,
  and the stocks with unresolved data issues.

#### Reading it correctly

- **A status is only true "as of" a hypothesis count.** The Bonferroni bar
  is 0.05 divided by that count, so it only gets harder as more is tried.
  Every Sharpe is shown with its status chip and "as of N".
- **A stock's Sharpe is a slice, not a verdict.** Strategies are tested as
  pooled hypotheses across a universe; one stock's Sharpe carries the status
  `SLICE_OF_POOLED_HYPOTHESIS` and names its parent. Judge a strategy by
  its pooled status, never by its best stock.
- **Equity is shown as "growth of 100".** A portfolio strategy trades one
  account while the benchmark is the sum of one account per stock, so a
  rupee plot of the two is off by the stock count. Each curve is divided by
  its own starting capital; its last value minus 100 is the table's total
  return.
- **Exposure has two definitions** (the chart's caption says which): the
  share of stocks' books that are long on each date, or, for momentum, the
  engine's "non-cash days" rule (0% until the first rebalance, 100% after),
  which does not measure cash held once invested.
- **Low-exposure strategies show very negative Sharpe by construction**: idle
  cash earns nothing in the engine's equity curve while Sharpe subtracts the
  risk-free rate. Each such strategy carries a note.
- **Prices are split/dividend-adjusted** and end at the research window's
  last close. There is no live feed; the app never pretends otherwise.
- **The heatmap covers Nifty 50 only** (the only universe with a sector map)
  and shows equal tiles, not market-cap sizes.
- **Out-of-sample 2020 to 2025 was a broad bull run**, so nearly every stock
  and every long strategy looks good there. Compare against buy-and-hold.

#### Changing things

- **Colours and look:** the `--variables` at the top of
  `webapp/frontend/src/styles.css`; the charts read the same ones.
- **After editing `webapp/backend/schemas.py`** (an API shape), regenerate
  the frontend's types so the compiler points at anything that no longer fits:
  ```bash
  python webapp/backend/export_openapi.py webapp/frontend/openapi.json
  cd webapp/frontend && npm run gen:types
  ```
- **Adding a strategy to the app:** register and test it through the harness
  first (that is what creates its hypothesis), then add an entry to `RECIPES`
  in `webapp/backend/snapshot.py` and regenerate.
- **API reference:** interactive docs at `http://127.0.0.1:8000/docs`.
  Routes: `/api/strategies`, `/api/strategies/{id}` (+ `/equity`, `/trades`),
  `/api/screener`, `/api/symbols/{symbol}` (+ `/prices`), `/api/data-quality`,
  `/api/ledger`, `/api/forward-test`, `/api/health`.
- **Charts** use TradingView's open-source `lightweight-charts`. The wheel
  scrolls the page, not the chart; drag to pan and use the range buttons.

#### Troubleshooting

| You see | Cause and fix |
|---|---|
| Pages say "No snapshot found" (HTTP 503) | No results yet: `python -m webapp.backend.snapshot`. |
| Status strip shows **STALE** | The ledger grew after the results were made: regenerate. |
| "Port 8000 is already in use" | An earlier run is still going, or another program: close it, or `--port 8010`. |
| `Missing package: fastapi` | Wrong Python. Use the one with the project's packages (`pip install -r requirements.txt`). |
| "npm was not found" | Install Node.js 22+ from nodejs.org (only needed to build the UI). |
| UI looks out of date | `python run_webapp.py --rebuild`. |
| A chart pane says the snapshot predates drawdown/exposure | Regenerate the snapshot. |
| Snapshot stops with "drawdown series minimum ... does not match" | Intentional integrity check: a charted series disagrees with its headline number. This means a bug, not bad luck: do not bypass it. |

Files: `run_webapp.py` / `.bat` (launcher), `webapp/backend/` (`snapshot.py`,
`main.py`, `schemas.py`, `store.py`, `export_openapi.py`),
`webapp/frontend/` (`src/pages`, `src/components`, `src/styles.css`),
`webapp/snapshots/` (generated, git-ignored, about 70 MB). Tests:
`tests/test_webapp_*.py`.

## How to run something

**Single symbol, one strategy, full report** (metrics, benchmarks,
charts, trade log CSV):

```bash
python run_backtest.py
```

Reads `config.SYMBOLS[0]`, `config.STRATEGY`, `config.START_DATE`/`END_DATE`.

**Multi-symbol validation** (per-symbol table, pooled aggregate, stress
cases, in-sample/out-of-sample split):

```bash
python run_validation.py
```

Reads `config.UNIVERSE` and `config.STRESS_SYMBOLS`.

**Parameter sweep** (grid search across `config.MA_SWEEP_FAST_VALUES` x
`config.MA_SWEEP_SLOW_VALUES`, pooled per cell):

```bash
python run_sweep.py
```

Slow — roughly 20 minutes for a 10x11 grid across ~48 symbols, because
`engine/backtest.py`'s day-by-day loop is deliberately written for
readability and hand-verification, not raw speed (see "Technical debt"
below). Run it in the background.

**Pairs cointegration research** (screening only, no execution):

```bash
python run_pairs_research.py
```

Reads `config.SECTOR_MAP`, `config.PAIRS_*`. Frozen methodology in
`METHODOLOGY.md` — do not tune any threshold here after seeing results.

**Midcap/Smallcap universe validation and control-comparison strategy
run** (see `MIDCAP_SMALLCAP_FINDINGS.md`):

```bash
python research/run_midcap_smallcap_validation.py
python research/run_midcap_smallcap_strategy.py
```

Reads `config.MIDCAP150_UNIVERSE` / `config.SMALLCAP250_UNIVERSE`. The
second script registers its result through `research/harness.py`
automatically — it will append to the hypothesis ledger every time you
run it. Don't re-run it casually; see "The mandatory workflow" below.

**All scripts load `config.py` for everything** — dates, symbols,
strategy parameters, costs, capital, risk-free rate. Change behavior
there, not by editing a script.

## How to test a new strategy through the harness

1. **Write the strategy.** Create `strategies/your_strategy.py` with one
   function:

   ```python
   def generate_signals(df: pd.DataFrame, **params) -> pd.Series:
       ...
       validate_signals(signal, df)  # from strategies/base.py
       return signal
   ```

   `df` has `open, high, low, close, volume` columns. Return a float
   Series, same index as `df`: `NaN` during warm-up, `1.0` for long,
   `0.0` for cash. No position sizing, no cost awareness, no execution
   timing — `strategies/ma_crossover.py` and `strategies/rsi_reversion.py`
   are the reference examples.

2. **Add its default parameters to `config.py`**, following the existing
   `MA_CROSSOVER_PARAMS` / `RSI_REVERSION_PARAMS` pattern.

3. **Write down the economic rationale BEFORE running anything at
   scale** — one or two sentences on why this rule should work, not
   what it does (`strategies/*.py`'s params already say what it does).
   `research/harness.py` will flag a missing or trivial rationale as
   PURE DATA MINING in the report regardless of performance; writing it
   first, not after seeing a good number, is what actually matters.

4. **Run it through `engine/universe.py`, twice** — once for
   `config.START_DATE` to `config.IN_SAMPLE_END_DATE`, once for the day
   after through `config.END_DATE`. Use the SAME `universe_data` (loaded
   once, full period) for both calls — `run_strategy_on_universe()`
   itself now restricts each call to its requested window (see
   `engine/backtest.py`'s docstring); you do not need to reload or
   re-slice the data yourself.

5. **Register both results through `research/harness.py`**:

   ```python
   from harness import evaluate_strategy, run_harness, print_harness_report

   result = evaluate_strategy(
       name="...", rationale="...",
       in_sample_sharpe=is_result["aggregate_metrics"]["sharpe_ratio"],
       in_sample_n_obs=len(is_result["combined_equity_curve"]),
       out_of_sample_sharpe=oos_result["aggregate_metrics"]["sharpe_ratio"],
       out_of_sample_n_obs=len(oos_result["combined_equity_curve"]),
   )
   run_output = run_harness([result], context="a short description of this run")
   print_harness_report(run_output)
   ```

   This appends to `research/hypothesis_ledger.json` — every call is a
   permanent addition to the cumulative multiple-testing count. Don't
   call it speculatively or in a loop while iterating; call it once,
   when you actually mean to record a result. If you re-run to fix a
   genuine bug in the same hypothesis (not to re-try after seeing a bad
   number), remove the tainted entry from the ledger and replace it —
   don't double-count. See `FINDINGS.md` Section 6 for the two times
   this project had to do exactly that.

6. **Read the status, not just the Sharpe.** `VALIDATED_CONFIRMED` means
   in-sample AND out-of-sample both independently cleared corrected
   significance — an actual replication. `OOS_ONLY_SIGNIFICANT` means
   out-of-sample alone cleared the bar with nothing behind it in-sample
   — treat this as MORE suspicious than a flat failure, not less (see
   `FINDINGS.md` Section 6, Bug 2). Neither status by itself means
   "beats buy-and-hold" — that's a separate comparison you still have to
   make explicitly (Section 4's zero-skill benchmark is the right way to
   check whether an apparent Sharpe edge is real or just lower exposure).

7. **To sweep its parameters**, you currently need a new function
   alongside `engine/sweep.py`'s `run_ma_crossover_sweep` (strategy-
   specific by design right now — see "Technical debt").

You do not need to touch `data/`, `engine/backtest.py`,
`engine/costs.py`, or `engine/metrics.py` to add a strategy. If you find
yourself needing to, something's wrong with the boundary.

## The mandatory workflow (standing rules, not suggestions)

These exist because every one of them was learned from a real mistake in
this project's own history — see `FINDINGS.md` Section 6 for the two
that actually produced a false result.

1. **Pre-register the rationale and any thresholds before seeing a
   result.** `METHODOLOGY.md` is the model to follow for anything with
   enough free parameters to overfit (a pairs strategy, a multi-
   parameter sweep) — freeze the rule in writing first.
2. **Never report a raw, uncorrected Sharpe or CAGR as "significant."**
   Always run it through `research/harness.py` and quote the corrected
   status, not the raw p-value.
3. **Check exposure, always.** A partially-invested strategy's Sharpe is
   not comparable to 100%-invested buy-and-hold on its face — compute
   the zero-skill benchmark (`FINDINGS.md` Section 4: scale
   buy-and-hold's own returns by the strategy's realized exposure
   fraction, blended with the risk-free rate) and compare against THAT,
   not raw buy-and-hold.
4. **In-sample and out-of-sample must be computed on genuinely different
   date windows, and you should be suspicious if they look too similar.**
   If two supposedly-different periods produce near-identical numbers,
   don't write it up as "stable" — check whether they're actually
   different at all (`tests/test_backtest_date_window.py` is the
   regression test that exists because this project didn't check once).
5. **`VALIDATED_CONFIRMED` requires both halves to independently clear
   correction.** An out-of-sample-only significant result
   (`OOS_ONLY_SIGNIFICANT`) is a regime-dependent red flag, not a
   near-miss — don't round it up to "basically confirmed."
6. **Watch the cumulative hypothesis count.** Check
   `research/hypothesis_ledger.json`'s `cumulative_hypotheses` before
   and after every run. If a result only survives correction against a
   smaller, wrong denominator, it doesn't survive.
7. **A result that looks unusually clean is a reason for MORE scrutiny,
   not less.** Both of this project's false positives looked good, not
   broken, right up until someone asked why.

## Project layout

```
config.py                        all tunables: symbols, dates, universes, costs, params
requirements.txt                 pinned dependencies
FINDINGS.md                      the complete, current research record (start here)
FORWARD_TEST.md                  pre-registered forward paper-trade test (frozen 2026-10-16)
MIDCAP_SMALLCAP_FINDINGS.md      full construction detail for the Midcap/Smallcap universes
METHODOLOGY.md                   pairs cointegration methodology, frozen before any result
CLAUDE.md                        project working rules for whoever (human or AI) works on this next
run_webapp.py / run_webapp.bat   start the research terminal (UI + API); see "Web app v2"

webapp/                          the research terminal (read-only; never runs a strategy)
  backend/snapshot.py            the ONLY place results are computed for the app: runs the library, writes JSON
  backend/main.py, schemas.py    read-only FastAPI + the contract every response is validated against
  frontend/                      React + TypeScript UI (src/pages, src/components, src/styles.css)
  snapshots/                     generated JSON (git-ignored)

data/
  loader.py                      download + cache + clean NSE price data
  refresh_cache.py               re-download the whole cache on one adjustment basis (see known_issues.md)
  validator.py                   data-quality checks + the discontinuity gate
  discontinuity_registry.py      GENUINE/ARTIFACT/UNREVIEWED review log (machine-readable)
  known_issues.md                same log, human-readable, with full evidence
  cache/                         per-symbol CSV cache (gitignore-worthy, not committed logic)

strategies/
  base.py                        the shared signal contract + validate_signals()
  ma_crossover.py
  rsi_reversion.py
  buy_and_hold.py                trivial always-long "strategy", used as the benchmark
  cross_sectional_momentum.py    ranks stocks against each other (needs engine/portfolio_backtest.py)
  dip_target.py                  RSI dip entry with take-profit / stop / time limit / trend filter

engine/
  backtest.py                    look-ahead lag, date-window restriction, execution, trade log
  costs.py                       India equity-delivery cost model
  metrics.py                     CAGR, Sharpe, Sortino, drawdown, trade-contribution analysis
  universe.py                    run + aggregate a strategy across many symbols
  sweep.py                       parameter grid search across the universe

research/
  harness.py                     multiple-testing correction, IS/OOS validation status, the hypothesis ledger
  hypothesis_ledger.json         persistent, cumulative record of every hypothesis ever tested
  cointegration.py               Engle-Granger pairs screening (no execution layer)
  liquidity_costs.py             per-symbol liquidity-based slippage model
  run_ma_vs_rsi_harness_demo.py  MA crossover vs RSI reversion, first harness-governed run
  run_midcap_smallcap_validation.py   Stage-1 data validation for the Midcap/Smallcap universes
  run_midcap_smallcap_strategy.py     the Midcap/Smallcap control-comparison run
  run_survivorship_and_exposure_check.py   survivorship magnitude + zero-skill exposure test
  run_dip_target_strategy.py     dip + take-profit, with vs without a stop (win rate vs open losses)
  run_dip_uptrend_strategy.py    dip in an uptrend, +4% / -12% / 60d
  search_dip_win_rate.py         bounded 36-variant search for a 90% win rate, with a 2026 holdout
  forward_test_2026.py           one-off forward test of two fixed configs on 2026 data
  forward_log.py                 the forward paper-trade log (FORWARD_TEST.md)

reports/
  plots.py                       equity curve, underwater, monthly heatmap, trade histogram, sweep heatmap
  output/                        generated PNGs and CSVs (regenerated by the run_*.py scripts)

tests/                           see "Test coverage" below
  conftest.py                    sys.path setup shared by every test

run_backtest.py                  single-symbol entry point
run_validation.py                multi-symbol + in/out-of-sample entry point
run_sweep.py                     parameter sweep entry point
run_pairs_research.py            pairs cointegration entry point
app.py                           web app (Streamlit) front-end
```

## Test coverage

184 tests, all passing (`python -m pytest tests/ -q`): 89 for the research
code, 13 for the loader's end-date / adjustment-basis behaviour in
`tests/test_loader_end_date.py`, 6 for the chart series added to
`test_metrics.py`, and 76 for the web app: the API contract and static serving in `tests/test_webapp_api.py` (62),
the indicator exports, snapshot price files and manifest provenance in
`tests/test_webapp_snapshot.py` (8), and source-level rules for the frontend
in `tests/test_webapp_frontend_rules.py` (6). `webapp/smoke_check.py` is the
complementary end-to-end check on the real results (not part of pytest). This is a
deliberately targeted suite, not full coverage — the same honesty
applies now as when it was first written: know what's covered, know
what isn't, don't assume either.

**Well covered, with hand-computed ground truth:**
- `engine/metrics.py` — CAGR, max drawdown (+ duration), Sharpe, Sortino,
  and edge cases (zero volatility, all-negative returns, single data
  point), every expected value derived by hand in the test itself
  (`test_metrics.py`).
- `engine/backtest.py`'s look-ahead lag — both that it's enforced and
  that the guard actually fires when deliberately broken, two different
  ways (`test_backtest_lookahead.py`).
- `engine/backtest.py`'s date-window restriction — that a window is
  genuinely respected, that a pre-existing trend is correctly inherited
  on day one, that two disjoint windows produce different results, and
  that a window with no data raises rather than silently running
  everything (`test_backtest_date_window.py`).
- `data/validator.py`'s discontinuity gate — fails closed on
  UNREVIEWED/ARTIFACT/malformed status, passes GENUINE, respects
  `override=True` (`test_gate.py`).
- `data/validator.py`'s OHLC floating-point tolerance — noise-level
  differences pass, a genuine violation still fails (`test_validator_ohlc_tolerance.py`).
- `engine/costs.py` — the full cost stack and the liquidity-slippage
  override path (`test_costs.py`).
- `engine/universe.py`'s pre-listing aggregation (a late-IPO symbol
  contributes idle cash, not zero, before it lists) and its graceful
  exclusion of a symbol with zero rows in a requested window
  (`test_universe_prelisting.py`).
- `research/harness.py`'s validation status logic — genuine replication,
  the OOS-only gap this project actually hit, in-sample-significant-
  but-failed-OOS, neither significant, no OOS check at all, and that
  `get_best_strategy()` never falls back to an OOS-only result
  (`test_harness.py`).

**Not covered — known, not hidden:**
- **`strategies/ma_crossover.py` and `strategies/rsi_reversion.py`
  themselves** — no test constructs a toy price series and checks that
  `generate_signals()` produces the exact expected crossover/threshold
  dates by hand. Both have been run against years of real data and
  eyeballed, and RSI's Wilder's-smoothing recursion was checked by hand
  against a calculator once (see the module docstring), but neither is
  locked in as a regression test. A silent change to either's logic
  (e.g. an off-by-one in the RSI seed position) would not be caught
  automatically.
- **`strategies/base.py`'s `validate_signals()`** — exercised indirectly
  every time a strategy runs, no dedicated test of its own failure
  modes (wrong length, wrong index, out-of-range values, all-NaN).
- **`engine/metrics.py`'s trade-level statistics** — win rate, profit
  factor, avg win/loss, `trade_contribution_table()`,
  `exclude_largest_trade_analysis()` have no ground-truth test; only
  the equity-curve-level metrics (CAGR, Sharpe, Sortino, drawdown) do.
- **`engine/sweep.py`** — zero tests. It's a thin loop over
  `run_strategy_on_universe()`, which is itself tested, but nothing
  checks the grid-construction logic (e.g. that `fast >= slow` cells are
  correctly skipped) in isolation.
- **`research/cointegration.py`** — zero automated tests. The
  Engle-Granger wrapper and the half-life OU-fit were each checked once
  by hand against synthetic data with a known ground truth (see the
  module's own docstring for the numbers), but neither check is a
  repeatable test in this suite. A regression here would not be caught
  until the next manual re-verification, if one happens.
- **`research/liquidity_costs.py`** — zero automated tests. The
  square-root impact model's numbers were sanity-checked by hand once
  (reference-ADV stock reproduces exactly 0.05%; the floor/cap bind at
  the extremes) but not locked in.
- **`data/loader.py`** — no dedicated test. Its caching and phantom-row-
  removal logic is exercised implicitly by every other test that reads
  real cached data, but there's no test that specifically constructs a
  cache-partial-coverage scenario (the "fetch only the missing head/tail"
  path) and checks it stitches correctly.
- **`reports/plots.py`** — zero tests, and reasonably so: it produces
  images, not values with an independently-checkable right answer. The
  practical risk here is low (a broken plot is visually obvious, not
  silently wrong) and is knowingly accepted.

**What would silently break right now, if it did:**
- A bug in `ma_crossover.generate_signals()`'s crossover logic (wrong
  comparison direction, an off-by-one in the rolling window) would
  produce a plausible-looking but wrong signal, and nothing in this
  suite would catch it — the only guard is the look-ahead lag, which
  checks the LAG is correct, not that the underlying signal is.
- A regression in `research/cointegration.py`'s hedge-ratio direction
  logic (picking the wrong regression side) would silently produce a
  differently-scaled spread — the half-life and Z-score numbers would
  still compute, just be wrong, with no test to flag it.
- A change to `engine/sweep.py`'s grid-skip condition (e.g. `fast <=
  slow` instead of `fast < slow`) would silently include or exclude the
  wrong cells from a multi-hour sweep, discovered only by someone
  noticing the output row count doesn't match `MA_SWEEP_FAST_VALUES` x
  `MA_SWEEP_SLOW_VALUES`'s expected combination count by hand.

## Technical debt

- **`engine/backtest.py`'s day-by-day Python loop is slow by design** —
  chosen for hand-verifiability (the look-ahead lag and the date-window
  fix both needed to be traceable line-by-line), not speed. A 10x11
  parameter sweep across ~48 symbols takes ~20 minutes. Vectorizing the
  trade-simulation loop would speed this up substantially but would
  make the next hand-verification pass harder — not attempted, on
  purpose, unless sweep runtime actually becomes a blocker.
- **`engine/sweep.py` is MA-crossover-specific.** Adding a second
  strategy's sweep currently means writing a new, near-duplicate sweep
  function rather than calling one generic interface. Not generalized
  yet because only one strategy has ever needed sweeping.
- **RSI reversion has never been parameter-swept**, unlike MA crossover
  — see "Limitations" in `FINDINGS.md`. Its one tested configuration
  failed clearly, but the same noise-floor rigor applied to MA crossover
  hasn't been applied here.
- **The zero-skill Sharpe benchmark (`FINDINGS.md` Section 4) is
  currently a one-off script** (`research/run_survivorship_and_exposure_check.py`),
  not a reusable function in `research/harness.py`. Given "check exposure,
  always" is now a standing rule (see above), it should probably move
  into the harness itself so it runs automatically alongside every
  registered result, rather than being something a caller has to
  remember to do separately.
- **No point-in-time constituent data exists for any universe** —
  survivorship bias is measured (`FINDINGS.md` Section 5) but not
  corrected for; building a true point-in-time universe would require a
  historical index-membership data source this project doesn't have
  access to.
- **The discontinuity registry has an unreviewed backlog for
  Midcap/Smallcap.** Several bank/NBFC symbols (e.g. INDUSINDBK,
  ICICIPRULI) are correctly excluded from those universes' results
  pending the same GENUINE/ARTIFACT/UNREVIEWED review already done for
  Nifty 50 — not yet done, disclosed rather than silently worked around.
- **`data/validator.py` has a known plausibility gap**, not yet fixed:
  an internally-consistent-but-implausible OHLC row (e.g. `open == high`
  exactly, even when the value is absurd relative to the stock's recent
  range) can pass the OHLC logic check. See `data/known_issues.md`'s
  OPEN ITEMS section for the one confirmed case (ADANIENT.NS
  2015-06-03) and why a fix needs deliberate threshold-tuning rather
  than a reactive patch.
