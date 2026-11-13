/** Browse shareable application filters with scope-aware creation. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useSession } from '../auth/SessionProvider';
import { reportApi } from '../reports/reportApi';
import { applicationApi } from './applicationApi';
import { ApplicationForm } from './ApplicationForm';
import { Button } from '../../components/Button';
import { DataTable } from '../../components/DataTable';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import type { Application, Page } from '../../types';
/** Never render stale results after the inventory URL changes. */
export default function ApplicationList() {
  const { user } = useSession();
  const writable = user && ['Administrator', 'Portfolio Leader', 'Engineer'].includes(user.role)
    && (user.role === 'Administrator' || user.portfolioAccess.length > 0);
  const [query, setQuery] = useSearchParams();
  const key = query.toString();
  const [data, setData] = useState<Page<Application> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const exportCsv = async () => {
    setExporting(true); setExportError(''); setNotice('');
    try { await reportApi.download('application-list', new URLSearchParams(key)); setNotice('CSV download started'); }
    catch (failure) { setExportError(failure instanceof Error ? failure.message : 'Unable to export applications'); }
    finally { setExporting(false); }
  };
  useEffect(() => { document.title = 'Applications · KP ETSIP'; }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setData(null);
    const filters = new URLSearchParams(key); filters.delete('format');
    applicationApi.list(filters).then((response) => { if (active) setData(response); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load applications'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, revision]);
  const filter = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const [name, value] of fields) if (String(value).trim()) next.set(name, String(value).trim());
    next.set('page', '1'); setQuery(next);
  };
  const selections = {
    criticality: ['Low', 'Medium', 'High', 'Critical'], lifecycleStatus: ['Active', 'Deprecated', 'Retired'],
    riskLevel: ['Low', 'Medium', 'High'], tier: ['1', '2', '3', '4'],
  };
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Applications</h1>
          <p className="muted">Review ownership, lifecycle, health and quality in your authorized inventory.</p>
        </div>
        {user && user.role !== 'Read Only' && (
          <Button variant="secondary" disabled={loading || !data} loading={exporting} onClick={exportCsv}>Export CSV</Button>
        )}
        {writable && <Button onClick={() => setCreating(true)}>Create application</Button>}
      </div>
      <form className="filters" key={key} onSubmit={filter}>
        {(['search', 'name', 'portfolioId', 'productArea'] as const).map((name) => (
          <div className="form-field" key={name}>
            <label htmlFor={`filter-${name}`}>
              {{ search: 'Search names', name: 'Name contains',
                portfolioId: 'Filter portfolio ID', productArea: 'Filter product area' }[name]}
            </label>
            <input id={`filter-${name}`} name={name} defaultValue={query.get(name) ?? ''} maxLength={200} />
          </div>
        ))}
        {(Object.keys(selections) as Array<keyof typeof selections>).map((name) => (
          <div className="form-field" key={name}>
            <label htmlFor={`filter-${name}`}>
              {{ criticality: 'Filter criticality', lifecycleStatus: 'Filter lifecycle status',
                riskLevel: 'Filter risk level', tier: 'Filter tier' }[name]}
            </label>
            <select id={`filter-${name}`} name={name} defaultValue={query.get(name) ?? ''}>
              <option value="">All</option>
              {selections[name].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
        ))}
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
      {exportError && <p role="alert" className="error-text">{exportError}</p>}
      {loading && <p role="status">Loading applications…</p>}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {!loading && data && (
        <>
          {!data.items.length ? (
            <p role="status">{Array.from(query.keys()).some((name) => !['page', 'pageSize'].includes(name))
              ? 'No applications match these filters.' : 'No applications available in your scope.'}</p>
          ) : (
            <DataTable caption="Application inventory" rows={data.items} rowKey={(row) => row.id} columns={[
              { key: 'name', label: 'Name', render: (row) => <Link to={`/applications/${row.id}`}>{row.name}</Link> },
              { key: 'portfolio', label: 'Portfolio', render: (row) => <Link to={`/portfolios/${row.portfolioId}`}>{row.portfolioId}</Link> },
              { key: 'criticality', label: 'Criticality', render: (row) => row.criticality },
              { key: 'tier', label: 'Tier', render: (row) => row.tier },
              { key: 'lifecycle', label: 'Lifecycle status', render: (row) => row.lifecycleStatus },
              { key: 'health', label: 'Health score', render: (row) => row.applicationHealthScore },
              { key: 'automation', label: 'Automation coverage', render: (row) => row.automationCoverage },
              { key: 'defects', label: 'Critical defects', render: (row) => row.openCriticalDefects },
              { key: 'risk', label: 'Risk level', render: (row) => row.riskLevel },
            ]} />
          )}
          <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPage={(page) => {
            const next = new URLSearchParams(query); next.set('page', String(page)); setQuery(next);
          }} />
        </>
      )}
      {creating && (
        <Modal title="Create application" onClose={() => setCreating(false)}>
          <ApplicationForm onCancel={() => setCreating(false)} onSaved={() => {
            setCreating(false); setNotice('Application created'); setRevision((value) => value + 1);
          }} />
        </Modal>
      )}
    </section>
  );
}
