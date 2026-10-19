import { useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

/**
 * Runs `load()` when the component first appears and again whenever anything
 * in `deps` changes, and reports where the request is: loading, failed, or
 * ready. This is the standard "fetch inside a React component" pattern:
 *
 *   const state = useApi(() => api.symbol(symbol), [symbol]);
 *
 * The `cancelled` flag stops a slow, stale response from overwriting a newer
 * one (e.g. you clicked a second stock before the first finished loading).
 */
export function useApi<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    load()
      .then((data) => { if (!cancelled) setState({ status: "ready", data }); })
      .catch((e: unknown) => {
        if (!cancelled) setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}


/**
 * Like useApi, but asks again every `everyMs` milliseconds and keeps showing the last answer while it does
 * (no flicker back to "Loading"). It pauses while the browser tab is in the background. Still only a GET,
 * still through the API client: the page never talks to the network itself.
 */
export function usePolling<T>(load: () => Promise<T>, everyMs: number): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const run = () => {
      if (document.hidden) return;
      load()
        .then((data) => { if (!cancelled) setState({ status: "ready", data }); })
        .catch((e: unknown) => {
          if (!cancelled) setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
        });
    };
    run();
    const id = window.setInterval(run, everyMs);
    return () => { cancelled = true; window.clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [everyMs]);

  return state;
}
