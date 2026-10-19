"""
webapp/backend/schemas.py

THE CONTRACT. Every shape the API sends, and every shape the snapshot
command writes to disk, is defined here once, as a Pydantic model.

Why this file matters more than it looks:

1. It is the single place that says what the API promises. FastAPI turns
   these models into the interactive docs page (/docs) and the frontend's
   TypeScript types will be generated from the same description, so the
   backend and frontend cannot quietly disagree.

2. Validation runs in BOTH directions. The snapshot command validates
   against these models BEFORE writing a file, and the API validates again
   BEFORE sending a response. A malformed number cannot reach the browser.

3. It makes the project's hardest rule structural. A Sharpe ratio cannot be
   represented in this API as a bare number: the only Sharpe-shaped thing
   that exists is `RiskAdjustedRatio`, and `status` and `as_of_hypotheses`
   are REQUIRED fields on it (no default). A snapshot that tried to emit a
   bare Sharpe would fail validation at write time. This is the lesson of
   FINDINGS.md Section 6 turned into a type.

Nothing in this file calculates anything. Models only describe data.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

# --- vocabulary ------------------------------------------------------------

# The four statuses research/harness.py can assign, plus one for benchmarks.
# A benchmark (buy-and-hold) is a yardstick, not a tested hypothesis, so it
# must NOT be given a validation status -- but it must still never appear as
# a bare number, so it gets this explicit label instead of a missing field.
Status = Literal[
    "UNVALIDATED",
    "VALIDATED_FAILED",
    "OOS_ONLY_SIGNIFICANT",
    "VALIDATED_CONFIRMED",
    "BENCHMARK_NOT_A_HYPOTHESIS",
    # One stock's result inside a pooled strategy test. The hypothesis tested
    # was "this rule works across the universe"; a single stock's Sharpe is a
    # slice of it, not an independent test (looking at 50 slices is 50
    # uncorrected comparisons). It can never stand alone: it must name its
    # parent strategy and the parent's status (enforced below).
    "SLICE_OF_POOLED_HYPOTHESIS",
]
Window = Literal["in_sample", "out_of_sample"]
Kind = Literal["per_symbol", "portfolio"]


# --- the rule that must not be breakable -------------------------------------

class RiskAdjustedRatio(BaseModel):
    """
    A Sharpe or Sortino ratio TOGETHER WITH what it is worth.

    `status` and `as_of_hypotheses` have no defaults on purpose: you cannot
    construct this object without them. A status is only true as of a
    hypothesis count (the Bonferroni bar is 0.05 / total and only tightens
    as the total grows), so the count travels with the status.
    """
    kind: Literal["sharpe", "sortino"]
    value: Optional[float]                     # null when undefined (e.g. zero volatility)
    window: Window
    status: Status
    as_of_hypotheses: int = Field(description="Ledger total the status was computed against.")
    p_value: Optional[float] = Field(None, description="One-sided p-value that true Sharpe > 0. Sharpe only.")
    bonferroni_bar: Optional[float] = Field(None, description="0.05 / as_of_hypotheses.")
    clears_bar: Optional[bool] = Field(None, description="p_value < bonferroni_bar.")
    # Only for status SLICE_OF_POOLED_HYPOTHESIS: which pooled test this is a piece of.
    parent_strategy_id: Optional[str] = None
    parent_status: Optional[Status] = None

    @model_validator(mode="after")
    def _a_slice_must_name_its_parent(self):
        if self.status == "SLICE_OF_POOLED_HYPOTHESIS":
            if not self.parent_strategy_id or self.parent_status is None:
                raise ValueError("a SLICE_OF_POOLED_HYPOTHESIS ratio must carry parent_strategy_id and parent_status")
            if self.parent_status == "SLICE_OF_POOLED_HYPOTHESIS":
                raise ValueError("a slice's parent must be a real hypothesis status")
        return self


class WindowMetrics(BaseModel):
    """Numbers straight from engine/metrics.py's compute_metrics(), one window."""
    sharpe: RiskAdjustedRatio
    sortino: RiskAdjustedRatio
    total_return_pct: Optional[float]
    cagr_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    max_drawdown_duration_days: Optional[float]
    win_rate_pct: Optional[float]
    avg_win_pct: Optional[float]
    avg_loss_pct: Optional[float]
    profit_factor: Optional[float] = Field(description="null when there are no losing trades (undefined, not infinite).")
    total_trades: Optional[int]
    avg_holding_days: Optional[float]
    market_exposure_pct: Optional[float]
    final_equity: Optional[float]
    n_symbols_included: Optional[int]


