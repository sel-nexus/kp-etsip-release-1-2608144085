/** Display the current user's safe access and durable profile settings. */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { LandingPage } from '../../types';
import { useSession } from '../auth/SessionProvider';
import { PasswordChangeForm } from './PasswordChangeForm';
import { landingChoices, profileApi } from './profileApi';
import { Card } from '../../components/Card';
import { Button } from '../../components/Button';
/** Keep profile preferences separate from credential state and server-side authorization. */
export default function ProfilePage() {
  const session = useSession();
  const user = session.user;
  const [destination, setDestination] = useState(user?.defaultLandingPage ?? 'profile');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { setDestination(user?.defaultLandingPage ?? 'profile'); }, [user?.defaultLandingPage]);
  if (!user) return null;
  const choices = landingChoices(user.role);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    setError(null);
    setSaved(false);
    if (!choices.includes(destination as LandingPage)) { setError('Choose a supported landing page'); return; }
    setPending(true);
    try {
      await session.updateProfile(() => profileApi.savePreferences({ defaultLandingPage: destination as LandingPage }));
      setSaved(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Unable to save preference');
    } finally { setPending(false); }
  };
  return (
    <div className="grid gap-6">
      <h1>My profile</h1>
      <Card>
        <h2>{user.name}</h2>
        <dl className="identity-details">
          <dt>Email</dt>
          <dd>{user.email}</dd>
          <dt>Role</dt>
          <dd>{user.role}</dd>
          <dt>Status</dt>
          <dd>{user.status}</dd>
          <dt>Portfolio access</dt>
          <dd>{user.portfolioAccess.length ? user.portfolioAccess.join(', ') :
            ['Administrator', 'Executive', 'Auditor'].includes(user.role) ? 'All portfolios' : 'No portfolio access'}</dd>
        </dl>
      </Card>
      <Card>
        <PasswordChangeForm />
      </Card>
      <Card>
        <h2>Landing preference</h2>
        <p className="muted">Release pages not yet available can be saved, but are not navigation links.</p>
        <form onSubmit={submit} aria-label="Landing preference" noValidate>
          <div className="form-field">
            <label htmlFor="landing-page">Default landing page</label>
            <select id="landing-page" className="button button-secondary" value={destination} disabled={pending}
              aria-required="true" aria-invalid={Boolean(error)} aria-describedby={error ? 'landing-error' : undefined}
              onChange={(event) => { setDestination(event.target.value); setSaved(false); }}>
              {!choices.includes(destination as LandingPage) && <option value={destination}>Choose a landing page</option>}
              {choices.map((choice) => <option key={choice} value={choice}>{choice[0].toUpperCase() + choice.slice(1)}</option>)}
            </select>
          </div>
          {error && <p id="landing-error" role="alert" className="error-text">{error}</p>}
          <Button type="submit" loading={pending}>{pending ? 'Saving preference…' : 'Save preference'}</Button>
          <p role="status" aria-live="polite">{pending ? 'Saving landing preference…' : saved ? 'Preference saved' : ''}</p>
        </form>
      </Card>
    </div>
  );
}
