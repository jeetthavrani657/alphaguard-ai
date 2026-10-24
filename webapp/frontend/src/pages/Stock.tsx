import { Link, Navigate, useParams } from "react-router-dom";
import { StockSearch } from "../components/StockSearch";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { checkLabel, strategyLabel } from "../labels";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { PriceChart } from "../components/charts/PriceChart";
import { day, int, num, pct, signClass } from "../fmt";
import type { SliceMetrics, SymbolStrategyResult } from "../api/types";

function SliceRow({ label, m, excluded }: { label: string; m: SliceMetrics | null | undefined; excluded?: string | null }) {
  if (!m) {
    return (
      <tr>
        <td>{label}</td>
        <td colSpan={5} className="wrap muted">not run: {excluded ?? "no result"}</td>
      </tr>
    );
  }
  return (
    <tr>
      <td>{label}</td>
      <td><Ratio ratio={m.sharpe} /></td>
      <td className={`num ${signClass(m.total_return_pct)}`}>{pct(m.total_return_pct)}</td>
      <td className={`num ${signClass(m.buy_hold_return_pct)}`}>{pct(m.buy_hold_return_pct)}</td>
      <td className="num">{pct(m.max_drawdown_pct)}</td>
      <td className="num">{pct(m.win_rate_pct)} of {int(m.total_trades)}</td>
      <td className="num">{pct(m.market_exposure_pct)}</td>
    </tr>
  );
}

