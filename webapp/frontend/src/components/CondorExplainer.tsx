import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { CondorCycle, CondorTrade, VolPoint } from "../api/types";
import { Async } from "./Async";
import { Panel } from "./Panel";
import { Tabs } from "./Tabs";
import { day, inr, int, num, pct, signClass } from "../fmt";

// Everything drawn here is a number the API sent from research/condor_payoff.py: the payoff curves, the result of each real trade, the volatility table.
// The only arithmetic is the position of a point on the screen (layout), never a rupee figure.

const W = 560;
const place = (v: number, lo: number, hi: number, size: number) => ((v - lo) / (hi - lo || 1)) * size;

/** One real trade's profit or loss at expiry across the Nifty's possible finishing levels, with the place it really finished marked. */
function PayoffChart({ t }: { t: CondorTrade }) {
  const H = 190, L = 8, R = 8, T = 16, B = 30;
  const xs = t.payoff.map((p) => p.level), ys = t.payoff.map((p) => p.pnl);
  const x0 = Math.min(...xs, t.final_level), x1 = Math.max(...xs, t.final_level);
  const y0 = Math.min(...ys, t.gross_pnl, 0), y1 = Math.max(...ys, t.gross_pnl, 0);
  const X = (v: number) => L + place(v, x0, x1, W - L - R);
  const Y = (v: number) => T + (H - T - B) - place(v, y0, y1, H - T - B);
  const path = t.payoff.map((p, i) => `${i ? "L" : "M"}${X(p.level).toFixed(1)},${Y(p.pnl).toFixed(1)}`).join(" ");
  const mark = (level: number, label: string, cls: string, dy = 0) => (
    <g key={label}>
      <line x1={X(level)} x2={X(level)} y1={T} y2={H - B} className={cls} strokeDasharray="3 3" />
      <text x={X(level)} y={H - B + 13 + dy} textAnchor="middle" className="axislabel">{label}</text>
    </g>
  );
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="payoff" role="img"
      aria-label={`Payoff at expiry of the ${t.label} trade. Best case ${inr(t.max_profit)}, worst case ${inr(-t.max_loss)}; the Nifty finished at ${num(t.final_level, 0)} and the position made ${inr(t.gross_pnl)} before costs.`}>
      <line x1={L} x2={W - R} y1={Y(0)} y2={Y(0)} className="axis" />
      <text x={L} y={Y(0) - 4} className="axislabel">0</text>
      <path d={path} className="payoff-line" fill="none" />
      {mark(t.short_put, `${num(t.short_put, 0)}`, "mark-strike")}
      {mark(t.short_call, `${num(t.short_call, 0)}`, "mark-strike")}
      <line x1={X(t.final_level)} x2={X(t.final_level)} y1={T} y2={H - B} className="mark-final" />
      <circle cx={X(t.final_level)} cy={Y(t.gross_pnl)} r={5} className={t.gross_pnl >= 0 ? "dot-pos" : "dot-neg"} />
      <text x={X(t.final_level)} y={T - 4} textAnchor="middle" className="barlabel">Nifty finished {num(t.final_level, 0)}</text>
      <text x={W - R} y={Y(t.payoff[0].pnl) - 6} textAnchor="end" className="axislabel">{inr(-t.max_loss)} at worst</text>
      <text x={X(t.short_put) + 4} y={Y(t.max_profit) - 6} className="axislabel">{inr(t.max_profit)} at best</text>
    </svg>
  );
}

