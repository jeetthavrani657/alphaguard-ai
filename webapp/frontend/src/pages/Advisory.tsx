import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StrategyChart } from "../components/charts/StrategyChart";
import { int, num, pct, signClass } from "../fmt";
import type { AdvisoryProfile, AdvisoryResponse } from "../api/types";

/**
 * Multi-asset advisory: pick (or work out) a risk profile and see the recommended mix, its risk measures and
 * a historical simulation next to Nifty 50. Educational only. Every number on this page was produced by
 * research/advisory.py; this page only displays it. The one thing it adds up is the questionnaire's points,
 * which the file itself defines (the points per answer and the bands), so the rule is visible, not hidden.
 */

function Questionnaire({ d, onPick }: { d: AdvisoryResponse; onPick: (profile: string) => void }) {
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const answered = d.questions.every((q) => answers[q.id] !== undefined);
  let total = 0;
  for (const q of d.questions) total += answers[q.id] ?? 0;
  const band = d.bands.find((b) => total <= b.max_points);
  const profile = d.profiles.find((p) => p.id === band?.profile);
  return (
    <>
      <p className="muted">Five questions. Each answer is worth 0 to 3 points; the total decides the profile. You can also skip this and pick a profile directly.</p>
      <div className="qgrid">
        {d.questions.map((q, qi) => (
          <fieldset key={q.id} className="qbox">
            <legend>{qi + 1}. {q.text}</legend>
            {q.options.map((o) => (
              <label key={o.label} className="qopt">
                <input type="radio" name={q.id} checked={answers[q.id] === o.points}
                  onChange={() => setAnswers({ ...answers, [q.id]: o.points })} />
                {o.label}
              </label>
            ))}
          </fieldset>
        ))}
      </div>
      {answered && profile ? (
        <p className="note info">
          Your score is <b>{total}</b> of {d.bands[d.bands.length - 1].max_points}, which matches the <b>{profile.name}</b> profile.{" "}
          <button onClick={() => onPick(profile.id)}>Show the {profile.name} allocation</button>
        </p>
      ) : (
        <p className="muted">Answer all five to see your profile.</p>
      )}
    </>
  );
}

function Allocation({ p, d }: { p: AdvisoryProfile; d: AdvisoryResponse }) {
  const name = (id: string) => d.assets.find((a) => a.id === id)?.name ?? id;
  return (
    <>
      <p className="muted">{p.blurb}</p>
      <div className="alloc">
        {p.allocation.map((w) => (
          <div key={w.asset_id}>
            <div className="alloc-row">
              <span>{name(w.asset_id)}</span>
              <div className="alloc-bar"><div className="alloc-fill" style={{ width: `${w.weight_pct}%` }} /></div>
              <b className="num">{pct(w.weight_pct, 1)}</b>
            </div>
            {w.role && <p className="why"><b>{w.role}</b> {w.why}</p>}
          </div>
        ))}
      </div>
      {p.excluded.length > 0 && (
        <p className="muted">Not used in this profile: {p.excluded.map((id) => name(id).split(" (")[0]).join(", ")}. The profile’s caps rule them out.</p>
      )}
      <p className="muted">
        Recommended on {p.recommended_on}. Target volatility {pct(p.target_volatility_pct, 0)} a year; drawdown guard at -{pct(p.drawdown_limit_pct, 0)}
        {p.guard_on ? " (the guard is ON: the risky part is halved right now)" : " (the guard is off)"}. Caps:{" "}
        {Object.entries(p.caps_pct).map(([k, v]) => `${name(k).split(" (")[0]} ${pct(v, 0)}`).join(" · ")}.
      </p>
    </>
  );
}

const AMOUNT_CHOICES = [100000, 500000, 1000000, 2500000];

/**
 * "If I put this much in": the recommended weights as rupees and whole units. The arithmetic is done by the API
 * (GET /api/advisory/basket); this component only asks and shows. It is a list to think with, never an order.
 */
