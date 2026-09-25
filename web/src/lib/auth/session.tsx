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
import { SessionQueryBoundary } from '@/lib/auth/session-query-boundary';
import { ApiError, createApi, type PostRiffApi } from '@/lib/api/client';
import type { WorkspaceBootstrap } from '@/lib/workspace/bootstrap';
import type { AuthMode } from '@/lib/api/types';
import { assurance } from '@/lib/auth/mfa';
import { hasSupabaseEnv } from '@/lib/supabase/env';
import { forgetPushOnSignOut } from '@/lib/coworker/push-signout';

export interface AuthUser {
  id: string;
  email?: string;
  name?: string;
  imageUrl?: string;
  emailVerified?: boolean;
  /** A new address awaiting confirmation (`updateUser({ email })` was called). */
  pendingEmail?: string;
  /** Sign-in provider id from the auth service (`google`, `email`…). */
  provider?: string;
  /** ISO timestamp of account creation. */
  createdAt?: string;
}

/** `mfa-required`: signed in, but a second factor is enrolled and this session has not shown it. */
export type AuthStatus = 'loading' | 'signed-out' | 'signed-in' | 'mfa-required' | 'unavailable';

export interface AuthContextValue {
  mode: AuthMode | null;
  status: AuthStatus;
  user: AuthUser | null;
  /** Why the API is unavailable (status === 'unavailable'). */
  error: string | null;
  getToken: () => Promise<string | null>;
  signOut: () => Promise<void>;
  /** Re-check the assurance level after a code was verified (leaves `mfa-required`). */
  completeMfa: () => Promise<void>;
  /** The browser Supabase client, for MFA and profile updates; null in dev mode. */
  supabase: SupabaseClient | null;
  /** Unauthenticated client for public routes; authenticated once signed in. */
  api: PostRiffApi;
}

const DEV_PRINCIPAL_KEY = 'postriff-dev-principal';

/** Unsent briefs and chosen destinations stay in this tab only while someone is signed in. */
function clearDraftStorage() {
  try {
    for (const key of Object.keys(window.sessionStorage)) {
      if (key.startsWith('rafii.brief.') || key.startsWith('rafii.destinations.')) window.sessionStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable: nothing was kept */
  }
}
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
  document.cookie = `postriff_dev_principal=${principal}; Path=/; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`;
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
  document.cookie = 'postriff_dev_principal=; Path=/; Max-Age=0';
}

function userFromSupabase(user: {
  id: string;
  email?: string;
  user_metadata?: Record<string, unknown>;
  app_metadata?: Record<string, unknown>;
  email_confirmed_at?: string;
  new_email?: string;
  created_at?: string;
}): AuthUser {
  const meta = user.user_metadata ?? {};
  return {
    id: user.id,
    email: user.email,
    name: (meta.full_name as string) || (meta.name as string) || undefined,
    imageUrl: (meta.avatar_url as string) || (meta.picture as string) || undefined,
    emailVerified: Boolean(user.email_confirmed_at),
    pendingEmail: user.new_email || undefined,
    provider: (user.app_metadata?.provider as string) || undefined,
    createdAt: user.created_at
  };
}

/** Signed in, or still owing a second factor for this session. */
async function statusFor(client: SupabaseClient): Promise<AuthStatus> {
  return (await assurance(client)) === 'pending' ? 'mfa-required' : 'signed-in';
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children, initial }: { children: ReactNode; initial?: WorkspaceBootstrap | null }) {
  const [mode, setMode] = useState<AuthMode | null>(initial?.mode ?? null);
  const [status, setStatus] = useState<AuthStatus>(initial ? 'signed-in' : 'loading');
  const [user, setUser] = useState<AuthUser | null>(initial ? { id: initial.me.userId, name: initial.me.displayName } : null);
  const [error, setError] = useState<string | null>(null);
  const [supabase, setSupabase] = useState<SupabaseClient | null>(null);
  const supabaseRef = useRef<SupabaseClient | null>(null);

  const getToken = useCallback(async (): Promise<string | null> => {
    if (mode === 'dev') {
      const principal = readDevPrincipal();
      return principal ? `dev:${principal}` : null;
    }
    if (mode === 'supabase') {
      if (!supabaseRef.current) { const { createClient } = await import('@/lib/supabase/client'); supabaseRef.current = createClient(); }
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
        detected = initial?.mode ?? ((await createApi(async () => null).catalog()).authMode === 'dev' ? 'dev' : 'supabase');
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Couldn’t reach Rafii. Check your connection and try again.');
        setStatus('unavailable');
        return;
      }
      if (cancelled) return;
      setMode(detected);

      if (detected === 'dev') {
        const principal = readDevPrincipal();
        if (principal) {
          document.cookie = `postriff_dev_principal=${principal}; Path=/; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`;
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
        setError('Sign-in isn’t available right now.');
        setStatus('unavailable');
        return;
      }
      const { createClient } = await import('@/lib/supabase/client');
      const client = createClient();
      supabaseRef.current = client;
      setSupabase(client);
      const { data } = await client.auth.getSession();
      if (cancelled) return;
      if (data.session?.user) {
        setUser(userFromSupabase(data.session.user));
        const next = await statusFor(client);
        if (cancelled) return;
        setStatus(next);
      } else {
        setStatus('signed-out');
      }
      const { data: sub } = client.auth.onAuthStateChange((_event, session) => {
        if (session?.user) {
          setUser(userFromSupabase(session.user));
          // Supabase asks that no auth call runs inside this callback, so the assurance check is deferred.
          setTimeout(() => {
            void statusFor(client).then((next) => {
              if (!cancelled) setStatus(next);
            });
          }, 0);
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
  }, [initial]);

  const signOut = useCallback(async () => {
    // A shared browser must not keep receiving the signed-out person's push notifications.
    await forgetPushOnSignOut();
    try {
      await api.logout();
    } catch {
      /* the server session may already be gone */
    }
    clearDraftStorage();
    if (mode === 'dev') {
      devSignOut();
    } else if (supabaseRef.current) {
      await supabaseRef.current.auth.signOut({ scope: 'local' });
    }
    setUser(null);
    setStatus('signed-out');
  }, [api, mode]);

  const completeMfa = useCallback(async () => {
    const client = supabaseRef.current;
    if (client) setStatus(await statusFor(client));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ mode, status, user, error, getToken, signOut, completeMfa, supabase, api }),
    [mode, status, user, error, getToken, signOut, completeMfa, supabase, api]
  );

  const identity = status === 'signed-in' ? user?.id ?? 'anonymous' : status;
  return <AuthContext.Provider value={value}><SessionQueryBoundary identity={identity} initial={initial}>{children}</SessionQueryBoundary></AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
