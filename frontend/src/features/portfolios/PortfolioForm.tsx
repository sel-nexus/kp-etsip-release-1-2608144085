/** Validate portfolio business fields and show real server feedback. */
import { useState } from 'react';
import type { FormEvent } from 'react';
import { FormField } from '../../components/FormField';
import { Button } from '../../components/Button';
import { portfolioApi } from './portfolioApi';
import type { Portfolio, PortfolioWrite } from '../../types';
interface PortfolioFormProps { portfolio?: Portfolio; onSaved: (portfolio: Portfolio) => void; onCancel: () => void }
/** Submit only editable fields and use the loaded edit timestamp for concurrency. */
export function PortfolioForm({ portfolio, onSaved, onCancel }: PortfolioFormProps) {
  const [values, setValues] = useState<PortfolioWrite>({
    name: portfolio?.name ?? '', ownerName: portfolio?.ownerName ?? '', description: portfolio?.description ?? '',
    productArea: portfolio?.productArea ?? '', status: portfolio?.status ?? 'Active',
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const body = { ...values };
    for (const key of ['name', 'ownerName', 'description', 'productArea'] as const) {
      body[key] = body[key].trim();
      if (!body[key]) errors[key] = 'This field is required';
      else if (body[key].length > (key === 'description' ? 4000 : 200)) errors[key] = 'Value is too long';
    }
    setFields(errors);
    if (Object.keys(errors).length) return;
    setLoading(true); setError(null);
    try {
      const saved = portfolio ? await portfolioApi.update(portfolio.id, body, portfolio.updatedAt) : await portfolioApi.create(body);
      onSaved(saved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to save portfolio');
    } finally { setLoading(false); }
  };
  return (
    <form onSubmit={submit} noValidate>
      {(['name', 'ownerName', 'productArea'] as const).map((key) => (
        <FormField key={key} id={`portfolio-${key}`} label={{ name: 'Name', ownerName: 'Owner name', productArea: 'Product area' }[key]}
          value={values[key]} required maxLength={200} error={fields[key]}
          onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
      ))}
      <div className="form-field">
        <label htmlFor="portfolio-description">Description</label>
        <textarea id="portfolio-description" value={values.description} required aria-required="true" maxLength={4000}
          aria-invalid={Boolean(fields.description)} aria-describedby={fields.description ? 'description-error' : undefined}
          onChange={(event) => setValues({ ...values, description: event.target.value })} />
        {fields.description && <p id="description-error" role="alert" className="error-text">{fields.description}</p>}
      </div>
      <div className="form-field">
        <label htmlFor="portfolio-status">Status</label>
        <select id="portfolio-status" value={values.status} required aria-required="true"
          onChange={(event) => setValues({ ...values, status: event.target.value as PortfolioWrite['status'] })}>
          <option value="Active">Active</option>
          <option value="Archived">Archived</option>
        </select>
      </div>
      {error && <p role="alert" className="error-text">{error}</p>}
      <div className="actions">
        <Button type="submit" loading={loading}>{loading ? 'Saving…' : 'Save portfolio'}</Button>
        <Button type="button" variant="secondary" disabled={loading} onClick={onCancel}>Cancel</Button>
      </div>
      <p role="status" aria-live="polite">{loading ? 'Saving portfolio…' : ''}</p>
    </form>
  );
}
