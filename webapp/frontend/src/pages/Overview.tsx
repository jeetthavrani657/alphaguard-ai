import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { StockSearch } from "../components/StockSearch";
import { Term } from "../components/Term";
import { day, pct, signClass } from "../fmt";

/**
 * The front door. Everything numeric here is read from the API and shown as given:
 * the ledger count, the significance bar the harness computed, the data date, and each
 * strategy's status. Nothing is counted, averaged or summarised in the browser, so the
 * page cannot say anything the results do not already say.
 */
export function Overview() {
  const health = useApi(() => api.health(), []);
  const ledger = useApi(() => api.ledger(), []);
  const strategies = useApi(() => api.strategies(), []);
  const advisory = useApi(() => api.advisory(), []);
  const forward = useApi(() => api.advisoryForward(), []);
  const multi = useApi(() => api.multiasset(), []);
  const momentum = useApi(() => api.multiasset("momentum"), []);

  return (
    <div>
      <section className="hero">
        <img className="hero-mark" src="/alphaguard-mark.svg" alt="" width={112} height={112} />
        <div>
          <h1 className="hero-title">Alpha<span>Guard</span> <em>AI</em></h1>
          <p className="hero-tag">Every edge, tested against the number of things you tried.</p>
          <p className="hero-sub">
            Build a risk-managed portfolio across Indian equity, gold, bonds, international shares and crypto, and see what
            trading rules would really have done. Every result comes with an honest check: does it survive the fact that
            many ideas were tried?
          </p>
          <div className="hero-chips">
            <span className="chip">research only · no orders, ever</span>
            <span className="chip">not investment advice</span>
          </div>
          <div className="hero-cta">
            <Link className="btn primary" to="/advisory">Build my portfolio</Link>
            <Link className="btn" to="/methodology">How it works</Link>
          </div>
        </div>
      </section>

      <h2 className="section-title">What would you like to do?</h2>
      <div className="tasks">
        <Link className="task" to="/advisory">
          <span className="task-ico" aria-hidden="true">◔</span>
          <b>Build a portfolio</b>
          <span>Answer five questions, get a mix for your risk appetite, see it in rupees, and what to buy or sell if you already hold some.</span>
        </Link>
        <Link className="task" to="/multiasset">
          <span className="task-ico" aria-hidden="true">↗</span>
          <b>See what a trading rule would have done</b>
          <span>A trend rule across six asset classes, against simply holding them, including through the 2020 crash.</span>
        </Link>
        <Link className="task" to="/paper">
          <span className="task-ico" aria-hidden="true">◷</span>
          <b>Watch the paper tests</b>
          <span>Rules frozen in advance, run forward on new days with no real money. This is where the honest evidence builds up.</span>
        </Link>
        <div className="task find">
          <span className="task-ico" aria-hidden="true">⌕</span>
          <b>Look up a stock</b>
          <span>Chart, how every strategy did on it, and its data quality.</span>
          <StockSearch />
        </div>
      </div>

      <h2 className="section-title">The scoreboard in numbers</h2>
      <div className="stats">
        <div className="stat">
          <span className="stat-label"><Term k="hypothesis">Ideas tested</Term></span>
          <Async state={health}>{(h) => <span className="stat-value">{h.ledger_total_now ?? "—"}</span>}</Async>
          <span className="stat-note">Everything ever tried is counted, successes and failures alike.</span>
        </div>
        <div className="stat">
          <span className="stat-label">Strategies on the scoreboard</span>
          <Async state={strategies}>{(d) => <span className="stat-value">{d.strategies.length}</span>}</Async>
          <span className="stat-note">Each tested in-sample, then out-of-sample, against buy-and-hold.</span>
        </div>
        <div className="stat">
          <span className="stat-label">A result must beat p &lt; <Term k="bonferroni">(the bar)</Term></span>
          <Async state={ledger}>
            {(l) => <span className="stat-value">{l.bonferroni_bar_at_snapshot?.toFixed(6) ?? "—"}</span>}
          </Async>
          <span className="stat-note">The Bonferroni bar: 0.05 divided by the hypothesis count. It only gets harder.</span>
        </div>
        <div className="stat">
          <span className="stat-label">Backtests judged through</span>
          <Async state={health}>{(h) => <span className="stat-value">{day(h.data_through)}</span>}</Async>
          <span className="stat-note">Adjusted for splits and dividends. The paper tests run on newer days.</span>
        </div>
      </div>

      <Panel title="Scoreboard" right={<Link to="/strategies" className="muted">all details →</Link>} flush>
        <Async state={strategies}>
          {(d) => (
            <div className="tablewrap">
              <table className="stack">
                <thead>
                  <tr>
                    <th>Strategy</th><th>Universe</th><th><Term k="out_of_sample">Out-of-sample</Term> <Term k="sharpe">Sharpe</Term>, with its status</th>
                  </tr>
                </thead>
                <tbody>
                  {d.strategies.map((s) => (
                    <tr key={s.id}>
                      <td><Link to={`/strategies/${s.id}`}>{s.name}</Link></td>
                      <td data-label="Universe">{s.universe}</td>
                      <td data-label="Out-of-sample Sharpe"><Ratio ratio={s.out_of_sample_sharpe} compact /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>

      <Panel title="Risk-managed advisory at a glance" right={<Link to="/advisory" className="muted">open the advisory →</Link>} flush>
        <Async state={advisory}>
          {(a) => (
            <div className="tablewrap">
              <table className="stack">
                <thead>
                  <tr>
                    <th>Profile</th><th className="num"><Term k="volatility">Target volatility</Term></th><th className="num">Worst fall, out-of-sample</th>
                    <th><Term k="out_of_sample">Out-of-sample</Term> <Term k="sharpe">Sharpe</Term>, with its status</th><th><Term k="forward">Forward</Term> paper test</th>
                  </tr>
                </thead>
                <tbody>
                  {a.profiles.map((p) => {
                    const f = forward.status === "ready" ? forward.data.profiles.find((x) => x.id === p.id) : undefined;
                    return (
                      <tr key={p.id}>
                        <td><Link to="/advisory">{p.name}</Link></td>
                        <td className="num" data-label="Target volatility">{pct(p.target_volatility_pct, 0)}</td>
                        <td className="num" data-label="Worst fall, out-of-sample">{pct(p.strategy.out_of_sample.max_drawdown_pct, 1)} <span className="muted">(Nifty 50 ETF {pct(p.benchmark.out_of_sample.max_drawdown_pct, 1)})</span></td>
                        <td data-label="Out-of-sample Sharpe"><Ratio ratio={p.strategy.out_of_sample.sharpe} compact /></td>
                        <td data-label="Forward paper test">
                          {f?.summary ? (
                            <span>day {f.n_trading_days}: <b className={signClass(f.summary.return_pct)}>{pct(f.summary.return_pct, 2)}</b> <span className="muted">vs {pct(f.summary.benchmark_return_pct, 2)}</span></span>
                          ) : f ? <StatusChip status={f.status} /> : <span className="muted">…</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>

      <Panel title="Multi-asset trading rules at a glance" right={<Link to="/multiasset" className="muted">open the rules →</Link>} flush>
        <Async state={multi}>
          {(m) => (
            <div className="tablewrap">
              <table className="stack">
                <thead>
                  <tr><th>Rule</th><th><Term k="out_of_sample">Out-of-sample</Term> <Term k="sharpe">Sharpe</Term>, with its status</th><th className="num">Worst fall, out-of-sample</th></tr>
                </thead>
                <tbody>
                  {m.strategies.map((s) => (
                    <tr key={s.id}>
                      <td><Link to="/multiasset">{s.name}</Link></td>
                      <td data-label="Out-of-sample Sharpe"><Ratio ratio={s.metrics.out_of_sample.sharpe} compact /></td>
                      <td className="num" data-label="Worst fall, out-of-sample">{pct(s.metrics.out_of_sample.max_drawdown_pct, 1)}</td>
                    </tr>
                  ))}
                  {momentum.status === "ready" && momentum.data.strategies.map((s) => (
                    <tr key={s.id}>
                      <td><Link to="/multiasset?family=momentum">{s.name}</Link></td>
                      <td data-label="Out-of-sample Sharpe"><Ratio ratio={s.metrics.out_of_sample.sharpe} compact /></td>
                      <td className="num" data-label="Worst fall, out-of-sample">{pct(s.metrics.out_of_sample.max_drawdown_pct, 1)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>{m.static_benchmark.name} <span className="muted">(comparison)</span></td>
                    <td data-label="Out-of-sample Sharpe"><Ratio ratio={m.static_benchmark.metrics.out_of_sample.sharpe} compact /></td>
                    <td className="num" data-label="Worst fall, out-of-sample">{pct(m.static_benchmark.metrics.out_of_sample.max_drawdown_pct, 1)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>

      <h2 className="section-title">How to read what you see</h2>
      <div className="principles">
        <div className="principle">
          <h3>Validate before you trust</h3>
          <p>
            A good-looking backtest is easy to find if you try enough things. Every result is judged against the
            total number of hypotheses tried so far, not in isolation.
          </p>
        </div>
        <div className="principle">
          <h3>A stock is a slice, not a verdict</h3>
          <p>
            Strategies are tested across a whole universe. One stock's Sharpe is a slice of that test, labelled
            as such, and never stands alone as evidence.
          </p>
        </div>
        <div className="principle">
          <h3>No number without its context</h3>
          <p>
            Every Sharpe ratio is shown with its validation status and the hypothesis count it is true as of.
            A bare number is exactly how a bug once misled this project.
          </p>
        </div>
      </div>
    </div>
  );
}
