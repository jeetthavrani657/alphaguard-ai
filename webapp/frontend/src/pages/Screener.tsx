import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Heatmap } from "../components/Heatmap";
import { Panel } from "../components/Panel";
import { Sparkline } from "../components/Sparkline";
import { Tabs } from "../components/Tabs";
import { day, num, pct, signClass } from "../fmt";
import type { ScreenerRow } from "../api/types";

type SortKey = "symbol" | "day" | "month" | "buy_hold_return_in_sample_pct" | "buy_hold_return_out_of_sample_pct";
type View = "overview" | "returns" | "data" | "heatmap";
type Win = "in_sample" | "out_of_sample";

const UNIVERSES = [["", "All"], ["nifty50", "Nifty 50"], ["midcap150", "Midcap 150"], ["smallcap250", "Smallcap 250"]] as const;

/** A filter you can see is on: a button that stays pressed. */
function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className={on ? "chip-btn on" : "chip-btn"} aria-pressed={on} onClick={onClick}>{children}</button>;
}

/** The value a row is sorted by; a missing one sorts last. Reading a field, never working one out. */
const sortValue = (r: ScreenerRow, k: Exclude<SortKey, "symbol">): number | null | undefined =>
  k === "day" ? r.latest?.change_pct : k === "month" ? r.latest?.change_1m_pct : r[k];

