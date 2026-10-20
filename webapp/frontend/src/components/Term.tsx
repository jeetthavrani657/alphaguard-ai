import { useState, type ReactNode } from "react";
import { GLOSSARY } from "../glossary";

/**
 * A word with a dotted underline that explains itself on hover, on keyboard focus, or on a tap. The explanation comes from
 * glossary.ts, so every page says the same thing. The tooltip is `position: fixed`, so a table's scroll area never clips it.
 */
export function Term({ k, children }: { k: string; children?: ReactNode }) {
  const entry = GLOSSARY[k];
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  if (!entry) return <>{children}</>;
  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setPos({ x: Math.max(8, Math.min(r.left, window.innerWidth - 300)), y: r.bottom + 6 });
  };
  return (
    <span
      className="term" tabIndex={0}
      onMouseEnter={(e) => show(e.currentTarget)} onMouseLeave={() => setPos(null)}
      onFocus={(e) => show(e.currentTarget)} onBlur={() => setPos(null)}
      onClick={(e) => (pos ? setPos(null) : show(e.currentTarget))}
      onKeyDown={(e) => { if (e.key === "Escape") setPos(null); }}
    >
      {children ?? entry.term}
      <span className="sr-only"> ({entry.short})</span>
      {pos && (
        <span className="tip" role="tooltip" style={{ left: pos.x, top: pos.y }}>
          <b>{entry.term}</b>
          {entry.short}
        </span>
      )}
    </span>
  );
}
