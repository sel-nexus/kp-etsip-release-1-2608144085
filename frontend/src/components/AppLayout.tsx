/** Show current session identity and links only to implemented routes. */
import { Link, useLocation } from 'react-router-dom';
import { useSession } from '../features/auth/SessionProvider';
import { useRequest } from '../lib/useRequest';
import { Button } from './Button';
import { Card } from './Card';
import type { PropsWithChildren } from 'react';
import { PasswordChangeForm } from '../features/profile/PasswordChangeForm';
/** Render the authenticated shell with explicit sign-out and identity refresh. */
export function AppLayout({ children }: PropsWithChildren) {
  const location = useLocation();
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
          <Link to="/" aria-current={location.pathname === '/' ? 'page' : undefined}>Session</Link>
          {!user.mustChangePassword && (
            <Link to="/dashboard" aria-current={location.pathname === '/dashboard' ? 'page' : undefined}>Dashboard</Link>
          )}
          {!user.mustChangePassword && <Link to="/profile" aria-current={location.pathname === '/profile' ? 'page' : undefined}>My profile</Link>}
          {!user.mustChangePassword && (
            <Link to="/portfolios" aria-current={location.pathname.startsWith('/portfolios') ? 'page' : undefined}>Portfolios</Link>
          )}
          {!user.mustChangePassword && (
            <Link to="/applications" aria-current={location.pathname.startsWith('/applications') ? 'page' : undefined}>Applications</Link>
          )}
          {!user.mustChangePassword && user.role === 'Administrator' && (
            <Link to="/users" aria-current={location.pathname.startsWith('/users') ? 'page' : undefined}>Users</Link>
          )}
          {!user.mustChangePassword && user.role === 'Administrator' && (
            <Link to="/roles" aria-current={location.pathname === '/roles' ? 'page' : undefined}>Roles</Link>
          )}
          {!user.mustChangePassword && ['Administrator', 'Auditor'].includes(user.role) && (
            <Link to="/audit" aria-current={location.pathname === '/audit' ? 'page' : undefined}>Audit history</Link>
          )}
          <Button variant="secondary" loading={request.loading} onClick={signOut}>Sign out</Button>
        </nav>
      </header>
      <main className="container">
        {user.mustChangePassword ? (
          <Card>
            <h1>Secure your account</h1>
            <PasswordChangeForm requiredChange />
          </Card>
        ) : children ?? (
          <>
            <h1>Authenticated session</h1>
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
                <dd>{user.portfolioAccess.length ? user.portfolioAccess.join(', ') : 'No explicit assignments'}</dd>
              </dl>
              <Button variant="secondary" loading={session.loading} onClick={() => void session.refresh()}>
                Refresh identity
              </Button>
              {session.error && <p role="alert" className="error-text">{session.error}</p>}
              <p role="status" aria-live="polite">{session.loading ? 'Refreshing identity…' : 'Signed in'}</p>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
