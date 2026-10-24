import type { ReactNode } from "react";

/**
 * A long explanation that most visitors have read once: it stays one click away instead of pushing the page's content below the first screen.
 * Closed by default; the summary line says what is inside.
 */
export function ReadFirst({ summary, children }: { summary: ReactNode; children: ReactNode }) {
  return (
    <details className="readfirst">
      <summary>{summary}</summary>
      <div className="readfirst-body">{children}</div>
    </details>
  );
}

/**
 * The disclaimer, never hidden: its one-line form is always on the page, and the full text (the regulatory wording, the "not advice" note) is one
 * click below it. `text` is the API's own disclaimer, shown untouched.
 */
export function Disclaimer({ text, extra }: { text: string; extra?: ReactNode }) {
  return (
    <div className="note disclaimer">
      <b>Educational research, not investment advice.</b> It places no orders.
      <details>
        <summary>Read the full note</summary>
        <p>{text}</p>
        {extra}
      </details>
    </div>
  );
}
