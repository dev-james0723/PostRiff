'use client';

/**
 * The founder session for everything under `/founder`: one API client, the control session (environment, capabilities,
 * CSRF) read from `GET /session`, and the data mode from the address. There is no consumer `AuthProvider` or
 * `WorkspaceProvider` here: the only identity is the `__Host-rafii-control` cookie the browser sends on its own, and
 * a 401 from any call sends the person back to `/founder/sign-in`.
 */
import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { founderApi, founderKeys, signInHref, type FounderApi } from '@/lib/founder/api';
import { useFounderMode } from '@/lib/founder/page-context';
import type { FounderEnvironment, FounderMode } from '@/lib/founder/types';

export interface FounderSessionValue {
  api: FounderApi;
  mode: FounderMode;
  setMode: (mode: FounderMode) => void;
  /** Known once `GET /session` answered; null while it loads or after it failed. */
  environment: FounderEnvironment | null;
  capabilities: string[];
  sessionStatus: 'loading' | 'ready' | 'error';
  sessionError: unknown;
  retrySession: () => void;
  can: (capability: string) => boolean;
  signOut: () => Promise<void>;
}

const FounderSessionContext = createContext<FounderSessionValue | null>(null);

export function FounderSessionProvider({ children }: { children: ReactNode }) {
  // The one client per page load (`founderApi()`), shared with the domain pages' `founderFetch` so the CSRF token
  // read from `GET /session` is cached once for everything under the shell.
  const api = founderApi();
  const client = useQueryClient();
  const [mode, setMode] = useFounderMode();
  const session = useQuery({
    queryKey: founderKeys.session,
    queryFn: () => api.session(),
    retry: false,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: true
  });

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      api.resetSession();
      client.removeQueries({ queryKey: ['founder'] });
      window.location.assign(signInHref());
    }
  }, [api, client]);

  const value = useMemo<FounderSessionValue>(() => {
    const capabilities = session.data?.data.capabilities ?? [];
    return {
      api,
      mode,
      setMode,
      environment: session.data?.environment ?? null,
      capabilities,
      sessionStatus: session.isPending ? 'loading' : session.isError ? 'error' : 'ready',
      sessionError: session.error,
      retrySession: () => void session.refetch(),
      can: (capability) => capabilities.includes(capability),
      signOut
    };
  }, [api, mode, setMode, session, signOut]);

  return <FounderSessionContext.Provider value={value}>{children}</FounderSessionContext.Provider>;
}

export function useFounderSession(): FounderSessionValue {
  const value = useContext(FounderSessionContext);
  if (!value) throw new Error('useFounderSession must be used inside <FounderSessionProvider>');
  return value;
}

export function useFounderApi(): FounderApi {
  return useFounderSession().api;
}
