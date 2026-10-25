import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { StrategyChart } from "../components/charts/StrategyChart";
import { Term } from "../components/Term";
import { DrawdownTable, EvidenceMeter, MonthlyHeatmap, TradeHistogram } from "../components/ReportViews";
import { plain, VERDICT } from "../labels";
import { GLOSSARY } from "../glossary";
import { Fold } from "../useViewMode";
import { int, num, pct, signClass, when } from "../fmt";
import type { Window, WindowMetrics } from "../api/types";

const PAGE = 10;

export function MetricsTable({ s, b }: { s: WindowMetrics; b: WindowMetrics }) {
  const row = (label: ReactNode, f: (m: WindowMetrics) => string, sign?: (m: WindowMetrics) => number | null) => (
    <tr>
      <td>{label}</td>
      <td className={`num ${sign ? signClass(sign(s)) : ""}`} data-label="Strategy">{f(s)}</td>
      <td className={`num ${sign ? signClass(sign(b)) : ""}`} data-label="Buy & hold">{f(b)}</td>
    </tr>
  );
  return (
    <div className="tablewrap">
      <table className="stack">
        <thead><tr><th></th><th className="num">Strategy</th><th className="num">Buy &amp; hold (same stocks) <Term k="benchmark">?</Term></th></tr></thead>
        <tbody>
          <tr><td><Term k="sharpe">Sharpe</Term></td><td className="num" data-label="Strategy"><Ratio ratio={s.sharpe} /></td><td className="num" data-label="Buy & hold"><Ratio ratio={b.sharpe} /></td></tr>
          <tr><td><Term k="sortino">Sortino</Term></td><td className="num" data-label="Strategy"><Ratio ratio={s.sortino} /></td><td className="num" data-label="Buy & hold"><Ratio ratio={b.sortino} /></td></tr>
          {row("Total return", (m) => pct(m.total_return_pct), (m) => m.total_return_pct)}
          {row(<Term k="cagr">CAGR</Term>, (m) => pct(m.cagr_pct), (m) => m.cagr_pct)}
          {row(<Term k="drawdown">Max drawdown</Term>, (m) => pct(m.max_drawdown_pct))}
          {row("Longest drawdown (days)", (m) => int(m.max_drawdown_duration_days))}
          {row("Win rate (closed trades)", (m) => pct(m.win_rate_pct))}
          {row("Profit factor", (m) => (m.profit_factor === null ? "no losing trades" : num(m.profit_factor)))}
          {row("Closed trades", (m) => int(m.total_trades))}
          {row(<Term k="exposure">Market exposure</Term>, (m) => pct(m.market_exposure_pct))}
          {row("Stocks included", (m) => int(m.n_symbols_included))}
        </tbody>
      </table>
    </div>
  );
}

