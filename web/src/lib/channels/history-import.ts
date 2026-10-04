import type { ChannelView } from '@/lib/api/types';

export interface HistoryImportStatus {
  connectionId: string;
  status: 'none' | 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  importId?: string;
  pages?: number;
  posts?: number;
  failure?: string | null;
  requestedAt?: number;
  updatedAt?: number;
  attempts?: number;
  retryAt?: number | null;
  windowDays: number;
  maxPosts: number;
  maxPages: number;
  pageLimit: number;
  purgePending: boolean;
  metricReads: Partial<Record<'pending' | 'claimed' | 'done' | 'unavailable' | 'dead' | 'cancelled', number>>;
}

export const historyImportKey = (workspaceId: string, connectionId: string) => ['history-import', workspaceId, connectionId] as const;
export const historyImportSupported = (platform: string) => ['threads', 'instagram'].includes(platform.toLowerCase());
export const historyImportActive = (status?: HistoryImportStatus) => Boolean(status && ['pending', 'running'].includes(status.status));
export function historyImportWaiting(status?: HistoryImportStatus) {
  return (status?.metricReads.pending ?? 0) + (status?.metricReads.claimed ?? 0);
}
export function historyImportPoll(status?: HistoryImportStatus) {
  return Boolean(status?.purgePending || historyImportActive(status) || historyImportWaiting(status));
}
export function historyImportAllowed(channel: ChannelView, canManage: boolean, status?: HistoryImportStatus) {
  return canManage && historyImportSupported(channel.platform) && channel.capabilities.analytics?.level === 'Direct'
    && !['token_expired', 'reauthorization_required', 'scope_missing', 'unknown'].includes(channel.connectionState)
    && !(channel.expiresAt && channel.expiresAt <= Date.now() / 1000)
    && !status?.purgePending && !historyImportActive(status);
}

export type HistoryImportError = 'disabled' | 'purging' | 'analyticsRequired' | 'throttled' | 'sessionExpired' | 'permission' | 'disconnected' | 'error';
export function historyImportError(error: { status?: number; code?: string }): HistoryImportError {
  if (error.code === 'feature_disabled') return 'disabled';
  if (error.code === 'history_purge_pending') return 'purging';
  if (error.code === 'analytics_required') return 'analyticsRequired';
  if (error.status === 429) return 'throttled';
  if (error.status === 401 || error.code === 'interactive_required') return 'sessionExpired';
  if (error.status === 403) return 'permission';
  if (error.status === 404) return 'disconnected';
  return 'error';
}
