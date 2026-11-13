/** Provide one flat tokenized content surface. */
import type { PropsWithChildren } from 'react';
/** Group related content without decorative elevation. */
export function Card({ children }: PropsWithChildren) {
  return (
    <section className="card">
      {children}
    </section>
  );
}
