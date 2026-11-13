/** Review global authorized history using shareable filters and real CSV downloads. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { auditApi, auditActions } from './auditApi';
import { Button } from '../../components/Button';
import { DataTable } from '../../components/DataTable';
import { Pagination } from '../../components/Pagination';
import type { AuditRow, Page } from '../../types';

/** Keep stale rows out of view while the URL-defined query is loading. */
export default function AuditLogPage() {
  const [query, setQuery] = useSearchParams();
  const key = query.toString();
  const [data, setData] = useState<Page<AuditRow> | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [exportError, setExportError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => { document.title = 'Audit history · KP ETSIP'; }, []);
  useEffect(() => {
    let active = true;
    setLoading(true); setData(null); setError(''); setNotice(''); setExportError('');
    auditApi.list(new URLSearchParams(key)).then((result) => { if (active) setData(result); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load audit history'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, revision]);
  const apply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const [name, value] of new FormData(event.currentTarget)) {
      if (String(value).trim()) next.set(name, String(value).trim());
    }
    next.set('page', '1'); setQuery(next);
  };
  const exportCsv = async () => {
    setExporting(true); setExportError(''); setNotice('');
    try { await auditApi.download(new URLSearchParams(key)); setNotice('CSV download started'); }
    catch (failure) { setExportError(failure instanceof Error ? failure.message : 'Unable to export audit history'); }
    finally { setExporting(false); }
  };
  return (
    <section className="audit-history">
      <div className="page-heading">
        <div>
          <h1>Audit history</h1>
          <p className="muted">Review sign-ins and sensitive changes across the platform.</p>
        </div>
        <Button disabled={loading || !data} loading={exporting} onClick={exportCsv}>
          {exporting ? 'Exporting CSV…' : 'Export CSV'}
        </Button>
      </div>
      <form className="filters" key={key} onSubmit={apply} aria-label="Audit filters">
        <div className="form-field">
          <label htmlFor="audit-user">User ID</label>
          <input id="audit-user" name="userId" defaultValue={query.get('userId') ?? ''} maxLength={24} />
        </div>
        <div className="form-field">
          <label htmlFor="audit-action">Action</label>
          <select id="audit-action" name="action" defaultValue={query.get('action') ?? ''}>
            <option value="">All actions</option>
            {auditActions.map((action) => <option key={action} value={action}>{action}</option>)}
          </select>
        </div>
        {(['from', 'to'] as const).map((name) => (
          <div className="form-field" key={name}>
            <label htmlFor={`audit-${name}`}>{name === 'from' ? 'From (UTC or offset)' : 'To (UTC or offset)'}</label>
            <input id={`audit-${name}`} name={name} defaultValue={query.get(name) ?? ''}
              placeholder="2026-01-01T00:00:00Z" maxLength={64} aria-describedby="audit-date-help" />
          </div>
        ))}
        <div className="form-field">
          <label htmlFor="audit-size">Rows per page</label>
          <select id="audit-size" name="pageSize" defaultValue={query.get('pageSize') ?? '25'}>
            {[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </div>
        <Button type="submit" variant="secondary" disabled={exporting}>Apply filters</Button>
        <Button type="button" variant="secondary" disabled={exporting} onClick={() => setQuery({})}>Clear filters</Button>
      </form>
      <p id="audit-date-help" className="muted">Use ISO timestamps with Z or an explicit offset. Date bounds are inclusive.</p>
      <p role="status" aria-live="polite">{notice}</p>
      {exportError && <p role="alert" className="error-text">{exportError}</p>}
      {loading && <p role="status">Loading audit history…</p>}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {!loading && data && (
        <>
          {!data.items.length ? <p role="status">No audit events match these filters.</p> : (
            <DataTable caption="Audit events" rows={data.items} rowKey={(row) => row.id} columns={[
              { key: 'timestamp', label: 'Timestamp (UTC)', render: (row) => <time dateTime={row.timestamp}>{row.timestamp}</time> },
              { key: 'userId', label: 'User ID', render: (row) => row.userId ?? '—' },
              { key: 'userName', label: 'User', render: (row) => row.userName },
              { key: 'action', label: 'Action', render: (row) => row.action },
              { key: 'entityType', label: 'Entity type', render: (row) => row.entityType },
              { key: 'entityId', label: 'Entity ID', render: (row) => row.entityId ?? '—' },
              { key: 'details', label: 'Details', render: (row) => row.details },
            ]} />
          )}
          <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPage={(page) => {
            const next = new URLSearchParams(query); next.set('page', String(page)); setQuery(next);
          }} />
        </>
      )}
    </section>
  );
}
