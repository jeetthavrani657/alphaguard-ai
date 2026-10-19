import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";

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

  return (
    <div>
      <section className="hero">
        <img className="hero-mark" src="/alphaguard-mark.svg" alt="" width={112} height={112} />
        <div>
          <h1 className="hero-title">Alpha<span>Guard</span> <em>AI</em></h1>
          <p className="hero-tag">Every edge, tested against the number of things you tried.</p>
          <p className="hero-sub">
            A multi-asset research and risk-advisory terminal for Indian markets. It tests trading strategies and builds
            risk-managed portfolios across equity, gold, bonds, international equity and crypto, and shows, before anything
            else, whether each result survives the fact that you looked at many.
          </p>
          <div className="hero-chips">
            <span className="chip">read-only</span>
            <span className="chip">validation-first</span>
            <span className="chip">research only · no orders, ever</span>
          </div>
          <div className="hero-cta">
            <Link className="btn primary" to="/advisory">Try the advisory</Link>
            <Link className="btn" to="/strategies">See the strategies</Link>
            <Link className="btn" to="/screener">Open the screener</Link>
          </div>
        </div>
      </section>

      <div className="stats">
        <div className="stat">
          <span className="stat-label">Hypotheses tested</span>
          <Async state={health}>{(h) => <span className="stat-value">{h.ledger_total_now ?? "—"}</span>}</Async>
          <span className="stat-note">Everything ever tried is counted, successes and failures alike.</span>
        </div>
        <div className="stat">
          <span className="stat-label">Strategies registered</span>
          <Async state={strategies}>{(d) => <span className="stat-value">{d.strategies.length}</span>}</Async>
          <span className="stat-note">Each tested in-sample, then out-of-sample, against buy-and-hold.</span>
        </div>
        <div className="stat">
          <span className="stat-label">A result must beat p &lt;</span>
          <Async state={ledger}>
            {(l) => <span className="stat-value">{l.bonferroni_bar_at_snapshot?.toFixed(6) ?? "—"}</span>}
          </Async>
          <span className="stat-note">The Bonferroni bar: 0.05 divided by the hypothesis count. It only gets harder.</span>
        </div>
        <div className="stat">
          <span className="stat-label">Data through</span>
          <Async state={health}>{(h) => <span className="stat-value">{h.data_through ?? "—"}</span>}</Async>
          <span className="stat-note">Split- and dividend-adjusted prices. No live feed.</span>
        </div>
      </div>

      <Panel title="Scoreboard" right={<Link to="/strategies" className="muted">all details →</Link>} flush>
        <Async state={strategies}>
          {(d) => (
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th><th>Universe</th><th>Out-of-sample Sharpe, with its status</th>
                  </tr>
                </thead>
                <tbody>
                  {d.strategies.map((s) => (
                    <tr key={s.id}>
                      <td><Link to={`/strategies/${s.id}`}>{s.name}</Link></td>
                      <td>{s.universe}</td>
                      <td><Ratio ratio={s.out_of_sample_sharpe} /></td>
                    </tr>
                  ))}
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
