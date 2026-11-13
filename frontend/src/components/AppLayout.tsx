/** Show current session identity and links only to implemented routes. */
import { Link } from 'react-router-dom';
import { useSession } from '../features/auth/SessionProvider';
import { useRequest } from '../lib/useRequest';
import { Button } from './Button';
import { Card } from './Card';
/** Render the authenticated shell with explicit sign-out and identity refresh. */
export function AppLayout() {
  const session = useSession();
  const request = useRequest();
  const user = session.user;
  if (!user) return null;
  const signOut = async () => {
    try { await request.run(session.logout); }
    catch { /* Session is cleared by provider even if the server is unavailable. */ }
  };
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="brand">KP ETSIP</Link>
        <nav aria-label="Session navigation">
          <Link to="/" aria-current="page">Session</Link>
          <Button variant="secondary" loading={request.loading} onClick={signOut}>Sign out</Button>
        </nav>
      </header>
      <main className="container">
        <h1>Authenticated session</h1>
        <Card>
          <h2>{user.name}</h2>
          <dl className="identity-details">
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Role</dt><dd>{user.role}</dd>
            <dt>Status</dt><dd>{user.status}</dd>
            <dt>Portfolio access</dt><dd>{user.portfolioAccess.length ? user.portfolioAccess.join(', ') : 'No explicit assignments'}</dd>
          </dl>
          {user.mustChangePassword && <p role="alert">Password change required. Protected actions are restricted.</p>}
          <Button variant="secondary" loading={session.loading} onClick={() => void session.refresh()}>Refresh identity</Button>
          {session.error && <p role="alert" className="error-text">{session.error}</p>}
          <p role="status" aria-live="polite">{session.loading ? 'Refreshing identity…' : 'Signed in'}</p>
        </Card>
      </main>
    </div>
  );
}
