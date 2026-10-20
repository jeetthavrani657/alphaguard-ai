import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { StrategyChart } from "../components/charts/StrategyChart";
import { Term } from "../components/Term";
import { num, pct, signClass } from "../fmt";
import type { MultiassetResponse } from "../api/types";

/**
 * Multi-asset trading rules: a trend filter over the six assets of the advisory (research/multiasset_trend.py). Two
 * hypotheses were registered and judged like every other strategy; the benchmark that matters for a timing rule is the
 * same six assets held WITHOUT timing. Every number on this page was produced by that file; this page only displays it,
 * and says plainly when timing did not beat the no-timing benchmark. Simulated only: nothing places an order.
 */

function ResultsTable({ d }: { d: MultiassetResponse }) {
  const rows = [
    ...d.strategies.map((s) => ({ key: s.id, name: s.name, status: s.harness_status as string | null, w: s.metrics })),
    { key: d.static_benchmark.id, name: d.static_benchmark.name, status: null, w: d.static_benchmark.metrics },
    { key: d.nifty_benchmark.id, name: d.nifty_benchmark.name, status: null, w: d.nifty_benchmark.metrics },
  ];
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th>Rule</th><th><Term k="sharpe">Sharpe</Term> <Term k="in_sample">in-sample</Term>, with its status</th><th><Term k="sharpe">Sharpe</Term> <Term k="out_of_sample">out-of-sample</Term>, with its status</th>
            <th className="num"><Term k="cagr">Return a year</Term> (out-of-sample)</th><th className="num"><Term k="volatility">Volatility</Term></th><th className="num"><Term k="drawdown">Worst fall</Term></th><th className="num"><Term k="calmar">Calmar</Term></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>{r.name}{r.status === null && <span className="muted"> (comparison, not a hypothesis)</span>}</td>
              <td><Ratio ratio={r.w.in_sample.sharpe} /></td>
              <td><Ratio ratio={r.w.out_of_sample.sharpe} /></td>
              <td className={`num ${signClass(r.w.out_of_sample.cagr_pct)}`}>{pct(r.w.out_of_sample.cagr_pct, 1)}</td>
              <td className="num">{pct(r.w.out_of_sample.volatility_pct, 1)}</td>
              <td className="num">{pct(r.w.out_of_sample.max_drawdown_pct, 1)}</td>
              <td className="num">{num(r.w.out_of_sample.calmar, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stress({ d }: { d: MultiassetResponse }) {
  const cols = [...d.strategies.map((s) => ({ id: s.id, name: s.name })), { id: d.static_benchmark.id, name: "No timing" }];
  return (
    <>
      <p className="muted">
        Return of someone who held through each named bad stretch, read from the close before it began. The stretches were fixed in advance
        (see the Advisory page); this describes history and is not a test.
      </p>
      <div className="tablewrap">
        <table>
          <thead>
            <tr><th>Stretch</th>{cols.map((c) => <th key={c.id} className="num">{c.name}</th>)}<th className="num">Nifty 50 ETF</th></tr>
          </thead>
          <tbody>
            {d.stress.map((e) => (
              <tr key={e.id}>
                <td>{e.name}<br /><span className="muted">{e.start} to {e.end}</span></td>
                {e.covered && e.benchmark ? (
                  <>
                    {cols.map((c) => {
                      const x = e.profiles.find((p) => p.id === c.id);
                      return <td key={c.id} className={`num ${signClass(x?.return_pct)}`}>{x ? `${pct(x.return_pct, 1)} (fall ${pct(x.max_drawdown_pct, 1)})` : "—"}</td>;
                    })}
                    <td className={`num ${signClass(e.benchmark.return_pct)}`}>{pct(e.benchmark.return_pct, 1)} (fall {pct(e.benchmark.max_drawdown_pct, 1)})</td>
                  </>
                ) : <td colSpan={cols.length + 1} className="muted">The simulation does not reach back to this stretch.</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function MultiAsset() {
  const state = useApi(() => api.multiasset(), []);
  const [chosen, setChosen] = useState("trend_risk_managed");
  return (
    <div>
      <div className="pagehead"><h1>Multi-asset trading rules</h1></div>
      <p className="lede">
        What a simple trend rule would have done across six asset classes, set against just holding them. The point is the comparison: a rule only earns its place if it beats the no-timing row.
      </p>
      <Async state={state}>
        {(d) => {
          const s = d.strategies.find((x) => x.id === chosen) ?? d.strategies[0];
          const name = (id: string) => (d.assets.find((a) => a.id === id)?.name ?? (id === "cash" ? "Cash" : id)).split(" (")[0];
          return (
            <>
              <p className="note">{d.disclaimer}</p>
              {d.is_stale && (
                <p className="note warn">These results were worked out when {d.ledger_total_at_generation} ideas had been tried; {d.ledger_total_now} have been tried since. The statuses shown may be a little out of date.</p>
              )}
              <p className="note info">
                A <b>trend filter</b> across six assets: Nifty 50, Nifty Midcap 150, Nasdaq-100, gold, government bonds and Bitcoin. An asset is held while its close is above its own{" "}
                {d.trend_days}-day trend line (its mean price over that time) and replaced by cash otherwise; decisions are made every {d.rule.rebalance_every_days} trading days and carried out one day later, with {pct(d.rule.cost_pct_per_side, 2)} cost each way.
                The rules were written down in full before any result was looked at. Two variants were registered as hypotheses; the comparison that matters for a
                timing rule is the same six assets held <b>without</b> timing. See <Link to="/methodology">Methodology</Link>.
              </p>

              <Panel title={`1. Results, simulated from ${d.simulation_start}`}>
                <p className="muted">
                  In-sample ends {d.in_sample_end}; nothing was fitted on either window. Each rule is one of {d.ledger_total_at_generation} tested hypotheses, so its Sharpe ratio is judged against that count.
                  If a rule’s Sharpe is not above the no-timing row, timing added nothing beyond being in these assets.
                </p>
                <ResultsTable d={d} />
              </Panel>

              <Panel title="2. Growth, drawdown and exposure">
                <div className="tabs" role="tablist" aria-label="Rule">
                  {d.strategies.map((x) => (
                    <button key={x.id} role="tab" aria-selected={chosen === x.id} onClick={() => setChosen(x.id)}>{x.name}</button>
                  ))}
                </div>
                <p className="muted">{s.blurb} Status: <StatusChip status={s.harness_status} /></p>
                <StrategyChart
                  data={{
                    growth_strategy: s.growth, growth_benchmark: d.static_benchmark.growth,
                    drawdown_strategy_pct: s.drawdown_pct, drawdown_benchmark_pct: d.static_benchmark.drawdown_pct,
                    exposure_strategy_pct: s.exposure_pct,
                    exposure_definition: "Share of the portfolio held in the six assets (the rest is cash). The trend filter and the risk rules lower it when assets turn down.",
                  }}
                />
                <p className="muted">Blue is the selected rule; the other line is the same six assets held without timing. {s.n_rebalances} rebalances, total cost {pct(s.cost_paid_pct_of_start, 2)} of the starting amount.</p>
              </Panel>

              <Panel title="3. Where the trend filter stands today">
                <p className="muted">A description of the present: each asset against its own {d.trend_days}-day trend line at the latest close, and what each rule was holding at its last decision ({s.held_decided_on}).</p>
                <div className="tablewrap">
                  <table>
                    <thead><tr><th>Asset</th><th>Today</th>{d.strategies.map((x) => <th key={x.id} className="num">Held by: {x.name}</th>)}</tr></thead>
                    <tbody>
                      {d.signals_now.map((g) => (
                        <tr key={g.asset_id}>
                          <td>{name(g.asset_id)}</td>
                          <td><span className={`sig ${g.uptrend ? "up" : "down"}`}>{g.uptrend ? "▲ above the line" : "▼ below the line"}</span></td>
                          {d.strategies.map((x) => <td key={x.id} className="num">{pct(x.held_now.find((h) => h.asset_id === g.asset_id)?.weight_pct ?? 0, 1)}</td>)}
                        </tr>
                      ))}
                      <tr>
                        <td>Cash</td><td></td>
                        {d.strategies.map((x) => <td key={x.id} className="num">{pct(x.held_now.find((h) => h.asset_id === "cash")?.weight_pct ?? 0, 1)}</td>)}
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p className="muted">The rules only look every {d.rule.rebalance_every_days} trading days, so what they hold can differ from today’s signal until the next decision.</p>
              </Panel>

              <Panel title="4. How it behaved in past crises">
                <Stress d={d} />
              </Panel>

              <p className="muted">Data through {d.data_through}. Simulated only: this project places no orders.</p>
            </>
          );
        }}
      </Async>
    </div>
  );
}