function Basket({ p }: { p: AdvisoryProfile }) {
  const [text, setText] = useState("500000");
  const [amount, setAmount] = useState(500000);
  // Wait for the typing to pause, so every keystroke does not become a request.
  useEffect(() => {
    const n = Number(text.replace(/,/g, ""));
    const t = setTimeout(() => { if (Number.isFinite(n)) setAmount(n); }, 400);
    return () => clearTimeout(t);
  }, [text]);
  const valid = amount >= 10000 && amount <= 1000000000;
  const state = useApi(() => (valid ? api.basket(p.id, amount) : Promise.reject(new Error("Enter an amount between ₹10,000 and ₹100 crore."))), [p.id, amount, valid]);
  return (
    <>
      <p className="muted">How much would you invest? The mix above is turned into rupees and whole units at the last close.</p>
      <div className="amountrow">
        <label>Amount (₹) <input className="amount" inputMode="numeric" value={text} onChange={(e) => setText(e.target.value)} aria-label="Amount to invest in rupees" /></label>
        {AMOUNT_CHOICES.map((a) => <button key={a} onClick={() => setText(String(a))}>{int(a)}</button>)}
        <button className="printbtn" onClick={() => window.print()}>Print / save as PDF</button>
      </div>
      <Async state={state}>
        {(b) => (
          <div className="printable">
            <h3 className="printonly">AlphaGuard AI: {b.profile_name} mix for ₹{int(b.amount)} (as of {b.recommended_on})</h3>
            <p className="printonly">Educational research output, not investment advice. This project places no orders.</p>
            <div className="tablewrap">
              <table>
                <thead><tr><th>Asset</th><th>Ticker</th><th className="num">Share</th><th className="num">Rupees</th><th className="num">Last close</th><th className="num">Units</th><th className="num">Rupees used</th></tr></thead>
                <tbody>
                  {b.lines.map((l) => (
                    <tr key={l.asset_id}>
                      <td>{l.name}</td><td>{l.ticker ?? "—"}</td><td className="num">{pct(l.weight_pct, 1)}</td><td className="num">{int(l.rupees)}</td>
                      <td className="num">{num(l.price)}</td>
                      <td className="num">{l.units === null || l.units === undefined ? "—" : l.units < 1 ? num(l.units, 6) : int(l.units)}</td>
                      <td className="num">{int(l.rupees_used)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>Left in cash (cash share plus what could not buy a whole unit): <b className="num">₹{int(b.cash_left)}</b></p>
            <ul className="muted">{b.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </div>
        )}
      </Async>
    </>
  );
}

function Trend({ d }: { d: AdvisoryResponse }) {
  const name = (id: string) => d.assets.find((a) => a.id === id)?.name ?? id;
  return (
    <>
      <p className="muted">
        A plain description of today: is each risky asset above or below its own 210-day (about ten-month) trend line (the mean price level of that period)? This is <b>not</b> part of the
        allocation rule, was never back-tested, and is not a hypothesis in the ledger: it does not claim that a trend predicts anything.
      </p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Asset</th><th className="num">Last close</th><th className="num">210-day line</th><th className="num">Distance</th><th className="num">Last 12 months</th><th>Today</th></tr></thead>
          <tbody>
            {d.trend.map((t) => (
              <tr key={t.asset_id}>
                <td>{name(t.asset_id)}</td><td className="num">{num(t.last_price)}</td><td className="num">{num(t.average_210d)}</td>
                <td className={`num ${signClass(t.distance_pct)}`}>{pct(t.distance_pct, 1)}</td>
                <td className={`num ${signClass(t.return_12m_pct)}`}>{pct(t.return_12m_pct, 1)}</td>
                <td><span className={`sig ${t.signal === "UPTREND" ? "up" : "down"}`}>{t.signal === "UPTREND" ? "▲ above the line" : "▼ below the line"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Metrics({ p }: { p: AdvisoryProfile }) {
  const rows: [string, (m: AdvisoryProfile["strategy"]["in_sample"]) => string][] = [
    ["Return a year (CAGR)", (m) => pct(m.cagr_pct, 1)],
    ["Volatility a year", (m) => pct(m.volatility_pct, 1)],
    ["Worst fall from a peak", (m) => pct(m.max_drawdown_pct, 1)],
    ["1-day Value at Risk (95%)", (m) => pct(m.var95_pct, 2)],
    ["1-day Expected Shortfall (95%)", (m) => pct(m.cvar95_pct, 2)],
    ["Worst month", (m) => pct(m.worst_month_pct, 1)],
    ["Return per unit of drawdown (Calmar)", (m) => num(m.calmar, 2)],
  ];
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th></th><th className="num">This mix, in-sample</th><th className="num">Nifty 50, in-sample</th>
            <th className="num">This mix, out-of-sample</th><th className="num">Nifty 50, out-of-sample</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, f]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="num">{f(p.strategy.in_sample)}</td><td className="num">{f(p.benchmark.in_sample)}</td>
              <td className="num">{f(p.strategy.out_of_sample)}</td><td className="num">{f(p.benchmark.out_of_sample)}</td>
            </tr>
          ))}
          <tr>
            <td>Sharpe ratio, with its status</td>
            <td className="num"><Ratio ratio={p.strategy.in_sample.sharpe} /></td><td className="num"><Ratio ratio={p.benchmark.in_sample.sharpe} /></td>
            <td className="num"><Ratio ratio={p.strategy.out_of_sample.sharpe} /></td><td className="num"><Ratio ratio={p.benchmark.out_of_sample.sharpe} /></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function Advisory() {
  const state = useApi(() => api.advisory(), []);
  const [chosen, setChosen] = useState("moderate");
  return (
    <div>
      <div className="pagehead"><h1>Multi-asset advisory</h1></div>
      <Async state={state}>
        {(d) => {
          const p = d.profiles.find((x) => x.id === chosen) ?? d.profiles[0];
          return (
            <>
              <p className="note">{d.disclaimer}</p>
              {d.is_stale && (
                <p className="note">These results were computed when the ledger held {d.ledger_total_at_generation} hypotheses; it now holds {d.ledger_total_now}. Regenerate with <code>python research/advisory.py</code>.</p>
              )}

              <Panel title="1. Choose a risk profile">
                <div className="tabs" role="tablist" aria-label="Risk profile">
                  {d.profiles.map((x) => (
                    <button key={x.id} role="tab" aria-selected={chosen === x.id} onClick={() => setChosen(x.id)}>{x.name}</button>
                  ))}
                </div>
                <details style={{ marginTop: 14 }}>
                  <summary>Not sure which one fits you? Answer five questions</summary>
                  <Questionnaire d={d} onPick={setChosen} />
                </details>
              </Panel>

              <Panel title={`2. Recommended mix: ${p.name}`}>
                <Allocation p={p} d={d} />
              </Panel>

              <Panel title="3. If you invest an amount: the shopping list">
                <Basket p={p} />
              </Panel>

              <Panel title="4. Risk and a historical simulation">
                <p className="muted">
                  Simulated from {d.simulation_start} to {d.data_through} with the frozen rule (weights decided at one close, carried out the next day,
                  rebalanced every {d.rule.rebalance_every_days} trading days, {pct(d.rule.cost_pct_per_side, 2)} cost each way, cash at {pct(d.rule.cash_rate_pct, 0)}).
                  In-sample ends {d.in_sample_end}; nothing was fitted on either window. This profile counted as one of {d.ledger_total_at_generation} tested
                  hypotheses and its status is <b>{p.harness_status}</b>: a simulation is not evidence of future results. The same rule is now running forward on paper; see <Link to="/paper">Paper trading</Link>.
                </p>
                <Metrics p={p} />
                <StrategyChart
                  data={{
                    growth_strategy: p.growth_strategy, growth_benchmark: p.growth_benchmark,
                    drawdown_strategy_pct: p.drawdown_strategy_pct, drawdown_benchmark_pct: p.drawdown_benchmark_pct,
                    exposure_strategy_pct: p.exposure_pct,
                    exposure_definition: "Share of the portfolio held in risky assets (the rest is cash). Volatility targeting and the drawdown guard lower it when markets are wild.",
                  }}
                />
                <p className="muted">Blue is this mix; the other line is buying and holding the Nifty 50 ETF over the same days.</p>
              </Panel>

              <Panel title="5. The assets it chooses from">
                <div className="tablewrap">
                  <table>
                    <thead><tr><th>Asset</th><th>Class</th><th className="num">Return a year</th><th className="num">Volatility</th><th className="num">Worst fall</th></tr></thead>
                    <tbody>
                      {d.assets.map((a) => (
                        <tr key={a.id}>
                          <td>{a.name}</td><td>{a.asset_class}</td>
                          <td className={`num ${signClass(a.cagr_pct)}`}>{pct(a.cagr_pct, 1)}</td>
                          <td className="num">{pct(a.volatility_pct, 1)}</td><td className="num">{pct(a.max_drawdown_pct, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted">Measured from {d.simulation_start}. Past returns of an asset class are not a forecast; gold, Nasdaq-100 and Bitcoin did unusually well in the later part of this window.</p>
                <h3>How closely the assets move together (correlation)</h3>
                <div className="tablewrap">
                  <table className="corr">
                    <thead><tr><th></th>{d.correlation.labels.map((l) => <th key={l} className="num">{l.replace("_", " ")}</th>)}</tr></thead>
                    <tbody>
                      {d.correlation.matrix.map((row, i) => (
                        <tr key={d.correlation.labels[i]}>
                          <th>{d.correlation.labels[i].replace("_", " ")}</th>
                          {row.map((v, j) => <td key={j} className={`num ${v >= 0.6 && i !== j ? "hi" : v <= 0 ? "lo" : ""}`}>{num(v, 2)}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted">Low or negative correlation is what makes diversification reduce risk. Shaded green means moves almost independently or opposite; amber means they tend to fall together.</p>
              </Panel>

              <Panel title="6. Where each asset stands today (trend monitor)">
                <Trend d={d} />
              </Panel>

              <Panel title="How the rule works">
                <ol>
                  <li>Look at each asset’s volatility over the last {d.rule.vol_lookback_days} trading days and give calmer assets more weight, within the profile’s caps.</li>
                  <li>Volatility targeting: if that mix would swing more than the profile’s target, scale it down and hold the rest in cash. It never borrows to go above 100%.</li>
                  <li>Drawdown guard: if the portfolio falls past the profile’s limit from its peak, halve the risky part until it recovers half the way.</li>
                  <li>Rebalance every {d.rule.rebalance_every_days} trading days. A decision is {d.rule.execution}.</li>
                </ol>
                <details>
                  <summary>Data cleaning: {int(d.data_cleaning.removed.length)} bad price(s) removed</summary>
                  <p className="muted">{d.data_cleaning.rule}.</p>
                  <ul>{d.data_cleaning.removed.map((r) => <li key={r.asset_id + r.date}>{r.asset_id} on {r.date}: {num(r.price, 2)} against {num(r.neighbour_price, 2)} the day before</li>)}</ul>
                </details>
              </Panel>
            </>
          );
        }}
      </Async>
    </div>
  );
}
