/** Edit account metadata and fetched portfolio assignments without password resets. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { FormField } from '../../components/FormField';
import { Button } from '../../components/Button';
import { userApi, supportedRoles, availablePortfolios } from './userApi';
import type { AdminUser, Portfolio, UserWrite } from '../../types';
interface UserFormProps { account?: AdminUser; onSaved: (account: AdminUser) => void; onCancel: () => void; onBusy?: (busy: boolean) => void }
/** Validate per field and retain entered data on honest partial-write errors. */
export function UserForm({ account, onSaved, onCancel, onBusy }: UserFormProps) {
  const [body, setBody] = useState<UserWrite>(account ? {
    name: account.name, email: account.email, role: account.role, portfolioAccess: account.portfolioAccess,
    status: account.status, managerName: account.managerName, vendorIndicator: account.vendorIndicator,
  } : { name: '', email: '', role: 'Engineer', portfolioAccess: [], status: 'Active', managerName: null, vendorIndicator: false });
  const [password, setPassword] = useState('');
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [loading, setLoading] = useState(true);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    setLoading(true); setPortfolioError(null);
    availablePortfolios().then((rows) => { if (active) setPortfolios(rows); })
      .catch((failure) => { if (active) setPortfolioError(failure instanceof Error ? failure.message : 'Unable to load portfolios'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [revision]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    if (!body.name.trim()) errors.name = 'Name is required';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email.trim())) errors.email = 'Enter a valid email';
    if (!account && !password) errors.password = 'Initial password is required';
    if (!account && new TextEncoder().encode(password).length > 72) errors.password = 'Password exceeds bcrypt byte limit';
    if (body.portfolioAccess.some((id) => !portfolios.some((portfolio) => portfolio.id === id))) {
      errors.portfolioAccess = 'Remove unavailable portfolio assignments before saving';
    }
    setFields(errors);
    if (Object.keys(errors).length || loading || portfolioError) return;
    setSaving(true); onBusy?.(true); setError(null);
    try {
      const normalized = { ...body, name: body.name.trim(), email: body.email.trim().toLowerCase(), managerName: body.managerName?.trim() || null };
      const result = account ? await userApi.update(account.id, normalized, account.updatedAt)
        : await userApi.create({ ...normalized, password });
      setPassword(''); onSaved(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Unable to save account'); }
    finally { setSaving(false); onBusy?.(false); }
  };
  return (
    <form onSubmit={submit} noValidate>
      <fieldset disabled={saving}>
        <legend className="sr-only">Account details</legend>
        <FormField id="user-name" label="Name" required maxLength={200} value={body.name} error={fields.name}
          onChange={(event) => setBody({ ...body, name: event.target.value })} />
        <FormField id="user-email" label="Email" type="email" required value={body.email} error={fields.email}
          onChange={(event) => setBody({ ...body, email: event.target.value })} />
        {!account && (
          <FormField id="user-password" label="Initial password" type="password" autoComplete="new-password" required
            value={password} error={fields.password} onChange={(event) => setPassword(event.target.value)} />
        )}
        <div className="form-field">
          <label htmlFor="user-role">Role</label>
          <select id="user-role" value={body.role} onChange={(event) => setBody({ ...body, role: event.target.value as UserWrite['role'] })}>
            {supportedRoles.map((role) => <option key={role}>{role}</option>)}
          </select>
        </div>
        <div className="form-field">
          <label htmlFor="user-status">Status</label>
          <select id="user-status" value={body.status}
            onChange={(event) => setBody({ ...body, status: event.target.value as UserWrite['status'] })}>
            <option>Active</option>
            <option>Inactive</option>
          </select>
        </div>
        <FormField id="user-manager" label="Manager name" maxLength={200} value={body.managerName ?? ''}
          onChange={(event) => setBody({ ...body, managerName: event.target.value || null })} />
        <div className="form-field">
          <label htmlFor="user-vendor">Vendor account</label>
          <input id="user-vendor" type="checkbox" checked={body.vendorIndicator}
            onChange={(event) => setBody({ ...body, vendorIndicator: event.target.checked })} />
        </div>
        <fieldset aria-describedby="assignment-help">
          <legend>Portfolio access</legend>
          <p id="assignment-help" className="muted">Empty access means all portfolios only for Administrator, Executive and Auditor; other roles see no inventory.</p>
          {loading && <p role="status">Loading available portfolios…</p>}
          {portfolioError && (
            <div>
              <p role="alert">{portfolioError}</p>
              <Button type="button" variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry portfolios</Button>
            </div>
          )}
          {!loading && !portfolioError && portfolios.length === 0 && <p role="status">No available portfolios.</p>}
          {portfolios.map((portfolio) => (
            <div key={portfolio.id} className="form-field">
              <label htmlFor={`access-${portfolio.id}`}>{portfolio.name} ({portfolio.status})</label>
              <input id={`access-${portfolio.id}`} type="checkbox" checked={body.portfolioAccess.includes(portfolio.id)}
                onChange={(event) => setBody({ ...body, portfolioAccess: event.target.checked
                  ? [...body.portfolioAccess, portfolio.id] : body.portfolioAccess.filter((id) => id !== portfolio.id) })} />
            </div>
          ))}
          {body.portfolioAccess.filter((id) => !portfolios.some((portfolio) => portfolio.id === id)).map((id) => (
            <Button key={id} type="button" variant="secondary" onClick={() => setBody({ ...body,
              portfolioAccess: body.portfolioAccess.filter((item) => item !== id) })}>Remove unavailable assignment {id}</Button>
          ))}
          {fields.portfolioAccess && <p role="alert" className="error-text">{fields.portfolioAccess}</p>}
        </fieldset>
      </fieldset>
      {error && <p role="alert" className="error-text">{error} Reload the account before retrying if a write may have completed.</p>}
      <p role="status" aria-live="polite">{saving ? 'Saving account…' : ''}</p>
      <div className="actions">
        <Button type="submit" loading={saving} disabled={loading || Boolean(portfolioError)}>Save user</Button>
        <Button type="button" variant="secondary" disabled={saving} onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
