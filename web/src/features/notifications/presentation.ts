import type { AttentionItem } from '@/lib/attention';
import type { ServerNotification } from '@/lib/coworker/types';
import { safeAppHref } from '@/lib/coworker/safe-href';
import type { NoticeRow } from '@/features/founder/settings/comms';
import { founderSafeHref } from '@/features/founder/shared/safe-href';
import { eventLabel } from '@/features/coworker/notifications/labels';

export type NotificationKind = 'action_required' | 'critical' | 'security' | 'warning' | 'success' | 'info';
export type NotificationPriority = 'critical' | 'high' | 'normal' | 'low';
export type NotificationSurface = 'live' | 'center' | 'toast' | 'activity';
export type NotificationSource = 'attention' | 'server' | 'founder';

export interface NotificationViewModel {
  id: string;
  source: NotificationSource;
  sourceId: string;
  dedupeKey?: string;
  kind: NotificationKind;
  priority: NotificationPriority;
  title: string;
  description?: string;
  createdAt: number;
  unread: boolean;
  actionable: boolean;
  durable: boolean;
  dismissible: boolean;
  href?: string;
  openLabel?: string;
  taskId?: string;
}

const PRIORITY: Record<NotificationPriority, number> = { critical: 0, high: 1, normal: 2, low: 3 };
const ACTION_LABELS: Record<string, string> = {
  'campaign.approval_required': 'Review',
  'campaign.drafts_ready': 'Review drafts',
  'research.needs_input': 'Respond',
  'asset.review_required': 'Review',
  'channel.reconnect_required': 'Reconnect',
  'billing.payment_failed': 'Fix billing',
  'publish.failed': 'View failure',
  'publish.uncertain': 'Review status',
  'security.new_device': 'Review sessions',
  'security.account_change': 'Review account'
};

function appHref(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const safe = safeAppHref(value);
  return safe === '/app' && value !== '/app' ? undefined : safe;
}

function descriptionOf(item: ServerNotification): string | undefined {
  const payload = item.payload ?? {};
  for (const key of ['reason', 'why', 'platform']) {
    const value = payload[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  if (typeof payload.count === 'number' && Number.isFinite(payload.count))
    return `${payload.count} item${payload.count === 1 ? '' : 's'}`;
  return undefined;
}

export function adaptAttention(item: AttentionItem): NotificationViewModel {
  return {
    id: `attention:${item.id}`, source: 'attention', sourceId: item.id,
    kind: 'action_required', priority: 'high', title: item.title,
    description: item.description, createdAt: 0, unread: false,
    actionable: true, durable: true, dismissible: false,
    href: appHref(item.href), openLabel: item.action
  };
}

export function adaptServer(item: ServerNotification): NotificationViewModel {
  const severity = item.severity;
  const completed = /(?:\.completed|\.verified|\.active|\.generated)$/.test(item.type);
  const kind: NotificationKind = severity === 'security' ? 'security'
    : severity === 'critical' ? 'critical'
      : severity === 'action' ? 'action_required'
        : severity === 'warning' ? 'warning'
          : completed ? 'success' : 'info';
  const priority: NotificationPriority = kind === 'security' || kind === 'critical' ? 'critical'
    : kind === 'action_required' ? 'high' : kind === 'warning' ? 'normal' : 'low';
  const rawTitle = item.payload?.title;
  const explicitKey = item.dedupeKey;
  const rawTaskId = item.payload?.runId ?? item.payload?.taskId;
  return {
    id: `server:${item.id}`, source: 'server', sourceId: item.id,
    // A server-supplied stable event key may join sources; a title or entity id may not.
    dedupeKey: typeof explicitKey === 'string' && explicitKey.length > 0
      ? `server:${item.workspaceId ?? 'global'}:${explicitKey}` : undefined,
    kind, priority, title: typeof rawTitle === 'string' && rawTitle.trim() ? rawTitle : eventLabel(item.type),
    description: descriptionOf(item), createdAt: item.createdAt * 1000,
    unread: item.status === 'delivered', actionable: item.actionable,
    durable: true, dismissible: kind === 'info' || kind === 'success',
    href: appHref(item.payload?.href), openLabel: ACTION_LABELS[item.type] ?? 'Open',
    taskId: typeof rawTaskId === 'string' && rawTaskId.length <= 200 ? rawTaskId : undefined
  };
}

export function adaptFounder(item: NoticeRow): NotificationViewModel {
  const kind: NotificationKind = item.severity === 'security' ? 'security'
    : item.severity === 'critical' ? 'critical'
      : item.severity === 'warning' ? 'warning' : 'info';
  return {
    id: `founder:${item.id}`, source: 'founder', sourceId: item.id,
    kind, priority: kind === 'critical' || kind === 'security' ? 'critical' : kind === 'warning' ? 'normal' : 'low',
    title: item.title, createdAt: item.createdAt * 1000, unread: !item.read,
    actionable: kind === 'critical' || kind === 'security', durable: true, dismissible: false,
    href: founderSafeHref(item.href) ?? undefined, openLabel: 'View'
  };
}

/** Only an explicit shared event key can merge records from different sources. */
export function sortNotifications(items: readonly NotificationViewModel[]): NotificationViewModel[] {
  const sorted = items.toSorted((a, b) => PRIORITY[a.priority] - PRIORITY[b.priority]
    || Number(b.unread) - Number(a.unread) || b.createdAt - a.createdAt || a.id.localeCompare(b.id));
  const seen = new Set<string>();
  return sorted.filter((item) => {
    const key = item.dedupeKey ? `event:${item.dedupeKey}` : `${item.source}:${item.sourceId}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function chooseSurfaces(event: NotificationViewModel | { status: 'running' | 'progress' | 'waiting' | 'success' | 'error' } | { local: true }): NotificationSurface[] {
  if ('local' in event) return ['toast'];
  if ('status' in event) return event.status === 'running' || event.status === 'progress' ? ['live']
    : event.status === 'waiting' ? ['live', 'center', 'activity']
      : event.status === 'success' ? ['live', 'activity'] : ['live', 'center', 'activity'];
  if (event.source === 'attention') return ['center'];
  if (event.kind === 'critical' || event.kind === 'security' || event.kind === 'action_required') return ['center', 'activity'];
  if (event.kind === 'warning') return event.unread ? ['center', 'activity'] : ['activity'];
  return event.unread ? ['center', 'activity'] : ['activity'];
}
