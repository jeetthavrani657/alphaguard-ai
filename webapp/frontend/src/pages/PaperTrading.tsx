import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { StrategyChart } from "../components/charts/StrategyChart";
import { int, num, pct, signClass } from "../fmt";
import type { ForwardBook } from "../api/types";

/**
 * Paper trading: the frozen candidate strategies, run forward on data that did not exist when they
 * were frozen (FORWARD_BOOKS.md). Nothing here places an order. Every figure is what
 * research/forward_books.py computed with the same engine as the backtests; this page only shows it.
 *
 * The honest feature is the clock: before a full year of forward days there is no verdict, and the
 * page says so instead of letting an early number look like evidence.
 */
const EXPOSURE_TEXT: Record<ForwardBook["kind"], string> = {
  per_symbol: "Share of the book's stocks that are long on each date (a stock not yet listed is absent, not counted as cash).",
  portfolio: "The engine's momentum definition: 0% until the first rebalance executes, 100% after. It does not measure cash held once invested.",
};

function Clock({ book }: { book: ForwardBook }) {
  return (
    <div className="clock">
      <div className="clock-head">
        <span className="stat-label">Forward clock</span>
        <span className="mono">{book.n_trading_days} of {book.days_needed_for_verdict} trading days</span>
      </div>
      <progress value={book.n_trading_days} max={book.days_needed_for_verdict} aria-label="forward days toward a verdict" />
      <span className="muted">
        Started {book.start}; first countable session {book.first_counted_day}. No verdict before{" "}
        {book.days_needed_for_verdict} days.
      </span>
    </div>
  );
}

function BookCard({ book }: { book: ForwardBook }) {
  const s = book.summary;
  return (
    <Panel
      title={book.name}
      right={<span><StatusChip status={book.status} /> <span className="muted">data through {book.data_through}</span></span>}
    >
      <p className="muted">{book.rationale}</p>
      <p className="note slice"><b>Why this is being tracked:</b> {book.why_forward_tested}</p>
      <Clock book={book} />

      {book.status === "NOT_STARTED" || !s ? (
        <>
          {book.notes.map((n) => <p className="note info" key={n}>{n}</p>)}
          {book.pending.length > 0 && (
            <>
              <h3>Signals pending at the last close</h3>
              <ul>{book.pending.map((p) => <li key={p.symbol + p.action}>{p.symbol}: {p.action}</li>)}</ul>
            </>
          )}
        </>
      ) : (
        <>
          <div className="stats" style={{ marginTop: 14 }}>
            <div className="stat">
              <span className="stat-label">Return since start</span>
              <span className={`stat-value ${signClass(s.return_pct)}`}>{pct(s.return_pct)}</span>
              <span className="stat-note">Buy &amp; hold, same stocks: <b className={signClass(s.benchmark_return_pct)}>{pct(s.benchmark_return_pct)}</b></span>
            </div>
            <div className="stat">
              <span className="stat-label">Worst drawdown</span>
              <span className="stat-value">{pct(s.max_drawdown_pct)}</span>
              <span className="stat-note">Buy &amp; hold: {pct(s.benchmark_max_drawdown_pct)}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Market exposure</span>
              <span className="stat-value">{pct(s.market_exposure_pct, 0)}</span>
              <span className="stat-note">{int(s.n_open_positions)} open positions · {s.n_closed_trades === null ? "rebalanced portfolio" : `${int(s.n_closed_trades)} closed trades`}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Sharpe, with its status</span>
              {book.risk_adjusted.book ? (
                <>
                  <span className="stat-note"><Ratio ratio={book.risk_adjusted.book} /></span>
                  {book.risk_adjusted.benchmark && <span className="stat-note">Buy &amp; hold: <Ratio ratio={book.risk_adjusted.benchmark} /></span>}
                </>
              ) : (
                <span className="stat-note">{book.risk_adjusted.withheld_reason ?? "Withheld."}</span>
              )}
            </div>
          </div>

          {book.growth_book && book.growth_benchmark && (
            <StrategyChart
              data={{
                growth_strategy: book.growth_book, growth_benchmark: book.growth_benchmark,
                drawdown_strategy_pct: book.drawdown_book, drawdown_benchmark_pct: book.drawdown_benchmark,
                exposure_strategy_pct: book.exposure, exposure_definition: EXPOSURE_TEXT[book.kind],
              }}
            />
          )}

          <div className="grid2" style={{ marginTop: 14 }}>
            <div>
              <h3>{book.kind === "portfolio" ? "Latest target holdings" : "Open positions"}</h3>
              {book.holdings.length === 0 ? <p className="muted">None.</p> : (
                <div className="tablewrap scroll" style={{ maxHeight: 260 }}>
                  <table>
                    <thead>
                      <tr><th>Stock</th><th className="num">{book.kind === "portfolio" ? "Target weight" : "Entry → last close"}</th></tr>
                    </thead>
                    <tbody>
                      {book.holdings.map((h) => (
                        <tr key={h.symbol}>
                          <td><Link to={`/stock/${encodeURIComponent(h.symbol)}`}>{h.symbol}</Link></td>
                          <td className="num">
                            {h.target_weight_pct !== null && h.target_weight_pct !== undefined
                              ? pct(h.target_weight_pct, 1)
                              : `${num(h.entry_price)} → ${num(h.last_close)} (since ${h.since})`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div>
              <h3>Signals pending for the next open</h3>
              {book.pending.length === 0 ? <p className="muted">None at the last close.</p> : (
                <ul>{book.pending.map((p) => <li key={p.symbol + p.action}>{p.symbol}: {p.action}</li>)}</ul>
              )}
              {book.notes.map((n) => <p className="muted" key={n}>{n}</p>)}
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}

export function PaperTrading() {
  const state = useApi(() => api.forwardBooks(), []);
  return (
    <div>
      <div className="pagehead"><h1>Paper trading</h1></div>
      <Async state={state}>
        {(d) => (
          <>
            <p className="note info">
              {d.disclaimer} The books and their pass criteria were frozen before any forward data existed, in{" "}
              <code>{d.criteria_document}</code>. The dip-buying rule's own forward test is on the{" "}
              <Link to="/research">Research record</Link> page.
            </p>
            {d.books.map((b) => <BookCard key={b.id} book={b} />)}
            <p className="muted">Generated {d.generated_at.slice(0, 16).replace("T", " ")} UTC.</p>
          </>
        )}
      </Async>
    </div>
  );
}
