/**
 * Founder notices, briefing versions and the founder workspace as Settings shows them (CONTRACTS §8.E, §8.H): the
 * payload types of `GET/PUT /notifications/preferences`, `GET /notifications`, `GET /reports[/{id}]` and
 * `GET/POST /ops-workspace`, and the pure rules the tabs use — the words for each fixed blocker code, the preferences
 * patch (validated here, validated again by the server), and how a report's basis and coverage are said. Nothing here
 * computes a business number; counts are shown as the server sent them. No React, so the node test loads it directly.
 */
import { clockToMinutes, minutesToClock } from '../customers/kit/format';

export const NOTICE_EVENTS = ['founder.incident_opened', 'founder.incident_recovered', 'founder.briefing_ready', 'founder.source_unavailable'] as const;
export type NoticeEvent = (typeof NOTICE_EVENTS)[number];
export type NoticeChannel = 'email' | 'push';

export interface NoticePreferences {
  revision: number;
  events: Record<string, { email: boolean; push: boolean }>;
  digest: { enabled: boolean; hour: number; email: boolean };
  quietHours: { start: number; end: number; timeZone: string };
  updatedAt: number | null;
}

export interface ChannelReadiness {
  ready: boolean;
  blockers: string[];
  policyListed?: boolean;
  liveDeliveryEnabled?: boolean;
  flag?: boolean;
  /** Whether the notification outbox has a transport for the channel here; null when Control cannot tell. */
  transport?: boolean | null;
}

export interface NoticeRoute {
  type: string;
  label: string;
  routes: Record<string, { email: string; push: string }>;
}

export interface PreferencesData {
  preferences: NoticePreferences;
  installed: boolean;
  readiness: { inApp: ChannelReadiness; email: ChannelReadiness; push: ChannelReadiness };
  policy: { liveDeliveryEnabled: boolean; channels: string[]; revision: number };
  flags: { founderEmailEnabled: boolean; founderPushEnabled: boolean };
  events: NoticeRoute[];
}

export interface PreferencesPatch {
  events: Record<string, { email: boolean; push: boolean }>;
  digest: { enabled: boolean; hour: number; email: boolean };
  quietHours: { start: number; end: number; timeZone: string };
}

export interface NoticeRow {
  id: string;
  type: string;
  severity: 'info' | 'warning' | 'critical' | 'security' | string;
  title: string;
  href: string;
  subject: { type: string; id: string };
  channels: Record<string, { mode?: string; reason?: string; blockers?: string[]; state?: string; outbox?: string }>;
  facts: Record<string, unknown>;
  digest: { state: string; id: string | null };
  createdAt: number;
  readAt: number | null;
  read: boolean;
}

export interface NoticesData {
  mode: 'live' | 'demo';
  notices: NoticeRow[];
  unread: number;
  installed?: boolean;
  reason?: string;
}

export interface ReportCoverage {
  measured?: number;
  unavailable?: number;
  total?: number;
  dataState?: string;
  basis?: 'metric_receipts' | 'cron_observations' | string;
  basisReason?: string;
}

export interface ReportSummary {
  id: string;
  kind: 'daily' | 'weekly' | 'incident' | 'test' | string;
  version: number;
  generatedAt: number;
  receiptIds: string[];
  sections: { id: string; title: string; lines: string[]; count?: number }[];
  coverage: ReportCoverage;
}

export interface ReportDetail extends ReportSummary {
  text: string;
}

export interface ReportsData {
  mode: 'live' | 'demo';
  reports: ReportSummary[];
  reason?: string;
}

export interface OpsWorkspace {
  workspaceId: string | null;
  source: 'environment' | 'settings' | null;
  name: string | null;
  canCreate: boolean;
}

export interface OpsWorkspaceCreated {
  workspaceId: string;
  source: 'environment' | 'settings' | string;
  created: boolean;
  name?: string | null;
}

export const EVENT_LABEL: Record<string, string> = {
  'founder.incident_opened': 'Incident opened',
  'founder.incident_recovered': 'Incident recovered',
  'founder.briefing_ready': 'Briefing ready',
  'founder.source_unavailable': 'Data source unavailable',
  'founder.digest_ready': 'Daily digest',
  'founder.test_notice': 'Test notice'
};

/** The gate a blocker code names, in words (the code is shown beside it). */
export const NOTICE_BLOCKER_COPY: Record<string, string> = {
  live_delivery_disabled: 'Live delivery is off in Contact & calls.',
  channel_not_in_policy: 'The contact policy does not list this channel.',
  deployment_flag_unset: 'The server flag for this channel is not set.',
  outbox_unavailable: 'The notification outbox has no transport for this channel here.',
  notifications_not_installed: 'The founder notice tables (migration 067) are not installed yet.',
  preference_off: 'Turned off in your preferences.',
  digest_disabled: 'The daily digest is off.',
  quiet_hours: 'Held for quiet hours.',
  not_routed: 'Not used for this notice.'
};

