/** Show deterministic inventory measures and shareable executive filters. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button } from '../../components/Button';
import { FormField } from '../../components/FormField';
import { dashboardApi } from './dashboardApi';
import { PortfolioComparison } from './PortfolioComparison';
import type { Dashboard, DashboardMetrics } from '../../types';

const metricLabels: Record<keyof DashboardMetrics, string> = {
  enterpriseQualityScore: 'Enterprise quality score',
  averageApplicationHealthScore: 'Average application health score',
  automationMaturityScore: 'Automation maturity score',
  openCriticalDefects: 'Open critical defects',
  applicationsAtRisk: 'Applications at risk',
  totalApplications: 'Total applications',
  totalPortfolios: 'Total portfolios',
};

/** Load on route activation and suppress obsolete results after URL changes. */
export default function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [portfolioId, setPortfolioId] = useState(params.get('portfolioId') ?? '');
  const [productArea, setProductArea] = useState(params.get('productArea') ?? '');
  const [riskLevel, setRiskLevel] = useState(params.get('riskLevel') ?? '');

  useEffect(() => {
    setPortfolioId(params.get('portfolioId') ?? '');
    setProductArea(params.get('productArea') ?? '');
    setRiskLevel(params.get('riskLevel') ?? '');
  }, [query]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    setData(null);
    dashboardApi.executive(new URLSearchParams(query)).then((result) => {
      if (current) setData(result);
    }).catch((failure: unknown) => {
      if (current) setError(failure instanceof Error ? failure.message : 'Unable to load dashboard. Try again.');
    }).finally(() => {
      if (current) setLoading(false);
    });
    return () => { current = false; };
  }, [query, attempt]);

  /** Apply exactly the supported filters as navigable URL state. */
  const apply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = new URLSearchParams();
    if (portfolioId.trim()) next.set('portfolioId', portfolioId.trim());
    if (productArea.trim()) next.set('productArea', productArea.trim());
    if (riskLevel) next.set('riskLevel', riskLevel);
    setParams(next);
    if (next.toString() === query) setAttempt((value) => value + 1);
  };

  return (
    <div className="dashboard-page">
      <header className="page-heading">
        <div>
          <h1>Executive dashboard</h1>
          <p className="muted">Current inventory quality, health and risk within your portfolio access.</p>
        </div>
      </header>
      <form className="filters" onSubmit={apply}>
        <FormField id="dashboard-portfolio" label="Filter portfolio ID" value={portfolioId}
          onChange={(event) => setPortfolioId(event.target.value)} />
        <FormField id="dashboard-area" label="Product area" value={productArea}
          onChange={(event) => setProductArea(event.target.value)} />
        <div className="form-field">
          <label htmlFor="dashboard-risk">Risk level</label>
          <select id="dashboard-risk" value={riskLevel} onChange={(event) => setRiskLevel(event.target.value)}>
            <option value="">All risk levels</option>
            {['Low', 'Medium', 'High'].map((risk) => (
              <option key={risk} value={risk}>{risk}</option>
            ))}
          </select>
        </div>
        <Button type="submit">Apply filters</Button>
        <Button type="button" variant="secondary" onClick={() => {
          setPortfolioId('');
          setProductArea('');
          setRiskLevel('');
          setParams({});
          if (!query) setAttempt((value) => value + 1);
        }}>Clear filters</Button>
      </form>
      <p className="muted">Total portfolios includes every visible portfolio, even empty portfolios, regardless of these filters.</p>
      {loading && (
        <p role="status" aria-live="polite">Loading dashboard…</p>
      )}
      {error && (
        <div>
          <p role="alert" className="error-text">{error}</p>
          <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>Retry dashboard</Button>
        </div>
      )}
      {!loading && data && (
        <>
          <dl className="dashboard-metrics" aria-label="Executive metrics">
            {(Object.keys(metricLabels) as (keyof DashboardMetrics)[]).map((key) => (
              <div className="metric-card" key={key}>
                <dt>{metricLabels[key]}</dt>
                <dd data-metric={key}>{data.metrics[key] ?? 'Not available'}</dd>
              </div>
            ))}
          </dl>
          {data.metrics.totalApplications === 0 && (
            <p role="status">No applications match your filters within your scope.</p>
          )}
          <PortfolioComparison rows={data.portfolioComparisons} />
        </>
      )}
    </div>
  );
}
