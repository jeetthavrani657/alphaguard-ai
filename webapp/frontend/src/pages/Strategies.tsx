import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { Term } from "../components/Term";
import { when } from "../fmt";

export function Strategies() {
  const state = useApi(() => api.strategies(), []);
  return (
    <div>
      <div className="pagehead"><h1>Strategies</h1></div>
      <p className="lede">
        Each row is a trading rule tested on a whole list of stocks, first on an early window and then on a later one it was not first judged on. Click one for the detail.
        Most rules that look good in one window fail the honest check, and the status beside each Sharpe ratio says which.
      </p>
      <Async state={state}>
        {(d) => (
          <>
            <p className="note info">
              <b>{d.ledger_total_now}</b> ideas have been tried so far, and results were generated {when(d.snapshot_generated_at)}. A status is only true as of the
              count beside it: the <Term k="bonferroni">Bonferroni bar</Term> is 0.05 divided by that count, so it only gets harder as more things are tried.
            </p>
            <Panel title="Registered strategies" flush>
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th>Strategy</th><th>Universe</th><th>Status</th><th><Term k="in_sample">In-sample</Term> <Term k="sharpe">Sharpe</Term></th>
                      <th><Term k="out_of_sample">Out-of-sample</Term> <Term k="sharpe">Sharpe</Term></th><th>Up to date?</th>
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