export const CHANNEL_FLAG: Record<NoticeChannel, string> = { email: 'RAFII_FOUNDER_EMAIL_ENABLED', push: 'RAFII_FOUNDER_PUSH_ENABLED' };

export function blockerCopy(code: string, channel?: NoticeChannel): string {
  if (code === 'deployment_flag_unset' && channel) return `The server flag ${CHANNEL_FLAG[channel]} is not set.`;
  return NOTICE_BLOCKER_COPY[code] ?? 'Blocked by a rule this page does not know yet.';
}

/** One line for a channel: ready, or the first failing gate in words (every code is listed beside it). */
export function readinessLine(channel: 'inApp' | NoticeChannel, readiness: ChannelReadiness | undefined): string {
  if (channel === 'inApp') return 'Always on: every founder notice lands in your notice list here and in your Rafii notifications.';
  if (!readiness) return 'Readiness unknown.';
  if (readiness.ready) return channel === 'email' ? 'Ready: urgent notices are emailed now, the rest in the daily digest.' : 'Ready: urgent notices are pushed to your subscribed devices.';
  const first = readiness.blockers[0];
  return first ? blockerCopy(first, channel) : 'Not ready.';
}

export interface PreferencesDraft {
  events: Record<string, { email: boolean; push: boolean }>;
  digestEnabled: boolean;
  digestEmail: boolean;
  digestHour: string;
  quietStart: string;
  quietEnd: string;
  timeZone: string;
}

export function draftFromPreferences(preferences: NoticePreferences): PreferencesDraft {
  const events: PreferencesDraft['events'] = {};
  for (const name of NOTICE_EVENTS) {
    const current = preferences.events?.[name];
    events[name] = { email: current?.email !== false, push: current?.push !== false };
  }
  return {
    events,
    digestEnabled: preferences.digest?.enabled !== false,
    digestEmail: preferences.digest?.email !== false,
    digestHour: String(preferences.digest?.hour ?? 9),
    quietStart: minutesToClock(preferences.quietHours?.start ?? 1320),
    quietEnd: minutesToClock(preferences.quietHours?.end ?? 480),
    timeZone: preferences.quietHours?.timeZone ?? 'America/Indiana/Indianapolis'
  };
}

/** The full preferences to save (every section, so a retry is the same request), or the first validation message. */
export function preferencesPatch(draft: PreferencesDraft): { patch: PreferencesPatch } | { error: string } {
  const hour = Number(draft.digestHour);
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return { error: 'The digest hour must be a whole hour from 0 to 23.' };
  const start = clockToMinutes(draft.quietStart);
  const end = clockToMinutes(draft.quietEnd);
  if (start === null || end === null) return { error: 'Quiet hours need a start and an end time (HH:MM).' };
  const zone = draft.timeZone.trim();
  if (!zone || zone.length > 64 || !/^[A-Za-z_]+(?:\/[A-Za-z0-9_+-]+){0,2}$/.test(zone)) return { error: 'Use an IANA time zone such as America/Indiana/Indianapolis.' };
  const events: PreferencesPatch['events'] = {};
  for (const name of NOTICE_EVENTS) events[name] = { email: Boolean(draft.events[name]?.email), push: Boolean(draft.events[name]?.push) };
  return { patch: { events, digest: { enabled: draft.digestEnabled, hour, email: draft.digestEmail }, quietHours: { start, end, timeZone: zone } } };
}

/** How a notice route reads for one severity: "email now · push now", "digest", "in-app only". */
export function routeSummary(route: { email: string; push: string }): string {
  const parts: string[] = [];
  if (route.email === 'immediate') parts.push('email now');
  if (route.email === 'digest') parts.push('email in the daily digest');
  if (route.push === 'immediate') parts.push('push now');
  return parts.length ? `In-app, ${parts.join(', ')}` : 'In-app only';
}

/**
 * Whether the contact policy lists a channel. The server sends `channels` as a list of 'call' | 'email' | 'push'
 * (`founder_contact.CHANNELS`); a map of flags is read the same way, and the phone channel answers to either name.
 */
export function channelListed(channels: unknown, channel: 'call' | 'email' | 'push'): boolean {
  const names = channel === 'call' ? ['call', 'phone'] : [channel];
  if (Array.isArray(channels)) return names.some((name) => channels.includes(name));
  if (channels && typeof channels === 'object') return names.some((name) => (channels as Record<string, unknown>)[name] === true);
  return false;
}

const CHANNEL_NAME: Record<NoticeChannel, string> = { email: 'Email', push: 'Push' };

