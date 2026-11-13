/** Group the complete inventory record into readable, validated business sections. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { applicationApi, applicationGroups, applicationLabels } from './applicationApi';
import { portfolioApi } from '../portfolios/portfolioApi';
import { Button } from '../../components/Button';
import type { Application, ApplicationWrite, Portfolio } from '../../types';
interface ApplicationFormProps { application?: Application; onSaved: (application: Application) => void; onCancel: () => void }
const options: Partial<Record<keyof ApplicationWrite, string[]>> = {
  criticality: ['Low', 'Medium', 'High', 'Critical'], lifecycleStatus: ['Active', 'Deprecated', 'Retired'], riskLevel: ['Low', 'Medium', 'High'],
};
const numeric = ['tier', 'applicationHealthScore', 'qualityScore', 'automationCoverage', 'unitTestCoverage', 'openDefects', 'openCriticalDefects'];
/** Submit no derived fields and preserve the observed timestamp on edits. */
export function ApplicationForm({ application, onSaved, onCancel }: ApplicationFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(applicationGroups.flatMap((group) =>
    group.keys.map((key) => [key, String(application?.[key] ?? (key === 'tier' ? 1 : numeric.includes(key) ? 0 : options[key]?.[0] ?? ''))]),
  )));
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [loadingParents, setLoadingParents] = useState(true);
  const [parentError, setParentError] = useState('');
  const [revision, setRevision] = useState(0);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    setLoadingParents(true); setParentError('');
    /** Fetch all visible parent pages, not a silently truncated selection. */
    const load = async () => {
      const result: Portfolio[] = [];
      let page = 1;
      let total = 0;
      do {
        const response = await portfolioApi.list(new URLSearchParams({ page: String(page), pageSize: '100' }));
        result.push(...response.items); total = response.total; page += 1;
      } while (result.length < total);
      return result;
    };
    load().then((rows) => { if (active) setPortfolios(rows); })
      .catch((failure) => { if (active) setParentError(failure instanceof Error ? failure.message : 'Unable to load portfolios'); })
      .finally(() => { if (active) setLoadingParents(false); });
    return () => { active = false; };
  }, [revision]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    const body: Record<string, unknown> = {};
    for (const group of applicationGroups) for (const key of group.keys) {
      const value = values[key].trim();
      if (numeric.includes(key)) {
        const maximum = key === 'tier' ? 4 : key.startsWith('open') ? Number.MAX_SAFE_INTEGER : 100;
        const minimum = key === 'tier' ? 1 : 0;
        if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) < minimum || Number(value) > maximum) {
          errors[key] = `Use an integer from ${minimum} to ${maximum}`;
        }
        body[key] = Number(value);
      } else if (key === 'repositoryUrl' || key === 'pipelineUrl') {
        body[key] = value || null;
        if (value) {
          try { if (!['http:', 'https:'].includes(new URL(value).protocol)) errors[key] = 'Enter a valid HTTP or HTTPS URL'; }
          catch { errors[key] = 'Enter a valid HTTP or HTTPS URL'; }
        }
      } else {
        body[key] = value;
        if (!value) errors[key] = 'This field is required';
        else if (value.length > (key === 'description' || key === 'technologyStack' ? 4000 : 200)) errors[key] = 'Value is too long';
        if (key === 'portfolioId' && !portfolios.some((row) => row.id === value)) errors[key] = 'Choose a visible portfolio';
      }
    }
    setFields(errors);
    if (Object.keys(errors).length || loadingParents || parentError) return;
    setSaving(true); setError('');
    try {
      const request = body as unknown as ApplicationWrite;
      const saved = application ? await applicationApi.update(application.id, request, application.updatedAt) : await applicationApi.create(request);
      onSaved(saved);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save application'); }
    finally { setSaving(false); }
  };
  return (
    <form onSubmit={submit} noValidate>
      {loadingParents && <p role="status">Loading portfolio choices…</p>}
      {parentError && (
        <div>
          <p role="alert" className="error-text">{parentError}</p>
          <Button type="button" variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry portfolios</Button>
        </div>
      )}
      {!loadingParents && !parentError && !portfolios.length && <p role="status">No portfolios available in your scope.</p>}
      {applicationGroups.map((group) => (
        <fieldset key={group.title} disabled={saving}>
          <legend>{group.title}</legend>
          {group.keys.map((key) => {
            const id = `application-${key}`;
            const required = key !== 'repositoryUrl' && key !== 'pipelineUrl';
            const common = {
              id, value: values[key], required, 'aria-required': required, 'aria-invalid': Boolean(fields[key]),
              'aria-describedby': fields[key] ? `${id}-error` : undefined,
              onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
                setValues((previous) => ({ ...previous, [key]: event.target.value }));
              },
            };
            return (
              <div className="form-field" key={key}>
                <label htmlFor={id}>{applicationLabels[key]}</label>
                {key === 'portfolioId' ? (
                  <select {...common} disabled={loadingParents || Boolean(parentError)}>
                    <option value="">Choose a portfolio</option>
                    {portfolios.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
                  </select>
                ) : options[key] ? (
                  <select {...common}>
                    {options[key]!.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                ) : key === 'description' || key === 'technologyStack' ? (
                  <textarea {...common} maxLength={4000} />
                ) : (
                  <input {...common} type={numeric.includes(key) ? 'number' : key.endsWith('Url') ? 'url' : 'text'}
                    min={numeric.includes(key) ? key === 'tier' ? 1 : 0 : undefined}
                    max={key === 'tier' ? 4 : numeric.includes(key) && !key.startsWith('open') ? 100 : undefined}
                    step={numeric.includes(key) ? 1 : undefined} maxLength={numeric.includes(key) ? undefined : 200} />
                )}
                {fields[key] && <p id={`${id}-error`} role="alert" className="error-text">{fields[key]}</p>}
              </div>
            );
          })}
        </fieldset>
      ))}
      {error && <p role="alert" className="error-text">{error}</p>}
      <div className="actions">
        <Button type="submit" loading={saving} disabled={loadingParents || Boolean(parentError) || !portfolios.length}>Save application</Button>
        <Button type="button" variant="secondary" disabled={saving} onClick={onCancel}>Cancel</Button>
      </div>
      <p role="status" aria-live="polite">{saving ? 'Saving application…' : ''}</p>
    </form>
  );
}
