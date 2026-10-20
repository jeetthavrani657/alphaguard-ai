import type { ReactNode } from "react";
import type { AsyncState } from "../api/useApi";

/** A shimmering placeholder block, so a page keeps its shape while its numbers load. */
export function Skeleton({ lines = 3, height = 14 }: { lines?: number; height?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <span key={i} style={{ height, width: `${92 - ((i * 17) % 40)}%` }} />)}
    </div>
  );
}

/** Renders the loading / error states once, so every page only writes its "ready" view. */
export function Async<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => ReactNode }) {
  if (state.status === "loading") {
    return <div className="loading" role="status" aria-live="polite"><span className="sr-only">Loading…</span><Skeleton /></div>;
  }
  if (state.status === "error") {
    return (
      <div className="error" role="alert">
        <b>This part could not be loaded.</b> {state.message}
        <div className="muted">If the message talks about a missing file, the command to create it is given above. Otherwise <a href="." onClick={(e) => { e.preventDefault(); window.location.reload(); }}>reload the page</a>.</div>
      </div>
    );
  }
  return <>{children(state.data)}</>;
}
