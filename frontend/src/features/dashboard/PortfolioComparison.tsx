/** Present filtered portfolio quality and risk without predictive scoring. */
import type { PortfolioComparisonRow } from '../../types';
interface PortfolioComparisonProps { rows: PortfolioComparisonRow[] }
/** Keep numeric comparisons accessible alongside quiet quality bars. */
export function PortfolioComparison({ rows }: PortfolioComparisonProps) {
  return (
    <section aria-labelledby="comparison-title">
      <h2 id="comparison-title">Portfolio comparison</h2>
      <p className="muted">Only portfolios represented by matching applications are compared.</p>
      {rows.length === 0 ? (
        <p role="status">No portfolios to compare.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="comparison-caption">Filtered quality scores and high-risk application counts</caption>
            <thead>
              <tr>
                <th scope="col">Portfolio</th>
                <th scope="col">Quality score</th>
                <th scope="col">Applications at risk</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.portfolioId}>
                  <th scope="row">{row.name}</th>
                  <td>
                    <div className="comparison-quality">
                      <span>{row.qualityScore}</span>
                      <span className="comparison-track" aria-hidden="true">
                        <span style={{ width: `${row.qualityScore}%` }} />
                      </span>
                    </div>
                  </td>
                  <td>{row.applicationsAtRisk}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
