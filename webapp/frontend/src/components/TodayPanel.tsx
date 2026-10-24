import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Async } from "./Async";
import { Sparkline } from "./Sparkline";
import { day, pct, signClass } from "../fmt";

type Tile = { id: string; name: string; to: string; days: number; need: number; ret?: number | null; bench?: number | null; growth?: number[] | null; growthBench?: number[] | null };

/**
 * What is true today, before anything else on the home page: how fresh the data is, whether execution is locked, and how every paper test stands
 * with a small picture of its path. Every figure is read from the API; the only things counted here are the tiles drawn.
 */
export function TodayPanel() {
  const health = useApi(() => api.health(), []);
  const golive = useApi(() => api.golive(), []);
  const books = useApi(() => api.forwardBooks(), []);
  const adv = useApi(() => api.advisoryForward(), []);

  const tiles: Tile[] = [];
  if (books.status === "ready") {
    for (const b of books.data.books) {
      tiles.push({ id: b.id, name: b.name, to: `/paper#book-${b.id}`, days: b.n_trading_days, need: b.days_needed_for_verdict, ret: b.summary?.return_pct, bench: b.summary?.benchmark_return_pct, growth: b.growth_book?.values, growthBench: b.growth_benchmark?.values });
    }
  }
  if (adv.status === "ready") {
    for (const p of adv.data.profiles) {
      tiles.push({ id: p.id, name: p.name, to: "/paper", days: p.n_trading_days, need: adv.data.days_needed_for_verdict, ret: p.summary?.return_pct, bench: p.summary?.benchmark_return_pct, growth: p.growth_strategy?.values, growthBench: p.growth_benchmark?.values });
    }
  }

  return (
    <section className="today" aria-label="Today">
      <h2 className="section-title">Today</h2>
      <div className="today-cards">
        <div className="today-card">
          <span className="stat-label">Data</span>
          <Async state={health}>
            {(h) => (
              <>
                <span className="today-value">{h.latest_prices_through ? day(h.latest_prices_through) : "—"}</span>
                <span className="stat-note">
                  Latest prices. Backtests were judged through {day(h.data_through)}.{" "}
                  {h.forward_health ? <>Daily paper-test check: <b className={h.forward_health === "OK" ? "pos" : "neg"}>{h.forward_health}</b>.</> : null}
                </span>
              </>
            )}
          </Async>
        </div>
        <div className="today-card">
          <span className="stat-label">Paper tests</span>
          <span className="today-value">{tiles.length > 0 ? `${tiles.length} running` : "—"}</span>
          <span className="stat-note">Each runs forward on new days with no real money. No verdict before its own number of days.</span>
        </div>
        <div className="today-card today-lock">
          <span className="stat-label">Execution</span>
          <Async state={golive}>
            {(g) => (
              <>
                <span className="today-value">{g.execution_locked ? "Locked" : "Check the rules"}</span>
                <span className="stat-note">
                  {g.rules.filter((r) => r.eligible).length} of {g.rules.length} paper rules meet every go-live gate. Nothing here places an order.{" "}
                  <Link to="/paper#go-live">See the gates</Link>
                </span>
              </>
            )}
          </Async>
        </div>
      </div>
      {tiles.length > 0 && (
        <div className="today-grid">
          {tiles.map((t) => (
            <Link key={t.id} className="today-tile" to={t.to}>
              <span className="tile-name">{t.name}</span>
              <Sparkline values={t.growth} benchmark={t.growthBench} label={t.name} />
              <span className="tile-meta">
                <span className="mono">day {t.days} of {t.need}</span>
                <b className={signClass(t.ret)}>{t.ret === null || t.ret === undefined ? "—" : pct(t.ret, 2)}</b>
                <span className="muted">vs {t.bench === null || t.bench === undefined ? "—" : pct(t.bench, 2)}</span>
              </span>
            </Link>
          ))}
        </div>
      )}
      <p className="muted today-foot">These are daily moves, not evidence: no paper test can be judged before it has run its full length. The dashed line is what holding the same assets would have done.</p>
    </section>
  );
}
