/** Provide the same real credential form for forced and voluntary replacement. */
import { useState } from 'react';
import type { FormEvent } from 'react';
import { useSession } from '../auth/SessionProvider';
import { profileApi } from './profileApi';
import { Button } from '../../components/Button';
import { FormField } from '../../components/FormField';
interface PasswordChangeFormProps { requiredChange?: boolean }
/** Validate full bcrypt-supported credentials, retain errors, and clear submitted secrets. */
export function PasswordChangeForm({ requiredChange = false }: PasswordChangeFormProps) {
  const session = useSession();
  const [currentPassword, setCurrent] = useState('');
  const [newPassword, setNew] = useState('');
  const [confirmPassword, setConfirm] = useState('');
  const [fields, setFields] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    const errors: Record<string, string> = {};
    for (const [key, value] of Object.entries({ currentPassword, newPassword })) {
      if (!value) errors[key] = 'Password is required';
      else if (new TextEncoder().encode(value).length > 72 || value.includes('\0')) {
        errors[key] = 'Use a password supported by bcrypt (up to 72 UTF-8 bytes, no null characters)';
      }
    }
    if (!confirmPassword) errors.confirmPassword = 'Confirm your new password';
    else if (confirmPassword !== newPassword) errors.confirmPassword = 'Passwords do not match';
    setFields(errors);
    setError(null);
    setSuccess(false);
    if (Object.keys(errors).length) return;
    setPending(true);
    try {
      await session.updateProfile(() => profileApi.changePassword({ currentPassword, newPassword }));
      setSuccess(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to change password');
    } finally {
      setCurrent('');
      setNew('');
      setConfirm('');
      setPending(false);
    }
  };
  return (
    <section>
      <h2>Change password</h2>
      {requiredChange && <p role="alert">Password change required. Change your initial password before continuing.</p>}
      <form onSubmit={submit} noValidate aria-label="Change password">
        <FormField id="current-password" label="Current password" type="password" autoComplete="current-password"
          required value={currentPassword} disabled={pending} error={fields.currentPassword}
          onChange={(event) => setCurrent(event.target.value)} />
        <FormField id="new-password" label="New password" type="password" autoComplete="new-password"
          required value={newPassword} disabled={pending} error={fields.newPassword}
          onChange={(event) => setNew(event.target.value)} />
        <FormField id="confirm-password" label="Confirm new password" type="password" autoComplete="new-password"
          required value={confirmPassword} disabled={pending} error={fields.confirmPassword}
          onChange={(event) => setConfirm(event.target.value)} />
        {error && <p role="alert" className="error-text">{error}</p>}
        <Button type="submit" loading={pending}>{pending ? 'Changing password…' : 'Change password'}</Button>
        <p role="status" aria-live="polite">{pending ? 'Updating credentials…' : success ? 'Password changed' : ''}</p>
      </form>
    </section>
  );
}
