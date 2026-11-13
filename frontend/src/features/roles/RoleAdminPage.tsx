/** Edit the fixed role vocabulary using semantic bounded permission controls. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useSession } from '../auth/SessionProvider';
import { Button } from '../../components/Button';
import { roleApi, roleMaximum } from './roleApi';
import type { Permission, RoleDefinition, RoleName } from '../../types';

/** Preserve each displayed version until save or explicit reload succeeds. */
function RoleEditor({ role, onSaved }: { role: RoleDefinition; onSaved: (role: RoleDefinition) => void }) {
  const [permissions, setPermissions] = useState<Permission[]>(role.permissions);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true); setError(null); setNotice('');
    try {
      const updated = await roleApi.update(role, permissions);
      onSaved(updated); setNotice('Permissions saved');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to save permissions');
    } finally { setSaving(false); }
  };
  return (
    <form className="role-editor" aria-label={`${role.name} permissions`} onSubmit={save}>
      <fieldset disabled={saving} aria-describedby={`bounds-${role.id}`}>
        <legend>{role.name}</legend>
        <p className="muted">{role.description}</p>
        <p id={`bounds-${role.id}`}>Maximum allowed: {roleMaximum[role.name].join(', ')}.</p>
        <div className="permission-controls">
          {roleMaximum[role.name].map((permission) => (
            <label key={permission} className="permission-control" htmlFor={`${role.id}-${permission}`}>
              <input id={`${role.id}-${permission}`} type="checkbox" checked={permissions.includes(permission)}
                onChange={(event) => setPermissions((current) => event.target.checked
                  ? [...current, permission] : current.filter((item) => item !== permission))} />
              {permission}
            </label>
          ))}
        </div>
      </fieldset>
      {error && (
        <p role="alert" className="error-text">
          {error} Reload roles before retrying; a write may already have completed.
        </p>
      )}
      <p role="status" aria-live="polite">{saving ? 'Saving permissions…' : notice}</p>
      <Button type="submit" variant="secondary" loading={saving} disabled={Boolean(error)}>
        Save {role.name} permissions
      </Button>
    </form>
  );
}

/** Show six fixed editors or explicit setup actions, never custom-role controls. */
export default function RoleAdminPage() {
  const { user } = useSession();
  const admin = user?.role === 'Administrator';
  const [roles, setRoles] = useState<RoleDefinition[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [ensuring, setEnsuring] = useState<RoleName | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => { document.title = 'Roles · KP ETSIP'; }, []);
  useEffect(() => {
    if (!admin) return;
    let active = true;
    setLoading(true); setError(null); setRoles(null);
    roleApi.list().then((result) => { if (active) setRoles(result.items); })
      .catch((failure) => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load roles'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [admin, revision]);
  const ensure = async (name: RoleName) => {
    setEnsuring(name); setError(null); setNotice('');
    try {
      const row = await roleApi.ensure(name);
      setRoles((current) => [...(current ?? []).filter((item) => item.name !== name), row]);
      setNotice(`${name} baseline ensured`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to ensure role');
    } finally { setEnsuring(null); }
  };
  if (!admin) return <p role="alert">Administrator access is required.</p>;
  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>Roles</h1>
          <p className="muted">Reduce or restore permissions within six fixed role boundaries.</p>
          <p>Changes affect existing sessions on their next request. Custom roles and deletion are not supported.</p>
        </div>
        <Button variant="secondary" disabled={loading || ensuring !== null}
          onClick={() => { setNotice(''); setRevision((value) => value + 1); }}>
          Reload roles
        </Button>
      </div>
      <p role="status" aria-live="polite">{notice}</p>
      {loading && <p role="status">Loading roles…</p>}
      {error && <p role="alert">{error} Reload roles to reconcile any partial write.</p>}
      {roles && (
        <div className="role-grid">
          {(Object.keys(roleMaximum) as RoleName[]).map((name) => {
            const role = roles.find((item) => item.name === name);
            return role ? (
              <RoleEditor key={`${role.id}-${revision}`} role={role} onSaved={(updated) => {
                setRoles((current) => current?.map((item) => item.id === updated.id ? updated : item) ?? []);
              }} />
            ) : (
              <section key={name} className="role-editor" aria-label={`${name} setup`}>
                <h2>{name}</h2>
                <p>Baseline role is missing. Maximum allowed: {roleMaximum[name].join(', ')}.</p>
                <Button variant="secondary" loading={ensuring === name} disabled={ensuring !== null || Boolean(error)}
                  onClick={() => void ensure(name)}>
                  Ensure {name} baseline
                </Button>
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}
