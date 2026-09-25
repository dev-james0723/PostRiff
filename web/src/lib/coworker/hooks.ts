'use client';

/**
 * TanStack Query hooks over the coworker routes, keyed per workspace like `@/lib/api/hooks`. A feature whose flag
 * is off answers 404 `feature_disabled`; `featureOff(query)` lets a view hide itself instead of showing an error.
 * Mutations invalidate the narrowest keys they change and never claim success the server did not verify.
 */
import { useMemo } from 'react';
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { createCoworkerApi, isFeatureDisabled, shouldRetry } from './api';
import type { CoworkerFlag, NoteInput, PreferencePatch, RecipeInput, SlotAction } from './types';

export const coworkerKeys = {
  status: (w: string) => ['coworker', w, 'status'] as const,
  attention: (w: string) => ['coworker', w, 'attention'] as const,
  notifications: (w: string) => ['coworker', w, 'notifications'] as const,
  preferences: (w: string) => ['coworker', w, 'notification-preferences'] as const,
  pushDevices: (w: string) => ['coworker', w, 'push-devices'] as const,
  weekly: (w: string) => ['coworker', w, 'weekly'] as const,
  week: (w: string, weekId: string) => ['coworker', w, 'weekly', 'week', weekId] as const,
  overlays: (w: string) => ['coworker', w, 'overlays'] as const,
  performance: (w: string) => ['coworker', w, 'performance'] as const,
  listening: (w: string) => ['coworker', w, 'listening'] as const,
  engagement: (w: string) => ['coworker', w, 'engagement'] as const
};

/** The notification centre and attention list refresh about once a minute while the tab is visible. */
export const POLL_MS = 60_000;

export function useCoworkerApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createCoworkerApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

/** True when the query failed only because the deployment has the feature switched off. */
export function featureOff(query: Pick<UseQueryResult, 'error'>): boolean {
  return isFeatureDisabled(query.error);
}

const base = { retry: shouldRetry } as const;

export function useCoworkerStatus() {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.status(w), queryFn: () => api.status(w), enabled, staleTime: 5 * 60_000, ...base });
}

/** `true` / `false` once the status is known, `null` while loading or when the coworker routes are unavailable. */
export function useCoworkerFlag(flag: CoworkerFlag): boolean | null {
  const status = useCoworkerStatus();
  if (!status.data) return null;
  return status.data.flags?.[flag] === true;
}

/**
 * Whether any of these features is on, per the status route (which answers even with every flag off). False while
 * the status loads. Feature queries wait for it, so a workspace with the features off makes no request that would
 * only return 404 (every page mounts the bell, and Overview mounts the attention panel).
 */
function useAnyFlagOn(...flags: CoworkerFlag[]): boolean {
  const status = useCoworkerStatus();
  return Boolean(status.data && flags.some((flag) => status.data.flags?.[flag] === true));
}

export function useCoworkerAttention() {
  const { api, w, enabled } = useCoworkerApi();
  const on = useAnyFlagOn('RAFII_NOTIFICATIONS_V2_ENABLED', 'RAFII_WEEKLY_OPERATOR_ENABLED');
  return useQuery({ queryKey: coworkerKeys.attention(w), queryFn: () => api.attention(w), enabled: enabled && on, refetchInterval: POLL_MS, refetchIntervalInBackground: false, ...base });
}

/* ---------- notifications ---------- */

export function useNotificationCenter() {
  const { api, w, enabled } = useCoworkerApi();
  const on = useAnyFlagOn('RAFII_NOTIFICATIONS_V2_ENABLED');
  return useQuery({ queryKey: coworkerKeys.notifications(w), queryFn: () => api.notifications(w), enabled: enabled && on, refetchInterval: POLL_MS, refetchIntervalInBackground: false, ...base });
}

export function useMarkNotification() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; action: 'read' | 'acted' | 'dismissed' }) => api.markNotification(w, input.id, input.action),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.notifications(w) })
  });
}

export function useNotificationPreferences() {
  const { api, w, enabled } = useCoworkerApi();
  const on = useAnyFlagOn('RAFII_NOTIFICATIONS_V2_ENABLED');
  return useQuery({ queryKey: coworkerKeys.preferences(w), queryFn: () => api.preferences(w), enabled: enabled && on, ...base });
}

export function useSetPreference() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patch: PreferencePatch) => api.setPreference(w, patch),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.preferences(w) })
  });
}

