'use client';

/**
 * How Rafii talks to this person (Contract 1), read from and saved to their profile: `GET/PATCH /api/me` →
 * `preferences.agentStyle`. It shares the `useMe` cache, so every screen shows the same style.
 *
 * A save shows at once (optimistic) and reaches the server one at a time, in the order it was made, so the last choice
 * is the one kept. A failed save rolls back, shows a toast and rejects, so a caller can say the change didn't happen.
 */
import { useCallback, useEffect, useMemo } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ApiError } from '@/lib/api/client';
import { keys, useMe } from '@/lib/api/hooks';
import type { Me } from '@/lib/api/types';
import { useWorkspace } from '@/lib/workspace/provider';
import { registerPanelActions } from './panel-actions';
import { normalizeStyle, PRESETS, type AgentStyle, type AgentStylePatch } from './style';

/** The style a patch leads to, merged the way the server merges it: the preset's choices first, then single fields. */
export function applyStylePatch(current: AgentStyle, patch: AgentStylePatch): AgentStyle {
  const { preset, ...fields } = patch;
  const given = Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined));
  return normalizeStyle({ ...current, ...(preset ? PRESETS[preset]?.style : undefined), ...given });
}

type SaveResult = { displayName: string; preferences: Me['preferences'] };

const ME = { queryKey: keys.me, exact: true } as const;
let queue: Promise<unknown> = Promise.resolve();
let unsettled = 0;

/** One save at a time, in the order they were made. */
function inOrder<T>(task: () => Promise<T>): Promise<T> {
  const run = queue.then(task, task);
  queue = run.catch(() => undefined);
  return run;
}

/** `save` from `useAgentStyle`, given its query client and the API call (exported for the unit tests). */
export async function saveStyle(client: QueryClient, send: (patch: AgentStylePatch) => Promise<SaveResult>, patch: AgentStylePatch): Promise<void> {
  await client.cancelQueries(ME);
  const previous = client.getQueryData<Me>(keys.me);
  if (previous) client.setQueryData<Me>(keys.me, { ...previous, preferences: { ...previous.preferences, agentStyle: applyStylePatch(normalizeStyle(previous.preferences?.agentStyle), patch) } });
  unsettled += 1;
  let saved: SaveResult;
  try {
    saved = await inOrder(() => send(patch));
  } catch (error) {
    unsettled -= 1;
    // While later saves are on their way the screen already shows them; the last one to settle sets the cache.
    if (unsettled === 0) {
      if (previous) client.setQueryData<Me>(keys.me, previous);
      void client.invalidateQueries(ME);
    }
    toast.error(error instanceof ApiError ? error.message : 'Couldn’t save how Rafii talks. Check your connection and try again.');
    throw error;
  }
  unsettled -= 1;
  if (unsettled === 0) client.setQueryData<Me>(keys.me, (current) => (current ? { ...current, displayName: saved.displayName, preferences: { ...current.preferences, ...saved.preferences } } : current));
}

export function useAgentStyle(): { style: AgentStyle; save: (patch: AgentStylePatch) => Promise<void>; loading: boolean } {
  const me = useMe();
  const { api } = useWorkspace();
  const client = useQueryClient();
  const stored = me.data?.preferences?.agentStyle;
  const style = useMemo(() => normalizeStyle(stored), [stored]);
  const save = useCallback((patch: AgentStylePatch) => saveStyle(client, api.updateAgentStyle, patch), [api, client]);
  return { style, save, loading: me.isPending };
}

/**
 * Lets a voice request, an answer or a typed command change the style (`panelActions.setStyle`). Mount it once: the
 * Rafii panel's always-present shell does, so it works while the panel is closed and a call carries on.
 */
export function useRegisterStyleAction() {
  const { save } = useAgentStyle();
  useEffect(() => registerPanelActions({ setStyle: save }), [save]);
}
