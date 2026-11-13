/** Browse visible portfolios with shareable filters and explicit admin actions. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useSession } from '../auth/SessionProvider';
import { portfolioApi } from './portfolioApi';
import { PortfolioForm } from './PortfolioForm';
import { Button } from '../../components/Button';
import { DataTable } from '../../components/DataTable';
import { Badge } from '../../components/Badge';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import type { Page, Portfolio } from '../../types';
/** Keep stale requests from repainting another URL's authorized results. */
export default function PortfolioList() {
  const { user } = useSession();
  const admin = user?.role === 'Administrator';
  const [query, setQuery] = useSearchParams();
  const key = query.toString();
  useEffect(() => { document.title = 'Portfolios · KP ETSIP'; }, []);
  const [data, setData] = useState<Page<Portfolio> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [edit, setEdit] = useState<Portfolio | 'new' | null>(null);
  const [removing, setRemoving] = useState<Portfolio | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null); setData(null);
    portfolioApi.list(new URLSearchParams(key)).then((result) => { if (active) setData(result); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load portfolios'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, revision]);
  const filter = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const name of ['search', 'status', 'productArea', 'pageSize']) {
      const value = String(fields.get(name) ?? '').trim();
      if (value) next.set(name, value);
    }
    next.set('page', '1'); setQuery(next);
  };
  const deletePortfolio = async () => {
    if (!removing) return;
    setDeleting(true); setDeleteError(null);
    try {
      await portfolioApi.delete(removing.id, removing.updatedAt);
      setRemoving(null); setNotice('Portfolio deleted'); setRevision((value) => value + 1);
    } catch (failure) {
      setDeleteError(failure instanceof Error ? failure.message : 'Unable to delete portfolio');
    } finally { setDeleting(false); }
  };
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Portfolios</h1>
          <p className="muted">Find portfolio ownership and application quality across your authorized inventory.</p>
        </div>
        {admin && <Button onClick={() => setEdit('new')}>Create portfolio</Button>}
      </div>
      <form className="filters" key={key} onSubmit={filter}>
        <div className="form-field">
          <label htmlFor="search">Search names</label>
          <input id="search" name="search" defaultValue={query.get('search') ?? ''} maxLength={200} type="search" />
        </div>
        <div className="form-field">
          <label htmlFor="filter-status">Filter status</label>
          <select id="filter-status" name="status" defaultValue={query.get('status') ?? ''}>
            <option value="">All statuses</option>
            <option value="Active">Active</option>
            <option value="Archived">Archived</option>
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="area">Filter product area</label>
          <input id="area" name="productArea" defaultValue={query.get('productArea') ?? ''} maxLength={200} />
        </div>
        <div className="form-field">
          <label htmlFor="page-size">Rows per page</label>
          <select id="page-size" name="pageSize" defaultValue={query.get('pageSize') ?? '25'}>
            {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </div>
        <Button type="submit" variant="secondary">Apply filters</Button>
        <Button type="button" variant="secondary" onClick={() => setQuery({})}>Clear filters</Button>
      </form>
      <p role="status" aria-live="polite">{notice}</p>
      {loading && <p role="status">Loading portfolios…</p>}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {!loading && data && (
        <>
          {data.items.length === 0 ? (
            <p role="status">{query.get('search') || query.get('status') || query.get('productArea')
              ? 'No portfolios match these filters.' : 'No portfolios available in your scope.'}</p>
          ) : (
            <DataTable caption="Portfolio inventory" rows={data.items} rowKey={(row) => row.id} columns={[
              { key: 'name', label: 'Name', render: (row) => <Link to={`/portfolios/${row.id}`}>{row.name}</Link> },
              { key: 'owner', label: 'Owner', render: (row) => row.ownerName },
              { key: 'area', label: 'Product area', render: (row) => row.productArea },
              { key: 'status', label: 'Status', render: (row) => <Badge>{row.status}</Badge> },
              { key: 'count', label: 'Applications', render: (row) => row.applicationCount },
              { key: 'quality', label: 'Quality score', render: (row) => row.qualityScore ?? 'Not available' },
              ...(admin ? [{ key: 'actions', label: 'Actions', render: (row: Portfolio) => (
                <div className="actions">
                  <Button variant="secondary" onClick={() => setEdit(row)} aria-label={`Edit ${row.name}`}>Edit</Button>
                  <Button variant="secondary" aria-label={`Delete ${row.name}`} onClick={() => {
                    setRemoving(row); setDeleteError(null);
                  }}>Delete</Button>
                </div>
              ) }] : []),
            ]} />
          )}
          <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPage={(page) => {
            const next = new URLSearchParams(query); next.set('page', String(page)); setQuery(next);
          }} />
        </>
      )}
      {edit && (
        <Modal title={edit === 'new' ? 'Create portfolio' : 'Edit portfolio'} onClose={() => setEdit(null)}>
          <PortfolioForm portfolio={edit === 'new' ? undefined : edit} onCancel={() => setEdit(null)} onSaved={() => {
            setNotice(edit === 'new' ? 'Portfolio created' : 'Portfolio updated'); setEdit(null); setRevision((value) => value + 1);
          }} />
        </Modal>
      )}
      {removing && (
        <Modal title="Delete portfolio" onClose={() => { if (!deleting) setRemoving(null); }}>
          <p>Delete {removing.name}? This cannot be undone. Referenced portfolios cannot be deleted.</p>
          {deleteError && <p role="alert" className="error-text">{deleteError}</p>}
          <div className="actions">
            <Button variant="secondary" disabled={deleting} onClick={() => setRemoving(null)}>Cancel</Button>
            <Button loading={deleting} onClick={deletePortfolio}>{deleting ? 'Deleting…' : 'Confirm delete'}</Button>
          </div>
        </Modal>
      )}
    </section>
  );
}
