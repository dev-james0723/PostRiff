import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { CapabilityLevel, ChannelView, MyChannel } from '@/lib/api/types';
import { formatDate, relativeTime } from '@/lib/time';

/**
 * One reading of a channel's state for every surface that shows it (Channels,
 * Overview, the profile page). The API decides `connectionState`
 * (`postriff_phase2/channels.py: connection_state`); this module only turns
 * it into a label, an attention flag and a plain sentence, and never blends
 * per-capability levels into a single "Connected".
 */

/** The fields any channel-shaped record needs for these helpers. `capabilities` is optional (MyChannel has none). */
export type ChannelStateInput = Pick<ChannelView, 'connectionState'> & {
  expiresAt?: number | null;
  capabilities?: Record<string, { evidence?: string } | undefined>;
};

/** The evidence `OAuthService.disconnect` writes on every capability row (`oauth.py`). */
const DISCONNECTED_EVIDENCE = 'Disconnected by the customer.';

/**
 * A disconnect only flags the snapshot channel as revoked (`store.py: channel_disconnect`), so the API
 * reports it as `reauthorization_required`. The capability rows tell the two apart: an account the
 * person disconnected on purpose is "Disconnected", not something that needs attention.
 */
export function disconnectedByCustomer(channel: ChannelStateInput) {
  if (channel.connectionState !== 'reauthorization_required' || !channel.capabilities) return false;
  return Object.values(channel.capabilities).some((value) => value?.evidence === DISCONNECTED_EVIDENCE);
}

/** Access that ends within a week is called out before it turns into a failure. */
export const EXPIRING_SOON_SECONDS = 7 * 86400;

export const VERIFIED_STATES: ReadonlySet<string> = new Set(['publish_verified', 'read_verified']);

/** States the person has to act on: the token is gone, was revoked, or carries no scopes. */
export const ATTENTION_STATES: ReadonlySet<string> = new Set(['token_expired', 'reauthorization_required', 'scope_missing']);

export const nowSeconds = () => Date.now() / 1000;

export function isVerified(channel: Pick<ChannelStateInput, 'connectionState'>) {
  return VERIFIED_STATES.has(channel.connectionState);
}

/** A verified channel whose access ends within `EXPIRING_SOON_SECONDS`. Expired access is `token_expired`, not "expiring". */
export function expiringSoon(channel: ChannelStateInput, now = nowSeconds()) {
  if (!isVerified(channel) || !channel.expiresAt) return false;
  const left = channel.expiresAt - now;
  return left > 0 && left < EXPIRING_SOON_SECONDS;
}

export interface ChannelBadge {
  label: string;
  status: AnimatedBadgeStatus;
}

/** Badge for one channel: the connection state in plain words, expiry called out a week ahead. */
export function channelBadge(channel: ChannelStateInput, now = nowSeconds()): ChannelBadge {
  const state = channel.connectionState;
  if (VERIFIED_STATES.has(state)) {
    if (expiringSoon(channel, now)) return { label: 'Expiring soon', status: 'warning' };
    return { label: state === 'publish_verified' ? 'Connected' : 'Connected · read only', status: 'success' };
  }
  if (disconnectedByCustomer(channel)) return { label: 'Disconnected', status: 'neutral' };
  if (state === 'token_expired' || state === 'reauthorization_required') return { label: 'Needs reconnect', status: 'warning' };
  if (state === 'scope_missing') return { label: 'Missing permissions', status: 'warning' };
  if (state === 'identity_known') return { label: 'Identity only', status: 'neutral' };
  return { label: 'Disconnected', status: 'neutral' };
}

/** Whether the card belongs at the top with a Reconnect button. Held jobs count too when the caller knows them. */
export function needsAttention(channel: ChannelStateInput, now = nowSeconds(), heldJobs = 0) {
  if (heldJobs > 0) return true;
  if (disconnectedByCustomer(channel)) return false;
  return ATTENTION_STATES.has(channel.connectionState) || expiringSoon(channel, now);
}

/** Reconnect is offered only where the person holds manage_connections and the channel needs it. */
export function needsReconnect(channel: Pick<MyChannel, 'connectionState' | 'canManage'>) {
  return channel.canManage && ATTENTION_STATES.has(channel.connectionState);
}

function heldSentence(heldJobs: number) {
  if (heldJobs <= 0) return '';
  return heldJobs === 1 ? ' 1 scheduled post is held.' : ` ${heldJobs} scheduled posts are held.`;
}

/**
 * One plain sentence for the attention banner, or null when nothing needs doing.
 * Dates come from the API; nothing here is invented when a date is missing.
 */
