import { useState } from 'react';
import Backdrop from '../components/Backdrop.jsx';
import Logo from '../components/Logo';
import { loginUrl, useAuth } from '../lib/auth';
import { navigate } from '../lib/router';
import { landingFor } from '../lib/tour';
import { OrbCursor, OrbOverlay } from '../orb/orbPresence';

const REASONS = {
  denied: 'You cancelled the Google sign-in. Try again when you are ready.',
  forbidden: 'That Google account is not on the allow-list. Ask the team to add it, or use another account.',
  unverified: 'Google says that email address is not verified. Verify it with Google, then try again.',
  failed: 'Sign-in did not complete. Please try again.',
};

const GoogleMark = () => (
  <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
    <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
    <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z" />
    <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1z" />
    <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z" />
  </svg>
);

// S0: Sign in. The dummy admin/admin pair signs in locally with no database; the Google button stays
// for servers that still offer it. One field pair, one primary action, one plain inline error.
const Login = ({ reason }) => {
  const { me, signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const message = reason ? REASONS[reason] ?? REASONS.failed : null;

  const submit = (event) => {
    event.preventDefault();
    if (busy) return;
    setError('');
    const result = signIn(email, password);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setBusy(true);
    navigate(landingFor(result.user));
  };

  const input =
    'h-11 w-full rounded-xl border border-white/15 bg-white/10 px-3.5 text-sm text-white placeholder:text-white/35 transition-colors focus:border-accent focus:bg-white/15 focus:outline-none';

  return (
    <div className="grid min-h-dvh place-items-center p-4">
      <Backdrop />
      <main className="glass-panel w-full max-w-sm rounded-[28px] p-8">
        <div className="flex flex-col items-center text-center">
          <Logo size={60} className="rounded-2xl" />
          <h1 className="mt-5 text-2xl font-semibold tracking-tight">Sign in to GrowIt</h1>
          <p className="mt-1 text-sm text-white/60">Your brand and campaigns, on your phone and laptop.</p>
        </div>

        {message && (
          <p role="alert" className="mt-5 rounded-xl bg-bad/15 px-3.5 py-2.5 text-sm text-white">
            {message}
          </p>
        )}

        <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium text-white/75">Email</span>
            <input
              type="text"
              name="email"
              autoComplete="username"
              spellCheck="false"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin"
              className={input}
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium text-white/75">Password</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="admin"
              className={input}
            />
          </label>
          {error && (
            <p role="alert" className="text-sm font-medium text-bad">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy} className="btn btn-primary h-11 w-full">
            {busy ? 'Signing in' : 'Sign in'}
            <OrbCursor active={busy} kind="loading" label="Signing in" />
          </button>
        </form>

        {me?.configured && (
          <>
            <div className="my-5 flex items-center gap-3 text-xs text-white/40">
              <span className="h-px flex-1 bg-white/10" />
              or
              <span className="h-px flex-1 bg-white/10" />
            </div>
            <a href={loginUrl()} className="btn h-11 w-full bg-white text-ink hover:bg-white/90">
              <GoogleMark /> Continue with Google
            </a>
          </>
        )}

        <p className="mt-6 text-center text-xs text-white/40">Demo sign-in: admin / admin</p>
      </main>
      <OrbOverlay show={busy} kind="loading" label="Signing you in" />
    </div>
  );
};

export default Login;
