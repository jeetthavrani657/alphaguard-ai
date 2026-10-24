import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { GoLiveGate, GoLiveRule } from "../api/types";
import { Async } from "./Async";
import { Panel } from "./Panel";
import { int, num, when } from "../fmt";

/**
 * Go-live gates (GO_LIVE_GATES.md): every paper-traded rule against the conditions that must all hold before execution is even considered.
 * Display only. This page cannot unlock anything and the project places no order; every status here was worked out by research/golive_gates.py
 * and is only drawn. A win rate is one gate among several on purpose: a rule can win most of its trades and still lose money.
 */
const STATUS_TEXT: Record<GoLiveGate["status"], string> = { MET: "met", NOT_YET: "not yet", NOT_MET: "not met", CANNOT_MEASURE: "cannot measure yet" };

function GateChip({ status }: { status: GoLiveGate["status"] }) {
  return <span className={`chip g-${status}`}>{STATUS_TEXT[status]}</span>;
}

function Progress({ value, max, label }: { value: number | null | undefined; max: number; label: string }) {
  if (value === null || value === undefined) return <span className="muted">not available</span>;
  return (
    <div className="gl-progress">
      <span className="mono">{int(value)} of {int(max)}</span>
      <progress value={Math.min(value, max)} max={max} aria-label={label} />
    </div>
  );
}

function GateList({ gates }: { gates: GoLiveGate[] }) {
  return (
    <ul className="gl-gates">
      {gates.map((g) => (
        <li key={g.gate}>
          <GateChip status={g.status} /> <b>{g.gate}</b>
          <div className="muted">{g.detail}</div>
        </li>
      ))}
    </ul>
  );
}

function RuleRow({ r }: { r: GoLiveRule }) {
  return (
    <tr className="gl-row">
      <td className="wrap">
        <b>{r.name}</b>
        <div className="muted">{r.kind === "book" ? "Trades stocks" : "Holds weights, no trades"}</div>
      </td>
      <td><Progress value={r.days} max={r.gate_days} label="forward days toward the verdict" /></td>
      <td>{r.kind === "allocation" ? <span className="muted">no trades to count</span> : <Progress value={r.n_trades} max={r.min_trades} label="trades toward the minimum" />}</td>
      <td className="wrap gl-verdict">
        <span className={`chip ${r.eligible ? "g-MET" : "g-NOT_MET"}`}>{r.eligible ? "eligible for you to consider" : "not eligible"}</span>
        <details className="gl-details">
          <summary>Every gate</summary>
          <GateList gates={r.gates} />
        </details>
      </td>
    </tr>
  );
}

export function GoLive() {
  const state = useApi(() => api.golive(), []);
  return (
    <Panel title="Go-live gates: what must be true before execution is even considered" flush>
      <Async state={state}>
        {(d) => (
          <>
            <div style={{ padding: "10px 14px" }}>
              {d.execution_locked ? (
                <p className="note info" style={{ margin: 0 }}>
                  <b>Execution is locked.</b> Nothing here places an order, and nothing on this page can unlock it. It stays locked until you amend rule 5 of the project rules in writing,
                  whatever the table below says.
                </p>
              ) : (
                <p className="note slice" style={{ margin: 0 }}>
                  <b>Check this:</b> the project rules no longer carry the order-placement prohibition. Read what they now allow before anything else.
                </p>
              )}
              <p className="muted" style={{ margin: "8px 0 0" }}>
                Every gate must be met together. A win rate of at least <b>{num(d.thresholds.win_rate_min_pct, 0)}%</b> is one of them, not the whole test: a rule can win most of its trades
                and still lose money, so it also needs enough trades, a profit after costs, no single large loss, a drawdown inside your limit and a finished forward test.
                The win-rate number is yours; the other limits are proposals until you confirm them.
              </p>
            </div>
            <div className="tablewrap scroll">
              <table>
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Forward days</th>
                    <th>Trades (open ones at their mark)</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>{d.rules.map((r) => <RuleRow key={r.id} r={r} />)}</tbody>
              </table>
            </div>
            <div style={{ padding: "10px 14px" }}>
              <h3 style={{ margin: "0 0 6px" }}>Gates of the project itself</h3>
              <GateList gates={d.project_gates} />
              <p className="muted" style={{ margin: "8px 0 0" }}>{d.note} Checked {when(d.generated_at)}.</p>
            </div>
          </>
        )}
      </Async>
    </Panel>
  );
}
