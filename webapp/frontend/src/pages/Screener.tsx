import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Heatmap } from "../components/Heatmap";
import { Panel } from "../components/Panel";
import { day, num, pct, signClass } from "../fmt";
import type { ScreenerRow } from "../api/types";

type SortKey = "symbol" | "buy_hold_return_in_sample_pct" | "buy_hold_return_out_of_sample_pct";
type View = "table" | "heatmap";
type Win = "in_sample" | "out_of_sample";

export function Screener() {
  // Filters are held in React "state". Changing one re-runs the fetch below,
  // and the FILTERING itself happens in the API (selection stays server-side).
  const [universe, setUniverse] = useState("");
  const [sector, setSector] = useState("");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [view, setView] = useState<View>("table");
  const [win, setWin] = useState<Win>("out_of_sample");

  const state = useApi(
    () => api.screener({ universe: universe || undefined, sector: sector || undefined, flagged_only: flaggedOnly }),
    [universe, sector, flaggedOnly],
  );

  const controls = (
    <div className="controls">
      <span className="seg">
        <button className={view === "table" ? "on" : ""} onClick={() => setView("table")}>Table</button>
        <button className={view === "heatmap" ? "on" : ""} onClick={() => setView("heatmap")}>Sector heatmap</button>
      </span>
      <label>
        Universe
        <select value={universe} onChange={(e) => setUniverse(e.target.value)}>
          <option value="">all</option>
          <option value="nifty50">Nifty 50</option>
          <option value="midcap150">Midcap 150</option>
          <option value="smallcap250">Smallcap 250</option>
        </select>
      </label>
      <label>
        Sector <input value={sector} placeholder="e.g. Bank" onChange={(e) => setSector(e.target.value)} />
      </label>
      <label>
        <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} /> flagged only
      </label>
      {view === "table" ? (
        <label>
          Sort
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
            <option value="symbol">symbol</option>
            <option value="buy_hold_return_in_sample_pct">in-sample return</option>
            <option value="buy_hold_return_out_of_sample_pct">out-of-sample return</option>
          </select>
        </label>
      ) : (
        <span className="seg">
          <button className={win === "in_sample" ? "on" : ""} onClick={() => setWin("in_sample")}>In-sample</button>
          <button className={win === "out_of_sample" ? "on" : ""} onClick={() => setWin("out_of_sample")}>Out-of-sample</button>
        </span>
      )}
    </div>
  );

  return (
    <div>
      <div className="pagehead"><h1>Stocks</h1></div>
      <p className="note info">
        Returns shown are what simply holding each stock would have made in each window. There is no Sharpe ranking here on purpose: with 441 stocks, the top of
        such a list would mostly be lucky ones. Stocks marked ⚠ have a data problem; read the flag before the return.
      </p>
      <Panel title="Stocks" right={controls}>
        <Async state={state}>
          {(data) => {
            // Ordering rows is presentation, not calculation: nothing is derived.
            const rows = [...data.rows].sort((a: ScreenerRow, b: ScreenerRow) =>
              sortKey === "symbol"
                ? a.symbol.localeCompare(b.symbol)
                : (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity),
            );
            return (
              <>
                <p className="muted">
                  {rows.length} stocks · data through {data.data_through} · in-sample {data.in_sample} ·
                  out-of-sample {data.out_of_sample}
                </p>
                {view === "heatmap" ? (
                  <Heatmap rows={data.rows} window={win} />
                ) : (
                  <div className="tablewrap scroll">
                    <table className="stack">
                      <thead>
                        <tr>
                          <th>Symbol</th><th>Universe</th><th>Sector</th><th className="num">Latest close</th>
                          <th className="num">Day</th><th>As of</th><th className="num">Buy&amp;hold in-sample</th>
                          <th className="num">Buy&amp;hold out-of-sample</th><th className="num">OOS max drawdown</th>
                          <th>Flags</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => {
                          const flagged = r.has_unresolved_discontinuity || !r.usable;
                          return (
                            <tr key={r.symbol} className={flagged ? "flagged" : ""}>
                              <td><Link to={`/stock/${encodeURIComponent(r.symbol)}`}>{r.symbol}</Link></td>
                              <td data-label="Universe">{r.universe}</td>
                              <td data-label="Sector">{r.sector ?? "—"}</td>
                              <td className="num" data-label="Latest close">{r.latest ? num(r.latest.close) : <span className="muted" title="No latest price yet: this is the close at the end of the research window.">{num(r.last_close)}</span>}</td>
                              <td className={`num ${signClass(r.latest?.change_pct)}`} data-label="Day">{r.latest ? pct(r.latest.change_pct) : "—"}</td>
                              <td data-label="As of">
                                {r.latest ? day(r.latest.date) : <span className="muted">{day(r.last_date)}</span>}
                                {r.latest?.stale && <> <span className="chip flag" title="This stock's newest price is more than a week older than the freshest stock's: it is not being updated every day.">STALE</span></>}
                                {r.latest?.suspect && <> <span className="chip flag" title="A one-day move above 25%: check it before trusting it.">CHECK</span></>}
                              </td>
                              <td className={`num ${signClass(r.buy_hold_return_in_sample_pct)}`} data-label="Buy&hold in-sample">{pct(r.buy_hold_return_in_sample_pct)}</td>
                              <td className={`num ${signClass(r.buy_hold_return_out_of_sample_pct)}`} data-label="Buy&hold out-of-sample">{pct(r.buy_hold_return_out_of_sample_pct)}</td>
                              <td className="num" data-label="OOS max drawdown">{pct(r.buy_hold_max_drawdown_out_of_sample_pct)}</td>
                              <td data-label="Flags">
                                {!r.usable && <span className="chip flag">UNUSABLE</span>}{" "}
                                {r.has_unresolved_discontinuity && <span className="chip flag">DATA FLAG</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            );
          }}
        </Async>
      </Panel>
    </div>
  );
}
