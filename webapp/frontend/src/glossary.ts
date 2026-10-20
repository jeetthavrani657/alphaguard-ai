/**
 * Plain-English meanings of the terms this app uses, in one place. `Term` shows the short line on hover or keyboard focus,
 * and the Methodology page lists them all. Wording only: nothing here is computed, and no definition makes a claim about results.
 */
export type Entry = { term: string; short: string; long?: string };

export const GLOSSARY: Record<string, Entry> = {
  sharpe: {
    term: "Sharpe ratio",
    short: "Return earned for each unit of risk taken. Higher is better; below 1 is unremarkable. On its own it can be luck, so this app always shows it beside a validation status.",
    long: "Yearly return above the cash rate, divided by how much the return swings (volatility). It rewards steady gains and punishes wild ones.",
  },
  sortino: { term: "Sortino ratio", short: "Like the Sharpe ratio, but only the downward swings count as risk." },
  cagr: { term: "CAGR (return a year)", short: "The steady yearly return that would have produced the same end result, compounding included." },
  volatility: { term: "Volatility", short: "How much returns swing up and down over a year. Higher means a bumpier ride." },
  drawdown: {
    term: "Drawdown / worst fall",
    short: "The biggest fall from a peak to a later low. It is what holding through the bad times would have felt like.",
  },
  var: {
    term: "Value at Risk (95%)",
    short: "On a bad day (the worst 1 in 20) the loss was at least this big, judged from history. It says nothing about how much worse the very worst days can be.",
  },
  cvar: {
    term: "Expected Shortfall (95%)",
    short: "How big the loss was on those worst 1-in-20 days, taken together. It looks further into the bad tail than Value at Risk does.",
  },
  calmar: { term: "Calmar ratio", short: "Yearly return divided by the worst fall. How much you earned for the pain of the deepest drop." },
  bonferroni: {
    term: "Bonferroni bar",
    short: "A stricter pass mark used because many ideas were tried: the usual 5% significance level divided by the number of ideas. The more you try, the harder it gets.",
  },
  hypothesis: { term: "Hypothesis", short: "Any strategy, setting or stock list that was tried. Every one is counted, the failures too, because trying many things makes luck look like skill." },
  in_sample: { term: "In-sample", short: "The first part of history, the window a rule is first looked at in." },
  out_of_sample: { term: "Out-of-sample", short: "The later part of history, kept apart so a rule has to prove itself on days it was not first judged on." },
  benchmark: { term: "Benchmark", short: "The simple alternative a rule must beat, usually just buying and holding the same assets." },
  paper: { term: "Paper trading", short: "Running a frozen rule forward on new data without real money, to see what it would have done." },
  forward: { term: "Forward test", short: "Judging a rule only on days that came after it was frozen, so the results cannot have been shaped to fit." },
  lookahead: { term: "Look-ahead", short: "Using information that was not yet available at the time of a decision. The engine acts one day after a signal so this cannot happen." },
  rebalance: { term: "Rebalance", short: "Moving the holdings back to the target mix. Doing it more often costs more." },
  voltarget: { term: "Volatility targeting", short: "Scaling the risky part down when markets get wild, holding the rest in cash, so the portfolio stays near a chosen level of risk." },
  ddguard: { term: "Drawdown guard", short: "A rule that halves the risky part after a deep fall from the peak, until part of the loss is recovered." },
  trend: { term: "Trend filter", short: "Hold an asset only while its price is above its own long-run level (here 210 days), otherwise sit in cash." },
  correlation: { term: "Correlation", short: "How closely two assets move together. Near 1 means together, near 0 independent, below 0 opposite. Low values are what makes mixing assets reduce risk." },
  survivorship: { term: "Survivorship bias", short: "Testing only the stocks that still exist today leaves out the ones that failed, which flatters every result." },
  slice: { term: "Slice", short: "One stock's share of a test that was run across a whole list. It is shown for context and is never evidence on its own." },
  exposure: { term: "Exposure", short: "The share of the portfolio actually invested; the rest is cash." },
  costs: { term: "Costs", short: "Taxes, charges and the small price loss of trading (slippage), all charged in every simulation." },
  pit: { term: "Point-in-time", short: "Using only what was publicly known on each date, never later corrections." },
  UNVALIDATED: { term: "Unvalidated", short: "No out-of-sample window to judge it on yet." },
  VALIDATED_FAILED: { term: "Validated: failed", short: "Tested in both windows and did not clear the Bonferroni bar. The honest result for most ideas." },
  OOS_ONLY_SIGNIFICANT: { term: "Out-of-sample only", short: "Cleared the bar only out-of-sample. A lead worth watching, not a result." },
  VALIDATED_CONFIRMED: { term: "Validated: confirmed", short: "Cleared the bar in both windows." },
  BENCHMARK_NOT_A_HYPOTHESIS: { term: "Comparison", short: "A yardstick shown for comparison. It was not one of the tested ideas." },
  SLICE_OF_POOLED_HYPOTHESIS: { term: "Slice of a pooled test", short: "One stock's part of a test run across a whole list; not an independent result." },
  RUNNING: { term: "Running", short: "The paper test is under way. No verdict is allowed before its pre-registered number of days." },
  NOT_STARTED: { term: "Not started", short: "The first session that counts has not happened yet." },
};