# --- provenance --------------------------------------------------------------

class Provenance(BaseModel):
    """Where a snapshot came from. Every file carries one."""
    generated_at: str
    git_commit: Optional[str]
    git_dirty: Optional[bool]
    ledger_total_at_snapshot: int
    bonferroni_bar_at_snapshot: float = Field(
        description="As returned by research/harness.py's classify_results() -- never recomputed here.")
    data_through: str
    in_sample_end: str
    risk_free_rate: float
    initial_capital: float


# --- strategies --------------------------------------------------------------

class WindowInfo(BaseModel):
    window: Window
    start: str
    end: str
    n_observations: int = Field(description="Trading days in the combined equity curve (the n behind the p-value).")
    strategy: WindowMetrics
    benchmark: WindowMetrics


class StrategySummary(BaseModel):
    id: str
    name: str
    family: str
    universe: str
    kind: Kind
    status: Status
    as_of_hypotheses: int
    in_sample_sharpe: RiskAdjustedRatio
    out_of_sample_sharpe: RiskAdjustedRatio
    stale: bool = Field(description="True if the ledger has grown since this status was computed.")


class StrategyDetail(BaseModel):
    id: str
    name: str
    family: str
    universe: str
    kind: Kind
    params: dict
    rationale: str
    status: Status
    as_of_hypotheses: int
    stale: bool = False
    notes: list[str] = []
    in_sample: WindowInfo
    out_of_sample: WindowInfo
    provenance: Provenance


class StrategyList(BaseModel):
    ledger_total_now: int
    snapshot_generated_at: str
    strategies: list[StrategySummary]


# --- equity curves -----------------------------------------------------------

class EquityCurve(BaseModel):
    """
    Two parallel arrays instead of a list of {date, value} objects. For ~1,400
    points that is roughly half the JSON (the keys are not repeated per
    point), and charting libraries want exactly this shape.
    """
    dates: list[str]
    values: list[float]


class EquityResponse(BaseModel):
    strategy_id: str
    window: Window
    strategy: EquityCurve
    benchmark: EquityCurve
    # Companion series, each computed by engine/metrics.py at snapshot time (null in snapshots
    # written before Stage C -- regenerate). Drawdown is percent below the running peak (<= 0);
    # exposure is percent of books invested (0-100); all share the equity curve's dates.
    drawdown_strategy_pct: Optional[EquityCurve] = None
    drawdown_benchmark_pct: Optional[EquityCurve] = None
    exposure_strategy_pct: Optional[EquityCurve] = None
    exposure_definition: Optional[str] = None
    # "What 100 became": each curve divided by ITS OWN initial capital (engine/metrics.py growth_of_100).
    # Compare strategy and benchmark with THESE, not the rupee curves: a portfolio strategy trades one
    # book while the benchmark is the sum of one book per stock, so the rupee curves differ in scale.
    growth_strategy: Optional[EquityCurve] = None
    growth_benchmark: Optional[EquityCurve] = None
    note: str = (
        "strategy/benchmark are portfolio value in Rs as the engine computed it. A portfolio strategy is one "
        "account, the benchmark is one account per stock, so do not compare the two rupee curves: use "
        "growth_strategy / growth_benchmark (both start at 100)."
    )


# --- trades ------------------------------------------------------------------

class ClosedTrade(BaseModel):
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    return_pct: float = Field(description="Net of costs.")
    holding_days: int
    total_costs: float


class Execution(BaseModel):
    """One buy or sell leg of a portfolio rebalance (momentum)."""
    date: str
    symbol: str
    side: Literal["buy", "sell"]
    shares: int
    price: float
    costs: float


class Rebalance(BaseModel):
    formation_date: str
    execution_date: str
    n_held: int
    turnover_value: float
    portfolio_value_pre_rebalance: float
    turnover_pct: float


