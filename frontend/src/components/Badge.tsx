/** Display status without relying on color alone. */
/** Use the existing neutral tonal surface for compact inventory states. */
export function Badge({ children }: { children: string }) {
  return (
    <span className="badge" role="status">{children}</span>
  );
}
