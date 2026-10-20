import type { ReactNode } from "react";

/** A titled box. `right` is for small controls or captions in the title bar. */
export function Panel({ title, right, flush, children, id }: { title: ReactNode; right?: ReactNode; flush?: boolean; children: ReactNode; id?: string }) {
  return (
    <section className="panel" id={id}>
      <header>
        <h2>{title}</h2>
        {right}
      </header>
      <div className={flush ? "body flush" : "body"}>{children}</div>
    </section>
  );
}
