/** Review portfolio fields and independently paged related application summaries. */
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { portfolioApi } from './portfolioApi';
import { DataTable } from '../../components/DataTable';
import { Badge } from '../../components/Badge';
import { Pagination } from '../../components/Pagination';
import { Button } from '../../components/Button';
import type { Page, PortfolioDetail, RelatedApplication } from '../../types';
/** Link related applications to their complete inventory details. */
export default function PortfolioDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [query, setQuery] = useSearchParams();
  const page = Number(query.get('page') ?? '1');
  const [detail, setDetail] = useState<PortfolioDetail | null>(null);
  const [apps, setApps] = useState<Page<RelatedApplication> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => { document.title = `${detail?.portfolio.name ?? 'Portfolio'} · KP ETSIP`; }, [detail]);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null); setDetail(null); setApps(null);
    if (!id || !Number.isInteger(page) || page < 1 || page > 100000) {
      setError('Invalid portfolio page'); setLoading(false); return;
    }
    Promise.all([portfolioApi.detail(id), portfolioApi.related(id, page)])
      .then(([portfolio, related]) => { if (active) { setDetail(portfolio); setApps(related); } })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load portfolio'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, page, revision]);
  return (
    <section>
      <Link to="/portfolios">Back to portfolios</Link>
      {loading && <p role="status">Loading portfolio…</p>}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {detail && apps && (
        <>
          <h1>{detail.portfolio.name}</h1>
          <Badge>{detail.portfolio.status}</Badge>
          <dl className="identity-details">
            <dt>Owner</dt>
            <dd>{detail.portfolio.ownerName}</dd>
            <dt>Product area</dt>
            <dd>{detail.portfolio.productArea}</dd>
            <dt>Description</dt>
            <dd>{detail.portfolio.description}</dd>
            <dt>Application count</dt>
            <dd>{detail.portfolio.applicationCount}</dd>
            <dt>Quality score</dt>
            <dd>{detail.portfolio.qualityScore ?? 'Not available'}</dd>
          </dl>
          <h2>Related applications</h2>
          {apps.items.length ? (
            <DataTable caption="Related applications" rows={apps.items} rowKey={(row) => row.id} columns={[
              { key: 'name', label: 'Name', render: (row) => <Link to={`/applications/${row.id}`}>{row.name}</Link> },
              { key: 'criticality', label: 'Criticality', render: (row) => row.criticality },
              { key: 'tier', label: 'Tier', render: (row) => row.tier },
              { key: 'lifecycle', label: 'Lifecycle status', render: (row) => row.lifecycleStatus },
              { key: 'risk', label: 'Risk level', render: (row) => row.riskLevel },
            ]} />
          ) : <p role="status">No related applications on this page.</p>}
          <Pagination page={apps.page} pageSize={apps.pageSize} total={apps.total} onPage={(next) => setQuery({ page: String(next) })} />
        </>
      )}
    </section>
  );
}