export function usePushDevices(enabledWhen = true) {
  const { api, w, enabled } = useCoworkerApi();
  const centre = useAnyFlagOn('RAFII_NOTIFICATIONS_V2_ENABLED');
  const push = useAnyFlagOn('RAFII_WEB_PUSH_ENABLED');
  return useQuery({ queryKey: coworkerKeys.pushDevices(w), queryFn: () => api.pushDevices(w), enabled: enabled && enabledWhen && centre && push, ...base });
}

/* ---------- weekly ---------- */

export function useWeekly(enabledWhen = true) {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.weekly(w), queryFn: () => api.weekly(w), enabled: enabled && enabledWhen, ...base });
}

export function useWeek(weekId: string | null) {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.week(w, weekId ?? ''), queryFn: () => api.week(w, weekId as string), enabled: enabled && Boolean(weekId), ...base });
}

export function useSaveRecipe() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { recipeId?: string; values: RecipeInput }) => (input.recipeId ? api.updateRecipe(w, input.recipeId, input.values) : api.createRecipe(w, input.values)),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.weekly(w) })
  });
}

export function useRecipeStatus() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { recipeId: string; status: 'active' | 'paused' | 'deleted' }) => api.recipeStatus(w, input.recipeId, input.status),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.weekly(w) })
  });
}

export function usePrepareWeek() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (recipeId: string) => api.prepareWeek(w, recipeId),
    onSettled: (result) => {
      void client.invalidateQueries({ queryKey: coworkerKeys.weekly(w) });
      if (result?.week?.id) void client.invalidateQueries({ queryKey: coworkerKeys.week(w, result.week.id) });
      void client.invalidateQueries({ queryKey: coworkerKeys.attention(w) });
    }
  });
}

export function useSlotAction(weekId: string | null) {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { slotId: string; action: SlotAction; answer?: string; reason?: string }) =>
      api.slotAction(w, weekId as string, input.slotId, input.action, input.action === 'answer' ? { answer: input.answer } : input.reason ? { reason: input.reason } : {}),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: coworkerKeys.week(w, weekId ?? '') });
      void client.invalidateQueries({ queryKey: coworkerKeys.weekly(w) });
      void client.invalidateQueries({ queryKey: coworkerKeys.attention(w) });
    }
  });
}

/* ---------- personalization ---------- */

export function useOverlays() {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.overlays(w), queryFn: () => api.overlays(w), enabled, ...base });
}

export function useSaveNote() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { noteId?: string; values: NoteInput }) => (input.noteId ? api.editNote(w, input.noteId, input.values) : api.addNote(w, input.values)),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.overlays(w) })
  });
}

export function useOverlayStatus() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; status: 'active' | 'disabled' | 'retired' }) => api.overlayStatus(w, input.id, input.status),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.overlays(w) })
  });
}

export function useResetOverlays() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scope: 'notes' | 'learned' | 'all') => api.resetOverlays(w, scope),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.overlays(w) })
  });
}

export function usePerformance(enabledWhen = true) {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.performance(w), queryFn: () => api.performance(w), enabled: enabled && enabledWhen, ...base });
}

export function useDecideHypothesis() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; decision: 'experiment' | 'dismissed' | 'rejected' }) => api.decideHypothesis(w, input.id, input.decision),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: coworkerKeys.overlays(w) });
      void client.invalidateQueries({ queryKey: coworkerKeys.performance(w) });
    }
  });
}

/* ---------- listening + engagement ---------- */

export function useListening(enabledWhen = true) {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.listening(w), queryFn: () => api.listening(w), enabled: enabled && enabledWhen, ...base });
}

export function useSaveWatchlist() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { query: string; goal: string }) => api.saveWatchlist(w, input),
    onSettled: () => client.invalidateQueries({ queryKey: coworkerKeys.listening(w) })
  });
}

export function useDecideOpportunity() {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; decision: 'act' | 'dismiss' }) => api.decideOpportunity(w, input.id, input.decision),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: coworkerKeys.listening(w) });
      void client.invalidateQueries({ queryKey: coworkerKeys.attention(w) });
    }
  });
}

export function useEngagementSummary(enabledWhen = true) {
  const { api, w, enabled } = useCoworkerApi();
  return useQuery({ queryKey: coworkerKeys.engagement(w), queryFn: () => api.engagement(w), enabled: enabled && enabledWhen, ...base });
}
