'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { founderFetch, randomKey } from '@/lib/founder/api';
import { isFounderApiError } from '@/lib/founder/errors';
import type { Envelope } from '@/lib/founder/types';
import { useFounderScope } from '../customers/kit/api';
import { writeFailure, type NoticePreferences, type NoticeRow, type NoticesData, type OpsWorkspace, type OpsWorkspaceCreated, type PreferencesData, type PreferencesPatch, type ReportDetail, type ReportsData } from './comms';

/**
 * Settings → Notifications, Reports and the founder workspace over `founderFetch` (CONTRACTS §8.E, §8.H). Preferences and
 * the founder workspace are settings, the same in either data mode, so their keys carry the environment only; notices
 * and briefing versions are data, so their keys and requests carry the mode (Demo answers them empty with a reason).
 * Every hook returns what the server sent.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const commsKeys = {
  preferences: (environment: string) => ['founder', 'notice-preferences', environment] as const,
  opsWorkspace: (environment: string) => ['founder', 'ops-workspace', environment] as const
};

/** A failed write, with the blocker a 409 carried. */
export function writeFailureOf(error: unknown) {
  if (isFounderApiError(error)) return writeFailure({ status: error.status, code: error.code, message: error.message, blocker: error.blocker });
  return writeFailure({ message: 'Control request could not be completed. Review its evidence and retry.' });
}

export function useNoticePreferences() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: commsKeys.preferences(scope.environment),
    enabled: scope.ready,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<PreferencesData>>('/notifications/preferences', { signal })).data
  });
}

export function useSaveNoticePreferences() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (patch: PreferencesPatch) => (await founderFetch<Envelope<{ preferences: NoticePreferences }>>('/notifications/preferences', { method: 'PUT', body: patch })).data,
    onSuccess: () => client.invalidateQueries({ queryKey: commsKeys.preferences(scope.environment) })
  });
}

export function useNotices(options: { enabled?: boolean; staleTime?: number } = {}) {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('notices'),
    enabled: scope.ready && options.enabled !== false,
    staleTime: options.staleTime,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<NoticesData>>(`/notifications?mode=${scope.mode}&limit=20`, { signal })).data
  });
}

/** One in-app test notice (Live only; never email or push). A retry of the same click is the same notice. */
export function useTestNotice() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (requestId: string) =>
      (await founderFetch<Envelope<{ notice: NoticeRow; replayed: boolean; unread: number }>>('/notifications/test?mode=live', { method: 'POST', body: UUID.test(requestId) ? { requestId } : {} })).data,
    onSuccess: () => client.invalidateQueries({ queryKey: scope.key('notices') })
  });
}

export function useMarkNoticeRead() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => (await founderFetch<Envelope<{ notice: NoticeRow; unread: number }>>(`/notifications/${encodeURIComponent(id)}/read?mode=live`, { method: 'POST', body: {} })).data,
    onSuccess: () => client.invalidateQueries({ queryKey: scope.key('notices') })
  });
}

export function useReports() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('reports'),
    enabled: scope.ready,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<ReportsData>>(`/reports?mode=${scope.mode}&limit=20`, { signal })).data
  });
}

/** One briefing version with its text; only asked for in Live, for an id the list returned. */
export function useReport(id: string | null) {
  const scope = useFounderScope();
  const valid = Boolean(id && UUID.test(id));
  return useQuery({
    queryKey: scope.key('report', id),
    enabled: scope.ready && scope.mode === 'live' && valid,
    queryFn: async ({ signal }) => {
      const envelope = await founderFetch<Envelope<{ report: ReportDetail }>>(`/reports/${encodeURIComponent(id as string)}?mode=live`, { signal });
      return { report: envelope.data.report, receiptIds: envelope.receiptIds ?? envelope.data.report.receiptIds, dataState: envelope.dataState };
    }
  });
}

export function useOpsWorkspace() {
  const scope = useFounderScope();
  return useQuery({
    queryKey: commsKeys.opsWorkspace(scope.environment),
    enabled: scope.ready,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<OpsWorkspace>>('/ops-workspace', { signal })).data
  });
}

/** Creates the founder workspace once (Live, control.settings, a fresh second factor); an existing one comes back unchanged. */
export function useCreateOpsWorkspace() {
  const scope = useFounderScope();
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await founderFetch<Envelope<OpsWorkspaceCreated>>('/ops-workspace?mode=live', { method: 'POST', body: {} })).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: commsKeys.opsWorkspace(scope.environment) });
      // Voice and Founder Rafii read the workspace on their next request; their availability is re-read now.
      void client.invalidateQueries({ predicate: (query) => query.queryKey.includes('voice-status') });
    }
  });
}

export { randomKey };
