import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi, usePolling } from "../api/useApi";
import { Async } from "../components/Async";
import { Panel } from "../components/Panel";
import { Ratio } from "../components/Ratio";
import { StatusChip } from "../components/StatusChip";
import { StrategyChart } from "../components/charts/StrategyChart";
import { int, num, pct, signClass } from "../fmt";
import type { AdvisoryForwardProfile, AdvisoryForwardResponse, ForwardBook, LiveQuote } from "../api/types";

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
        {book.days_needed_for_verdict} days{book.verdict_note ? ` ${book.verdict_note}` : ""} (criteria: {book.criteria_document}).
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

/**
 * The three multi-asset advisory profiles, run forward on paper (research/advisory_forward.py). Same discipline as the
 * books above: no verdict and no Sharpe before the pre-registered number of days. Compared with buying and holding the
 * Nifty 50 ETF. The advisory rule was frozen and counted in the ledger when it was registered, so this adds no hypothesis.
 */
function AdvisoryProfileCard({ p, need, name }: { p: AdvisoryForwardProfile; need: number; name: (id: string) => string }) {
  const s = p.summary;
  return (
    <Panel title={`${p.name} profile`} right={<span><StatusChip status={p.status} /> <span className="muted">data through {p.data_through}</span></span>}>
      <div className="clock">
        <div className="clock-head">
          <span className="stat-label">Forward clock</span>
          <span className="mono">{p.n_trading_days} of {need} trading days</span>
        </div>
        <progress value={p.n_trading_days} max={need} aria-label="forward days toward a verdict" />
      </div>
      {!s ? <p className="note info">{p.note}</p> : (
        <>
          <div className="stats" style={{ marginTop: 14 }}>
            <div className="stat">
              <span className="stat-label">Return since start</span>
              <span className={`stat-value ${signClass(s.return_pct)}`}>{pct(s.return_pct, 2)}</span>
              <span className="stat-note">Nifty 50 ETF: <b className={signClass(s.benchmark_return_pct)}>{pct(s.benchmark_return_pct, 2)}</b></span>
            </div>
            <div className="stat">
              <span className="stat-label">Worst drawdown</span>
              <span className="stat-value">{pct(s.max_drawdown_pct, 2)}</span>
              <span className="stat-note">Nifty 50 ETF: {pct(s.benchmark_max_drawdown_pct, 2)}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Invested (not in cash)</span>
              <span className="stat-value">{pct(s.exposure_pct, 0)}</span>
              <span className="stat-note">{p.guard_on ? "drawdown guard ON" : "drawdown guard off"} · {p.n_rebalances_since_start} rebalances since start</span>
            </div>
            <div className="stat">
              <span className="stat-label">Sharpe</span>
              <span className="stat-note">{s.withheld_reason || "Not computed here."}</span>
            </div>
          </div>
          <h3>Mix the rule currently recommends (formed {p.mix_as_of})</h3>
          <div className="alloc">
            {p.current_mix.map((w) => (
              <div className="alloc-row" key={w.asset_id}>
                <span>{name(w.asset_id)}</span>
                <div className="alloc-bar"><div className="alloc-fill" style={{ width: `${w.weight_pct}%` }} /></div>
                <b className="num">{pct(w.weight_pct, 1)}</b>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

function AdvisoryForward() {
  const state = useApi(() => api.advisoryForward(), []);
  const assets = useApi(() => api.advisory(), []);
  const names: Record<string, string> = {};
  if (assets.status === "ready") for (const a of assets.data.assets) names[a.id] = a.name;
  const name = (id: string) => names[id] ?? id;
  return (
    <>
      <h2 className="sectionhead">Multi-asset advisory profiles, run forward</h2>
      <Async state={state}>
        {(d: AdvisoryForwardResponse) => (
          <>
            <p className="note info">
              The three <Link to="/advisory">Advisory</Link> profiles, run on data that did not exist when the rule was frozen, from {d.start}{" "}
              (first countable session {d.first_counted_day}), against buying and holding the {d.benchmark.replace(" buy-and-hold", "")}. Paper only: nothing places an order.
              No verdict and no Sharpe before {d.days_needed_for_verdict} trading days.
            </p>
            {d.profiles.map((p) => <AdvisoryProfileCard key={p.id} p={p} need={d.days_needed_for_verdict} name={name} />)}
          </>
        )}
      </Async>
    </>
  );
}

/**
 * Near-live prices of the stocks the books hold. A display only: the books run on daily bars and never use
 * these prices. research/live_quotes.py writes them (and works out the change %); this page shows them,
 * refreshing every 10 seconds, and says so plainly when the feed is off, stale or the token has expired.
 */
function LivePrices({ books }: { books: ForwardBook[] }) {
  const state = usePolling(() => api.liveQuotes(), 10000);
  const [bookId, setBookId] = useState("all");
  return (
    <Panel title="Live prices" right={state.status === "ready" ? <LiveStatus quotes={state.data} /> : undefined}>
      <Async state={state}>
        {(d) => {
          if (!d.available) {
            return <p className="note warn">{d.reason ?? "Live prices are not available."}</p>;
          }
          const rows: LiveQuote[] = bookId === "all" ? d.quotes : d.quotes.filter((q) => q.held_by.includes(bookId));
          return (
            <>
              {d.is_stale && (
                <p className="note warn">
                  These prices are {int(d.age_seconds)} seconds old, so the price writer has probably stopped. Restart it with{" "}
                  <code>python research/live_quotes.py --loop</code>.
                </p>
              )}
              <div className="tabs" role="tablist" aria-label="Show stocks held by">
                <button role="tab" aria-selected={bookId === "all"} onClick={() => setBookId("all")}>All ({d.quotes.length})</button>
                {books.map((b) => (
                  <button key={b.id} role="tab" aria-selected={bookId === b.id} onClick={() => setBookId(b.id)}>{b.name}</button>
                ))}
              </div>
              <div className="tablewrap scroll" style={{ maxHeight: 340, marginTop: 10 }}>
                <table>
                  <thead>
                    <tr><th>Stock</th><th className="num">Last</th><th className="num">Prev close</th><th className="num">Change</th><th className="num">Volume</th></tr>
                  </thead>
                  <tbody>
                    {rows.map((q) => (
                      <tr key={q.symbol}>
                        <td><Link to={`/stock/${encodeURIComponent(q.symbol)}`}>{q.symbol}</Link></td>
                        <td className="num">{num(q.last_price)}</td>
                        <td className="num">{num(q.prev_close)}</td>
                        <td className={`num ${signClass(q.change_pct)}`}>{pct(q.change_pct, 2)}</td>
                        <td className="num">{int(q.volume)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">{d.market_note} A display only: the books trade on daily bars, not on these prices.</p>
            </>
          );
        }}
      </Async>
    </Panel>
  );
}

function LiveStatus({ quotes }: { quotes: { market_status: string; available: boolean; age_seconds?: number | null } }) {
  if (!quotes.available) return <span className="muted">feed off</span>;
  return <span><b>{quotes.market_status.toUpperCase()}</b> <span className="muted">updated {int(quotes.age_seconds)} s ago</span></span>;
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
              {Array.from(new Set(d.books.map((b) => b.criteria_document))).map((doc, i) => (
                <span key={doc}>{i > 0 && " and "}<code>{doc}</code></span>
              ))}
              . The dip-buying rule's own forward test is on the{" "}
              <Link to="/research">Research record</Link> page.
            </p>
            <LivePrices books={d.books} />
            {d.books.map((b) => <BookCard key={b.id} book={b} />)}
            <AdvisoryForward />
            <p className="muted">Generated {d.generated_at.slice(0, 16).replace("T", " ")} UTC.</p>
          </>
        )}
      </Async>
    </div>
  );
}
