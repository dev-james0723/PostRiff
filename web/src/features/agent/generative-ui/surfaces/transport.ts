'use client';

/**
 * The consumer UiTransport (lane F): the signed-in session's Bearer token and the request guard for the current workspace.
 * Entering a new scope (sign-out, workspace switch) disposes every view, stream, saved-state timer and registry entry of the
 * old one. The founder transport lives in founder-transport.ts so no founder code reaches consumer bundles.
 */
import { useEffect, useMemo } from 'react';
import { createConsumerUiTransport } from '@/lib/agent-runtime/use-ui-artifact-stream';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { UiTransport } from '@/features/agent/generative-ui/bridges/types';
import { enterUiScope } from '../state/registry';
import { setActiveSessionScope } from './session';

export function useUiScope(transport: UiTransport | null) {
  const key = transport?.scopeKey ?? null;
  useEffect(() => {
    enterUiScope(key);
    setActiveSessionScope(key);
  }, [key]);
}

export function useConsumerUiTransport(): UiTransport | null {
  const { getToken, user } = useAuth();
  const { workspaceId } = useWorkspaceApi();
  const principal = user?.id ?? null;
  const transport = useMemo(
    () => (workspaceId && principal ? createConsumerUiTransport({ workspaceId, principal, getToken }) : null),
    [workspaceId, principal, getToken]
  );
  useUiScope(transport);
  return transport;
}
