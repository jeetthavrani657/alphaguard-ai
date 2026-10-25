import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { day, pct, signClass, when } from "../fmt";
import type { TrackCheck } from "../api/types";

const WORDS: Record<TrackCheck["status"], string> = { PASS: "PASSED", FAIL: "FAILED", CANNOT_CHECK: "TOO EARLY TO CHECK" };
const CLASS: Record<TrackCheck["status"], string> = { PASS: "pos", FAIL: "neg", CANNOT_CHECK: "muted" };

/**
 * The record, and the checks that it was not rewritten. Everything shown was worked out by research/track_record.py from the git history of the public repository;
 * this page only displays it. A check with too little history is shown as that, never as a pass.
 */
export function TrackRecord() {
  const state = useApi(() => api.trackRecord(), []);
  const books = useApi(() => api.forwardBooks(), []);

  return (
    <div>
      <div className="pagehead"><h1>Track record</h1></div>
      <p className="lede">
        Anyone can show a good-looking backtest. What is harder to fake is a record that can be audited: every idea counted, every design written down before it was tested,
        and every day of paper trading kept exactly as it was first written. The checks below are made from the history of the public code repository, which cannot be quietly edited afterwards.
        They show the record is honest. They do <b>not</b> show that any strategy is good: that is what the scoreboard and the go-live gates are for.
      </p>

      <Async state={state}>
        {(d) => {
          const repo = d.repo_url;
          const link = (hash?: string | null) => hash && repo ? <a href={`${repo}/commit/${hash}`} target="_blank" rel="noreferrer">{hash.slice(0, 7)}</a> : <span className="muted">—</span>;
          const failed = d.checks.some((c) => c.status === "FAIL");
          return (
            <>
              <p className={failed ? "error" : "note info"} role={failed ? "alert" : "status"}>
                {failed
                  ? <><b>A check failed.</b> Part of the record was changed after it was written. Read the failed line below before trusting any number on this site.</>
                  : <>No check failed. Checked {when(d.generated_at)}{d.ledger_total !== null && d.ledger_total !== undefined ? <>, with <b>{d.ledger_total}</b> ideas counted in the ledger</> : null}.</>}
              </p>
              <Panel title="Was the record rewritten?" flush>
                <div className="tablewrap">
                  <table className="stack">
                    <thead><tr><th>Check</th><th>Result</th><th>What was found</th></tr></thead>
                    <tbody>
                      {d.checks.map((c) => (
                        <tr key={c.id}>
                          <td className="wrap"><b>{c.title}</b></td>
                          <td data-label="Result"><span className={`chip ${c.status === "FAIL" ? "flag" : ""} ${CLASS[c.status]}`}>{WORDS[c.status]}</span></td>
                          <td className="wrap" data-label="What was found">{c.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              <Panel title="Designs written down first" flush>
                <div className="tablewrap">
                  <table className="stack">
                    <thead><tr><th>Document</th><th>First saved</th><th className="num">Edited since</th><th>Test counted from</th><th>Saved before the test began?</th></tr></thead>
                    <tbody>
                      {d.documents.map((x) => (
                        <tr key={x.document}>
                          <td><b>{x.document}</b></td>
                          <td data-label="First saved">{x.first_committed ? <>{day(x.first_committed.slice(0, 10))} · {link(x.first_commit)}</> : <span className="muted">not saved yet</span>}</td>
                          <td className="num" data-label="Edited since">{x.edits_since ?? "—"}</td>
                          <td data-label="Test counted from">{x.forward_started ? day(x.forward_started) : <span className="muted">no forward test for it</span>}</td>
                          <td data-label="Saved before the test began?">{x.before_forward_start === null || x.before_forward_start === undefined ? <span className="muted">not judged</span> : x.before_forward_start ? <span className="pos">yes</span> : <span className="neg">no</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted" style={{ padding: "8px 14px", margin: 0, fontSize: 12 }}>
                  "Before" is judged by the order of the saved versions in the history, not by their dates, because a date can be set to anything. A design edited since it was first saved is not
                  wrong, but the edits are all in the history for anyone to read.
                </p>
              </Panel>

              <Panel title="Where the paper tests stand">
                <Async state={books}>
                  {(b) => (
                    <div className="tablewrap">
                      <table className="stack">
                        <thead><tr><th>Paper book</th><th className="num">Days so far</th><th className="num">Days needed</th><th className="num">Return</th><th className="num">Buy &amp; hold</th></tr></thead>
                        <tbody>
                          {b.books.map((x) => (
                            <tr key={x.id}>
                              <td>{x.name}</td>
                              <td className="num" data-label="Days so far">{x.n_trading_days}</td>
                              <td className="num" data-label="Days needed">{x.days_needed_for_verdict}</td>
                              <td className={`num ${signClass(x.summary?.return_pct)}`} data-label="Return">{pct(x.summary?.return_pct)}</td>
                              <td className="num" data-label="Buy & hold">{pct(x.summary?.benchmark_return_pct)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </Async>
                <p className="muted" style={{ marginBottom: 0, fontSize: 12 }}>
                  Until a book has its full number of days these are monitoring, not evidence. <Link to="/paper">Scoreboard</Link> · <Link to="/paper#go-live">Go-live gates</Link>
                </p>
              </Panel>

              <Panel title="Check it yourself">
                <p style={{ marginTop: 0 }}>
                  You do not have to trust this page. The code, the idea ledger, the design documents and every saved version of the paper-trading files are in the public repository
                  {repo ? <> (<a href={repo} target="_blank" rel="noreferrer">{repo.replace("https://", "")}</a>)</> : null}. After copying it, one command repeats every check above from the history:
                </p>
                <pre className="codeblock">python research/track_record.py</pre>
                <p className="muted" style={{ marginBottom: 0, fontSize: 12 }}>
                  These checks ran at commit {link(d.checked_at_commit)}. They cannot show that the numbers were measured correctly, only that nothing was changed after it was written;
                  the tests in the repository and the smoke check are what guard the measuring.
                </p>
              </Panel>
            </>
          );
        }}
      </Async>
    </div>
  );
}