function Facts({ t }: { t: CondorTrade }) {
  const row = (label: string, value: React.ReactNode) => <tr><td>{label}</td><td className="num" data-label={label}>{value}</td></tr>;
  return (
    <div className="tablewrap">
      <table className="stack">
        <tbody>
          {row("Opened → expires", `${day(t.entry_day)} → ${day(t.expiry)}`)}
          {row("Size", `${int(t.lots)} lots (${int(t.units)} units)`)}
          {row("Bought put · sold put", `${num(t.long_put, 0)} · ${num(t.short_put, 0)}`)}
          {row("Sold call · bought call", `${num(t.short_call, 0)} · ${num(t.long_call, 0)}`)}
          {row("Break-even levels", `${num(t.breakeven_low, 0)} and ${num(t.breakeven_high, 0)}`)}
          {row("Most it could make", <span className="pos">{inr(t.max_profit)}</span>)}
          {row("Most it could lose", <span className="neg">{inr(-t.max_loss)}</span>)}
          {row("Nifty finished at", num(t.final_level, 0))}
          {row("Result before costs", <span className={signClass(t.gross_pnl)}>{inr(t.gross_pnl)}</span>)}
          {row("Costs paid", inr(-(t.entry_cost + t.exit_cost)))}
          {row("Result after costs", <b className={signClass(t.net_pnl)}>{inr(t.net_pnl)}</b>)}
        </tbody>
      </table>
    </div>
  );
}

/** The result of every trade, in order: the shape the rule is known for (many small gains, rare large losses) is visible at a glance. */
function TradeBars({ cycles }: { cycles: CondorCycle[] }) {
  const H = 150, T = 6;
  const tops = cycles.map((c) => c.net_pnl);
  const hi = Math.max(...tops, 0), lo = Math.min(...tops, 0);
  const span = hi - lo;                               // the whole height holds the biggest gain above zero and the biggest loss below it
  const zero = T + place(hi, 0, span, H - T);         // the y of "0": the biggest gain's share of the height, down from the top
  const bw = (W - 2) / Math.max(cycles.length, 1);
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} className="payoff" role="img" aria-label={`The result after costs of each of ${cycles.length} trades, oldest first`}>
      {cycles.map((c, i) => {
        const h = place(Math.abs(c.net_pnl), 0, span, H - T);
        return (
          <rect key={c.expiry} x={1 + i * bw} width={Math.max(bw - 1, 0.8)} y={c.net_pnl >= 0 ? zero - h : zero} height={Math.max(h, 0.5)} className={c.net_pnl >= 0 ? "bar-pos" : "bar-neg"}>
            <title>{`${day(c.expiry)}: ${inr(c.net_pnl)}`}</title>
          </rect>
        );
      })}
      <line x1="0" x2={W} y1={zero} y2={zero} className="axis" />
      <text x="0" y={H + 14} className="axislabel">{day(cycles[0]?.expiry)}</text>
      <text x={W} y={H + 14} textAnchor="end" className="axislabel">{day(cycles[cycles.length - 1]?.expiry)}</text>
    </svg>
  );
}

