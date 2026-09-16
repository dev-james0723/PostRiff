'use client';

/**
 * Session provider for the app shell.
 *
 * The API tells the client which identity mode a deployment uses
 * (`GET /api/catalog` → `authMode`):
 *   - `supabase`: real accounts; the bearer token is the Supabase access token.
 *   - `dev`: the local harness (`scripts/postriff_dev_hosted.py`); identity is a
 *     browser-generated principal and the token is `dev:<uuid>`. Never mounted
 *     by a production catalog.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { SupabaseClient } from '@supabase/supabase-js';
import { ApiError, createApi, type PostRiffApi } from '@/lib/api/client';
import type { AuthMode } from '@/lib/api/types';
import { hasSupabaseEnv } from '@/lib/supabase/env';

export interface AuthUser {
  id: string;
  email?: string;
  name?: string;
  imageUrl?: string;
}

export type AuthStatus = 'loading' | 'signed-out' | 'signed-in' | 'unavailable';

export interface AuthContextValue {
  mode: AuthMode | null;
  status: AuthStatus;
  user: AuthUser | null;
  /** Why the API is unavailable (status === 'unavailable'). */
  error: string | null;
  getToken: () => Promise<string | null>;
  signOut: () => Promise<void>;
  /** Unauthenticated client for public routes; authenticated once signed in. */
  api: PostRiffApi;
}

const DEV_PRINCIPAL_KEY = 'postriff-dev-principal';
const DEV_COOKIE = 'postriff_dev';

export function readDevPrincipal(): string | null {
  try {
    return localStorage.getItem(DEV_PRINCIPAL_KEY);
  } catch {
    return null;
  }
}

/** Dev harness only: mint a principal and mark the browser so the proxy lets /app through. */
export function devSignIn(fresh = false): string {
  let principal = fresh ? null : readDevPrincipal();
  if (!principal) {
    principal = crypto.randomUUID();
    localStorage.setItem(DEV_PRINCIPAL_KEY, principal);
  }
  document.cookie = `${DEV_COOKIE}=1; Path=/; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`;
  return principal;
}

function devSignOut() {
  try {
    localStorage.removeItem(DEV_PRINCIPAL_KEY);
  } catch {
    /* ignore */
  }
  document.cookie = `${DEV_COOKIE}=; Path=/; Max-Age=0`;
}

function userFromSupabase(user: {
  id: string;
  email?: string;
  user_metadata?: Record<string, unknown>;
}): AuthUser {
  const meta = user.user_metadata ?? {};
  return {
    id: user.id,
    email: user.email,
    name: (meta.full_name as string) || (meta.name as string) || undefined,
    imageUrl: (meta.avatar_url as string) || (meta.picture as string) || undefined
  };
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<AuthMode | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const supabaseRef = useRef<SupabaseClient | null>(null);

  const getToken = useCallback(async (): Promise<string | null> => {
    if (mode === 'dev') {
      const principal = readDevPrincipal();
      return principal ? `dev:${principal}` : null;
    }
    if (mode === 'supabase' && supabaseRef.current) {
      const { data } = await supabaseRef.current.auth.getSession();
      return data.session?.access_token ?? null;
    }
    return null;
  }, [mode]);

  const api = useMemo(() => createApi(getToken), [getToken]);

  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;

    async function boot() {
      let detected: AuthMode;
      try {
        const catalog = await createApi(async () => null).catalog();
        detected = catalog.authMode === 'dev' ? 'dev' : 'supabase';
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'The PostRiff API is not reachable.');
        setStatus('unavailable');
        return;
      }
      if (cancelled) return;
      setMode(detected);

      if (detected === 'dev') {
        const principal = readDevPrincipal();
        if (principal) {
          setUser({
            id: principal,
            name: 'Dev identity',
            email: `dev-${principal.slice(0, 8)}@postriff.invalid`
          });
          setStatus('signed-in');
        } else {
          setStatus('signed-out');
        }
        return;
      }

      if (!hasSupabaseEnv()) {
        setError('Supabase is not configured for this deployment.');
        setStatus('unavailable');
        return;
      }
      const { createClient } = await import('@/lib/supabase/client');
      const client = createClient();
      supabaseRef.current = client;
      const { data } = await client.auth.getSession();
      if (cancelled) return;
      if (data.session?.user) {
        setUser(userFromSupabase(data.session.user));
        setStatus('signed-in');
      } else {
        setStatus('signed-out');
      }
      const { data: sub } = client.auth.onAuthStateChange((_event, session) => {
        if (session?.user) {
          setUser(userFromSupabase(session.user));
          setStatus('signed-in');
        } else {
          setUser(null);
          setStatus('signed-out');
        }
      });
      unsubscribe = () => sub.subscription.unsubscribe();
    }

    void boot();
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* the server session may already be gone */
    }
    if (mode === 'dev') {
      devSignOut();
    } else if (supabaseRef.current) {
      await supabaseRef.current.auth.signOut({ scope: 'local' });
    }
    setUser(null);
    setStatus('signed-out');
  }, [api, mode]);

  const value = useMemo<AuthContextValue>(
    () => ({ mode, status, user, error, getToken, signOut, api }),
    [mode, status, user, error, getToken, signOut, api]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
