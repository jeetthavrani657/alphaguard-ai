import { useState } from "react";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import type { Window } from "../api/types";
import { Async } from "./Async";
import { Panel } from "./Panel";
import { Tabs } from "./Tabs";
import { pct, signClass } from "../fmt";

/**
 * The four monthly stock-selection rules rerun at higher trading costs, beside holding the whole list at the same cost (research/cost_sensitivity.py). Every figure is read from the API.
 * No Sharpe ratio is drawn here: the file carries none with a status, so the page shows returns and costs only.
 */
export function CostSensitivity() {
  const state = useApi(() => api.costSensitivity(), []);
  const [ruleId, setRuleId] = useState("");
  const [window, setWindow] = useState<Window>("out_of_sample");
  return (
    <Panel title="What worse trading costs do to the stock-picking rules" id="cost-sensitivity">
      <Async state={state}>
        {(d) => {
          const rule = d.rules.find((r) => r.id === ruleId) ?? d.rules[0];
          if (!rule) return <p className="muted">No results yet.</p>;
          const w = rule.windows.find((x) => x.window === window) ?? rule.windows[0];
          return (
            <>
              <p style={{ marginTop: 0 }}>
                These rules pick a handful of stocks each month, so they trade a lot, and every trade costs money: taxes and fees that are fixed, plus <em>slippage</em>, the gap between the price you see and the price you
                get, which nobody can know in advance. The engine assumes 0.05% per side. Here the same rule is rerun assuming it is worse, next to simply owning the whole list at the same assumption.
                When the last column goes below zero, the rule has become worse than doing nothing clever.
              </p>
              <Tabs label="Which rule" value={rule.id} onChange={setRuleId} items={d.rules.map((r) => ({ id: r.id, label: r.label }))} />
              <div className="windowbar" style={{ marginTop: 10 }}>
                <span className="muted">Window</span>
                <span className="seg">
                  {(["in_sample", "out_of_sample"] as Window[]).map((x) => (
                    <button key={x} className={x === window ? "on" : ""} onClick={() => setWindow(x)}>{x === "in_sample" ? "Early (in-sample)" : "Later (out-of-sample)"}</button>
                  ))}
                </span>
                <span className="muted">{w.start} → {w.end}</span>
              </div>
              <div className="tablewrap">
                <table className="stack">
                  <thead>
                    <tr>
                      <th className="num">Assumed slippage per side</th><th className="num">Rule: yearly return</th><th className="num">Rule: costs paid a year</th>
                      <th className="num">Holding all: yearly return</th><th className="num">Rule minus holding all</th>
                    </tr>
                  </thead>
                  <tbody>
                    {w.rows.map((r) => (
                      <tr key={r.slippage_pct}>
                        <td className="num" data-label="Assumed slippage per side">{pct(r.slippage_pct, 2)}{r.slippage_pct === 0.05 ? " (the engine's)" : ""}</td>
                        <td className={`num ${signClass(r.rule_cagr_pct)}`} data-label="Rule: yearly return">{pct(r.rule_cagr_pct)}</td>
                        <td className="num" data-label="Rule: costs paid a year">{pct(r.rule_cost_per_year_pct)}</td>
                        <td className={`num ${signClass(r.hold_all_cagr_pct)}`} data-label="Holding all: yearly return">{pct(r.hold_all_cagr_pct)}</td>
                        <td className={`num ${signClass(r.cagr_edge_pct)}`} data-label="Rule minus holding all"><b>{pct(r.cagr_edge_pct)}</b></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
                Costs paid are a share of the starting capital, per year. A positive gap is not a pass: whether a rule clears the honest check is on the Strategies and Stocks tables, and a rule can be ahead of
                holding everything and still not be distinguishable from luck. Run on {d.generated_at.slice(0, 10)}; {d.note}
              </p>
            </>
          );
        }}
      </Async>
    </Panel>
  );
}