class TradePage(BaseModel):
    strategy_id: str
    window: Window
    kind: Kind
    total: int = Field(description="Total rows available (closed trades, or executions for a portfolio strategy).")
    limit: int
    offset: int
    closed_trades: Optional[list[ClosedTrade]] = None
    executions: Optional[list[Execution]] = None
    rebalances: Optional[list[Rebalance]] = None


# --- what is stored on disk per strategy (not an API response) ---------------

class StoredWindowData(BaseModel):
    equity_strategy: EquityCurve
    equity_benchmark: EquityCurve
    drawdown_strategy_pct: Optional[EquityCurve] = None
    drawdown_benchmark_pct: Optional[EquityCurve] = None
    exposure_strategy_pct: Optional[EquityCurve] = None
    exposure_definition: Optional[str] = None
    growth_strategy: Optional[EquityCurve] = None
    growth_benchmark: Optional[EquityCurve] = None
    closed_trades: list[ClosedTrade] = []
    executions: list[Execution] = []
    rebalances: list[Rebalance] = []


class StrategyFile(BaseModel):
    detail: StrategyDetail
    data: dict[Window, StoredWindowData]


# --- data quality --------------------------------------------------------------

class QualityCheck(BaseModel):
    name: str
    passed: bool
    affected_rows: int


class Discontinuity(BaseModel):
    date: str
    magnitude_pct: float
    status: str = Field(description="GENUINE, ARTIFACT or UNREVIEWED, from data/discontinuity_registry.py.")
    reason: Optional[str] = None


class SymbolQuality(BaseModel):
    symbol: str
    universe: str
    rows: int
    first_date: str
    last_date: str
    usable: bool
    checks: list[QualityCheck]
    discontinuities: list[Discontinuity]


class DataQualityResponse(BaseModel):
    generated_at: str
    n_symbols: int
    n_usable: int
    n_with_unresolved_discontinuity: int
    symbols: list[SymbolQuality]


# --- per-stock views (screener, cockpit) ----------------------------------------------

class ScreenerRow(BaseModel):
    """
    One stock in the screener / heatmap. Returns are the buy-and-hold total
    return over each window as the engine computed it (per_symbol_comparison_table),
    null where the engine did not run the stock (gate block, not yet listed).
    No Sharpe appears here by design: a screener ranks, and a ranking of bare
    Sharpes is exactly the multiple-comparison trap the harness exists for.
    """
    symbol: str
    universe: str
    sector: Optional[str] = Field(None, description="From config.SECTOR_MAP; Nifty 50 only. null = not classified.")
    rows: int
    first_date: str
    last_date: str
    last_close: float = Field(description="Split/dividend-adjusted close on last_date, as stored by the loader.")
    usable: bool
    has_unresolved_discontinuity: bool
    buy_hold_return_in_sample_pct: Optional[float]
    buy_hold_return_out_of_sample_pct: Optional[float]
    buy_hold_max_drawdown_out_of_sample_pct: Optional[float]


class ScreenerResponse(BaseModel):
    generated_at: str
    data_through: str
    in_sample: str
    out_of_sample: str
    rows: list[ScreenerRow]


class PriceSeries(BaseModel):
    """Columnar OHLCV plus the indicator series read from the strategy modules."""
    symbol: str
    adjusted: bool = True
    dates: list[str]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[float]
    indicators: dict[str, list[Optional[float]]] = Field(
        description="Keyed e.g. sma_50, sma_200, rsi_14; same length as dates; null during warm-up.")
    indicator_sources: dict[str, str] = Field(
        description="Which library function produced each series, e.g. strategies/ma_crossover.moving_average.")


class SliceMetrics(BaseModel):
    """One stock's own result for one window of one pooled strategy."""
    sharpe: RiskAdjustedRatio
    total_return_pct: Optional[float]
    cagr_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    win_rate_pct: Optional[float]
    total_trades: Optional[int]
    market_exposure_pct: Optional[float]
    buy_hold_return_pct: Optional[float] = Field(None, description="Same stock, same window, held throughout.")


class SymbolSlices(BaseModel):
    """What is stored on disk per strategy: {window: {SYMBOL: SliceMetrics}}."""
    strategy_id: str
    parent_status: Status
    as_of_hypotheses: int
    windows: dict[Window, dict[str, SliceMetrics]]
    excluded: dict[Window, dict[str, str]] = Field(
        description="{window: {SYMBOL: reason}} for stocks the engine did not run (gate block, no data yet).")


