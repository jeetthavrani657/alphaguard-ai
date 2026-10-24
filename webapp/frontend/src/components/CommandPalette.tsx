import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { NAV } from "./Sidebar";

type Item = { key: string; group: "Pages" | "Strategies" | "Stocks"; label: string; hint: string; to: string };
const LIMITS: Record<Item["group"], number> = { Pages: 6, Strategies: 5, Stocks: 8 };

/** Best first: an exact match, then names that start with the text, then names that merely contain it. Selection only; nothing is computed about a stock. */
function rank(items: Item[], needle: string): Item[] {
  const l = (i: Item) => i.label.toLowerCase();
  const hit = (i: Item) => `${i.label} ${i.hint}`.toLowerCase().includes(needle);
  return [...items.filter((i) => l(i) === needle), ...items.filter((i) => l(i) !== needle && l(i).startsWith(needle)), ...items.filter((i) => !l(i).startsWith(needle) && hit(i))];
}

/**
 * Ctrl+K (or the search box in the top bar): jump to a page, a strategy or a stock. The strategy and stock lists are fetched the first time it opens.
 * Arrow keys move, Enter goes, Escape closes; focus returns to where it was.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [strategies, setStrategies] = useState<Item[] | null>(null);
  const [stocks, setStocks] = useState<Item[] | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const before = useRef<Element | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    before.current = document.activeElement;
    setQ("");
    setActive(0);
    window.setTimeout(() => input.current?.focus(), 0);
    if (strategies === null) {
      api.strategies()
        .then((d) => setStrategies(d.strategies.map((s) => ({ key: `s:${s.id}`, group: "Strategies" as const, label: s.name, hint: s.universe, to: `/strategies/${s.id}` }))))
        .catch(() => setStrategies([]));
    }
    if (stocks === null) {
      api.screener({})
        .then((d) => setStocks(d.rows.map((r) => ({ key: `k:${r.symbol}`, group: "Stocks" as const, label: r.symbol, hint: `${r.universe}${r.sector ? ` · ${r.sector}` : ""}`, to: `/stock/${encodeURIComponent(r.symbol)}` }))))
        .catch(() => setStocks([]));
    }
    return () => { (before.current as HTMLElement | null)?.focus?.(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const pages: Item[] = useMemo(() => NAV.flatMap((g) => g.items.map((i) => ({ key: `p:${i.to}`, group: "Pages" as const, label: i.label, hint: g.group, to: i.to }))), []);
  const results: Item[] = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return pages.slice(0, LIMITS.Pages + 2);
    return [
      ...rank(pages, needle).slice(0, LIMITS.Pages),
      ...rank(strategies ?? [], needle).slice(0, LIMITS.Strategies),
      ...rank(stocks ?? [], needle).slice(0, LIMITS.Stocks),
    ];
  }, [q, pages, strategies, stocks]);

  if (!open) return null;
  const go = (i: Item | undefined) => { if (i) { onClose(); navigate(i.to); } };
  const loading = q.trim() !== "" && (strategies === null || stocks === null);
  let lastGroup = "";
  return (
    <div className="palette-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search">
        <input
          ref={input} type="search" value={q} placeholder="Type a stock symbol, a rule or a page" autoComplete="off" aria-label="Search stocks, rules and pages"
          role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={results[active] ? `opt-${results[active].key}` : undefined}
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, Math.max(results.length - 1, 0))); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            else if (e.key === "Enter") { e.preventDefault(); go(results[active]); }
          }}
        />
        <ul id="palette-list" role="listbox" aria-label="Results">
          {results.map((r, i) => {
            const head = r.group !== lastGroup ? r.group : null;
            lastGroup = r.group;
            return (
              <li key={r.key} role="presentation">
                {head && <div className="palette-group">{head}</div>}
                <div
                  id={`opt-${r.key}`} role="option" aria-selected={i === active} className={`palette-opt${i === active ? " active" : ""}`}
                  onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); go(r); }}
                >
                  <b>{r.label}</b> <span className="muted">{r.hint}</span>
                </div>
              </li>
            );
          })}
          {results.length === 0 && <li className="palette-empty">{loading ? "Searching…" : `Nothing matches "${q.trim()}". Try a stock symbol such as RELIANCE.`}</li>}
        </ul>
        <div className="palette-foot"><kbd>↑</kbd> <kbd>↓</kbd> to move, <kbd>Enter</kbd> to open, <kbd>Esc</kbd> to close</div>
      </div>
    </div>
  );
}
