import type { TwitchAction, TwitchCapability, TwitchField, TwitchPayload, TwitchValue } from './types';

export const TWITCH_GROUPS = [
  { id: 'channel', label: 'Channel & live', description: 'Channel settings, stream information and the current live state.' },
  { id: 'schedule', label: 'Schedule & markers', description: 'Upcoming broadcasts and markers. A schedule entry does not start a live broadcast; your encoder remains separate.' },
  { id: 'chat', label: 'Chat & replies', description: 'Messages, replies and chat settings. Review the audience before sending in a Shared Chat session.' },
  { id: 'moderation', label: 'Moderation', description: 'Timeouts, bans, message deletion, AutoMod and Shield Mode for channels you can moderate.' },
  { id: 'media', label: 'Clips & VOD', description: 'Official clip and video operations. Content access does not grant copyright or permission to republish.' },
  { id: 'engagement', label: 'Community', description: 'Polls, predictions, raids, Channel Points and rewards, where your account qualifies.' },
  { id: 'monetization', label: 'Subscriptions, Bits & ads', description: 'Each operation requires the account eligibility and permissions shown below.' },
  { id: 'events', label: 'Notifications', description: 'EventSub subscriptions and delivery receipts. Worker health and delivery evidence come from Rafii.' },
  { id: 'analytics', label: 'Available analytics', description: 'Only data exposed by Twitch’s official APIs. A viewer count is a snapshot, not unique viewers, watch time or a revenue report.' }
] as const;

export type TwitchGroupId = (typeof TWITCH_GROUPS)[number]['id'];

/** The action prefix remains canonical even if the server changes a display group label. */
export function capabilityGroup(capability: Pick<TwitchCapability, 'action' | 'group'>): TwitchGroupId {
  const action = capability.action.replace(/^twitch\./, '');
  if (/^(analytics|game\.analytics|extension\.analytics)/.test(action)) return 'analytics';
  if (/^(eventsub|notification|event)\./.test(action)) return 'events';
  if (/^(subscription|subscriptions|bits|ads|ad|commercial|goals|charity)\./.test(action)) return 'monetization';
  if (/^(poll|polls|prediction|predictions|raid|raids|reward|rewards|redemption|channel_points)\./.test(action)) return 'engagement';
  if (/^(clip|clips|vod|video|videos)\./.test(action)) return 'media';
  if (/^(moderation|moderator|ban|timeout|automod|shield|blocked_term|unban|warning)\./.test(action) || /^(chat\.(delete|clear|ban|timeout|warning|message\.delete))/.test(action)) return 'moderation';
  if (/^(chat|whisper)\./.test(action)) return 'chat';
  if (/^(schedule|marker|markers)\./.test(action)) return 'schedule';
  const group = TWITCH_GROUPS.find((item) => item.id === capability.group.toLowerCase());
  return group?.id ?? 'channel';
}

export function capabilityAvailable(capability: TwitchCapability | undefined): boolean {
  // Offline implementation and a granted scope alone never establish live availability.
  // Encoder secrets require a separate custody flow; never reveal them through generic data controls.
  return capability?.availability?.state === 'available' && capability.risk !== 'secret' && capability.action !== 'twitch.stream.key.get';
}

export function verificationLabel(capability: TwitchCapability): 'Verified' | 'Unverified' | 'Blocked' {
  if (capability.availability?.state === 'blocked' || capability.verification === 'blocked') return 'Blocked';
  return capability.verification === 'verified' && capability.liveVerified === true ? 'Verified' : 'Unverified';
}

export function effectsList(value: string | string[] | undefined): string[] {
  return typeof value === 'string' ? [value] : Array.isArray(value) ? value.filter((v) => typeof v === 'string') : [];
}

function empty(value: unknown): boolean {
  return value === '' || value === undefined || value === null;
}

