/** Attach one stored bearer only to protected requests and safely expire sessions. */
import type { ErrorEnvelope } from '../types';
export const TOKEN_KEY = 'kp-etsip-token';
export const SESSION_EXPIRED = 'kp-etsip-session-expired';
export class ApiError extends Error {
  /** Preserve safe server failures for feature-level rendering. */
  constructor(public status: number, public code: string, message: string) { super(message); }
}
/** Execute typed HTTP without adding identity to the public login request. */
export async function apiRequest<T>(path: string, options: RequestInit = {}, protectedCall = true): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  headers.delete('Authorization');
  if (protectedCall) {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers.set('Authorization', `Bearer ${token}`);
  }
  let response: Response;
  try {
    response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? '/api'}${path}`, { ...options, headers, cache: 'no-store' });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Unable to reach the service. Try again.');
  }
  if (!response.ok) {
    if (response.status === 401 && protectedCall) {
      localStorage.removeItem(TOKEN_KEY);
      window.dispatchEvent(new Event(SESSION_EXPIRED));
    }
    let body: ErrorEnvelope | null = null;
    try { body = await response.json() as ErrorEnvelope; } catch { body = null; }
    throw new ApiError(response.status, body?.error?.code ?? 'REQUEST_FAILED', body?.error?.message ?? 'Request failed. Try again.');
  }
  return response.json() as Promise<T>;
}
