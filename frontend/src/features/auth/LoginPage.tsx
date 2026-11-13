/** Present local credential entry without signup or invented demo passwords. */
import { useState } from 'react';
import type { FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import { useSession } from './SessionProvider';
import { useRequest } from '../../lib/useRequest';
import { Button } from '../../components/Button';
import { Card } from '../../components/Card';
import { FormField } from '../../components/FormField';
/** Validate explicit credentials and surface safe backend failures inline. */
export default function LoginPage() {
  const session = useSession();
  const request = useRequest();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fields, setFields] = useState<Record<string, string>>({});
  if (session.user) return <Navigate to="/" replace />;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const errors: Record<string, string> = {};
    if (!email.trim()) errors.email = 'Email is required';
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) errors.email = 'Enter a valid email';
    if (!password) errors.password = 'Password is required';
    setFields(errors);
    if (Object.keys(errors).length) return;
    try { await request.run(() => session.login({ email: email.trim(), password })); }
    catch { setPassword(''); }
  };
  return (
    <main className="login-page">
      <div className="login-content">
        <p className="brand">KP ETSIP</p>
        <Card>
          <h1>Sign in</h1>
          <p className="muted">Use your local Platform Foundation account.</p>
          <form onSubmit={submit} noValidate>
            <FormField id="email" label="Email" type="email" autoComplete="username" required value={email}
              onChange={(event) => setEmail(event.target.value)} error={fields.email} />
            <FormField id="password" label="Password" type="password" autoComplete="current-password" required value={password}
              onChange={(event) => setPassword(event.target.value)} error={fields.password} />
            {request.error && <p role="alert" className="error-text">{request.error}</p>}
            <Button type="submit" loading={request.loading}>{request.loading ? 'Signing in…' : 'Sign in'}</Button>
            <p role="status" aria-live="polite">{request.loading ? 'Verifying credentials…' : ''}</p>
          </form>
        </Card>
      </div>
    </main>
  );
}
