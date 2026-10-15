import type { ReactNode } from "react";
import type { AsyncState } from "../api/useApi";

/** Renders the loading / error states once, so every page only writes its "ready" view. */
export function Async<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => ReactNode }) {
  if (state.status === "loading") return <p className="loading">Loading…</p>;
  if (state.status === "error") return <p className="error" role="alert">Could not load: {state.message}</p>;
  return <>{children(state.data)}</>;
}