function fieldValue(field: TwitchField, value: unknown, label: string, required = false): TwitchValue | undefined {
  // An explicitly cleared field can be meaningful (for example clearing a reward prompt).
  const allowedEmptyText = value === '' && field.type === 'string' && field.minLength === 0;
  if (empty(value) && !allowedEmptyText) {
    if (required || field.required === true) throw new Error(`${label} is required.`);
    return undefined;
  }
  let parsed: TwitchValue;
  if (field.type === 'boolean') {
    if (value !== true && value !== false && value !== 'true' && value !== 'false') throw new Error(`Choose Yes or No for ${label}.`);
    parsed = value === true || value === 'true';
  } else if (field.type === 'integer' || field.type === 'number') {
    if (typeof value !== 'number' && (typeof value !== 'string' || value.trim() === '')) throw new Error(`${label} must be a number.`);
    parsed = Number(value);
    if (!Number.isFinite(parsed) || (field.type === 'integer' && !Number.isSafeInteger(parsed))) throw new Error(`${label} must be ${field.type === 'integer' ? 'a whole number' : 'a number'}.`);
    const minimum = field.minimum ?? field.min;
    const maximum = field.maximum ?? field.max;
    if (minimum !== undefined && parsed < minimum) throw new Error(`${label} must be at least ${minimum}.`);
    if (maximum !== undefined && parsed > maximum) throw new Error(`${label} must be at most ${maximum}.`);
  } else if (field.type === 'array') {
    if (!Array.isArray(value) || !field.items) throw new Error(`${label} has an unsupported list format.`);
    if (field.minItems !== undefined && value.length < field.minItems) throw new Error(`${label} needs at least ${field.minItems} items.`);
    if (field.maxItems !== undefined && value.length > field.maxItems) throw new Error(`${label} allows at most ${field.maxItems} items.`);
    parsed = value.map((item, index) => {
      const result = fieldValue(field.items!, item, `${label} ${index + 1}`, true);
      if (result === undefined) throw new Error(`${label} ${index + 1} is required.`);
      return result;
    });
  } else if (field.type === 'object') {
    if (typeof value !== 'object' || Array.isArray(value) || !field.properties) throw new Error(`${label} has an unsupported object format.`);
    const requiredProperties = Array.isArray(field.required) ? field.required : [];
    parsed = parseFields(field.properties, value as Record<string, unknown>, `${label}: `, requiredProperties);
  } else if (field.type === 'string') {
    if (typeof value !== 'string') throw new Error(`${label} must be text.`);
    // Preserve exact content. Trimming a chat message after preview would change the approved payload.
    parsed = value;
    const length = Array.from(parsed).length;
    if (field.minLength !== undefined && length < field.minLength) throw new Error(`${label} needs at least ${field.minLength} characters.`);
    if (field.maxLength !== undefined && length > field.maxLength) throw new Error(`${label} allows at most ${field.maxLength} characters.`);
  } else {
    throw new Error(`${label} is not supported by this version of Rafii. Refresh before continuing.`);
  }
  if (field.enum && !field.enum.includes(parsed as string | number | boolean)) throw new Error(`Choose an available value for ${label}.`);
  return parsed;
}

export function parseFields(fields: Record<string, TwitchField>, values: Record<string, unknown>, prefix = '', requiredProperties: string[] = []): TwitchPayload {
  const result: TwitchPayload = {};
  for (const name of Object.keys(values)) {
    if (!Object.prototype.hasOwnProperty.call(fields, name)) throw new Error(`Unexpected field: ${name}. Refresh the form before continuing.`);
  }
  for (const [name, field] of Object.entries(fields)) {
    const value = fieldValue(field, values[name], `${prefix}${field.label || name.replaceAll('_', ' ')}`, requiredProperties.includes(name));
    if (value !== undefined) result[name] = value;
  }
  return result;
}

function canonical(value: TwitchValue): TwitchValue {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.keys(value).toSorted().map((key) => [key, canonical(value[key])]));
  return value;
}

/** A local fingerprint invalidates the preview on any edit; the server alone creates the approval hash. */
export function submissionSignature(action: string, payload: TwitchPayload, executeAt?: string, declarations?: Record<string, boolean>): string {
  return JSON.stringify([action, canonical(payload), executeAt ?? null, declarations ? canonical(declarations) : null]);
}