class SymbolStrategyResult(BaseModel):
    strategy_id: str
    strategy_name: str
    kind: Kind
    parent_status: Status
    as_of_hypotheses: int
    in_sample: Optional[SliceMetrics] = None
    out_of_sample: Optional[SliceMetrics] = None
    excluded_in_sample: Optional[str] = None
    excluded_out_of_sample: Optional[str] = None
    note: Optional[str] = None


class SymbolMarker(BaseModel):
    strategy_id: str
    strategy_name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float


class SymbolExecution(BaseModel):
    strategy_id: str
    strategy_name: str
    date: str
    side: Literal["buy", "sell"]
    shares: int
    price: float


class SymbolDetail(BaseModel):
    symbol: str
    universe: str
    sector: Optional[str]
    usable: bool
    first_date: str
    last_date: str
    last_close: float
    quality: Optional[SymbolQuality]
    results: list[SymbolStrategyResult]
    markers: list[SymbolMarker]
    executions: list[SymbolExecution]
    caveat: str = (
        "Per-stock figures are slices of pooled tests, not independent hypotheses. "
        "Judge a strategy by its pooled status, not by its best stock."
    )


# --- ledger and forward test ----------------------------------------------------

class LedgerRun(BaseModel):
    run_id: str
    timestamp: str
    context: str
    n_hypotheses_this_run: int
    cumulative_hypotheses_before_run: int
    cumulative_hypotheses_after_run: int


class LedgerResponse(BaseModel):
    cumulative_hypotheses: int
    bonferroni_bar_at_snapshot: Optional[float] = Field(
        description="The bar the harness computed when the snapshot was taken (for snapshot_total). The API "
                    "deliberately does not compute a 'bar now': that arithmetic belongs to research/harness.py.")
    snapshot_total: Optional[int]
    snapshot_is_stale: Optional[bool]
    runs: list[LedgerRun]


class ForwardRow(BaseModel):
    run_date: str
    data_through: str
    status: str
    n_closed: Optional[float]
    n_open: Optional[float]
    win_rate_all_in: Optional[float]
    win_rate_closed: Optional[float]
    expectancy_pct: Optional[float]
    pooled_return_pct: Optional[float]
    buy_hold_return_pct: Optional[float]


class ForwardResponse(BaseModel):
    spec_document: str = "FORWARD_TEST.md"
    min_positions_to_conclude: int = 100
    rows: list[ForwardRow]


# --- forward paper books ---------------------------------------------------------------

class BookSummary(BaseModel):
    """The headline figures of one forward book, as research/forward_books.py computed them."""
    return_pct: Optional[float]
    benchmark_return_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    benchmark_max_drawdown_pct: Optional[float]
    market_exposure_pct: Optional[float]
    n_open_positions: Optional[int]
    n_closed_trades: Optional[int]


class BookRiskAdjusted(BaseModel):
    """
    A forward book's Sharpe, when it exists. Withheld (both null, with a reason) until a full year of
    forward days; once shown it is a RiskAdjustedRatio like every other, so it cannot appear without a
    status. Status is UNVALIDATED because the pre-registered criteria (FORWARD_BOOKS.md) are judged by
    a person at the gate, never automatically.
    """
    book: Optional[RiskAdjustedRatio] = None
    benchmark: Optional[RiskAdjustedRatio] = None
    withheld_reason: Optional[str] = None


class BookHolding(BaseModel):
    symbol: str
    since: Optional[str] = None
    entry_price: Optional[float] = None
    last_close: Optional[float] = None
    target_weight_pct: Optional[float] = None
    as_of_formation_date: Optional[str] = None


class BookPending(BaseModel):
    symbol: str
    action: str


