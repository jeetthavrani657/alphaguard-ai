// Display formatting only: turning a number the API sent into text (or a CSS class).
// Nothing here changes a value or derives a new one.

export const num = (x: number | null | undefined, dp = 2): string =>
  x === null || x === undefined ? "—" : x.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });

export const pct = (x: number | null | undefined, dp = 1): string =>
  x === null || x === undefined ? "—" : `${num(x, dp)}%`;

export const int = (x: number | null | undefined): string =>
  x === null || x === undefined ? "—" : Math.round(x).toLocaleString("en-IN");

/** CSS class for the SIGN of a figure. The sign is also printed, so colour is never the only signal. */
export const signClass = (x: number | null | undefined): string =>
  x === null || x === undefined ? "" : x > 0 ? "pos" : x < 0 ? "neg" : "";

/** "2025-12-31" as "31 Dec 2025". A string that is not a date is shown as it came. */
export const day = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};

/** "2026-10-19T20:59:38+00:00" as "19 Oct 2026, 20:59 UTC". */
export const when = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${day(iso)}, ${d.toISOString().slice(11, 16)} UTC`;
};

/** A number of seconds as "42 seconds", "9 minutes", "14 hours" or "3 days": how long ago something was updated. */
export const ago = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined) return "—";
  const unit = (n: number, name: string) => `${Math.round(n)} ${name}${Math.round(n) === 1 ? "" : "s"}`;
  if (seconds < 90) return unit(seconds, "second");
  if (seconds < 5400) return unit(seconds / 60, "minute");
  if (seconds < 129600) return unit(seconds / 3600, "hour");
  return unit(seconds / 86400, "day");
};
