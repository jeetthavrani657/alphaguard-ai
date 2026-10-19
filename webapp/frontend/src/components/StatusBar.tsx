import { api } from "../api/client";
import { useApi } from "../api/useApi";

/**
 * The strip across the top. Where FINAGENT shows a live index ticker, this
 * shows what is actually true about THIS data: how fresh it is, which code
 * produced it, and how many hypotheses stand behind every status on screen.
 * Every value is read from the API; nothing here is simulated.
 */
export function StatusBar() {
  const state = useApi(() => api.health(), []);
  if (state.status === "loading") return <div className="statusbar">connecting to API…</div>;
  if (state.status === "error") {
    return <div className="statusbar"><span className="bad">API UNREACHABLE</span> {state.message}</div>;
  }
  const h = state.data;
  return (
    <div className="statusbar">
      <span className={h.ok ? "ok" : "bad"}>● {h.ok ? "API OK" : "API NOT READY"}</span>
      {!h.ok && <span className="warn">{h.detail}</span>}
      <span>DATA THROUGH <b>{h.data_through ?? "—"}</b></span>
      <span>LEDGER <b>{h.ledger_total_now ?? "—"}</b> hypotheses</span>
      {h.snapshot_stale && <span className="warn">⚠ RESULTS COMPUTED AT {h.snapshot_ledger_total} — STALE</span>}
      {h.forward_health && (
        h.forward_health_stale ? (
          <span className="warn">⚠ FORWARD-TEST HEALTH CHECK HAS STOPPED (last {h.forward_health_generated_at?.slice(0, 16).replace("T", " ")} UTC)</span>
        ) : h.forward_health === "OK" ? (
          <span>FORWARD TEST <b className="ok">OK</b></span>
        ) : (
          <span className={h.forward_health === "FAIL" ? "bad" : "warn"}>
            ⚠ FORWARD TEST {h.forward_health}: {h.forward_health_problems.join(" · ")}
          </span>
        )
      )}
      <span>RESULTS GENERATED <b>{h.snapshot_generated_at?.slice(0, 16).replace("T", " ") ?? "—"}</b> UTC</span>
      <span>
        CODE <b>{h.git_commit ?? "?"}</b>
        {h.git_dirty ? <span className="warn"> +uncommitted changes</span> : null}
      </span>
      <span>RESEARCH PRICES: SPLIT/DIVIDEND-ADJUSTED, THROUGH THE DATE ABOVE</span>
    </div>
  );
}
