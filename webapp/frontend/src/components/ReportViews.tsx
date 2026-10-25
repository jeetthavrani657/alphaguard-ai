import type { ReactNode } from "react";
import type { DrawdownPeriod, EvidenceBlock, HistogramBin, MonthlyReturn } from "../api/types";
import { day, num, pct, signClass } from "../fmt";

// Four views of numbers the API already worked out. Nothing here computes a figure: a bar's height is
// only the bin's count drawn against the tallest bin, and a tile's colour is only the sign and size band of
// a return that was sent.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Display bands only; the exact return is printed on every tile, so colour is never the only carrier. */
function band(v: number): string {
  if (v <= -5) return "h-neg3";
  if (v <= -2) return "h-neg2";
  if (v < 0) return "h-neg1";
  if (v < 2) return "h-pos1";
  if (v < 5) return "h-pos2";
  return "h-pos3";
}

/** Calendar months as a grid: one row per year, twelve columns. A month with no data stays blank. */
export function MonthlyHeatmap({ rows, label }: { rows: MonthlyReturn[]; label: string }) {
  if (rows.length === 0) return <p className="muted">Not enough days in this window to show months.</p>;
  const years = [...new Set(rows.map((r) => r.year))].sort();
  const cell = new Map(rows.map((r) => [`${r.year}-${r.month}`, r.return_pct]));
  return (
    <div className="monthgrid" role="table" aria-label={label}>
      <div className="mrow mhead" role="row">
        <span role="columnheader" />
        {MONTHS.map((m) => <span key={m} role="columnheader">{m}</span>)}
      </div>
      {years.map((y) => (
        <div className="mrow" role="row" key={y}>
          <span className="myear" role="rowheader">{y}</span>
          {MONTHS.map((m, i) => {
            const v = cell.get(`${y}-${i + 1}`);
            return v === undefined
              ? <span key={m} className="mcell na" role="cell" aria-label={`${m} ${y}: no data`} />
              : <span key={m} className={`mcell ${band(v)}`} role="cell" title={`${m} ${y}: ${pct(v, 2)}`}>{pct(v, 1)}</span>;
          })}
        </div>
      ))}
      <div className="legend" style={{ marginTop: 10 }}>
        <span><i className="h-neg3" /> ≤ −5%</span><span><i className="h-neg2" /> −5…−2%</span><span><i className="h-neg1" /> −2…0%</span>
        <span><i className="h-pos1" /> 0…2%</span><span><i className="h-pos2" /> 2…5%</span><span><i className="h-pos3" /> ≥ 5%</span>
      </div>
    </div>
  );
}

const edge = (b: HistogramBin) =>
  b.low_pct === null || b.low_pct === undefined ? `< ${num(b.high_pct, 1)}%`
    : b.high_pct === null || b.high_pct === undefined ? `≥ ${num(b.low_pct, 1)}%`
      : `${num(b.low_pct, 1)} to ${num(b.high_pct, 1)}%`;

/** How the closed trades' net returns spread: bars left of zero are losses. */
export function TradeHistogram({ bins }: { bins: HistogramBin[] }) {
  const tallest = Math.max(1, ...bins.map((b) => b.count));
  const zeroAt = bins.findIndex((b) => b.low_pct !== null && b.low_pct !== undefined && b.low_pct >= 0);   // the first bin that holds gains
  const W = 560, H = 150, TOP = 18, gap = 3, bw = (W - gap * (bins.length - 1)) / bins.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${TOP + H + 34}`} className="histo" role="img" aria-label="Number of trades in each net-return band">
        <g transform={`translate(0 ${TOP})`}>
        {bins.map((b, i) => {
          const h = (b.count / tallest) * H;
          const x = i * (bw + gap);
          const lossBin = b.high_pct !== null && b.high_pct !== undefined && b.high_pct <= 0;
          return (
            <g key={i}>
              <rect x={x} y={H - h} width={bw} height={Math.max(h, b.count ? 1 : 0)} className={lossBin ? "bar-neg" : "bar-pos"}>
                <title>{`${edge(b)}: ${b.count} trade${b.count === 1 ? "" : "s"}`}</title>
              </rect>
              {b.count > 0 && <text x={x + bw / 2} y={H - h - 4} textAnchor="middle" className="barlabel">{b.count}</text>}
            </g>
          );
        })}
        <line x1="0" x2={W} y1={H} y2={H} className="axis" />
        {zeroAt > 0 && <text x={zeroAt * (bw + gap) - gap / 2} y={H + 14} textAnchor="middle" className="axislabel">0%</text>}
        <text x="0" y={H + 28} className="axislabel">bigger losses</text>
        <text x={W} y={H + 28} textAnchor="end" className="axislabel">bigger gains</text>
        </g>
      </svg>
      <details className="provenance">
        <summary>Show the counts as a table</summary>
        <div className="tablewrap">
          <table className="stack">
            <thead><tr><th>Net return of a trade</th><th className="num">Trades</th></tr></thead>
            <tbody>{bins.filter((b) => b.count > 0).map((b, i) => <tr key={i}><td>{edge(b)}</td><td className="num" data-label="Trades">{b.count}</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/** The deepest falls from a peak, with when they began, bottomed and recovered. */
export function DrawdownTable({ rows, label }: { rows: DrawdownPeriod[]; label: string }) {
  if (rows.length === 0) return <p className="muted">{label}: never fell below its previous peak in this window.</p>;
  return (
    <div className="tablewrap">
      <table className="stack">
        <caption className="sr-only">{label}</caption>
        <thead><tr><th>Peak</th><th>Bottom</th><th>Back at peak</th><th className="num">Fall</th><th className="num">Days down</th></tr></thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={i}>
              <td data-label="Peak">{day(p.peak_date)}</td>
              <td data-label="Bottom">{day(p.trough_date)}</td>
              <td data-label="Back at peak">{p.recovered_date ? day(p.recovered_date) : <span className="chip stale">not yet</span>}</td>
              <td className={`num ${signClass(p.depth_pct)}`} data-label="Fall">{pct(p.depth_pct, 1)}</td>
              <td className="num" data-label="Days down">{p.days_underwater}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const yrs = (x: number | null | undefined) => (x === null || x === undefined ? "more than 300 years" : `${num(x, 1)} years`);

/** How much evidence there is: the length of the window against how long luck would need to be ruled out. */
export function EvidenceMeter({ e, extra }: { e: EvidenceBlock; extra?: ReactNode }) {
  return (
    <div className="evidence">
      <div className="evrow">
        <div><b>{num(e.window_years, 1)} years</b><span className="muted"> of data in this window ({e.window_days} trading days)</span></div>
        <div><b>{e.ideas_tried}</b><span className="muted"> ideas tried in this project so far</span></div>
      </div>
      <p>
        With that many ideas tried, luck alone would be expected to produce a best result of about <b>{num(e.luck_bar_annual, 2)}</b> a year
        over this window. A result has to clear that bar before it means anything.
      </p>
      <p>
        A real edge worth 1.0 a year would need about <b>{yrs(e.years_needed_for_edge_of_1)}</b> of data to stand out from luck at this
        number of tries. If it had been the only idea tried, about <b>{yrs(e.years_needed_for_edge_of_1_single_try)}</b>.
      </p>
      {extra}
    </div>
  );
}
