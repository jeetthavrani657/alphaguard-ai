const W = 150;
const H = 36;
const PAD = 3;

/** The points of one line, fitted into the box. Only a position on the screen is worked out here, never a return. */
function line(values: number[], lo: number, hi: number): string {
  const span = hi - lo || 1;
  const step = values.length > 1 ? (W - 2 * PAD) / (values.length - 1) : 0;
  return values.map((v, i) => `${(PAD + i * step).toFixed(1)},${(H - PAD - ((v - lo) / span) * (H - 2 * PAD)).toFixed(1)}`).join(" ");
}

/**
 * A tiny picture of how a paper test has done since it started: the test as a solid line and what holding the same assets would have done as a dashed
 * grey one, on one shared scale. The numbers are the API's growth-of-100 series, untouched; the label says where each ended.
 */
export function Sparkline({ values, benchmark, label }: { values?: number[] | null; benchmark?: number[] | null; label: string }) {
  if (!values || values.length < 2) {
    return <div className="spark spark-empty" role="img" aria-label={`${label}: not enough days yet to draw`}>too early to draw</div>;
  }
  const all = [...values, ...(benchmark ?? [])];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`${label}: ended at ${values[values.length - 1]} against ${benchmark?.length ? benchmark[benchmark.length - 1] : "no comparison"}, from a start of 100`}>
      {benchmark && benchmark.length > 1 && <polyline className="spark-bench" points={line(benchmark, lo, hi)} fill="none" strokeWidth={1.5} strokeDasharray="4 3" />}
      <polyline className="spark-line" points={line(values, lo, hi)} fill="none" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