class ForwardBook(BaseModel):
    id: str
    name: str
    kind: Kind
    universe: str
    rationale: str
    why_forward_tested: str
    status: Literal["NOT_STARTED", "RUNNING"]
    data_through: str
    start: str
    first_counted_day: str
    n_trading_days: int
    days_needed_for_verdict: int
    verdict_note: Optional[str] = None      # extra pre-registered condition besides the days, e.g. completed rebalances
    criteria_document: str = "FORWARD_BOOKS.md"   # where this book's pass criteria were frozen
    summary: Optional[BookSummary] = None
    risk_adjusted: BookRiskAdjusted
    growth_book: Optional[EquityCurve] = None
    growth_benchmark: Optional[EquityCurve] = None
    drawdown_book: Optional[EquityCurve] = None
    drawdown_benchmark: Optional[EquityCurve] = None
    exposure: Optional[EquityCurve] = None
    holdings: list[BookHolding] = []
    pending: list[BookPending] = []
    notes: list[str] = []


class ForwardBooksResponse(BaseModel):
    generated_at: str
    start: str
    first_counted_day: str
    criteria_document: str = "FORWARD_BOOKS.md"
    disclaimer: str = ("Paper trading only: nothing here places an order. No verdict is allowed before each book's own "
                       "pre-registered gate (a full year of forward days at the least); until then these numbers are "
                       "monitoring, not evidence.")
    books: list[ForwardBook]


# --- multi-asset advisory -------------------------------------------------------------

class AdvisoryAsset(BaseModel):
    id: str
    name: str
    ticker: Optional[str] = None
    asset_class: str
    cagr_pct: Optional[float] = None
    volatility_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    role: Optional[str] = Field(None, description="What this asset is for in a portfolio (growth, hedge, stability...).")
    last_price: Optional[float] = Field(None, description="Last close in the price file, in rupees. Not a live quote.")
    price_date: Optional[str] = None


class AdvisoryWeight(BaseModel):
    asset_id: str
    weight_pct: float
    role: Optional[str] = None
    volatility_pct: Optional[float] = Field(None, description="Annualised volatility over the rule's lookback window.")
    risk_contribution_pct: Optional[float] = Field(None, description="This asset's share of the portfolio's total risk (adds to 100 over the risky assets).")
    capped: Optional[bool] = Field(None, description="True when the weight sits at the profile's cap for this asset.")
    why: Optional[str] = Field(None, description="One sentence from research/advisory.py on why the asset got this weight.")


class AdvisoryTrend(BaseModel):
    """Where a risky asset stands against its own 210-day average. A description of today, not a back-tested signal."""
    asset_id: str
    last_price: float
    average_210d: float
    distance_pct: float
    return_12m_pct: float
    signal: str


class BasketLine(BaseModel):
    asset_id: str
    name: str
    ticker: Optional[str] = None
    weight_pct: float
    rupees: float
    price: Optional[float] = None
    price_date: Optional[str] = None
    units: Optional[float] = Field(None, description="Whole units for exchange-traded funds; fractional for Bitcoin; None for cash.")
    rupees_used: float


class BasketResponse(BaseModel):
    """An indicative shopping list for a given amount: the recommended weights turned into rupees and whole units. Not an order."""
    profile_id: str
    profile_name: str
    amount: float
    recommended_on: str
    lines: list[BasketLine]
    cash_left: float = Field(description="Cash weight plus whatever could not buy a whole unit.")
    notes: list[str]


class AdvisoryRiskMetrics(BaseModel):
    """One window of a simulated allocation. The Sharpe ratio is a RiskAdjustedRatio, so it cannot appear without its status."""
    sharpe: RiskAdjustedRatio
    cagr_pct: Optional[float] = None
    volatility_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    var95_pct: Optional[float] = Field(None, description="Historical 1-day Value at Risk at 95%, as a % of the portfolio.")
    cvar95_pct: Optional[float] = Field(None, description="Average loss on the worst 5% of days (expected shortfall).")
    worst_month_pct: Optional[float] = None
    calmar: Optional[float] = None
    n_days: int


class AdvisoryWindows(BaseModel):
    in_sample: AdvisoryRiskMetrics
    out_of_sample: AdvisoryRiskMetrics


