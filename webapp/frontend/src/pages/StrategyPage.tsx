import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { StrategyChart } from "../components/charts/StrategyChart";
import { int, num, pct, signClass } from "../fmt";
import type { Window, WindowMetrics } from "../api/types";

const PAGE = 10;

function MetricsTable({ s, b }: { s: WindowMetrics; b: WindowMetrics }) {
  const row = (label: string, f: (m: WindowMetrics) => string, sign?: (m: WindowMetrics) => number | null) => (
    <tr>
      <td>{label}</td>
      <td className={`num ${sign ? signClass(sign(s)) : ""}`}>{f(s)}</td>
      <td className={`num ${sign ? signClass(sign(b)) : ""}`}>{f(b)}</td>
    </tr>
  );
  return (
    <div className="tablewrap">
      <table>
        <thead><tr><th></th><th className="num">Strategy</th><th className="num">Buy &amp; hold (same stocks)</th></tr></thead>
        <tbody>
          <tr><td>Sharpe</td><td className="num"><Ratio ratio={s.sharpe} /></td><td className="num"><Ratio ratio={b.sharpe} /></td></tr>
          <tr><td>Sortino</td><td className="num"><Ratio ratio={s.sortino} /></td><td className="num"><Ratio ratio={b.sortino} /></td></tr>
          {row("Total return", (m) => pct(m.total_return_pct), (m) => m.total_return_pct)}
          {row("CAGR", (m) => pct(m.cagr_pct), (m) => m.cagr_pct)}
          {row("Max drawdown", (m) => pct(m.max_drawdown_pct))}
          {row("Longest drawdown (days)", (m) => int(m.max_drawdown_duration_days))}
          {row("Win rate (closed trades)", (m) => pct(m.win_rate_pct))}
          {row("Profit factor", (m) => (m.profit_factor === null ? "undefined" : num(m.profit_factor)))}
          {row("Closed trades", (m) => int(m.total_trades))}
          {row("Market exposure", (m) => pct(m.market_exposure_pct))}
          {row("Stocks included", (m) => int(m.n_symbols_included))}
        </tbody>
      </table>
    </div>
  );
}

export function StrategyPage() {
  const { id = "" } = useParams();
  const [window, setWindow] = useState<Window>("out_of_sample");
  const [offset, setOffset] = useState(0);
  // Component state survives a change of :id (React reuses the instance), so a page offset from
  // one strategy would otherwise be applied to another that has fewer trades.
  useEffect(() => { setOffset(0); }, [id]);

  const detail = useApi(() => api.strategy(id), [id]);
  const equity = useApi(() => api.equity(id, window), [id, window]);
  const trades = useApi(() => api.trades(id, window, PAGE, offset), [id, window, offset]);

  return (
    <div>
      <Link to="/strategies" className="back">← Strategies</Link>
      <Async state={detail}>
        {(d) => (
          <>
            <div className="pagehead">
              <h1>{d.name}</h1>
              <span className="chip">{d.universe}</span>
              <StatusChip status={d.status} />
              <span className="muted">as of {d.as_of_hypotheses} hypotheses</span>
              {d.stale && <span className="chip stale">STALE: ledger has grown since</span>}
            </div>
            <p className="muted">{d.rationale} · parameters <code>{JSON.stringify(d.params)}</code></p>
            {d.notes.map((n) => <p className="note" key={n}>{n}</p>)}

            <div className="grid2">
              <Panel title={`In-sample · ${d.in_sample.start} → ${d.in_sample.end}`} flush>
                <MetricsTable s={d.in_sample.strategy} b={d.in_sample.benchmark} />
              </Panel>
              <Panel title={`Out-of-sample · ${d.out_of_sample.start} → ${d.out_of_sample.end}`} flush>
                <MetricsTable s={d.out_of_sample.strategy} b={d.out_of_sample.benchmark} />
              </Panel>
            </div>
            <p className="muted" style={{ marginTop: -4 }}>
              Generated {d.provenance.generated_at} · code {d.provenance.git_commit ?? "?"}
              {d.provenance.git_dirty ? " (uncommitted changes)" : ""} · data through {d.provenance.data_through} ·
              annual risk-free rate {d.provenance.risk_free_rate} · ledger {d.provenance.ledger_total_at_snapshot}
            </p>
          </>
        )}
      </Async>

      <Panel
        title={`Growth, drawdown, exposure · ${window === "in_sample" ? "in-sample" : "out-of-sample"}`}
        right={
          <span className="seg">
            {(["in_sample", "out_of_sample"] as Window[]).map((w) => (
              <button key={w} className={w === window ? "on" : ""} onClick={() => { setWindow(w); setOffset(0); }}>
                {w === "in_sample" ? "In-sample" : "Out-of-sample"}
              </button>
            ))}
          </span>
        }
      >
        <Async state={equity}>{(e) => <StrategyChart data={e} />}</Async>
      </Panel>

      <Panel title="Trade log" flush>
        <Async state={trades}>
          {(t) => (
            <>
              <div className="controls" style={{ padding: "8px 14px" }}>
                <span className="muted">
                  {t.total} {t.kind === "portfolio" ? "executions" : "closed trades"} · showing{" "}
                  {t.total === 0 ? 0 : t.offset + 1}–{Math.min(t.offset + t.limit, t.total)}
                </span>
                <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← prev</button>
                <button disabled={offset + PAGE >= t.total} onClick={() => setOffset(offset + PAGE)}>next →</button>
              </div>
              <div className="tablewrap">
                <table>
                  <thead>
                    {t.kind === "portfolio"
                      ? <tr><th>Stock</th><th>Date</th><th>Side</th><th className="num">Shares @ price</th></tr>
                      : <tr><th>Stock</th><th className="num">Entry</th><th className="num">Exit</th><th className="num">Net return</th><th className="num">Held</th></tr>}
                  </thead>
                  <tbody>
                    {(t.closed_trades ?? []).map((x, i) => (
                      <tr key={i}>
                        <td><Link to={`/stock/${encodeURIComponent(x.symbol)}`}>{x.symbol}</Link></td>
                        <td className="num">{x.entry_date} @ {num(x.entry_price)}</td>
                        <td className="num">{x.exit_date} @ {num(x.exit_price)}</td>
                        <td className={`num ${signClass(x.return_pct)}`}>{pct(x.return_pct)}</td>
                        <td className="num">{x.holding_days}d</td>
                      </tr>
                    ))}
                    {(t.executions ?? []).map((x, i) => (
                      <tr key={i}>
                        <td><Link to={`/stock/${encodeURIComponent(x.symbol)}`}>{x.symbol}</Link></td>
                        <td>{x.date}</td>
                        <td className={x.side === "buy" ? "pos" : "neg"}>{x.side}</td>
                        <td className="num">{x.shares} @ {num(x.price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Async>
      </Panel>
    </div>
  );
}
