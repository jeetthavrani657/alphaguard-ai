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

/**
 * One calm message for a part that could not be shown, in words a person can act on. Not found is a plain note (nothing is broken); results that
 * have not been generated yet say how to make them; only a real failure is drawn as an error.
 */
export function ErrorNote({ message, code }: { message: string; code?: number }) {
  if (code === 404) {
    return <div className="note info" role="status"><b>We couldn't find that.</b> {message}</div>;
  }
  if (code === 503 || /generate|python |run `/i.test(message)) {
    return <div className="note info" role="status"><b>These results haven't been generated yet.</b> {message}</div>;
  }
  const cantReach = code === undefined;
  return (
    <div className="error" role="alert">
      <b>{cantReach ? "Can't reach the data service." : "Something went wrong loading this part."}</b>{" "}
      {cantReach ? "Check that the app is still running, then " : message + " "}
      <a href="." onClick={(e) => { e.preventDefault(); window.location.reload(); }}>{cantReach ? "reload the page" : "Reload the page"}</a>{cantReach ? "." : " to try again."}
    </div>
  );
}

/** Renders the loading / error states once, so every page only writes its "ready" view. */
export function Async<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => ReactNode }) {
  if (state.status === "loading") {
    return <div className="loading" role="status" aria-live="polite"><span className="sr-only">Loading…</span><Skeleton /></div>;
  }
  if (state.status === "error") return <ErrorNote message={state.message} code={state.code} />;
  return <>{children(state.data)}</>;
}
