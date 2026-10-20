import { Term } from "./Term";

/** A validation status as a small coloured label. The words are always shown, never just a colour; hovering explains them. */
export function StatusChip({ status }: { status: string }) {
  return <span className={`chip s-${status}`}><Term k={status}>{status.replaceAll("_", " ")}</Term></span>;
}
