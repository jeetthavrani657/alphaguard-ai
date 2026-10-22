import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "./Async";
import { Panel } from "./Panel";
import { Ratio } from "./Ratio";
import { Term } from "./Term";
import { strategyLabel } from "../labels";
import { day, int, num, pct, signClass } from "../fmt";

/**
 * The three stock-selection ideas registered together (FACTOR_IDEAS.md): what each one did in the practice and the unseen period,
 * against holding every stock in its universe and against choosing the same number of stocks by lot. Every figure is read from the
 * API; the only Sharpe values drawn here go through <Ratio>, so none appears without its status.
 */
export function StockIdeas() {
  const state = useApi(() => api.stockSelection(), []);
  return (
    <Panel title="Stock-selection ideas" flush>
      <Async state={state}>
        {(d) => (
          <>
            <div style={{ padding: "10px 14px" }}>
              <p className="note info" style={{ margin: 0 }}>
                Three ideas, written down and frozen before any result existed, then run once and counted together. Each picks stocks monthly from one index and holds them equally.
                Results are from {day(d.generated_at)}, when <b>{d.ledger_total_at_generation}</b> ideas had been tried{d.is_stale ? " (more have been tried since)" : ""}.
                Past results on today's index lists are flattered, because the stocks that fell out of an index are missing.
              </p>
            </div>
            <div className="tablewrap scroll">
              <table>
                <thead>
                  <tr>
                    <th>Idea</th>
                    <th>Practice period</th>
                    <th>Unseen period</th>
                    <th className="num">Unseen return a year</th>
                    <th className="num">Holding all stocks</th>
                    <th className="num">Unseen worst fall</th>
                    <th>Against random picks (unseen)</th>
                  </tr>
                </thead>
                <tbody>
                  {d.ideas.map((i) => {
                    const unseen = i.windows.find((w) => w.window === "out_of_sample");
                    return (
                      <tr key={i.id}>
                        <td className="wrap"><b>{strategyLabel(i.id)}</b><div className="muted">{i.name}</div></td>
                        <td><Ratio ratio={i.strategy.in_sample.sharpe} /></td>
                        <td><Ratio ratio={i.strategy.out_of_sample.sharpe} /></td>
                        <td className={`num ${signClass(i.strategy.out_of_sample.cagr_pct)}`}>{pct(i.strategy.out_of_sample.cagr_pct)}</td>
                        <td className={`num ${signClass(i.universe_benchmark.out_of_sample.cagr_pct)}`}>{pct(i.universe_benchmark.out_of_sample.cagr_pct)}</td>
                        <td className="num neg">{pct(i.strategy.out_of_sample.max_drawdown_pct)}</td>
                        <td className="wrap">
                          {unseen?.zero_skill_percentile == null ? "n/a" : <>Better than <b>{num(unseen.zero_skill_percentile, 0)}%</b> of {int(unseen.zero_skill_n_portfolios)} random portfolios</>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ padding: "10px 14px" }}>
              <p className="muted" style={{ margin: "0 0 6px" }}>
                A result only counts if it clears the <Term k="bonferroni">Bonferroni bar</Term>, which gets harder with every idea tried. Making money in the past is not the same as passing it.
              </p>
              {d.survivorship && (
                <>
                  <p style={{ margin: "10px 0 6px" }}>
                    <b>How much does using today's index list help the mid-cap idea?</b>{" "}
                    {d.survivorship.n_late_listed} of {d.survivorship.n_universe} of its stocks were not yet trading when the history starts.
                  </p>
                  <div className="tablewrap scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Period</th>
                          <th className="num">Return a year, today's list</th>
                          <th className="num">With four failed companies added back</th>
                          <th className="num">Without the late-listed stocks</th>
                          <th className="num">Late-listed share of the picks</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.survivorship.rows.map((r) => (
                          <tr key={r.window}>
                            <td>{r.window === "in_sample" ? "Practice" : "Unseen"}</td>
                            <td className="num">{pct(r.todays_list.cagr_pct)}</td>
                            <td className="num">{pct(r.with_casualties.cagr_pct)}</td>
                            <td className="num">{pct(r.without_late_listed.cagr_pct)}</td>
                            <td className="num">{pct(r.late_listed_share_of_picks_pct)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted" style={{ margin: "6px 0 0" }}>
                    Adding back failed companies (Jet Airways, Reliance Capital, Reliance Communications, Reliance Naval) barely moves the result, but the stocks that only joined later
                    account for a large part of the unseen-period return. Neither check removes the bias; they only show how big part of it is.
                  </p>
                </>
              )}
            </div>
          </>
        )}
      </Async>
    </Panel>
  );
}
