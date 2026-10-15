import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";

export function Strategies() {
  const state = useApi(() => api.strategies(), []);
  return (
    <div>
      <div className="pagehead"><h1>Strategies</h1></div>
      <Async state={state}>
        {(d) => (
          <>
            <p className="note info">
              Hypothesis ledger now: <b>{d.ledger_total_now}</b> · results generated {d.snapshot_generated_at}. A status
              is only true as of the hypothesis count beside it: the Bonferroni bar is 0.05 divided by that count, so it
              only gets harder as more things are tried.
            </p>
            <Panel title="Registered strategies" flush>
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th>Strategy</th><th>Universe</th><th>Status</th><th>In-sample Sharpe</th>
                      <th>Out-of-sample Sharpe</th><th>Fresh?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.strategies.map((s) => (
                      <tr key={s.id}>
                        <td><Link to={`/strategies/${s.id}`}>{s.name}</Link></td>
                        <td>{s.universe}</td>
                        <td><StatusChip status={s.status} /> <span className="muted">as of {s.as_of_hypotheses}</span></td>
                        <td><Ratio ratio={s.in_sample_sharpe} /></td>
                        <td><Ratio ratio={s.out_of_sample_sharpe} /></td>
                        <td>{s.stale ? <span className="chip stale">STALE: ledger has grown</span> : <span className="muted">current</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        )}
      </Async>
    </div>
  );
}
