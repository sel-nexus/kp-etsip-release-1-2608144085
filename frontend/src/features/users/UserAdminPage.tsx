/** Browse and administer safe accounts with URL filters and explicit deactivation. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams, useParams } from 'react-router-dom';
import { useSession } from '../auth/SessionProvider';
import { userApi, supportedRoles } from './userApi';
import { UserForm } from './UserForm';
import { Button } from '../../components/Button';
import { DataTable } from '../../components/DataTable';
import { Modal } from '../../components/Modal';
import { Pagination } from '../../components/Pagination';
import { Badge } from '../../components/Badge';
import type { AdminUser, Page } from '../../types';
/** Keep stale requests from replacing a newer URL's account results. */
export default function UserAdminPage() {
  const { user } = useSession();
  const { id } = useParams();
  const [query, setQuery] = useSearchParams();
  const key = query.toString();
  const admin = user?.role === 'Administrator';
  const [data, setData] = useState<Page<AdminUser> | null>(null);
  const [detail, setDetail] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [edit, setEdit] = useState<AdminUser | 'new' | null>(null);
  const [removing, setRemoving] = useState<AdminUser | null>(null);
  const [saving, setSaving] = useState(false);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => { document.title = `${detail?.name ?? 'Users'} · KP ETSIP`; }, [detail?.name]);
  useEffect(() => {
    if (!admin) return;
    let active = true;
    setLoading(true); setError(null); setData(null); setDetail(null);
    const operation = id ? userApi.detail(id).then((row) => { if (active) setDetail(row); })
      : userApi.list(new URLSearchParams(key)).then((rows) => { if (active) setData(rows); });
    operation.catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load users'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, key, revision, admin]);
  if (!admin) return <p role="alert">Administrator access is required.</p>;
  const filter = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const name of ['search', 'role', 'status', 'pageSize']) {
      const value = String(fields.get(name) ?? '').trim();
      if (value) next.set(name, value);
    }
    next.set('page', '1'); setQuery(next);
  };
  const deactivate = async () => {
    if (!removing) return;
    setSaving(true); setWriteError(null);
    try {
      await userApi.deactivate(removing.id, removing.updatedAt);
      setRemoving(null); setNotice('User deactivated'); setRevision((value) => value + 1);
    } catch (failure) { setWriteError(failure instanceof Error ? failure.message : 'Unable to deactivate user'); }
    finally { setSaving(false); }
  };
  const actions = (row: AdminUser) => (
    <div className="actions">
      <Button variant="secondary" onClick={() => setEdit(row)} aria-label={`Edit ${row.name}`}>Edit user</Button>
      {row.status === 'Active' && (
        <Button variant="secondary" onClick={() => { setRemoving(row); setWriteError(null); }}
          aria-label={`Deactivate ${row.name}`}>Deactivate user</Button>
      )}
    </div>
  );
  return (
    <section>
      <div className="page-heading">
        <div>
          {id && <Link to={`/users?${key}`}>Back to users</Link>}
          <h1>{detail?.name ?? (id ? 'User account' : 'Users')}</h1>
          <p className="muted">Manage local accounts, roles and portfolio assignments.</p>
        </div>
        {!id && <Button onClick={() => setEdit('new')}>Create user</Button>}
      </div>
      {!id && (
        <form className="filters" key={key} onSubmit={filter}>
          <div className="form-field">
            <label htmlFor="user-search">Search names or emails</label>
            <input id="user-search" name="search" type="search" maxLength={200} defaultValue={query.get('search') ?? ''} />
          </div>
          <div className="form-field">
            <label htmlFor="filter-role">Filter role</label>
            <select id="filter-role" name="role" defaultValue={query.get('role') ?? ''}>
              <option value="">All roles</option>
              {supportedRoles.map((role) => <option key={role}>{role}</option>)}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="filter-status">Filter status</label>
            <select id="filter-status" name="status" defaultValue={query.get('status') ?? ''}>
              <option value="">All statuses</option>
              <option>Active</option>
              <option>Inactive</option>
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="page-size">Rows per page</label>
            <select id="page-size" name="pageSize" defaultValue={query.get('pageSize') ?? '25'}>
              {[10, 25, 50, 100].map((size) => <option key={size}>{size}</option>)}
            </select>
          </div>
          <Button type="submit" variant="secondary">Apply filters</Button>
          <Button type="button" variant="secondary" onClick={() => setQuery({})}>Clear filters</Button>
        </form>
      )}
      <p role="status" aria-live="polite">{notice}</p>
      {loading && <p role="status">Loading users…</p>}
      {error && (
        <div>
          <p role="alert">{error}</p>
          <Button variant="secondary" onClick={() => setRevision((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {detail && (
        <>
          <dl className="identity-details">
            {Object.entries({ Email: detail.email, Role: detail.role, Status: detail.status,
              'Portfolio access': detail.portfolioAccess.join(', ') || 'No explicit assignments',
              'Authentication source': detail.authSource, Manager: detail.managerName ?? 'Not set',
              Vendor: detail.vendorIndicator ? 'Yes' : 'No', 'Last login': detail.lastLogin ?? 'Never',
              'Password change required': detail.mustChangePassword ? 'Yes' : 'No' }).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {actions(detail)}
        </>
      )}
      {data && (
        <>
          {data.items.length === 0 ? <p role="status">No users match these filters.</p> : (
            <DataTable caption="User accounts" rows={data.items} rowKey={(row) => row.id} columns={[
              { key: 'name', label: 'Name', render: (row) => <Link to={`/users/${row.id}?${key}`}>{row.name}</Link> },
              { key: 'email', label: 'Email', render: (row) => row.email },
              { key: 'role', label: 'Role', render: (row) => row.role },
              { key: 'status', label: 'Status', render: (row) => <Badge>{row.status}</Badge> },
              { key: 'access', label: 'Assigned portfolios', render: (row) => row.portfolioAccess.length },
              { key: 'login', label: 'Last login', render: (row) => row.lastLogin ?? 'Never' },
              { key: 'actions', label: 'Actions', render: actions },
            ]} />
          )}
          <Pagination page={data.page} pageSize={data.pageSize} total={data.total} onPage={(page) => {
            const next = new URLSearchParams(query); next.set('page', String(page)); setQuery(next);
          }} />
        </>
      )}
      {edit && (
        <Modal title={edit === 'new' ? 'Create user' : 'Edit user'} onClose={() => { if (!saving) setEdit(null); }}>
          <UserForm onBusy={setSaving} account={edit === 'new' ? undefined : edit} onCancel={() => setEdit(null)} onSaved={() => {
            setNotice(edit === 'new' ? 'User created' : 'User updated'); setEdit(null); setRevision((value) => value + 1);
          }} />
        </Modal>
      )}
      {removing && (
        <Modal title="Deactivate user" onClose={() => { if (!saving) setRemoving(null); }}>
          <p>Deactivate {removing.name}? Their existing tokens and future sign-ins will be denied. Account history is retained.</p>
          {writeError && <p role="alert">{writeError} Reload before retrying if a write may have completed.</p>}
          <div className="actions">
            <Button loading={saving} onClick={deactivate}>Confirm deactivate</Button>
            <Button variant="secondary" disabled={saving} onClick={() => setRemoving(null)}>Cancel</Button>
          </div>
        </Modal>
      )}
    </section>
  );
}