/** What each channel did with one notice, as the server recorded it (the plan's mode, reason and outbox hand-off). */
export function noticeChannelLines(notice: Pick<NoticeRow, 'channels' | 'digest'>): string[] {
  const lines = [notice.channels?.in_app?.state === 'delivered' ? 'In-app: delivered' : 'In-app: recorded'];
  for (const channel of ['email', 'push'] as const) {
    const entry = notice.channels?.[channel];
    const name = CHANNEL_NAME[channel];
    if (!entry?.mode) lines.push(`${name}: not recorded`);
    else if (entry.mode === 'immediate') lines.push(`${name}: ${entry.outbox === 'planned' ? 'handed to the outbox' : 'due now, but no outbox here'}`);
    else if (entry.mode === 'digest') lines.push(`${name}: daily digest`);
    else lines.push(`${name}: off${entry.reason ? ` (${entry.reason})` : ''}`);
  }
  if (notice.digest?.state === 'pending') lines.push('waiting for the next digest');
  if (notice.digest?.state === 'included') lines.push('included in a digest');
  return lines;
}

/** Where a report's values came from, said plainly. */
export function reportBasis(coverage: ReportCoverage | undefined): string {
  if (coverage?.basis === 'metric_receipts') return 'Receipted metric queries';
  if (coverage?.basis === 'cron_observations') return `Cron observations without receipts${coverage.basisReason ? ` (${coverage.basisReason.replaceAll('_', ' ')})` : ''}`;
  return 'Basis not recorded';
}

/** "6 of 8 values available" exactly as the report counted them, or a word when it did not count. */
export function reportCoverage(coverage: ReportCoverage | undefined): string {
  if (!coverage || typeof coverage.total !== 'number' || typeof coverage.measured !== 'number') return 'Coverage not recorded';
  return `${coverage.measured} of ${coverage.total} values available`;
}

const KIND_LABEL: Record<string, string> = { daily: 'Daily', weekly: 'Weekly', incident: 'Incident', test: 'Test' };

export function reportTitle(report: Pick<ReportSummary, 'kind' | 'version'>): string {
  const kind = KIND_LABEL[report.kind];
  return kind ? `${kind} briefing v${report.version}` : `Briefing v${report.version}`;
}

/** What the founder workspace panel says for a state. */
export function opsWorkspaceSummary(ops: OpsWorkspace | undefined): { state: 'set' | 'creatable' | 'unavailable'; title: string; description: string } {
  if (ops?.workspaceId) {
    return ops.source === 'environment'
      ? { state: 'set', title: 'Founder workspace set by the server', description: 'RAFII_FOUNDER_OPS_WORKSPACE_ID names the internal workspace Founder Rafii, voice and founder calls run in. It is classified internal, so its usage never counts as a customer’s.' }
      : { state: 'set', title: ops.name ?? 'Rafii Ops (founder)', description: 'Created here. Founder Rafii, voice and founder calls run in this internal workspace; it is classified internal, so its usage never counts as a customer’s.' };
  }
  if (ops?.canCreate) {
    return { state: 'creatable', title: 'No founder workspace yet', description: 'Founder Rafii, voice and founder calls need one internal workspace to run in. Creating it makes one “Rafii Ops (founder)” workspace with you as its only member, classified internal; it never gets a trial, subscription or connection.' };
  }
  return { state: 'unavailable', title: 'No founder workspace, and it cannot be created here', description: 'Control runs without the Rafii app runtime here, so the workspace cannot be created from this page. Set RAFII_FOUNDER_OPS_WORKSPACE_ID instead.' };
}

/** A failed write, in the words Settings shows: a stale second factor asks for a fresh sign-in, a missing table says so. */
export function writeFailure(failure: { status?: number; code?: string; message?: string; blocker?: string }): { kind: 'step_up' | 'permission' | 'not_installed' | 'error'; message: string } {
  if (failure.code === 'STEP_UP_REQUIRED') {
    return { kind: 'step_up', message: 'This change needs a fresh second factor (within the last five minutes). Sign in again with your authenticator, then retry.' };
  }
  if (failure.status === 403) return { kind: 'permission', message: 'This operator does not hold the control.settings capability needed for this change.' };
  if (failure.blocker === 'notifications_not_installed') return { kind: 'not_installed', message: blockerCopy('notifications_not_installed') };
  return { kind: 'error', message: failure.message ?? 'The change could not be saved.' };
}

export function severityStatus(severity: string): 'danger' | 'warning' | 'info' | 'neutral' {
  if (severity === 'critical' || severity === 'security') return 'danger';
  if (severity === 'warning') return 'warning';
  if (severity === 'info') return 'info';
  return 'neutral';
}
