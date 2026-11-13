/** Own the sole token lifecycle and refresh safe identity after browser reload. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { PropsWithChildren } from 'react';
import type { LoginCredentials, SafeUser, SessionContextValue } from '../../types';
import { ApiError, SESSION_EXPIRED, TOKEN_KEY } from '../../lib/api';
import { authApi } from './authApi';
const SessionContext = createContext<SessionContextValue | null>(null);
/** Keep stale asynchronous identity responses from restoring a signed-out session. */
export function SessionProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<SafeUser | null>(null);
  const [loading, setLoading] = useState(Boolean(localStorage.getItem(TOKEN_KEY)));
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const clear = useCallback(() => {
    generation.current += 1;
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
    setError(null);
    setLoading(false);
  }, []);
  const refresh = useCallback(async () => {
    if (!localStorage.getItem(TOKEN_KEY)) { clear(); return; }
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const identity = await authApi.me();
      if (current === generation.current) setUser(identity);
    } catch (failure) {
      if (current === generation.current) {
        setUser(null);
        setError(failure instanceof Error ? failure.message : 'Unable to restore session');
      }
      if (failure instanceof ApiError && failure.status === 401) clear();
    } finally { if (current === generation.current) setLoading(false); }
  }, [clear]);
  useEffect(() => {
    void refresh();
    window.addEventListener(SESSION_EXPIRED, clear);
    const storage = (event: StorageEvent) => { if (event.key === TOKEN_KEY) void refresh(); };
    window.addEventListener('storage', storage);
    return () => {
      generation.current += 1;
      window.removeEventListener(SESSION_EXPIRED, clear);
      window.removeEventListener('storage', storage);
    };
  }, [clear, refresh]);
  const login = useCallback(async (credentials: LoginCredentials) => {
    const current = ++generation.current;
    const result = await authApi.login(credentials);
    if (current !== generation.current) return;
    localStorage.setItem(TOKEN_KEY, result.token);
    setUser(result.user);
    setError(null);
  }, []);
  const logout = useCallback(async () => {
    try { await authApi.logout(); }
    finally { clear(); }
  }, [clear]);
  return (
    <SessionContext.Provider value={{ user, loading, error, login, logout, refresh }}>
      {children}
    </SessionContext.Provider>
  );
}
/** Require provider ownership rather than silently using an anonymous fallback. */
export function useSession(): SessionContextValue {
  const session = useContext(SessionContext);
  if (!session) throw new Error('SessionProvider is required');
  return session;
}
