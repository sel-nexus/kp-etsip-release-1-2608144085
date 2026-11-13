/** Share bounded page controls while callers own URL navigation. */
import { Button } from './Button';
interface PaginationProps { page: number; pageSize: number; total: number; onPage: (page: number) => void }
/** Keep empty and out-of-range pages navigable back to available results. */
export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="pagination" aria-label="Pagination">
      <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
      <span aria-current="page">Page {page} of {pages} · {total} results</span>
      <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
    </nav>
  );
}