export function Screener() {
  // Filters are held in React "state". Universe, sector and "flagged only" re-run the fetch below, and that FILTERING
  // happens in the API (selection stays server-side). The search box, the sort and the tabs only change what is shown of the rows already here.
  const [universe, setUniverse] = useState("");
  const [sector, setSector] = useState("");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("symbol");
  const [view, setView] = useState<View>("overview");
  const [win, setWin] = useState<Win>("out_of_sample");

  const state = useApi(
    () => api.screener({ universe: universe || undefined, sector: sector || undefined, flagged_only: flaggedOnly }),
    [universe, sector, flaggedOnly],
  );
  const anyFilter = universe !== "" || sector !== "" || flaggedOnly || search !== "";
  const clear = () => { setUniverse(""); setSector(""); setFlaggedOnly(false); setSearch(""); };

  return (
    <div>
      <div className="pagehead"><h1>Stocks</h1></div>
      <p className="note info">
        Returns shown are what simply holding each stock would have made in each window. There is no Sharpe ranking here on purpose: with 441 stocks, the top of
        such a list would mostly be lucky ones, and sorting by a recent move is only sorting, not a signal. Stocks marked ⚠ have a data problem; read the flag before the return.
      </p>
      <Panel title="Stocks" right={<Tabs label="Stocks view" value={view} onChange={(v) => setView(v as View)} items={[
        { id: "overview", label: "Prices" }, { id: "returns", label: "Returns" }, { id: "data", label: "Data checks" }, { id: "heatmap", label: "Sector heatmap" },
      ]} />}>
        <Async state={state}>
          {(data) => {
            // Ordering and searching rows is presentation, not calculation: nothing is derived.
            const needle = search.trim().toLowerCase();
            const rows = data.rows
              .filter((r) => !needle || r.symbol.toLowerCase().includes(needle))
              .sort((a, b) => sortKey === "symbol" ? a.symbol.localeCompare(b.symbol) : (sortValue(b, sortKey) ?? -Infinity) - (sortValue(a, sortKey) ?? -Infinity));
            return (
              <>
                <div className="filters">
                  <input className="search" type="search" value={search} placeholder="Find a symbol" aria-label="Find a symbol" onChange={(e) => setSearch(e.target.value)} />
                  <span className="chips" role="group" aria-label="Universe">
                    {UNIVERSES.map(([id, label]) => <Chip key={id} on={universe === id} onClick={() => { setUniverse(id); setSector(""); }}>{label}</Chip>)}
                  </span>
                  <Chip on={flaggedOnly} onClick={() => setFlaggedOnly(!flaggedOnly)}>⚠ Flagged only</Chip>
                  {anyFilter && <button type="button" className="linklike" onClick={clear}>Clear filters</button>}
                  {view === "heatmap" ? (
                    <span className="seg">
                      <button className={win === "in_sample" ? "on" : ""} onClick={() => setWin("in_sample")}>In-sample</button>
                      <button className={win === "out_of_sample" ? "on" : ""} onClick={() => setWin("out_of_sample")}>Out-of-sample</button>
                    </span>
                  ) : (
                    <label className="sortpick">
                      Sort
                      <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
                        <option value="symbol">symbol</option>
                        <option value="day">today's move</option>
                        <option value="month">1-month move</option>
                        <option value="buy_hold_return_in_sample_pct">in-sample return</option>
                        <option value="buy_hold_return_out_of_sample_pct">out-of-sample return</option>
                      </select>
                    </label>
                  )}
                </div>
                {(data.sectors ?? []).length > 0 && (
                  <details className="sectorfold" open={sector !== ""}>
                    <summary>Sector (Nifty 50){sector ? `: ${sector}` : ""}</summary>
                    <div className="chips sectorchips" role="group" aria-label="Sector">
                      {(data.sectors ?? []).map((s) => <Chip key={s} on={sector === s} onClick={() => setSector(sector === s ? "" : s)}>{s}</Chip>)}
                    </div>
                  </details>
                )}
                <p className="muted">
                  {rows.length}{rows.length !== data.rows.length ? ` of ${data.rows.length}` : ""} stocks · research data through {data.data_through} · in-sample {data.in_sample} · out-of-sample {data.out_of_sample}
                </p>
                {rows.length === 0 ? (
                  <p className="note">No stock matches these filters. <button type="button" className="linklike" onClick={clear}>Clear filters</button></p>
                ) : view === "heatmap" ? (
                  <Heatmap rows={rows} window={win} />
                ) : (
                  <div className="tablewrap scroll">
                    <table className="stack">
                      <thead>
                        {view === "overview" && <tr><th>Symbol</th><th>Universe</th><th className="num">Latest close</th><th className="num">Today</th><th className="num">1 month</th><th>Last 60 days</th><th>As of</th></tr>}
                        {view === "returns" && <tr><th>Symbol</th><th>Universe</th><th>Sector</th><th className="num">Buy&amp;hold in-sample</th><th className="num">Buy&amp;hold out-of-sample</th><th className="num">OOS max drawdown</th></tr>}
                        {view === "data" && <tr><th>Symbol</th><th>Universe</th><th className="num">Days of data</th><th>First day</th><th>Last day (research)</th><th>Flags</th></tr>}
                      </thead>
                      <tbody>
                        {rows.map((r) => {
                          const flagged = r.has_unresolved_discontinuity || !r.usable;
                          return (
                            <tr key={r.symbol} className={flagged ? "flagged" : ""}>
                              <td><Link to={`/stock/${encodeURIComponent(r.symbol)}`}>{r.symbol}{flagged ? " ⚠" : ""}</Link></td>
                              <td data-label="Universe">{r.universe}</td>
                              {view === "overview" && <>
                                <td className="num" data-label="Latest close">{r.latest ? num(r.latest.close) : <span className="muted" title="No latest price yet: this is the close at the end of the research window.">{num(r.last_close)}</span>}</td>
                                <td className={`num ${signClass(r.latest?.change_pct)}`} data-label="Today">{r.latest ? pct(r.latest.change_pct) : "—"}</td>
                                <td className={`num ${signClass(r.latest?.change_1m_pct)}`} data-label="1 month">{r.latest ? pct(r.latest.change_1m_pct) : "—"}</td>
                                <td className="spark-cell" data-label="Last 60 days">
                                  <Sparkline values={r.latest?.recent_closes} label={r.symbol} description={`${r.symbol}: closing prices over the last ${r.latest?.recent_closes?.length ?? 0} trading days`} />
                                </td>
                                <td data-label="As of">
                                  {r.latest ? day(r.latest.date) : <span className="muted">{day(r.last_date)}</span>}
                                  {r.latest?.stale && <> <span className="chip flag" title="This stock's newest price is more than a week older than the freshest stock's: it is not being updated every day.">STALE</span></>}
                                  {r.latest?.suspect && <> <span className="chip flag" title="A one-day move above 25%: check it before trusting it.">CHECK</span></>}
                                </td>
                              </>}
                              {view === "returns" && <>
                                <td data-label="Sector">{r.sector ?? "—"}</td>
                                <td className={`num ${signClass(r.buy_hold_return_in_sample_pct)}`} data-label="Buy&hold in-sample">{pct(r.buy_hold_return_in_sample_pct)}</td>
                                <td className={`num ${signClass(r.buy_hold_return_out_of_sample_pct)}`} data-label="Buy&hold out-of-sample">{pct(r.buy_hold_return_out_of_sample_pct)}</td>
                                <td className="num" data-label="OOS max drawdown">{pct(r.buy_hold_max_drawdown_out_of_sample_pct)}</td>
                              </>}
                              {view === "data" && <>
                                <td className="num" data-label="Days of data">{r.rows}</td>
                                <td data-label="First day">{day(r.first_date)}</td>
                                <td data-label="Last day (research)">{day(r.last_date)}</td>
                                <td data-label="Flags">
                                  {!r.usable && <span className="chip flag">UNUSABLE</span>}{" "}
                                  {r.has_unresolved_discontinuity && <span className="chip flag">DATA FLAG</span>}
                                  {r.usable && !r.has_unresolved_discontinuity && <span className="muted">none</span>}
                                </td>
                              </>}
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
