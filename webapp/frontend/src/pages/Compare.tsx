import { useMemo, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { CompareChart } from "../components/charts/CompareChart";
import { Term } from "../components/Term";
import { int, pct, signClass } from "../fmt";
import type { StrategyDetail, Window, WindowMetrics } from "../api/types";

const MAX = 3;

/** Two or three strategies side by side: one chart, one table. The choice lives in the address (?ids=a,b&window=...), so a comparison can be bookmarked or sent. */
export function Compare() {
  const [params, setParams] = useSearchParams();
  const window: Window = params.get("window") === "in_sample" ? "in_sample" : "out_of_sample";
  const list = useApi(() => api.strategies(), []);

  const known = list.status === "ready" ? list.data.strategies.map((s) => s.id) : [];
  const asked = (params.get("ids") ?? "").split(",").filter(Boolean);
  // Only strategies that exist, at most MAX; with nothing valid asked for, the first two.
  const ids = useMemo(() => {
    const valid = asked.filter((x, i) => known.includes(x) && asked.indexOf(x) === i).slice(0, MAX);
    return valid.length > 0 ? valid : known.slice(0, 2);
  }, [params, list.status]);   // eslint-disable-line react-hooks/exhaustive-deps

  const key = ids.join(",");
  const loaded = useApi(
    () => ids.length === 0 ? Promise.resolve(null)
      : Promise.all(ids.map((id) => Promise.all([api.strategy(id), api.equity(id, window)]))),
    [key, window],
  );

  const set = (next: string[], w: Window = window) => setParams({ ids: next.join(","), window: w }, { replace: true });
  const toggle = (id: string) => set(ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id].slice(-MAX));

  return (
    <div>
      <div className="pagehead"><h1>Compare strategies</h1></div>
      <p className="lede">
        Pick two or three. Each curve starts at 100 on the first day of the window. Strategies run on different lists of stocks, so a gap between curves is only a fair comparison when the lists are the same.
        A line that ends higher is not a better strategy until its status says it passed the honest check.
      </p>

      <Panel title="Choose up to three">
        <Async state={list}>
          {(d) => (
            <div className="picker">
              {d.strategies.map((s) => (
                <label key={s.id} className={ids.includes(s.id) ? "pick on" : "pick"}>
                  <input type="checkbox" checked={ids.includes(s.id)} onChange={() => toggle(s.id)} /> {s.name} <span className="muted">{s.universe}</span>
                </label>
              ))}
            </div>
          )}
        </Async>
        <div className="windowbar" style={{ marginTop: 10, marginBottom: 0 }}>
          <span className="muted">Window</span>
          <span className="seg">
            {(["in_sample", "out_of_sample"] as Window[]).map((w) => (
              <button key={w} className={w === window ? "on" : ""} onClick={() => set(ids, w)}>{w === "in_sample" ? "Early (in-sample)" : "Later (out-of-sample)"}</button>
            ))}
          </span>
        </div>
      </Panel>

      {list.status === "ready" && <Async state={loaded}>
        {(rows) => {
          if (!rows || rows.length === 0) return <div className="note">Pick at least one strategy above.</div>;
          const details = rows.map(([d]) => d);
          const curves = rows.map(([d, e]) => {
            const g = e.growth_strategy ?? e.strategy;
            return { id: d.id, name: `${d.name} · ${d.universe}`, dates: g.dates, values: g.values };
          });
          return (
            <>
              {rows.length === 1 && <p className="note info">Pick a second strategy to compare against.</p>}
              <Panel title={`Growth of 100 · ${window === "in_sample" ? "early window" : "later window"}`}>
                <CompareChart curves={curves} />
              </Panel>
              <Panel title="Side by side" flush>
                <CompareTable details={details} window={window} />
              </Panel>
            </>
          );
        }}
      </Async>}
    </div>
  );
}

function CompareTable({ details, window }: { details: StrategyDetail[]; window: Window }) {
  const m = (d: StrategyDetail): WindowMetrics => (window === "in_sample" ? d.in_sample : d.out_of_sample).strategy;
  const row = (label: ReactNode, cell: (d: StrategyDetail) => ReactNode) => (
    <tr>
      <td>{label}</td>
      {details.map((d) => <td key={d.id} className="num" data-label={`${d.name} · ${d.universe}`}>{cell(d)}</td>)}
    </tr>
  );
  return (
    <div className="tablewrap">
      <table className="stack">
        <thead>
          <tr><th></th>{details.map((d) => <th key={d.id} className="num"><Link to={`/strategies/${d.id}`}>{d.name}</Link><br /><span className="muted">{d.universe}</span></th>)}</tr>
        </thead>
        <tbody>
          {row("Honest-check status", (d) => <><StatusChip status={d.status} /> <span className="muted">as of {d.as_of_hypotheses}</span></>)}
          {row(<Term k="sharpe">Sharpe</Term>, (d) => <Ratio ratio={m(d).sharpe} compact />)}
          {row("Total return", (d) => <span className={signClass(m(d).total_return_pct)}>{pct(m(d).total_return_pct)}</span>)}
          {row(<Term k="cagr">CAGR</Term>, (d) => <span className={signClass(m(d).cagr_pct)}>{pct(m(d).cagr_pct)}</span>)}
          {row(<Term k="drawdown">Max drawdown</Term>, (d) => pct(m(d).max_drawdown_pct))}
          {row("Longest drawdown (days)", (d) => int(m(d).max_drawdown_duration_days))}
          {row("Win rate (closed trades)", (d) => pct(m(d).win_rate_pct))}
          {row("Closed trades", (d) => int(m(d).total_trades))}
          {row(<Term k="exposure">Market exposure</Term>, (d) => pct(m(d).market_exposure_pct))}
          {row("Stocks included", (d) => int(m(d).n_symbols_included))}
        </tbody>
      </table>
    </div>
  );
}