export function attentionSentence(channel: ChannelStateInput, now = nowSeconds(), heldJobs = 0): string | null {
  const state = channel.connectionState;
  const held = heldSentence(heldJobs);
  if (disconnectedByCustomer(channel)) {
    return heldJobs > 0 ? `Disconnected. Reconnect to release the posts on hold.${held}` : null;
  }
  if (state === 'token_expired') {
    const when = channel.expiresAt ? ` on ${formatDate(channel.expiresAt)}` : '';
    return `Access expired${when}. Scheduled posts for this account are waiting.${held}`;
  }
  if (state === 'reauthorization_required') {
    return `Access was revoked or withdrawn. Sign in again to resume scheduled posts.${held}`;
  }
  if (state === 'scope_missing') {
    return `The account is connected but no permissions were granted. Reconnect and approve them.${held}`;
  }
  if (expiringSoon(channel, now) && channel.expiresAt) {
    return `Access ends ${relativeTime(channel.expiresAt, now)} (${formatDate(channel.expiresAt)}). Reconnect before then to keep scheduled posts moving.${held}`;
  }
  if (heldJobs > 0) return `Posts for this account are on hold.${held}`;
  return null;
}

/** Attention first, then platform, then account — a stable order that survives refetches. */
export function sortForAttention<T extends ChannelStateInput & Pick<ChannelView, 'id' | 'platform' | 'account'>>(
  channels: readonly T[],
  now = nowSeconds(),
  heldByChannel: Readonly<Record<string, number>> = {}
): T[] {
  return channels.toSorted((a, b) => {
    const attentionA = needsAttention(a, now, heldByChannel[a.id] ?? 0) ? 0 : 1;
    const attentionB = needsAttention(b, now, heldByChannel[b.id] ?? 0) ? 0 : 1;
    if (attentionA !== attentionB) return attentionA - attentionB;
    return a.platform.localeCompare(b.platform) || a.account.localeCompare(b.account);
  });
}

/* ---------- capability levels ---------- */

const LEVEL_RANK: Record<CapabilityLevel, number> = { Direct: 3, Assisted: 2, Bridge: 1, Unsupported: 0 };

export function levelRank(level: string | undefined) {
  return LEVEL_RANK[level as CapabilityLevel] ?? 0;
}

/** The capabilities a person can ask a provider for, in the order the OAuth start endpoint expects them. */
export const CONNECT_CAPABILITIES = ['publish', 'analytics', 'comments_read', 'reply'] as const;
export type ConnectCapability = (typeof CONNECT_CAPABILITIES)[number];

/**
 * Which capability to request again when reconnecting: the one this account holds at the
 * highest level, publish winning ties. Reconnecting re-runs the same grant, so the card keeps
 * what it had rather than silently asking for less.
 */
export function reconnectCapability(channel: Pick<ChannelView, 'capabilities'>): ConnectCapability {
  let best: ConnectCapability = 'publish';
  let bestRank = -1;
  for (const key of CONNECT_CAPABILITIES) {
    const rank = levelRank(channel.capabilities[key]?.level);
    if (rank > bestRank) {
      best = key;
      bestRank = rank;
    }
  }
  return best;
}

/* ---------- filters and summary ---------- */

export type ChannelFilter = 'all' | 'attention' | 'direct' | 'assisted' | 'local';

export const CHANNEL_FILTERS: readonly ChannelFilter[] = ['all', 'attention', 'direct', 'assisted', 'local'];

export function parseChannelFilter(value: string | null | undefined): ChannelFilter {
  return (CHANNEL_FILTERS as readonly string[]).includes(value ?? '') ? (value as ChannelFilter) : 'all';
}

export function publishLevel(channel: Pick<ChannelView, 'capabilities'>) {
  return channel.capabilities.publish?.level ?? 'Unsupported';
}

/** Cards still listed by the API but no longer usable are not "connected" for any count. */
export function isConnected(channel: ChannelStateInput) {
  return channel.connectionState !== 'disconnected' && !disconnectedByCustomer(channel);
}

export function matchesFilter(
  channel: ChannelView,
  filter: ChannelFilter,
  now = nowSeconds(),
  heldJobs = 0
): boolean {
  switch (filter) {
    case 'attention':
      return needsAttention(channel, now, heldJobs);
    case 'direct':
      return publishLevel(channel) === 'Direct';
    case 'assisted':
      return publishLevel(channel) === 'Assisted';
    case 'local':
      return false; // the Local tab shows the companion directory, not connected cards
    default:
      return true;
  }
}

export interface ChannelCounts {
  all: number;
  attention: number;
  direct: number;
  assisted: number;
  connected: number;
}

/** Every number the summary strip and the filter tabs show, from the real list only. */
export function channelCounts(
  channels: readonly ChannelView[],
  now = nowSeconds(),
  heldByChannel: Readonly<Record<string, number>> = {}
): ChannelCounts {
  const counts: ChannelCounts = { all: channels.length, attention: 0, direct: 0, assisted: 0, connected: 0 };
  for (const channel of channels) {
    if (needsAttention(channel, now, heldByChannel[channel.id] ?? 0)) counts.attention += 1;
    const level = publishLevel(channel);
    if (level === 'Direct') counts.direct += 1;
    if (level === 'Assisted') counts.assisted += 1;
    if (isConnected(channel)) counts.connected += 1;
  }
  return counts;
}
