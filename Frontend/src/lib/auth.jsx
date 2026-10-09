import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { API_URL, api } from '../campaign/lib/api';

// Who is signed in, from GET /auth/me. The server session lives in an HttpOnly cookie the page never reads.
// Alongside it, a local "dummy" sign-in lets the app run with no database: the flag lives in localStorage
// and gates the app on its own, so the demo works even when the API is down. No secret is stored or sent.
const AuthContext = createContext(null);

const LOCAL_KEY = 'growit-signed-in';
const LOCAL_EVENT = 'growit-signed-in-change';
// The demo credentials the owner asked for. Compared in memory only; nothing leaves the browser.
const DEMO = { email: 'admin', password: 'admin' };

export const loginUrl = () => `${API_URL}/auth/google/login`;

// The stored local session, or null. A blocked storage simply reads as signed out.
const readLocal = () => {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

const writeLocal = (value) => {
  try {
    if (value) localStorage.setItem(LOCAL_KEY, JSON.stringify(value));
    else localStorage.removeItem(LOCAL_KEY);
  } catch {
    // Storage blocked: the session still holds for this visit through the in-memory state.
  }
};

export const AuthProvider = ({ children }) => {
  const [me, setMe] = useState(null); // null while loading
  const [unreachable, setUnreachable] = useState(false);
  const [local, setLocal] = useState(readLocal);

  const refresh = useCallback(async () => {
    try {
      const next = await api('/auth/me');
      setMe(next);
      setUnreachable(false);
    } catch {
      setUnreachable(true);
      setMe((cur) => cur ?? { configured: false, require_login: false, signed_in: false, user: null, restricted: false });
    }
  }, []);

  useEffect(() => {
    refresh();
    // Any API call that comes back "login required" means the session ended: ask again.
    window.addEventListener('ll-login-required', refresh);
    return () => window.removeEventListener('ll-login-required', refresh);
  }, [refresh]);

  // Keep the local flag in step with other tabs (storage) and with this one (LOCAL_EVENT).
  useEffect(() => {
    const sync = () => setLocal(readLocal());
    window.addEventListener(LOCAL_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(LOCAL_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  // The dummy sign-in. Case-insensitive email, exact password. Returns { ok } or { ok: false, error }.
  const signIn = useCallback((email, password) => {
    const ok = String(email || '').trim().toLowerCase() === DEMO.email && String(password || '').trim() === DEMO.password;
    if (!ok) {
      return { ok: false, error: 'That email and password do not match. Use admin and admin.' };
    }
    const session = { email: DEMO.email, name: 'Admin', sub: DEMO.email, at: Date.now() };
    writeLocal(session);
    setLocal(session);
    window.dispatchEvent(new Event(LOCAL_EVENT));
    return { ok: true, user: session };
  }, []);

  const logout = useCallback(async () => {
    writeLocal(null);
    setLocal(null);
    try {
      await api('/auth/logout', { method: 'POST' });
    } catch {
      // The server session is already gone, or the API is unreachable: the local flag is what gates the app.
    } finally {
      await refresh();
    }
  }, [refresh]);

  // Signed in if the local demo flag is set, or the server says so. The local flag wins, so the demo
  // never depends on the API being reachable.
  const signedIn = Boolean(local) || Boolean(me?.signed_in);
  const effectiveMe = useMemo(() => {
    if (!local) return me;
    return {
      ...(me || {}),
      configured: me?.configured ?? false,
      require_login: false,
      signed_in: true,
      restricted: false,
      user: me?.user || { name: local.name, email: local.email, sub: local.sub },
    };
  }, [local, me]);

  const value = useMemo(
    () => ({ me: effectiveMe, loading: effectiveMe === null, unreachable, refresh, logout, signIn, signedIn, local }),
    [effectiveMe, unreachable, refresh, logout, signIn, signedIn, local]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);
