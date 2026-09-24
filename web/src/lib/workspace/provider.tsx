'use client';

/**
 * Active workspace for the signed-in user.
 *
 * Lists memberships from `GET /api/workspaces`; a first-time account has none,
 * so we bootstrap one with the plan chosen at sign-up (`POST /api/auth/verify`).
 * The selection is remembered per browser. Access (role → permissions, plan)
 * is derived here and published through `WorkspaceAccessProvider` so navigation
 * and page gating never need to know where it came from.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError, type PostRiffApi } from '@/lib/api/client';
import type { Membership, WorkspaceListItem } from '@/lib/api/types';
import { WorkspaceAccessProvider, type WorkspaceAccess } from '@/lib/auth/access';
import { permissionsFor } from '@/lib/auth/permissions';
import { useAuth } from '@/lib/auth/session';
import type { WorkspaceBootstrap } from './bootstrap';
import type { WorkspacePlan } from '@/types';

const WORKSPACE_KEY = 'postriff-workspace';
const PLAN_KEY = 'postriff-plan';

export type TrialPlan = 'studio' | 'assist';

export function selectedPlan(): TrialPlan {
  try {
    return localStorage.getItem(PLAN_KEY) === 'assist' ? 'assist' : 'studio';
  } catch {
    return 'studio';
  }
}

export function rememberPlan(plan: string) {
  try {
    localStorage.setItem(PLAN_KEY, plan === 'assist' ? 'assist' : 'studio');
  } catch {
    /* ignore */
  }
}

function readSelection(): string | null {
  try {
    return localStorage.getItem(WORKSPACE_KEY);
  } catch {
    return null;
  }
}

export type WorkspaceStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface WorkspaceContextValue {
  status: WorkspaceStatus;
  error: string | null;
  workspaceId: string | null;
  membership: Membership | null;
  workspaces: WorkspaceListItem[];
  plan: WorkspacePlan;
  api: PostRiffApi;
  switchTo: (workspaceId: string) => void;
  /** Reload the list; `select` makes that workspace active once it appears (after joining one). */
  refresh: (select?: string) => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function toPlan(value: string | undefined | null): WorkspacePlan {
  return value === 'studio' || value === 'assist' ? value : 'trial';
}

export function WorkspaceProvider({ children, initial }: { children: ReactNode; initial?: WorkspaceBootstrap | null }) {
  const auth = useAuth();
  const { api } = auth;
  const seed = initial?.me.userId === auth.user?.id ? initial : null;
  const seeded = useRef(Boolean(seed));
  const [status, setStatus] = useState<WorkspaceStatus>(seed ? 'ready' : 'idle');
  const [error, setError] = useState<string | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceListItem[]>(seed?.workspaces ?? []);
  const [selected, setSelected] = useState<string | null>(seed?.workspaceId ?? null);

  const load = useCallback(async (select?: string) => {
    setStatus('loading');
    setError(null);
    try {
      let list = (await api.workspaces()).workspaces;
      if (list.length === 0) {
        // First sign-in: create the trial workspace with the plan chosen at sign-up, then read the
        // list back so its summary (name, plan, member counts) comes from the one place that owns it.
        await api.bootstrap(selectedPlan());
        list = (await api.workspaces()).workspaces;
      }
      if (list.length === 0) throw new ApiError('Your workspace could not be created.', 500);
      setWorkspaces(list);
      const remembered = select ?? readSelection();
      const active = list.find((w) => w.workspaceId === remembered)?.workspaceId ?? list[0].workspaceId;
      setSelected(active);
      try {
        localStorage.setItem(WORKSPACE_KEY, active);
        document.cookie = `postriff_workspace=${encodeURIComponent(active)}; Path=/; SameSite=Lax`;
      } catch {
        /* ignore */
      }
      setStatus('ready');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Your workspace could not be loaded.');
      setStatus('error');
    }
  }, [api]);

  useEffect(() => {
    if (auth.status === 'signed-in') {
      if (seeded.current) { seeded.current = false; return; }
      void load();
    } else {
      setStatus('idle');
      setWorkspaces([]);
      setSelected(null);
    }
  }, [auth.status, load]);

  const switchTo = useCallback(
    (workspaceId: string) => {
      if (!workspaces.some((w) => w.workspaceId === workspaceId)) return;
      setSelected(workspaceId);
      try {
        localStorage.setItem(WORKSPACE_KEY, workspaceId);
        document.cookie = `postriff_workspace=${encodeURIComponent(workspaceId)}; Path=/; SameSite=Lax`;
      } catch {
        /* ignore */
      }
    },
    [workspaces]
  );

  const membership = useMemo(
    () => workspaces.find((w) => w.workspaceId === selected)?.membership ?? null,
    [workspaces, selected]
  );

  // The plan comes from the usage view (subscription or trial terms); cached like every other query.
  const usage = useQuery({
    queryKey: ['usage', selected],
    queryFn: () => api.usage(selected as string),
    enabled: status === 'ready' && Boolean(selected),
    staleTime: 60_000
  });
  const plan = toPlan(usage.data?.subscription?.plan ?? seed?.workspaces.find((w) => w.workspaceId === selected)?.plan);

  const access = useMemo<WorkspaceAccess>(
    () => ({
      role: membership?.role ?? 'viewer',
      permissions: membership ? permissionsFor(membership) : [],
      plan,
      hasWorkspace: Boolean(selected && membership),
      capabilities: []
    }),
    [membership, plan, selected]
  );

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      status,
      error,
      workspaceId: selected,
      membership,
      workspaces,
      plan,
      api,
      switchTo,
      refresh: load
    }),
    [status, error, selected, membership, workspaces, plan, api, switchTo, load]
  );

  return (
    <WorkspaceContext.Provider value={value}>
      <WorkspaceAccessProvider value={access}>{children}</WorkspaceAccessProvider>
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error('useWorkspace must be used inside <WorkspaceProvider>');
  return ctx;
}

/** Convenience for pages: the API plus a non-null workspace id (pages render behind the gate). */
export function useWorkspaceApi() {
  const { api, workspaceId } = useWorkspace();
  return { api, workspaceId: workspaceId as string };
}
