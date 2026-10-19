import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Panel } from "../components/Panel";

/**
 * How everything in this application was produced, in one place, for a reader who wants to judge the method before
 * the numbers. The two figures that change (the hypothesis count and the significance bar) are read from the API; the
 * rest describes fixed design decisions and names the file that holds each one, so a claim here can be checked.
 */
export function Methodology() {
  const ledger = useApi(() => api.ledger(), []);
  const total = ledger.status === "ready" ? ledger.data.cumulative_hypotheses : null;
  const snapshotTotal = ledger.status === "ready" ? ledger.data.snapshot_total : null;
  const bar = ledger.status === "ready" ? ledger.data.bonferroni_bar_at_snapshot?.toFixed(6) : null;

  return (
    <div>
      <div className="pagehead"><h1>Methodology</h1></div>
      <p className="note info">
        This page explains how the results were produced and what they can and cannot show. Nothing here is a forecast, and nothing in the
        application places an order: it is read-only research.
      </p>

      <Panel title="1. The question, and the stance">
        <p>
          Each strategy is asked one question: <i>after realistic costs, did trading this rule beat simply holding the same assets over
          the same days?</i> The design assumes the honest answer is usually no, and is built to avoid fooling itself: a good-looking
          backtest is easy to find if enough things are tried, so every result is judged against <b>how many things were tried</b>.
        </p>
      </Panel>

      <Panel title="2. Data">
        <ul>
          <li><b>Prices:</b> daily bars for NSE stocks and ETFs from a free source, adjusted for splits and dividends (<code>data/loader.py</code>).</li>
          <li><b>Validation before use:</b> every series passes a data-quality gate (<code>data/validator.py</code>). Price jumps that look like unadjusted corporate actions block a stock from the tests instead of being silently trusted. Known problems are listed in <code>data/known_issues.md</code>.</li>
          <li><b>Survivorship bias is disclosed, not hidden:</b> the stock lists are today’s index members, so stocks that fell out of the index are missing, which flatters every result. The bias is quantified in the findings documents.</li>
          <li><b>Free-data bad prints:</b> the advisory’s ETF prices once held one-day errors that looked like a 90% crash. They are detected by a stated rule, carried forward, and listed on the Advisory page.</li>
          <li><b>Latest day:</b> the free source publishes the newest day late, so the paper books take today’s candle from a read-only broker market-data feed. No order, position or funds data is ever requested.</li>
        </ul>
      </Panel>

      <Panel title="3. Testing protocol">
        <ul>
          <li><b>No look-ahead:</b> a signal formed at one close is acted on one day later. This single lag lives in one place in the engine, and a guard fails loudly if it is ever removed (<code>engine/backtest.py</code>).</li>
          <li><b>Two windows:</b> in-sample runs from 2015-01-01 to 2020-06-30 and out-of-sample from 2020-07-01 to 2025-12-31 (<code>config.py</code>). A result is only called confirmed if it holds in both.</li>
          <li><b>Universe, not a single stock:</b> a rule is tested across a whole index. One stock’s Sharpe is a slice of that test, labelled as such, and never evidence by itself.</li>
          <li><b>Benchmark:</b> buy-and-hold of the same assets over the same days, with the same costs.</li>
          <li><b>Zero-skill control:</b> for portfolio rules, hundreds of random portfolios with the same size and rebalance dates give the Sharpe ratio luck alone produces; a result has to beat that distribution, not just beat zero.</li>
        </ul>
      </Panel>

      <Panel title="4. The hypothesis ledger and the significance bar">
        <p>
          Every strategy, parameter set or universe ever tried is registered in a ledger (<code>research/hypothesis_ledger.json</code>),
          successes and failures alike. The Bonferroni correction divides the 5% significance level by the <b>cumulative</b> number of hypotheses,
          so the bar only ever gets harder as more is tried.
        </p>
        <p className="note">
          The ledger holds <b>{total ?? "…"}</b> hypotheses. When the results were last generated it held <b>{snapshotTotal ?? "…"}</b>, and a result
          then needed a p-value below <b>{bar ?? "…"}</b> to count. The statuses are:
        </p>
        <ul>
          <li><b>VALIDATED_CONFIRMED</b>: significant against the bar in-sample and out-of-sample.</li>
          <li><b>OOS_ONLY_SIGNIFICANT</b>: significant only out-of-sample, which is a lead and not a result.</li>
          <li><b>VALIDATED_FAILED</b>: tested in both windows and did not clear the bar.</li>
          <li><b>UNVALIDATED</b>: no out-of-sample window to judge it with.</li>
        </ul>
        <p>
          Every Sharpe ratio in the application is shown with its status and the hypothesis count it is true as of, because the same numbers can change
          status when the count grows. A ratio without that context is exactly how a bug once misled this project (see the research record).
        </p>
      </Panel>

      <Panel title="5. Costs">
        <ul>
          <li><b>Equity strategies</b> (<code>engine/costs.py</code>, rates in <code>config.py</code>): securities transaction tax 0.1% on both buy and sell for delivery, stamp duty 0.015% on the buy side, NSE transaction charge 0.00307%, SEBI fee, 18% GST on the charges it applies to, zero brokerage, and a 0.05% slippage assumption per side. Midcap and smallcap runs add a liquidity-based cost per stock.</li>
          <li><b>Advisory</b>: a flat 0.10% of the amount traded on each side, and cash assumed to earn 6% a year. Taxes and the exact spread of each fund are not modelled.</li>
        </ul>
      </Panel>

      <Panel title="6. The advisory rule (frozen before any result was looked at)">
        <ol>
          <li>Every 21 trading days, weight each allowed asset by one over its 63-day volatility, within the profile’s per-asset caps.</li>
          <li>Volatility targeting: if the mix would swing more than the profile’s target, scale it down and hold the rest in cash. It never borrows.</li>
          <li>Drawdown guard: after a fall past the profile’s limit from its peak, halve the risky part until half the loss is recovered.</li>
          <li>Decisions at one close are carried out one day later.</li>
        </ol>
        <p>
          The three profiles were each counted as a hypothesis when registered, and none cleared the bar. What the advisory does show is lower drawdowns, not proven higher returns.
          See the <Link to="/advisory">Advisory</Link> page for the numbers, the crisis stress test and the data cleaning.
        </p>
      </Panel>

      <Panel title="7. The multi-asset trading rules">
        <p>
          A trend filter over the advisory’s six assets (<code>MULTIASSET_TREND.md</code>, <code>research/multiasset_trend.py</code>): an asset is held while its close is above its own 210-day trend line
          and replaced by cash otherwise, checked every 21 trading days and carried out one day later. Two variants were registered as hypotheses (equal slots, and the advisory’s risk machinery applied to the assets in an uptrend).
          The benchmark that matters for a timing rule is the same assets <b>without</b> timing, because that answers whether the timing itself added anything. See the <Link to="/multiasset">Multi-asset</Link> page.
        </p>
      </Panel>

      <Panel title="8. Forward (paper) testing">
        <p>
          The closest candidates were frozen with written pass criteria on 2026-10-16 and are now run forward on data that did not exist when they were frozen
          (<Link to="/paper">Paper trading</Link>). Everything is recomputed from raw prices, one history row is kept per run so any change in the free data would show, and
          nothing is judged before a full year of forward sessions. The paper books and the advisory profiles place no orders.
        </p>
      </Panel>

      <Panel title="9. What this does not do">
        <ul>
          <li>It does not place orders, hold positions or connect to an account. The broker feed is read-only market data.</li>
          <li>It does not claim an edge: the research record is mainly a list of things that looked good and were not.</li>
          <li>It is not investment advice. Simulations are not forecasts, and history from a free data source covers a short, unusual period.</li>
          <li>Backtests use today’s index members; the survivorship bias is disclosed and only partly estimated.</li>
        </ul>
      </Panel>

      <Panel title="10. How to check any of this">
        <p>
          Every number comes from code in the repository, with automated tests for the engine, the harness, the advisory, the API and the interface rules (the page is not
          allowed to compute a result, only to show it). The full record is in <code>FINDINGS.md</code>, with <code>ADVISORY.md</code>, <code>FORWARD_BOOKS.md</code> and <code>FUNDAMENTALS_PREREG.md</code> holding the frozen designs.
        </p>
      </Panel>
    </div>
  );
}