class AdvisoryProfile(BaseModel):
    id: str
    name: str
    blurb: str
    target_volatility_pct: float
    drawdown_limit_pct: float
    caps_pct: dict[str, float]
    recommended_on: str
    guard_on: bool
    allocation: list[AdvisoryWeight]
    excluded: list[str] = Field([], description="Asset ids this profile never holds (cap of zero).")
    harness_status: Status
    strategy: AdvisoryWindows
    benchmark: AdvisoryWindows
    growth_strategy: EquityCurve
    growth_benchmark: EquityCurve
    drawdown_strategy_pct: EquityCurve
    drawdown_benchmark_pct: EquityCurve
    exposure_pct: EquityCurve
    n_rebalances: int
    cost_paid_pct_of_start: float


class AdvisoryOption(BaseModel):
    label: str
    points: int


class AdvisoryQuestion(BaseModel):
    id: str
    text: str
    options: list[AdvisoryOption]


class AdvisoryBand(BaseModel):
    max_points: int
    profile: str


class AdvisoryCorrelation(BaseModel):
    labels: list[str]
    matrix: list[list[float]]


class AdvisoryRule(BaseModel):
    vol_lookback_days: int
    rebalance_every_days: int
    cost_pct_per_side: float
    cash_rate_pct: float
    execution: str


class AdvisoryRemovedPrice(BaseModel):
    asset_id: str
    date: str
    price: float
    neighbour_price: float


class AdvisoryCleaning(BaseModel):
    rule: str
    removed: list[AdvisoryRemovedPrice] = []


class AdvisoryResponse(BaseModel):
    """
    The multi-asset, risk-managed allocation tool (research/advisory.py). Educational only: not investment advice,
    places no orders. Each profile was a registered hypothesis and carries its harness status as of the ledger total
    at generation; `is_stale` says the ledger has grown since.
    """
    generated_at: str
    data_through: str
    simulation_start: str
    in_sample_end: str
    out_of_sample_start: str
    ledger_total_at_generation: int
    ledger_total_now: Optional[int] = None
    is_stale: bool
    disclaimer: str
    benchmark: str
    rule: AdvisoryRule
    data_cleaning: AdvisoryCleaning
    assets: list[AdvisoryAsset]
    correlation: AdvisoryCorrelation
    trend: list[AdvisoryTrend] = []
    questions: list[AdvisoryQuestion]
    bands: list[AdvisoryBand]
    profiles: list[AdvisoryProfile]


# --- live prices ------------------------------------------------------------------

class LiveQuote(BaseModel):
    symbol: str
    last_price: Optional[float] = None
    prev_close: Optional[float] = None
    change_pct: Optional[float] = None      # worked out by research/live_quotes.py, never by the page
    volume: Optional[float] = None
    held_by: list[str] = []                 # ids of the paper books that hold (or would hold) the stock


class LiveQuotesResponse(BaseModel):
    """
    Near-live last traded prices written by `python research/live_quotes.py --loop`. A display only: the
    paper books run on daily bars and never use these prices. `available` is false, with a plain reason,
    when the writer has not run or the Upstox token has expired.
    """
    generated_at: Optional[str] = None
    age_seconds: Optional[int] = None
    is_stale: bool = True
    market_status: Literal["open", "pre-open", "closed", "unknown"] = "unknown"
    market_note: str = ""
    available: bool = False
    reason: Optional[str] = None
    n_requested: int = 0
    quotes: list[LiveQuote] = []


# --- housekeeping ------------------------------------------------------------

class Manifest(BaseModel):
    provenance: Provenance
    strategy_ids: list[str]
    notes: list[str] = []


class Health(BaseModel):
    ok: bool
    snapshot_present: bool
    ledger_present: bool
    detail: str
    # Provenance for the UI's status strip. All read from the snapshot manifest and the ledger file,
    # null when absent. `snapshot_stale` is an integer comparison, nothing more.
    data_through: Optional[str] = None
    snapshot_generated_at: Optional[str] = None
    git_commit: Optional[str] = None
    git_dirty: Optional[bool] = None
    ledger_total_now: Optional[int] = None
    snapshot_ledger_total: Optional[int] = None
    snapshot_stale: Optional[bool] = None
    # The forward test's own health (research/health_check.py, run at the start of each daily run): is the
    # unattended recording still happening? `forward_health_stale` means the checker itself has stopped.
    forward_health: Optional[Literal["OK", "WARN", "FAIL"]] = None
    forward_health_generated_at: Optional[str] = None
    forward_health_stale: Optional[bool] = None
    forward_health_problems: list[str] = []
