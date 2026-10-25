import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Simple or Detailed. The same pages, the same numbers: in Simple the long parts are folded closed behind a clear "Show" line, in Detailed they are open. Nothing is removed in either mode,
 * so every figure stays one click away, and the two things that never fold are the disclaimer and the status that sits beside every ratio.
 * The choice is a convenience, remembered in this browser only; browser storage can be blocked, so every access is guarded.
 */
export type ViewMode = "simple" | "detailed";
const KEY = "alphaguard-view";

function firstMode(): ViewMode {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "simple" || saved === "detailed") return saved;
  } catch { /* storage unavailable: fall through */ }
  return "simple";                                   // a first visit starts with the short version
}

const Ctx = createContext<{ mode: ViewMode; setMode: (m: ViewMode) => void }>({ mode: "simple", setMode: () => undefined });

export function ViewModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ViewMode>(firstMode);
  useEffect(() => {
    document.documentElement.setAttribute("data-view", mode);
    try { localStorage.setItem(KEY, mode); } catch { /* not saved: still works for this visit */ }
  }, [mode]);
  const setMode = useCallback((m: ViewMode) => setModeState(m), []);
  return <Ctx.Provider value={{ mode, setMode }}>{children}</Ctx.Provider>;
}

export const useViewMode = () => useContext(Ctx);

/**
 * A part of a page that can be folded: a title line you can always see, and the content under it. Closed in Simple, open in Detailed; either way you can open or close it yourself.
 * Changing the mode redraws it in the new state. `hint` says in a few words what is inside, so the closed line is a promise and not a mystery.
 */
export function Fold({ title, hint, children, id }: { title: ReactNode; hint?: ReactNode; children: ReactNode; id?: string }) {
  const { mode } = useViewMode();
  const ref = useRef<HTMLDetailsElement>(null);
  // A link to a part inside a closed fold (/paper#book-xyz) must still land on it: open the fold that holds the target, then scroll to the target.
  useEffect(() => {
    const reveal = () => {
      const target = decodeURIComponent(window.location.hash.slice(1));
      const el = target ? document.getElementById(target) : null;
      if (el && ref.current && ref.current !== el && ref.current.contains(el) && !ref.current.open) {
        ref.current.open = true;
        el.scrollIntoView();
      }
    };
    reveal();
    window.addEventListener("hashchange", reveal);
    return () => window.removeEventListener("hashchange", reveal);
  }, [mode]);
  return (
    <details className="fold" key={mode} ref={ref} open={mode === "detailed"} id={id}>
      <summary>
        <span className="fold-title">{title}</span>
        {hint && <span className="fold-hint">{hint}</span>}
        <span className="fold-cue" aria-hidden="true" />
      </summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}

/** The two-way switch for the top bar. */
export function ViewSwitch() {
  const { mode, setMode } = useViewMode();
  return (
    <span className="seg viewswitch" role="group" aria-label="How much to show">
      <button type="button" className={mode === "simple" ? "on" : ""} aria-pressed={mode === "simple"} onClick={() => setMode("simple")} title="The short version: the answer first, details folded away">Simple</button>
      <button type="button" className={mode === "detailed" ? "on" : ""} aria-pressed={mode === "detailed"} onClick={() => setMode("detailed")} title="Everything open, as in a research notebook">Detailed</button>
    </span>
  );
}
