import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { DrawdownTable, EvidenceMeter, MonthlyHeatmap } from "../components/ReportViews";
import { StatusChip } from "../components/StatusChip";
import { GLOSSARY } from "../glossary";
import { day, num, when } from "../fmt";
import type { EquityResponse } from "../api/types";
import { MetricsTable } from "./StrategyPage";

/**
 * One strategy on one printable page: what it is, its honest-check status, both windows against buy & hold, the later window's growth, months and worst falls,
 * and how much evidence there is. "Save as PDF" is the browser's own print dialog, so nothing new is installed and nothing leaves this computer.
 * Every figure is one the API sent; the pictures only place those figures on the page.
 */

const W = 640, H = 170;

/** Growth of 100 for the strategy and buy & hold, as two lines on one scale. Only screen positions are worked out here. */
function MiniGrowth({ e }: { e: EquityResponse }) {
  const s = e.growth_strategy ?? e.strategy, b = e.growth_benchmark ?? e.benchmark;
  if (!s || !b || s.values.length < 2) return null;
  const all = [...s.values, ...b.values];
  const lo = Math.min(...all), hi = Math.max(...all);
  const pts = (v: number[]) => v.map((y, i) => `${((i / (v.length - 1)) * (W - 50)).toFixed(1)},${(8 + (H - 30) - ((y - lo) / (hi - lo || 1)) * (H - 30)).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="rc-chart" role="img"
      aria-label={`Growth of 100 from ${day(s.dates[0])} to ${day(s.dates[s.dates.length - 1])}: strategy ended at ${num(s.values[s.values.length - 1], 1)}, buy and hold at ${num(b.values[b.values.length - 1], 1)}`}>
      <polyline points={pts(b.values)} className="rc-bench" fill="none" />
      <polyline points={pts(s.values)} className="rc-strat" fill="none" />
      <text x={W - 46} y={14} className="axislabel">{num(hi, 0)}</text>
      <text x={W - 46} y={H - 22} className="axislabel">{num(lo, 0)}</text>
      <text x="0" y={H - 4} className="axislabel">{day(s.dates[0])}</text>
      <text x={W - 50} y={H - 4} textAnchor="end" className="axislabel">{day(s.dates[s.dates.length - 1])}</text>
    </svg>
  );
}

export function ReportCard() {
  const { id = "" } = useParams();
  const detail = useApi(() => api.strategy(id), [id]);
  const equity = useApi(() => api.equity(id, "out_of_sample"), [id]);
  const report = useApi(() => api.report(id, "out_of_sample"), [id]);

  // Paper is white: whatever theme is on screen, the page prints in the light one (dark text on white), then goes back.
  useEffect(() => {
    const root = document.documentElement;
    let before: string | null = null;
    const toLight = () => { before = root.getAttribute("data-theme"); root.setAttribute("data-theme", "light"); };
    const restore = () => { if (before === null) root.removeAttribute("data-theme"); else root.setAttribute("data-theme", before); };
    window.addEventListener("beforeprint", toLight);
    window.addEventListener("afterprint", restore);
    return () => { window.removeEventListener("beforeprint", toLight); window.removeEventListener("afterprint", restore); };
  }, []);

  return (
    <article className="reportcard">
      <div className="rc-actions noprint">
        <Link to={`/strategies/${encodeURIComponent(id)}`} className="back">← Back to the strategy</Link>
        <button type="button" onClick={() => window.print()}>Save as PDF / print</button>
        <span className="muted">In the print dialog choose "Save as PDF". Tick "Background graphics" to keep the colours.</span>
      </div>
      <Async state={detail}>
        {(d) => (
          <>
            <header className="rc-head">
              <div className="rc-brand">AlphaGuard AI · Strategy report card</div>
              <h1>{d.name}</h1>
              <div className="rc-meta">
                <span className="chip">{d.universe}</span> <StatusChip status={d.status} /> <span>judged against {d.as_of_hypotheses} ideas tried</span>
                {d.stale && <span className="chip stale">STALE: more ideas have been tried since</span>}
              </div>
              <p className="rc-verdict">{GLOSSARY[d.status]?.short ?? ""}</p>
              <p>{d.rationale}</p>
            </header>

            <section className="rc-windows">
              <div>
                <h2>Early window (in-sample) · {d.in_sample.start} → {d.in_sample.end}</h2>
                <MetricsTable s={d.in_sample.strategy} b={d.in_sample.benchmark} />
              </div>
              <div>
                <h2>Later window (out-of-sample) · {d.out_of_sample.start} → {d.out_of_sample.end}</h2>
                <MetricsTable s={d.out_of_sample.strategy} b={d.out_of_sample.benchmark} />
              </div>
            </section>

            <section>
              <h2>Growth of 100 in the later window <span className="rc-key"><i className="k-strat" /> strategy <i className="k-bench" /> buy &amp; hold (same stocks)</span></h2>
              <Async state={equity}>{(e) => <MiniGrowth e={e} />}</Async>
            </section>

            <Async state={report}>
              {(r) => (
                <>
                  <section className="rc-windows">
                    <div><h2>How much evidence is there?</h2><EvidenceMeter e={r.evidence} /></div>
                    <div><h2>Biggest falls from a peak (later window)</h2><DrawdownTable rows={r.drawdown_periods_strategy} label="Strategy" /></div>
                  </section>
                  <section className="rc-months">
                    <h2>Return of each month (later window)</h2>
                    <MonthlyHeatmap rows={r.monthly_strategy} label="Strategy return by month" />
                  </section>
                </>
              )}
            </Async>

            <footer className="rc-foot">
              <p><b>Research only, not investment advice. AlphaGuard AI places no orders.</b> Past results are simulated on historical prices with stated costs; they do not predict future returns.</p>
              <p className="muted">
                Worked out {when(d.provenance.generated_at)} · prices through {d.provenance.data_through} · cash rate {d.provenance.risk_free_rate} ·
                {" "}{d.provenance.ledger_total_at_snapshot} ideas tested at the time · strategy id {d.id}
              </p>
            </footer>
          </>
        )}
      </Async>
    </article>
  );
}
