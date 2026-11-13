/** Compose the sole browser router and session owner. */
import { BrowserRouter } from 'react-router-dom';
import { SessionProvider } from './features/auth/SessionProvider';
import { AppRoutes } from './routes';
/** Bootstrap only implemented feature routes. */
export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </BrowserRouter>
  );
}
