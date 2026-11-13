/** Define implemented session routes and a single protected entry point. */
import { Navigate, Route, Routes } from 'react-router-dom';
import { useSession } from './features/auth/SessionProvider';
import ProfilePage from './features/profile/ProfilePage';
import LoginPage from './features/auth/LoginPage';
import PortfolioList from './features/portfolios/PortfolioList';
import PortfolioDetailPage from './features/portfolios/PortfolioDetailPage';
import UserAdminPage from './features/users/UserAdminPage';
import RoleAdminPage from './features/roles/RoleAdminPage';
import ApplicationList from './features/applications/ApplicationList';
import ApplicationDetailPage from './features/applications/ApplicationDetailPage';
import { AppLayout } from './components/AppLayout';
import { Button } from './components/Button';
/** Guard the shell while restored credentials are checked against the backend. */
export function AppRoutes() {
  const session = useSession();
  if (session.loading) return <main className="container" role="status">Restoring session…</main>;
  if (!session.user && session.error && localStorage.getItem('kp-etsip-token')) {
    return (
      <main className="container">
        <p role="alert">{session.error}</p>
        <Button onClick={() => void session.refresh()}>Retry session</Button>
        <Button variant="secondary" onClick={() => void session.logout().catch(() => undefined)}>Sign out</Button>
      </main>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={session.user ? <AppLayout /> : <Navigate to="/login" replace />} />
      <Route path="/profile" element={session.user ? session.user.mustChangePassword ? <Navigate to="/" replace /> : (
        <AppLayout>
          <ProfilePage />
        </AppLayout>
      ) : <Navigate to="/login" replace />} />
      <Route path="/portfolios" element={session.user ? (
        <AppLayout>
          <PortfolioList />
        </AppLayout>
      ) : <Navigate to="/login" replace />} />
      <Route path="/portfolios/:id" element={session.user ? (
        <AppLayout>
          <PortfolioDetailPage />
        </AppLayout>
      ) : <Navigate to="/login" replace />} />
      <Route path="/applications" element={session.user ? (
        <AppLayout>
          <ApplicationList />
        </AppLayout>
      ) : <Navigate to="/login" replace />} />
      <Route path="/applications/:id" element={session.user ? (
        <AppLayout>
          <ApplicationDetailPage />
        </AppLayout>
      ) : <Navigate to="/login" replace />} />
      {['/users', '/users/:id'].map((path) => (
        <Route key={path} path={path} element={session.user ? session.user.role === 'Administrator' ? (
          <AppLayout>
            <UserAdminPage />
          </AppLayout>
        ) : <Navigate to="/" replace /> : <Navigate to="/login" replace />} />
      ))}
      <Route path="/roles" element={session.user ? session.user.role === 'Administrator' ? (
        <AppLayout>
          <RoleAdminPage />
        </AppLayout>
      ) : <Navigate to="/" replace /> : <Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
