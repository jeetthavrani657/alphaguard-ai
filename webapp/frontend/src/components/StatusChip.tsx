/** A validation status as a small coloured label. The words are always shown, never just a colour. */
export function StatusChip({ status }: { status: string }) {
  return <span className={`chip s-${status}`}>{status.replaceAll("_", " ")}</span>;
}
