/** Display fixed report facts with URL filters and separately initiated CSV. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useSession } from '../auth/SessionProvider';
import { reportApi, applicationColumns } from './reportApi';
import { Button } from '../../components/Button';
import { DataTable } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import type { ApplicationReportRow, Page } from '../../types';
/** Hide stale rows during requests and never export merely by opening a route. */
export default function ApplicationReportPage() {
  const { user } = useSession();
  const [query, setQuery] = useSearchParams();
  const key = query.toString();
  const [data, setData] = useState<Page<ApplicationReportRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => { document.title = 'Application report · KP ETSIP'; }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setData(null); setError(''); setNotice(''); setExportError('');
    // A bookmarked format must never initiate a download; exports require a click.
    const filters = new URLSearchParams(key); filters.delete('format');
    reportApi.applications(filters).then((result) => { if (active) setData(result); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load report'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, revision]);
  const apply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const [name, value] of new FormData(event.currentTarget)) if (String(value).trim()) next.set(name, String(value).trim());
    next.set('page', '1'); setQuery(next);
  };
  const exportCsv = async () => {
    setExporting(true); setExportError(''); setNotice('');
    try { await reportApi.download('applications', new URLSearchParams(key)); setNotice('CSV download started'); }
    catch (failure) { setExportError(failure instanceof Error ? failure.message : 'Unable to export report'); }
    finally { setExporting(false); }
  };
  const selections = { criticality: ['Low','Medium','High','Critical'], lifecycleStatus: ['Active','Deprecated','Retired'], riskLevel: ['Low','Medium','High'], tier: ['1','2','3','4'] };
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Application report</h1>
          <p className="muted">Review authorized inventory. CSV includes all matching rows, not just this page.</p>
        </div>
        {user && user.role !== 'Read Only' && (
          <Button disabled={loading || !data} loading={exporting} onClick={exportCsv}>
            {exporting ? 'Exporting CSV…' : 'Export CSV'}
          </Button>
        )}
      </div>
      <nav aria-label="Report navigation">
        <Link to="/reports/applications">Application report</Link>{' · '}
        <Link to="/reports/portfolios">Portfolio report</Link>
      </nav>
      <form className="filters" key={key} onSubmit={apply} aria-label="Report filters">
        {['search', 'name', 'portfolioId', 'productArea'].map((name) => (
          <div className="form-field" key={name}>
            <label htmlFor={`report-${name}`}>{name}</label>
            <input id={`report-${name}`} name={name} defaultValue={query.get(name) ?? ''} maxLength={200} />
          </div>
        ))}
        {(Object.keys(selections) as Array<keyof typeof selections>).map((name) => (
          <div className="form-field" key={name}>
            <label htmlFor={`report-${name}`}>{name}</label>
            <select id={`report-${name}`} name={name} defaultValue={query.get(name) ?? ''}>
              <option value="">All</option>
              {selections[name].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </div>
        ))}
        <div className="form-field">
          <label htmlFor="report-size">Rows per page</label>
          <select id="report-size" name="pageSize" defaultValue={query.get('pageSize') ?? '25'}>
            {[10,25,50,100].map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </div>
        <Button type="submit" variant="secondary" disabled={exporting}>Apply filters</Button>
        <Button type="button" variant="secondary" disabled={exporting} onClick={() => setQuery({})}>Clear filters</Button>
      </form>
      <p role="status" aria-live="polite">{notice}</p>
      {exportError && <p role="alert" className="error-text">{exportError}</p>}
      {loading && <p role="status">Loading report…</p>}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {!loading && data && (
        <>
          {!data.items.length ? <p role="status">No applications match your scope and filters.</p> : (
            <DataTable<ApplicationReportRow>
              caption="Application report"
              rows={data.items}
              rowKey={(item) => item.id}
              columns={applicationColumns.map((column) => ({
                key: column, label: column,
                render: (item) => column === 'name' ? <Link to={`/applications/${item.id}`}>{item.name}</Link> : item[column] ?? '—',
              }))}
            />
          )}
          <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPage={(page) => {
            const next = new URLSearchParams(query); next.set('page', String(page)); setQuery(next);
          }} />
        </>
      )}
    </section>
  );
}
