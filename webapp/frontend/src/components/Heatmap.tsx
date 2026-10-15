import { Link } from "react-router-dom";
import type { ScreenerRow } from "../api/types";
import { pct } from "../fmt";

type Win = "in_sample" | "out_of_sample";

// Display buckets only: which colour a return falls in. The legend below shows
// the exact cut-offs, and the percentage is printed on every tile, so colour is
// never the only carrier of the number.
const BUCKETS: { upTo: number; cls: string; label: string }[] = [
  { upTo: -20, cls: "h-neg3", label: "≤ −20%" },
  { upTo: -5, cls: "h-neg2", label: "−20…−5%" },
  { upTo: 0, cls: "h-neg1", label: "−5…0%" },
  { upTo: 25, cls: "h-pos1", label: "0…25%" },
  { upTo: 100, cls: "h-pos2", label: "25…100%" },
  { upTo: 300, cls: "h-pos3", label: "100…300%" },
  { upTo: Infinity, cls: "h-pos4", label: "> 300%" },
];
const bucketOf = (v: number) => BUCKETS.find((b) => v <= b.upTo)!;

/**
 * Stocks grouped by sector, one equal-sized tile each, coloured by the
 * engine's buy-and-hold return for the chosen window.
 *
 * No tile sizes by market cap (the project has no market-cap data) and no
 * sector averages (that would be a new calculation). Only classified stocks
 * appear in sector groups; Nifty 50 is the only universe with a sector map.
 */
export function Heatmap({ rows, window }: { rows: ScreenerRow[]; window: Win }) {
  const key = window === "in_sample" ? "buy_hold_return_in_sample_pct" : "buy_hold_return_out_of_sample_pct";
  const classified = rows.filter((r) => r.sector);
  const bySector = new Map<string, ScreenerRow[]>();
  for (const r of classified) bySector.set(r.sector!, [...(bySector.get(r.sector!) ?? []), r]);
  const sectors = [...bySector.keys()].sort();
  const unclassified = rows.length - classified.length;

  return (
    <div>
      <div className="legend" style={{ marginBottom: 12 }}>
        {BUCKETS.map((b) => (
          <span key={b.cls}><i className={b.cls} /> {b.label}</span>
        ))}
        <span><i style={{ border: "1px dashed var(--warn)" }} /> data flag</span>
        <span><i className="tile na" /> not run in this window</span>
      </div>
      {sectors.map((s) => (
        <div className="heat-sector" key={s}>
          <h2>{s}</h2>
          <div className="tiles">
            {bySector.get(s)!.map((r) => {
              const v = r[key];
              const cls = v === null || v === undefined ? "na" : bucketOf(v).cls;
              return (
                <Link
                  key={r.symbol}
                  to={`/stock/${encodeURIComponent(r.symbol)}`}
                  className={`tile ${cls} ${r.has_unresolved_discontinuity || !r.usable ? "flagged" : ""}`}
                  title={r.has_unresolved_discontinuity ? "Unresolved data discontinuity — read the stock page before trusting this return" : undefined}
                >
                  <span className="sym">{r.symbol}{r.has_unresolved_discontinuity || !r.usable ? " ⚠" : ""}</span>
                  <span className="ret">{v === null || v === undefined ? "not run" : pct(v, 0)}</span>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
      {unclassified > 0 && (
        <p className="muted">
          {unclassified} stock{unclassified === 1 ? "" : "s"} in this selection have no sector in the project
          (config.SECTOR_MAP covers the Nifty 50 only) and appear in the table view, not here.
        </p>
      )}
    </div>
  );
}
