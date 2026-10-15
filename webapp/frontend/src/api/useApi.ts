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
