import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { day, when } from "../fmt";

/**
 * The strip across the top: is everything up to date, which date the research prices run to, and how many ideas have been
 * tried. A problem is always shown on the strip itself; the technical details (when the results were produced, which version of
 * the code) are one click away. Every value is read from the API; nothing here is simulated.
 */
export function StatusBar() {
  const state = useApi(() => api.health(), []);
  if (state.status === "loading") return <div className="statusbar">Connecting…</div>;
  if (state.status === "error") {
    return <div className="statusbar"><span className="bad">● Can't reach the data service</span> <span>{state.message}</span></div>;
  }
  const h = state.data;
  const problems: string[] = [];
  if (!h.ok) problems.push(h.detail ?? "The data service is not ready.");
  if (h.snapshot_stale) problems.push(`Results were computed when ${h.snapshot_ledger_total} ideas had been tried; more have been added since.`);
  if (h.forward_health_stale) problems.push("The daily paper-test health check has stopped running.");
  else if (h.forward_health && h.forward_health !== "OK") problems.push(`Daily paper test: ${h.forward_health}. ${h.forward_health_problems.join(" · ")}`);
  const good = problems.length === 0;
  return (
    <div className="statusbar">
      <span className={good ? "ok" : "warn"} title={good ? "Data, results and the daily paper test are all up to date." : problems.join(" ")}>
        ● {good ? "All up to date" : "Needs attention"}
      </span>
      <span>Backtest prices through <b>{day(h.data_through)}</b></span>
      <span><b>{h.ledger_total_now ?? "—"}</b> ideas tested so far</span>
      {problems.map((p) => <span className="warn" key={p}>⚠ {p}</span>)}
      <details className="tech">
        <summary>Details</summary>
        <div>
          <p>Results generated <b>{when(h.snapshot_generated_at)}</b></p>
          <p>Research prices are adjusted for splits and dividends and run to the date above. Live prices are on the Paper trading page.</p>
        </div>
      </details>
    </div>
  );
}