/** What the options market priced in (implied) against what the Nifty then did (realised), as two lines. */
function VolChart({ series }: { series: VolPoint[] }) {
  const H = 150, T = 8, B = 20;
  const all = series.flatMap((p) => [p.implied_pct, p.realised_pct]);
  const lo = Math.min(...all), hi = Math.max(...all);
  const X = (i: number) => 1 + place(i, 0, series.length - 1, W - 2);
  const Y = (v: number) => T + (H - T - B) - place(v, lo, hi, H - T - B);
  const line = (pick: (p: VolPoint) => number) => series.map((p, i) => `${X(i).toFixed(1)},${Y(pick(p)).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="payoff" role="img" aria-label="Implied volatility and the volatility that followed, over time">
      <polyline points={line((p) => p.realised_pct)} className="vol-real" fill="none" />
      <polyline points={line((p) => p.implied_pct)} className="vol-impl" fill="none" />
      <text x="0" y={H - 4} className="axislabel">{day(series[0]?.date)}</text>
      <text x={W} y={H - 4} textAnchor="end" className="axislabel">{day(series[series.length - 1]?.date)}</text>
      <text x="2" y={T + 8} className="axislabel">{num(hi, 0)}%</text>
      <text x="2" y={H - B - 2} className="axislabel">{num(lo, 0)}%</text>
    </svg>
  );
}

const LABELS: Record<string, string> = { worst: "Worst trade", best: "Best trade", typical: "A typical trade", latest: "Latest trade" };

export function CondorExplainer() {
  const state = useApi(() => api.optionsExplainer(), []);
  const [ruleId, setRuleId] = useState("");
  const [label, setLabel] = useState("worst");
  return (
    <Panel title="How an options condor really pays" id="condor-payoff">
      <Async state={state}>
        {(d) => {
          const rule = d.rules.find((r) => r.id === ruleId) ?? d.rules[0];
          if (!rule) return <p className="muted">No condor results yet.</p>;
          const trade = rule.trades.find((t) => t.label === label) ?? rule.trades[0];
          return (
            <>
              <p>
                An iron condor sells one put and one call just outside where the Nifty is expected to finish, and buys a cheaper put and call further out as protection.
                The seller is paid up front. If the Nifty finishes between the two sold strikes, the seller keeps all of it; the further it finishes outside, the more is lost, until the protection takes over.
                So the profit is small and capped, and the loss is much larger and also capped. The pictures below are real trades from the stored Nifty option prices, data through {day(d.data_through)}.
              </p>
              <Tabs label="Which rule" value={rule.id} onChange={setRuleId} items={d.rules.map((r) => ({ id: r.id, label: r.id === "condor_weekly" ? "Weekly" : "Monthly" }))} />
              <p className="muted" style={{ marginTop: 8 }}>{rule.name}</p>
              {trade && (
                <>
                  <Tabs label="Which trade" value={trade.label} onChange={setLabel} items={rule.trades.map((t) => ({ id: t.label, label: LABELS[t.label] ?? t.label }))} />
                  <div className="grid2" style={{ marginTop: 12 }}>
                    <div><PayoffChart t={trade} /><p className="muted" style={{ fontSize: 12 }}>Profit or loss at expiry, before costs, for any level the Nifty could finish at. Dashed lines are the two sold strikes; the dot is where it really finished.</p></div>
                    <Facts t={trade} />
                  </div>
                </>
              )}
              <h3 className="sub" style={{ marginTop: 18 }}>The result of every trade of this rule, after costs ({rule.cycles.length} trades)</h3>
              <TradeBars cycles={rule.cycles} />
              <p className="muted" style={{ fontSize: 12 }}>Many small gains and a few large losses. A short run of calm months can look excellent and still be luck.</p>

              <h3 className="sub" style={{ marginTop: 18 }}>Why sell this: options have usually priced in more movement than followed</h3>
              <div className="legend" style={{ marginBottom: 6 }}><span><i className="vol-impl-key" /> priced in by the options (30 days out)</span><span><i className="vol-real-key" /> what the Nifty then did</span></div>
              <VolChart series={d.series} />
              <div className="tablewrap">
                <table className="stack">
                  <thead><tr><th>Year</th><th className="num">Priced in</th><th className="num">Then happened</th><th className="num">Gap</th><th className="num">Days options were dearer</th><th className="num">Worst gap</th></tr></thead>
                  <tbody>
                    {d.years.map((y) => (
                      <tr key={y.year}>
                        <td>{y.year}</td>
                        <td className="num" data-label="Priced in">{pct(y.implied_pct)}</td>
                        <td className="num" data-label="Then happened">{pct(y.realised_pct)}</td>
                        <td className={`num ${signClass(y.premium_pct)}`} data-label="Gap">{pct(y.premium_pct)}</td>
                        <td className="num" data-label="Days options were dearer">{pct(y.share_implied_above_pct, 0)}</td>
                        <td className="num neg" data-label="Worst gap">{pct(y.worst_premium_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ fontSize: 12 }}>
                The gap is real in most years, which is why the idea exists. But a yearly figure hides the bad days: in the worst moments what followed was far larger than what was priced in, and that is when these trades lose.
                Whether the rule beats cash after costs, and whether it clears the honest check, is in the table above.
              </p>
            </>
          );
        }}
      </Async>
    </Panel>
  );
}
