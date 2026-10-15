import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { StatusChip } from "../components/StatusChip";
import { int, pct, signClass } from "../fmt";

export function Research() {
  const ledger = useApi(() => api.ledger(), []);
  const forward = useApi(() => api.forwardTest(), []);
  const quality = useApi(() => api.dataQuality({ only_issues: true }), []);

  return (
    <div>
      <div className="pagehead"><h1>Research record</h1></div>

      <Panel title="Hypothesis ledger" flush>
        <Async state={ledger}>
          {(l) => (
            <>
              <div style={{ padding: "10px 14px" }}>
                <p className="note info" style={{ margin: 0 }}>
                  <b>{l.cumulative_hypotheses}</b> hypotheses registered in total. Results were generated when the
                  count was <b>{l.snapshot_total ?? "?"}</b>
                  {l.snapshot_is_stale ? " (STALE: more have been registered since)" : ""}; the harness's Bonferroni
                  bar at that point was <code>{l.bonferroni_bar_at_snapshot ?? "?"}</code>.
                </p>
              </div>
              <div className="tablewrap scroll" style={{ maxHeight: 420 }}>
                <table>
                  <thead>
                    <tr><th>When (UTC)</th><th>What was tried</th><th className="num">New</th><th className="num">Total after</th></tr>
                  </thead>
                  <tbody>
                    {l.runs.map((r) => (
                      <tr key={r.run_id}>
                        <td>{r.timestamp.slice(0, 16).replace("T", " ")}</td>
                        <td className="wrap">{r.context}</td>
                        <td className="num">{r.n_hypotheses_this_run}</td>
                        <td className="num">{r.cumulative_hypotheses_after_run}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Async>
      </Panel>

      <div className="grid2">
        <Panel title="Forward test (pre-registered, FORWARD_TEST.md)" flush>
          <Async state={forward}>
            {(f) => (
              <>
                <div style={{ padding: "10px 14px" }}>
                  <p className="note slice" style={{ margin: 0 }}>
                    No conclusion is allowed before {f.min_positions_to_conclude} counted positions. Open positions
                    count at their current mark: an underwater open position is a loss.
                  </p>
                </div>
                <div className="tablewrap scroll" style={{ maxHeight: 360 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Run</th><th>Through</th><th>Status</th><th className="num">Closed</th><th className="num">Open</th>
                        <th className="num">Win rate (all-in)</th><th className="num">Expectancy</th>
                        <th className="num">Pooled</th><th className="num">Buy&amp;hold</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...f.rows].reverse().slice(0, 30).map((r) => (
                        <tr key={r.run_date}>
                          <td>{r.run_date}</td><td>{r.data_through}</td><td><span className="chip">{r.status}</span></td>
                          <td className="num">{int(r.n_closed)}</td><td className="num">{int(r.n_open)}</td>
                          <td className="num">{pct(r.win_rate_all_in)}</td>
                          <td className={`num ${signClass(r.expectancy_pct)}`}>{pct(r.expectancy_pct)}</td>
                          <td className={`num ${signClass(r.pooled_return_pct)}`}>{pct(r.pooled_return_pct)}</td>
                          <td className={`num ${signClass(r.buy_hold_return_pct)}`}>{pct(r.buy_hold_return_pct)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Async>
        </Panel>

        <Panel title="Data quality · stocks with an unresolved issue">
          <Async state={quality}>
            {(q) => (
              <>
                <p className="muted">
                  {q.n_symbols} stocks checked · {q.n_usable} usable · {q.n_with_unresolved_discontinuity} with an
                  unresolved discontinuity
                </p>
                {q.symbols.length === 0 && <p>None.</p>}
                {q.symbols.map((s) => (
                  <div className="note" key={s.symbol}>
                    <Link to={`/stock/${encodeURIComponent(s.symbol)}`}><b>{s.symbol}</b></Link>{" "}
                    <span className="muted">{s.universe}</span>
                    {s.discontinuities.filter((d) => d.status !== "GENUINE").map((d) => (
                      <div key={d.date}>
                        {d.date} {pct(d.magnitude_pct)} <StatusChip status={d.status} />
                      </div>
                    ))}
                  </div>
                ))}
              </>
            )}
          </Async>
        </Panel>
      </div>
    </div>
  );
}