export function timestampMillis(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : Date.parse(value);
  return Number.isFinite(n) ? n : null;
}

export function reviewCanApprove(review: TwitchAction, generation: string | number | undefined, now = Date.now()): boolean {
  const expiry = timestampMillis(review.expiresAt);
  return review.state === 'draft' && /^[a-f0-9]{64}$/.test(review.payloadHash) &&
    generation !== undefined && String(generation) === String(review.generation) && expiry !== null && expiry > now;
}

export function scheduledInstant(value: string, now = Date.now()): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || date.getTime() <= now) throw new Error('Choose a future time for this action.');
  return date.toISOString();
}

/** Restore only a user-requested schedule; the worker's immediate timestamp is not a schedule. */
export function reviewScheduledInstant(review: TwitchAction, capability: TwitchCapability): string | undefined {
  const at = timestampMillis(review.executeAt);
  return review.scheduled === true && capability.schedulable === true && at !== null ? new Date(at).toISOString() : undefined;
}

export function actionStateLabel(state: string): string {
  const labels: Record<string, string> = {
    draft: 'Awaiting your approval', approved: 'Approved · waiting for worker', queued: 'Queued',
    scheduled: 'Scheduled', claimed: 'Worker claimed', running: 'Running', executing: 'Running', dispatching: 'Sending to Twitch',
    accepted: 'Twitch accepted · resource processing',
    partial: 'Partially confirmed · inspect remaining items',
    succeeded: 'Twitch confirmed', completed: 'Twitch confirmed', failed: 'Failed', paused: 'Paused',
    canceled: 'Canceled', cancelled: 'Canceled', expired: 'Approval expired', held: 'Held',
    unknown: 'Outcome unknown · inspect before retry', outcome_unknown: 'Outcome unknown · inspect before retry', ambiguous: 'Outcome unknown · inspect before retry',
    reconciling: 'Checking Twitch outcome', revoked: 'Authorization revoked'
  };
  return labels[state] ?? state;
}

export function canPauseAction(state: string): boolean {
  return ['approved', 'queued', 'scheduled'].includes(state);
}

export function canCancelAction(state: string): boolean {
  return ['draft', 'approved', 'queued', 'scheduled', 'paused', 'held'].includes(state);
}

export function canReconcileAction(action: TwitchAction): boolean {
  if (!['accepted', 'outcome_unknown'].includes(action.state) || !action.result || typeof action.result !== 'object') return false;
  const confirmation = (action.result as Record<string, unknown>).confirmation;
  return Boolean(confirmation && typeof confirmation === 'object' && (confirmation as Record<string, unknown>).action === 'twitch.clip.lookup');
}

/** Safe display only. API responses must already omit secrets, including stream configuration. */
export function safeDisplay(value: unknown, depth = 0): unknown {
  if (depth > 12) return '[Nested data]';
  if (Array.isArray(value)) return value.map((item) => safeDisplay(item, depth + 1));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
      /(?:^|_)(?:access_token|refresh_token|token|secret|password|stream_key|authorization|client_secret)(?:$|_)/i.test(key) || /^(accessToken|refreshToken|clientSecret|streamKey)$/i.test(key)
        ? '[Not displayed]' : safeDisplay(item, depth + 1)
    ]));
  }
  return value;
}

export function twitchAuthorizeUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'id.twitch.tv' && url.pathname === '/oauth2/authorize' && !url.username && !url.password ? url.toString() : null;
  } catch { return null; }
}

/** Exact official CDN constraints match the server's expiring clip-link validation. */
export function clipDownloadHref(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 8192 || value.includes('\\') || Array.from(value).some((character) => character.charCodeAt(0) < 33)) return null;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    const official = ['twitch.tv', 'twitchcdn.net', 'ttvnw.net'].some((suffix) => host === suffix || host.endsWith(`.${suffix}`));
    return url.protocol === 'https:' && official && !url.username && !url.password && !url.hash && (!url.port || url.port === '443') ? url.toString() : null;
  } catch { return null; }
}