function ResultBlock({ r }: { r: SymbolStrategyResult }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <h3>
        <Link to={`/strategies/${r.strategy_id}`}>{r.strategy_name}</Link>{" "}
        <span className="muted">pooled status</span> <StatusChip status={r.parent_status} />{" "}
        <span className="muted">as of {r.as_of_hypotheses}</span>
      </h3>
      {r.note ? (
        <p className="note info">{r.note}</p>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Window</th><th>Sharpe (this stock only)</th><th className="num">Strategy return</th>
                <th className="num">Buy&amp;hold return</th><th className="num">Max drawdown</th>
                <th className="num">Win rate (closed)</th><th className="num">Exposure</th>
              </tr>
            </thead>
            <tbody>
              <SliceRow label="in-sample" m={r.in_sample} excluded={r.excluded_in_sample} />
              <SliceRow label="out-of-sample" m={r.out_of_sample} excluded={r.excluded_out_of_sample} />
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function Stock() {
  const { symbol = "" } = useParams();
  const detail = useApi(() => api.symbol(symbol), [symbol]);
  const prices = useApi(() => api.prices(symbol), [symbol]);
  if (/\.(NS|BO)$/i.test(symbol)) return <Navigate to={`/stock/${encodeURIComponent(symbol.replace(/\.(NS|BO)$/i, ""))}`} replace />;   // people type RELIANCE.NS: the app's own names have no suffix
  if (detail.status === "error" && detail.code === 404) {
    return (
      <div>
        <Link to="/screener" className="back">← All stocks</Link>
        <div className="note info" role="status">
          <b>We don't have a stock called "{symbol}".</b> The app covers the Nifty 50, the Midcap 150 and the Smallcap 250. Search for the symbol below.
        </div>
        <div style={{ maxWidth: 420, marginTop: 12 }}><StockSearch /></div>
      </div>
    );
  }

  return (
    <div>
      <Link to="/screener" className="back">← All stocks</Link>
      <Async state={detail}>
        {(d) => (
          <div className="pagehead">
            <h1>{symbol}</h1>
            <span className="price" title={d.latest ? "The newest close the daily run holds, shown for reference." : "Split/dividend-adjusted close on the last day of the research window"}>
              ₹{num(d.latest?.close ?? d.last_close)}
            </span>
            {d.latest ? (
              <>
                <span className={signClass(d.latest.change_pct)}>{pct(d.latest.change_pct, 2)}</span>
                <span className="muted">close · {day(d.latest.date)}</span>
                {d.latest.stale && <span className="chip flag" title="This stock's newest price is more than a week older than the freshest stock's: it is not being updated every day.">STALE PRICE</span>}
                {d.latest.suspect && <span className="chip flag" title="A one-day move above 25%: check it before trusting it.">CHECK THIS MOVE</span>}
              </>
            ) : (
              <span className="muted">adj. close · {d.last_date}</span>
            )}
            <span className="chip">{d.universe}</span>
            {d.sector && <span className="chip">{d.sector}</span>}
            {!d.usable && <span className="chip flag" title="Its price data has a problem, so no strategy was tested on it.">DATA PROBLEM: NOT TESTED</span>}
            {d.quality?.discontinuities.some((x) => x.status !== "GENUINE") && (
              <span className="chip flag" title="A large one-day price move that could not be explained as a real move.">UNEXPLAINED PRICE JUMP</span>
            )}
            <span className="muted">research data {d.first_date} → {d.last_date}</span>
          </div>
        )}
      </Async>
      <Async state={detail}>
        {(d) => d.latest && d.latest.date > d.last_date ? (
          <p className="muted" style={{ margin: "0 0 10px" }}>
            The chart and every strategy on this page belong to the research window, which ends {day(d.last_date)}. The latest close above is the daily run's newest price, shown for reference only.
          </p>
        ) : null}
      </Async>

      <Panel title="Price chart, with the trades each strategy made">
        <Async state={prices}>
          {(p) => (
            <Async state={detail}>{(d) => <PriceChart prices={p} markers={d.markers} />}</Async>
          )}
        </Async>
      </Panel>

      <Async state={detail}>
        {(d) => (
          <div className="grid2">
            <Panel title="Strategy results on this stock">
              <p className="note slice">{d.caveat}</p>
              {d.results.length === 0 && <p className="muted">No registered strategy was run on this stock's universe.</p>}
              {d.results.map((r) => <ResultBlock key={r.strategy_id} r={r} />)}
            </Panel>

            <div>
              <Panel title="Data quality">
                {d.quality ? (
                  <>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {d.quality.checks.map((c) => (
                        <li key={c.name} className={c.passed ? "" : d.usable ? "muted" : "neg"}>
                          {c.passed ? "OK" : d.usable ? "Minor note" : "Problem"} — {checkLabel(c.name)}
                          {c.affected_rows > 0 ? ` (${c.affected_rows} rows)` : ""}
                        </li>
                      ))}
                    </ul>
                    {d.quality.discontinuities.length > 0 && (
                      <>
                        <h3 style={{ marginTop: 12 }}>Large single-day moves, reviewed</h3>
                        {d.quality.discontinuities.map((x) => (
                          <div key={x.date + x.status} className={x.status === "GENUINE" ? "note info" : "note"}>
                            <b>{x.date}</b> {pct(x.magnitude_pct)} <span className={`chip ${x.status === "GENUINE" ? "" : "flag"}`}>{x.status}</span>
                            {x.reason && <div className="muted" style={{ marginTop: 4 }}>{x.reason}</div>}
                          </div>
                        ))}
                      </>
                    )}
                  </>
                ) : (
                  <p className="muted">No data-quality report is available for this stock.</p>
                )}
              </Panel>

              <Panel title={`Trades on this stock · ${d.markers.length} closed, ${d.executions.length} portfolio executions`} flush>
                <div className="tablewrap scroll" style={{ maxHeight: 260 }}>
                  <table>
                    <thead><tr><th>Strategy</th><th>Entry</th><th>Exit</th><th className="num">Net return</th></tr></thead>
                    <tbody>
                      {d.markers.map((m, i) => (
                        <tr key={i}>
                          <td>{strategyLabel(m.strategy_id)}</td>
                          <td className="num">{m.entry_date} @ {num(m.entry_price)}</td>
                          <td className="num">{m.exit_date} @ {num(m.exit_price)}</td>
                          <td className={`num ${signClass(m.return_pct)}`}>{pct(m.return_pct)}</td>
                        </tr>
                      ))}
                      {d.markers.length === 0 && <tr><td colSpan={4} className="muted">none</td></tr>}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </div>
        )}
      </Async>
    </div>
  );
}
