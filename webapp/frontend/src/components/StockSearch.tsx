import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ScreenerRow } from "../api/types";

/**
 * Type a few letters of an NSE symbol and jump to its page. The list of symbols is fetched once, the first time the box is
 * used, and filtering it is plain selection (a substring match); nothing about a stock is computed here.
 */
export function StockSearch() {
  const [rows, setRows] = useState<ScreenerRow[] | null>(null);
  const [q, setQ] = useState("");
  const [failed, setFailed] = useState(false);
  const navigate = useNavigate();
  const load = () => {
    if (rows === null && !failed) api.screener({}).then((r) => setRows(r.rows)).catch(() => setFailed(true));
  };
  const needle = q.trim().toLowerCase();
  const hits = needle && rows
    ? [...rows.filter((r) => r.symbol.toLowerCase() === needle), ...rows.filter((r) => r.symbol.toLowerCase() !== needle && r.symbol.toLowerCase().startsWith(needle)),
       ...rows.filter((r) => !r.symbol.toLowerCase().startsWith(needle) && r.symbol.toLowerCase().includes(needle))].slice(0, 7)
    : [];
  return (
    <div className="search">
      <input
        type="search" value={q} placeholder="Type a symbol, e.g. RELIANCE" aria-label="Find a stock by symbol" autoComplete="off"
        onFocus={load} onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits.length > 0) navigate(`/stock/${encodeURIComponent(hits[0].symbol)}`);
          if (e.key === "Escape") setQ("");
        }}
      />
      {needle && (
        <ul role="listbox" aria-label="Matching stocks">
          {hits.map((r) => (
            <li key={r.symbol}>
              <Link to={`/stock/${encodeURIComponent(r.symbol)}`}>
                <b>{r.symbol}</b> <span className="muted">{r.universe}{r.sector ? ` · ${r.sector}` : ""}</span>
              </Link>
            </li>
          ))}
          {hits.length === 0 && <li className="muted nohit">{rows === null && !failed ? "Loading the list…" : failed ? "The stock list could not be loaded." : "No symbol matches that."}</li>}
        </ul>
      )}
    </div>
  );
}