/** The headline figures of the chosen window, strategy over buy & hold. Every figure is one the API sent. */
function KpiRow({ s, b }: { s: WindowMetrics; b: WindowMetrics }) {
  const tile = (label: ReactNode, value: ReactNode, vs: ReactNode, cls = "", wide = false) => (
    <div className={wide ? "kpi wide" : "kpi"}>
      <span className="kpi-label">{label}</span>
      <span className={`kpi-value ${cls}`}>{value}</span>
      <span className="kpi-vs muted">{vs}</span>
    </div>
  );
  return (
    <div className="kpis">
      {tile(<Term k="cagr">CAGR</Term>, pct(s.cagr_pct), <>buy &amp; hold {pct(b.cagr_pct)}</>, signClass(s.cagr_pct))}
      {tile("Total return", pct(s.total_return_pct), <>buy &amp; hold {pct(b.total_return_pct)}</>, signClass(s.total_return_pct))}
      {tile(<Term k="drawdown">Max drawdown</Term>, pct(s.max_drawdown_pct), <>buy &amp; hold {pct(b.max_drawdown_pct)}</>)}
      {tile("Win rate", pct(s.win_rate_pct), <>{int(s.total_trades)} closed trades</>)}
      {tile(<Term k="sharpe">Sharpe</Term>, <Ratio ratio={s.sharpe} compact />, <>buy &amp; hold <Ratio ratio={b.sharpe} compact /></>, "", true)}
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
  const report = useApi(() => api.report(id, window), [id, window]);
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
              <Link to={`/strategies/${encodeURIComponent(id)}/card`} className="cardlink">Report card (PDF)</Link>
            </div>
            <p className="lede">
              {d.rationale}
              {Object.keys(d.params).length > 0 && <> Settings: {Object.entries(d.params).map(([k, v]) => `${k.replaceAll("_", " ")} ${String(v)}`).join(" · ")}.</>}
            </p>
            <div className={d.status === "VALIDATED_CONFIRMED" ? "verdict ok" : "verdict"} role="status">
              <span className="verdict-label">The honest check</span>
              <b className="verdict-line">{VERDICT[d.status] ?? GLOSSARY[d.status]?.term}</b>
              <span className="verdict-note">{GLOSSARY[d.status]?.short} Judged against the {d.as_of_hypotheses} ideas tried so far.</span>
            </div>
            {d.notes.map((n) => <p className="note" key={n}>{plain(n)}</p>)}

            <div className="windowbar">
              <span className="muted">Window</span>
              <span className="seg">
                {(["in_sample", "out_of_sample"] as Window[]).map((w) => (
                  <button key={w} className={w === window ? "on" : ""} onClick={() => { setWindow(w); setOffset(0); }}>
                    {w === "in_sample" ? "Early (in-sample)" : "Later (out-of-sample)"}
                  </button>
                ))}
              </span>
              <span className="muted">{window === "in_sample" ? `${d.in_sample.start} → ${d.in_sample.end}` : `${d.out_of_sample.start} → ${d.out_of_sample.end}`}</span>
            </div>
            <KpiRow s={(window === "in_sample" ? d.in_sample : d.out_of_sample).strategy} b={(window === "in_sample" ? d.in_sample : d.out_of_sample).benchmark} />

            <Panel title={`Growth, drawdown, exposure · ${window === "in_sample" ? "in-sample" : "out-of-sample"}`}>
              <Async state={equity}>{(e) => <StrategyChart data={e} />}</Async>
            </Panel>

            <Async state={report}>
              {(r) => (
                <>
                  <Panel title="How much evidence is there?" id="evidence">
                    <EvidenceMeter e={r.evidence} />
                  </Panel>
                  <Fold title="The bad stretches, month by month, and how the trades turned out" hint="biggest falls from a peak, every month's return, and the spread of the trades">
                  <Panel title="Biggest falls from a peak">
                    <h3 className="sub">Strategy</h3>
                    <DrawdownTable rows={r.drawdown_periods_strategy} label="Strategy" />
                    <h3 className="sub">Buy &amp; hold (same stocks)</h3>
                    <DrawdownTable rows={r.drawdown_periods_benchmark} label="Buy and hold" />
                  </Panel>
                  <Panel title="Return of each month">
                    <h3 className="sub">Strategy</h3>
                    <MonthlyHeatmap rows={r.monthly_strategy} label="Strategy return by month" />
                    <h3 className="sub">Buy &amp; hold (same stocks)</h3>
                    <MonthlyHeatmap rows={r.monthly_benchmark} label="Buy and hold return by month" />
                  </Panel>
                  {r.trade_histogram && (
                    <Panel title="How the trades turned out (net return per closed trade)">
                      <TradeHistogram bins={r.trade_histogram} />
                    </Panel>
                  )}
                  </Fold>
                </>
              )}
            </Async>

            <Fold title="Every number for both windows" hint="the full comparison with buy & hold, early window and later window, and where the numbers came from">
            <div className="grid2">
              <Panel title={`Early window (in-sample) · ${d.in_sample.start} → ${d.in_sample.end}`} flush>
                <MetricsTable s={d.in_sample.strategy} b={d.in_sample.benchmark} />
              </Panel>
              <Panel title={`Later window (out-of-sample) · ${d.out_of_sample.start} → ${d.out_of_sample.end}`} flush>
                <MetricsTable s={d.out_of_sample.strategy} b={d.out_of_sample.benchmark} />
              </Panel>
            </div>
            <details className="provenance">
              <summary>Where these numbers came from</summary>
              <p className="muted">
                Worked out {when(d.provenance.generated_at)} · prices through {d.provenance.data_through} ·
                yearly cash rate used for the Sharpe ratio {d.provenance.risk_free_rate} · {d.provenance.ledger_total_at_snapshot} ideas tested at the time
              </p>
            </details>
            </Fold>
          </>
        )}
      </Async>

      <Fold title="Every trade" hint="the full list, a page at a time">
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
      </Fold>
    </div>
  );
}
