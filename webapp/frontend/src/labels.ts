// Turning the machine names the API uses (strategy ids, indicator keys, check names) into words a person would write.
// Display only: nothing here changes a value.

const UNIVERSES: Record<string, string> = { nifty50: "Nifty 50", midcap150: "Midcap 150", smallcap250: "Smallcap 250" };
const WORDS: Record<string, string> = { ma: "MA", rsi: "RSI", sma: "SMA", oos: "out-of-sample", dip: "Dip-buying", lowvol: "Low volatility", reversal1m: "One-month reversal" };

/** "ma_crossover_nifty50" as "MA crossover · Nifty 50". */
export function strategyLabel(id: string): string {
  const parts = id.split("_");
  const universe = UNIVERSES[parts[parts.length - 1]];
  const rest = (universe ? parts.slice(0, -1) : parts).map((w, i) => WORDS[w] ?? (i === 0 ? w[0].toUpperCase() + w.slice(1) : w));
  return universe ? `${rest.join(" ")} · ${universe}` : rest.join(" ");
}

/** A validation status as the plain headline of a verdict: what a person would say, not the label of the test. The exact name stays on the status chip beside it. */
export const VERDICT: Record<string, string> = {
  VALIDATED_FAILED: "It did not pass",
  UNVALIDATED: "Too early to judge",
  OOS_ONLY_SIGNIFICANT: "It passed only in the later period",
  VALIDATED_CONFIRMED: "It passed in both periods",
  BENCHMARK_NOT_A_HYPOTHESIS: "A yardstick, not a strategy",
  SLICE_OF_POOLED_HYPOTHESIS: "One stock's part of a larger test",
};

/** "sma_50" as "SMA 50", "rsi_14" as "RSI 14". */
export const indicatorLabel = (key: string): string => key.split("_").map((w) => WORDS[w] ?? w).join(" ");

/** "no_nan_prices" as "No nan prices" (first letter capital, underscores gone). */
export const checkLabel = (name: string): string => {
  const s = name.replaceAll("_", " ");
  return s[0].toUpperCase() + s.slice(1);
};

/**
 * Text that was written for the research record (a note, a ledger entry, a definition) often points at a file or a function
 * ("see FINDINGS.md Section 7", "From engine/metrics.py exposure_series_pct"). Those pointers mean nothing to someone using the
 * app, so they are taken out when the text is shown; the reviewers' list on the How it works page says where everything lives.
 */
export function plain(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/\b(shown|pre-registered|registered|documented) in [A-Z][A-Z_]*\.md(?:,?\s*Section\s*\d+)?/g, "$1")
    .replace(/\s*(?:--|—|;|,)?\s*see\s+[A-Z][A-Z_]*\.md(?:,?\s*Section\s*\d+)?/g, "")
    .replace(/\s*From\s+[\w/]+\.py\s+\w+\.?/g, "")
    .replace(/\s*\((?:[\w/]+\.py)\)/g, "")
    .replace(/\s*;?\s*[A-Z][A-Z_]*\.md(?:,|;)?/g, "")
    .replace(/\s*\((?:[\w/]+\.py),?\s*\)/g, "")
    .replace(/\bmarket_exposure_pct\b/g, "Market exposure")
    .replace(/those are null by design/g, "those do not apply")
    .replace(/harness-governed/g, "properly tested")
    .replace(/\bthe harness('s)?\b/gi, "the testing procedure$1")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;])/g, "$1")
    .trim();
}
