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
