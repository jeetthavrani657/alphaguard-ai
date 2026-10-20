import { useRef, type KeyboardEvent, type ReactNode } from "react";

/**
 * A row of tabs that works from the keyboard as well as the mouse: Tab moves into the row (onto the chosen tab), the left and
 * right arrows move between tabs and choose them, Home and End jump to the first and last. Only the chosen tab is in the Tab order,
 * as screen-reader users expect.
 */
export function Tabs({ label, items, value, onChange }: { label: string; items: { id: string; label: ReactNode }[]; value: string; onChange: (id: string) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (to: number) => {
    const next = (to + items.length) % items.length;
    onChange(items[next].id);
    refs.current[next]?.focus();
  };
  const onKey = (e: KeyboardEvent, i: number) => {
    if (e.key === "ArrowRight") { e.preventDefault(); move(i + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); move(i - 1); }
    else if (e.key === "Home") { e.preventDefault(); move(0); }
    else if (e.key === "End") { e.preventDefault(); move(items.length - 1); }
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((it, i) => (
        <button
          key={it.id} role="tab" ref={(el) => { refs.current[i] = el; }}
          aria-selected={value === it.id} tabIndex={value === it.id ? 0 : -1}
          onClick={() => onChange(it.id)} onKeyDown={(e) => onKey(e, i)}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
