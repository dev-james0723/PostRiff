/**
 * Plain words for the workspace audit log. Pure functions: the page renders what these return.
 *
 * Every kind below is one the API writes today (grep `audit(` in `src/postriff_phase2`):
 * - hosted.py: workspace.created, member.updated / removed / left, ownership.transferred,
 *   invitation.created / revoked / accepted / declined, billing.checkout_started / portal_opened,
 *   data.exported / diagnostics, memory.egress_decided, research.egress_decided
 * - oauth.py: oauth.started / rejected / denied, channel.connected / verified / disconnected
 * - audience.py: reply.approved
 * billing.py and learning_service.py write no audit rows (webhooks and preference decisions keep
 * their own records), and account events (sign-ins, two-factor, sessions) carry no workspace, so
 * they never reach this log. A kind added later still renders: its words are built from the kind.
 *
 * Sentences live here rather than in JSX so the page can be translated in one place.
 */
import { channelByPlatform } from '@/config/channels';
import { navGroups } from '@/config/nav-config';
import type { AuditEvent, ChannelView, Invitation, Member, ProviderView } from '@/lib/api/types';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import { capabilityLabel } from '@/lib/channels/capabilities';
import { formatBytes, formatDate, timeDefaults } from '@/lib/time';
import type { NavItem, PermissionCheck, WorkspaceRole } from '@/types';

/** `hosted.py` `audit_events`: `ORDER BY at DESC LIMIT 200`, with no paging parameters yet. */
export const AUDIT_API_LIMIT = 200;

/* ---------- families (the category pills) ---------- */

export const FAMILIES = ['all', 'members', 'channels', 'privacy', 'billing', 'replies', 'other'] as const;
export type Family = (typeof FAMILIES)[number];

export const FAMILY_LABELS: Record<Family, string> = {
  all: 'All',
  members: 'Members',
  channels: 'Channels',
  privacy: 'Data & privacy',
  billing: 'Billing',
  replies: 'Replies',
  other: 'Other'
};

export function familyOf(kind: string): Exclude<Family, 'all'> {
  if (kind === 'workspace.created' || kind.startsWith('member.') || kind.startsWith('ownership.') || kind.startsWith('invitation.')) return 'members';
  if (kind.startsWith('channel.') || kind.startsWith('oauth.')) return 'channels';
  if (kind.startsWith('data.') || kind.startsWith('memory.') || kind.startsWith('research.')) return 'privacy';
  if (kind.startsWith('billing.')) return 'billing';
  if (kind.startsWith('reply.')) return 'replies';
  return 'other';
}

export function inFamily(event: AuditEvent, family: Family) {
  return family === 'all' || familyOf(event.kind) === family;
}

/* ---------- people ---------- */

/** The actor filter's value for events no person caused. */
export const SYSTEM_ACTOR = 'system';

export function actorKey(actor: string | null | undefined) {
  return actor || SYSTEM_ACTOR;
}

export type PersonKind = 'you' | 'member' | 'former' | 'outside' | 'unknown' | 'system';

export interface Person {
  kind: PersonKind;
  /**
   * The name on the member's profile when they set one. Otherwise "You", "System", a role ("Editor"),
   * "Former editor", "Not a member" or "Person".
   */
  name: string;
  /** Shown beside a profile name: the role today ("Admin") or before ("Former admin"). Null when `name` is already the role. */
  role: string | null;
  /** First 8 characters of the id; null for You and System. Shown beside the name when there is no profile name. */
  short: string | null;
  /** The full id for the detail sheet; null for System. */
  id: string | null;
  /** One line for a tooltip or the sheet. */
  explains: string;
}

/** "Sam · Admin" for a named member, "Admin 22222222" for one without a name, "You" or "System". */
export function personText(person: Person) {
  if (person.role) return `${person.name} · ${person.role}`;
  return person.short ? `${person.name} ${person.short}` : person.name;
}

export interface AuditLookup {
  /** Every membership row the API returns, active or revoked, by user id. */
  members: ReadonlyMap<string, Member>;
  /** False while the members list is loading or unavailable, so nobody is called "Not a member" by mistake. */
  membersKnown: boolean;
  youId: string | null;
  invitations: ReadonlyMap<string, Invitation>;
  channels: ReadonlyMap<string, ChannelView>;
  providers: readonly ProviderView[];
  /** Provider per connection or connection attempt, taken from the events that name one. */
  providerBySubject: ReadonlyMap<string, string>;
}

function roleName(role: unknown) {
  return typeof role === 'string' ? (ROLE_LABELS[role as WorkspaceRole] ?? capitalise(role)) : null;
}

/** The log stores ids only; a name comes from today's member list, and only when the member set one on their profile. */
export function personOf(userId: string | null | undefined, lookup: AuditLookup): Person {
  if (!userId) {
    return { kind: 'system', name: 'System', role: null, short: null, id: null, explains: 'Recorded by PostRiff itself, not by a person.' };
  }
  const short = userId.slice(0, 8);
  const member = lookup.members.get(userId);
  if (member?.you || userId === lookup.youId) {
    return { kind: 'you', name: 'You', role: null, short: null, id: userId, explains: 'Something you did.' };
  }
  if (member) {
    const role = roleName(member.role) ?? 'Member';
    const profileName = typeof member.displayName === 'string' ? member.displayName.trim() : '';
    const active = member.status === 'active';
    const roleWord = active ? role : `Former ${role.toLowerCase()}`;
    const explains = active
      ? profileName
        ? `A member whose role is ${role} today, shown by the name on their profile.`
        : `A member whose role is ${role} today. They have not set a name on their profile, so the start of their id stands in.`
      : profileName
        ? `No longer a member; their role was ${role}. Shown by the name on their profile.`
        : `No longer a member; their role was ${role}. They had not set a name, so the start of their id stands in.`;
    return {
      kind: active ? 'member' : 'former',
      name: profileName || roleWord,
      role: profileName ? roleWord : null,
      short,
      id: userId,
      explains
    };
  }
  if (!lookup.membersKnown) {
    return { kind: 'unknown', name: 'Person', role: null, short, id: userId, explains: 'The member list could not be read, so their name and role are not shown.' };
  }
  return {
    kind: 'outside',
    name: 'Not a member',
    role: null,
    short,
    id: userId,
    explains: 'Not on the member list, now or before, such as a person who declined an invitation.'
  };
}

/* ---------- sentences ---------- */

export type AuditTone = 'neutral' | 'warning';

export interface AuditDescription {
  /** What happened, as a sentence. Never a raw id. */
  headline: string;
  /** What it was about, from the event's details or the records it points at. */
  detail: string | null;
  tone: AuditTone;
}

function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function text(value: unknown) {
  return typeof value === 'string' && value ? value : null;
}

function list(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/** Flags `validate_grant` returns alongside a role (`permissions.py`). */
const GRANT_LABELS: Record<string, string> = {
  can_publish: 'approve posts',
  can_reply: 'reply to comments',
  can_moderate: 'moderate',
  can_manage_connections: 'manage channels'
};

function grantsOf(meta: Record<string, unknown>) {
  return Object.keys(GRANT_LABELS).filter((key) => meta[key] === true).map((key) => GRANT_LABELS[key]);
}

function grantsSentence(meta: Record<string, unknown>) {
  const grants = grantsOf(meta);
  return grants.length ? `Also allowed to ${joinWords(grants)}.` : null;
}

function joinWords(words: string[]) {
  if (words.length <= 1) return words.join('');
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

export function providerName(id: string | null | undefined, providers: readonly ProviderView[]) {
  if (!id) return null;
  return providers.find((provider) => provider.id === id)?.platform ?? channelByPlatform(id)?.name ?? capitalise(id);
}

/** "Threads (@studio)" when the connection is still listed, else the provider the events named. */
function channelName(event: AuditEvent, lookup: AuditLookup) {
  const channel = lookup.channels.get(event.subject);
  if (channel) return { platform: channel.platform, full: channel.account ? `${channel.platform} (${channel.account})` : channel.platform };
  const provider = providerName(text(event.meta?.provider) ?? lookup.providerBySubject.get(event.subject), lookup.providers);
  return provider ? { platform: provider, full: provider } : null;
}

const PLAN_NAMES: Record<string, string> = { trial: 'Trial', studio: 'Studio', assist: 'Studio Assist' };

/** Plan terms ids are `<plan>-v<n>` or `<plan>-<variant>-v<n>` (`007_consumer_web_billing.sql`). */
function planFromTerms(termsId: string) {
  const plan = termsId.split('-')[0];
  return PLAN_NAMES[plan] ?? null;
}

const VERIFY_RESULTS: Record<string, { detail: string; tone: AuditTone }> = {
  publish_verified: { detail: 'The account answered and publishing is confirmed.', tone: 'neutral' },
  read_verified: { detail: 'The same account answered.', tone: 'neutral' },
  reauthorization_required: { detail: 'A different account answered, so it needs connecting again.', tone: 'warning' },
  token_expired: { detail: 'Access had expired, so it needs connecting again.', tone: 'warning' }
};

export function describeAuditEvent(event: AuditEvent, lookup: AuditLookup): AuditDescription {
  const meta = event.meta ?? {};
  const role = roleName(meta.role);
  switch (event.kind) {
    case 'api_token.created': return { headline: 'Created an API token', detail: 'Read/draft access with a mandatory expiry.', tone: 'neutral' };
    case 'api_token.revoked': return { headline: 'Revoked an API token', detail: 'The token can no longer access this workspace.', tone: 'neutral' };
    case 'api_token.draft_requested': return { headline: 'Requested a draft through an API token', detail: 'Uses the same source and writing allowance checks as the app.', tone: 'neutral' };
    case 'workspace.created': {
      const plan = text(meta.plan);
      // `pr_bootstrap` starts every workspace on a trial of the plan chosen at sign-up.
      return {
        headline: 'Created this workspace',
        detail: plan && plan !== 'trial' ? `Started on a trial of ${PLAN_NAMES[plan] ?? capitalise(plan)}.` : plan ? 'Started on a trial.' : null,
        tone: 'neutral'
      };
    }
    case 'invitation.created':
      return { headline: role ? `Invited someone to join as ${role}` : 'Invited someone to join', detail: grantsSentence(meta), tone: 'neutral' };
    case 'invitation.revoked': {
      const invited = roleName(lookup.invitations.get(event.subject)?.role);
      return { headline: invited ? `Withdrew the invitation to join as ${invited}` : 'Withdrew an invitation', detail: null, tone: 'neutral' };
    }
    case 'invitation.accepted':
      return { headline: role ? `Joined the workspace as ${role}` : 'Joined the workspace', detail: null, tone: 'neutral' };
    case 'invitation.declined': {
      const invited = roleName(lookup.invitations.get(event.subject)?.role);
      return { headline: invited ? `Declined the invitation to join as ${invited}` : 'Declined an invitation', detail: null, tone: 'neutral' };
    }
    case 'member.updated': {
      const target = personOf(event.subject, lookup);
      const whose = target.kind === 'you' ? 'your' : "a member's";
      const who = target.kind === 'you' ? null : memberReference(target);
      return {
        headline: role ? `Changed ${whose} role to ${role}` : `Changed ${whose} access`,
        detail: [who, grantsSentence(meta)].filter(Boolean).join(' ') || null,
        tone: 'neutral'
      };
    }
    case 'member.removed': {
      const target = personOf(event.subject, lookup);
      if (target.kind === 'you') return { headline: 'Removed you from the workspace', detail: null, tone: 'warning' };
      if (target.role) {
        // Named: the headline says who. The detail only matters if they have since come back.
        return { headline: `Removed ${target.name} from the workspace`, detail: target.kind === 'former' ? null : memberReference(target), tone: 'warning' };
      }
      return { headline: 'Removed a member', detail: memberReference(target), tone: 'warning' };
    }
    case 'member.left':
      return { headline: 'Left the workspace', detail: null, tone: 'neutral' };
    case 'ownership.transferred': {
      // `transfer_ownership`: the subject is the new owner (an active admin until then); the actor, the owner until then,
      // becomes an admin with every grant in the same transaction.
      const target = personOf(event.subject, lookup);
      const to = target.kind === 'you' ? 'you' : target.role ? target.name : 'another member';
      const actorIsYou = event.actor ? personOf(event.actor, lookup).kind === 'you' : false;
      return {
        headline: `Handed ownership to ${to}`,
        detail:
          [target.kind === 'you' ? null : memberReference(target), actorIsYou ? 'You became an admin with every grant.' : 'The previous owner became an admin with every grant.']
            .filter(Boolean)
            .join(' ') || null,
        tone: 'warning'
      };
    }
    case 'billing.checkout_started': {
      const plan = planFromTerms(event.subject);
      return {
        headline: plan ? `Started checkout for ${plan}` : 'Started a checkout',
        detail: 'Nothing changes until the payment provider confirms the subscription.',
        tone: 'neutral'
      };
    }
    case 'billing.portal_opened':
      return { headline: 'Opened the billing portal', detail: null, tone: 'neutral' };
    case 'data.exported':
      return { headline: 'Exported the workspace data', detail: typeof meta.bytes === 'number' ? `A ${formatBytes(meta.bytes)} download.` : null, tone: 'neutral' };
    case 'data.diagnostics':
      return { headline: 'Created a diagnostics package', detail: 'Counts and states for troubleshooting, with no content.', tone: 'neutral' };
    case 'memory.egress_decided':
      return {
        headline:
          meta.cloud === true
            ? 'Let the cloud model read the memory files'
            : meta.cloud === false
              ? 'Stopped the cloud model reading the memory files'
              : 'Changed cloud access to the memory files',
        detail: null,
        tone: 'neutral'
      };
    case 'research.egress_decided':
      return {
        headline: meta.web === true ? 'Turned web research on' : meta.web === false ? 'Turned web research off' : 'Changed the web research setting',
        detail: null,
        tone: 'neutral'
      };
    case 'oauth.started': {
      const channel = channelName(event, lookup);
      const capability = text(meta.capability);
      return {
        headline: channel ? `Started connecting ${channel.platform}` : 'Started connecting a channel',
        detail: capability ? `Asked for: ${capabilityLabel(capability)}.` : null,
        tone: 'neutral'
      };
    }
    case 'oauth.rejected': {
      const channel = channelName(event, lookup);
      return {
        headline: channel ? `A ${channel.platform} connection attempt was turned away` : 'A connection attempt was turned away',
        detail: 'The answer from the provider did not match a request started here, so nothing was connected.',
        tone: 'warning'
      };
    }
    case 'oauth.denied': {
      const channel = channelName(event, lookup);
      return {
        headline: channel ? `Did not approve the connection at ${channel.platform}` : 'Did not approve a connection at the provider',
        detail: 'Nothing was connected.',
        tone: 'warning'
      };
    }
    case 'channel.connected': {
      const channel = channelName(event, lookup);
      const capability = text(meta.capability);
      const level = text(meta.publishLevel);
      const missing = list(meta.missingScopes);
      const parts = [
        capability ? `For: ${capabilityLabel(capability)}.` : null,
        level ? `Publishing level: ${level}.` : null,
        missing.length ? `${missing.length} permission${missing.length === 1 ? ' was' : 's were'} not granted.` : null
      ].filter(Boolean);
      return { headline: channel ? `Connected ${channel.full}` : 'Connected a channel', detail: parts.join(' ') || null, tone: missing.length ? 'warning' : 'neutral' };
    }
    case 'channel.verified': {
      const channel = channelName(event, lookup);
      const result = VERIFY_RESULTS[text(meta.state) ?? ''];
      return { headline: channel ? `Re-checked ${channel.full}` : 'Re-checked a channel', detail: result?.detail ?? null, tone: result?.tone ?? 'neutral' };
    }
    case 'channel.disconnected': {
      const channel = channelName(event, lookup);
      const where = channel?.platform ?? 'the provider';
      return {
        headline: channel ? `Disconnected ${channel.full}` : 'Disconnected a channel',
        detail: meta.remoteRevoked === true ? `Access was withdrawn at ${where} too.` : `Access was removed here; ${where} did not confirm withdrawing it.`,
        tone: 'warning'
      };
    }
    case 'reply.approved': {
      const provider = providerName(text(meta.provider), lookup.providers);
      return { headline: provider ? `Approved a reply on ${provider}` : 'Approved a reply to a comment', detail: null, tone: 'neutral' };
    }
    default: {
      const words = event.kind.replace(/[._]/g, ' ').trim();
      return { headline: words ? capitalise(words) : 'Unnamed event', detail: null, tone: 'neutral' };
    }
  }
}

/** Who an event was about, for the detail line: "Sam, Admin today." or "Member 22222222, no longer in the workspace." */
function memberReference(person: Person) {
  const label = person.role ? person.name : person.short ? `Member ${person.short}` : null;
  if (!label) return null;
  if (person.kind === 'former') return `${label}, no longer in the workspace.`;
  if (person.kind === 'member') return `${label}, ${person.role ?? person.name} today.`;
  return `${label}.`;
}

/** Map a subject to the provider the connection events name, so later events about it can say which channel. */
export function providersBySubject(events: readonly AuditEvent[]) {
  const map = new Map<string, string>();
  // Oldest first, so the newest event naming a provider wins.
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const provider = text(event.meta?.provider);
    if (provider && event.subject && familyOf(event.kind) === 'channels') map.set(event.subject, provider);
  }
  return map;
}

/* ---------- the detail sheet ---------- */

/** What the subject id is, by kind. Null when the kind has no subject worth showing. */
export function subjectLabel(event: AuditEvent): string | null {
  if (!event.subject) return null;
  if (event.kind.startsWith('member.')) return 'Member id';
  if (event.kind === 'ownership.transferred') return 'New owner id';
  if (event.kind.startsWith('invitation.')) return 'Invitation id';
  if (event.kind.startsWith('channel.')) return 'Connection id';
  if (event.kind.startsWith('oauth.')) return 'Connection attempt id';
  if (event.kind.startsWith('data.')) return 'Request id';
  if (event.kind === 'billing.checkout_started') return 'Plan terms';
  if (event.kind === 'reply.approved') return 'Reply id';
  if (event.kind === 'memory.egress_decided' || event.kind === 'research.egress_decided') return 'Setting';
  return 'Subject';
}

const META_LABELS: Record<string, string> = {
  role: 'Role',
  plan: 'Plan',
  provider: 'Provider',
  capability: 'Asked for',
  missingScopes: 'Permissions not granted',
  publishLevel: 'Publishing level',
  state: 'Result',
  remoteRevoked: 'Withdrawn at the provider',
  reason: 'Reason',
  bytes: 'Size',
  cloud: 'Cloud model may read memory',
  web: 'Web research on',
  can_publish: 'Can approve posts',
  can_reply: 'Can reply to comments',
  can_moderate: 'Can moderate',
  can_manage_connections: 'Can manage channels'
};

const REASONS: Record<string, string> = { mismatch_or_replay: 'The answer did not match a request started here' };

function words(key: string) {
  const spaced = key.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_.]/g, ' ').toLowerCase();
  return capitalise(spaced);
}

export interface MetaRow {
  key: string;
  label: string;
  value: string;
  /** Objects are shown as formatted JSON. */
  block: boolean;
}

export function metaRows(event: AuditEvent, lookup: AuditLookup): MetaRow[] {
  return Object.entries(event.meta ?? {}).map(([key, value]) => {
    const label = META_LABELS[key] ?? words(key);
    if (typeof value === 'boolean') return { key, label, value: value ? 'Yes' : 'No', block: false };
    if (key === 'bytes' && typeof value === 'number') return { key, label, value: formatBytes(value), block: false };
    if (key === 'role') return { key, label, value: roleName(value) ?? String(value), block: false };
    if (key === 'provider' && typeof value === 'string') return { key, label, value: providerName(value, lookup.providers) ?? value, block: false };
    if (key === 'capability' && typeof value === 'string') return { key, label, value: capabilityLabel(value), block: false };
    if (key === 'plan' && typeof value === 'string') return { key, label, value: PLAN_NAMES[value] ?? value, block: false };
    if (key === 'state' && typeof value === 'string') return { key, label, value: VERIFY_RESULTS[value]?.detail ?? words(value), block: false };
    if (key === 'reason' && typeof value === 'string') return { key, label, value: REASONS[value] ?? words(value), block: false };
    if (Array.isArray(value)) {
      const items = value.map((item) => (typeof item === 'string' ? item : JSON.stringify(item)));
      return { key, label, value: items.length ? items.join(', ') : 'None', block: false };
    }
    if (value !== null && typeof value === 'object') return { key, label, value: JSON.stringify(value, null, 2), block: true };
    return { key, label, value: value === null || value === undefined || value === '' ? '—' : String(value), block: false };
  });
}

/* ---------- where it happened ---------- */

export interface AuditLink {
  href: string;
  label: string;
  access?: PermissionCheck;
}

function flatten(items: readonly NavItem[]): NavItem[] {
  return items.flatMap((item) => [item, ...flatten(item.items ?? [])]);
}

const NAV_ITEMS = flatten(navGroups.flatMap((group) => group.items));

/** The nav entry's own access rule, so a link is offered only where the sidebar would offer the page. */
function navLink(href: string, label: string): AuditLink {
  return { href, label, access: NAV_ITEMS.find((item) => item.url === href)?.access };
}

export function linkFor(kind: string): AuditLink | null {
  if (kind.startsWith('member.') || kind.startsWith('ownership.') || kind.startsWith('invitation.')) return navLink('/app/workspace/members', 'Members');
  if (kind.startsWith('channel.') || kind.startsWith('oauth.')) return navLink('/app/channels', 'Channels');
  if (kind.startsWith('data.')) return navLink('/app/account/privacy', 'Privacy');
  if (kind.startsWith('memory.') || kind.startsWith('research.')) return navLink('/app/workspace/memory', 'Memory');
  if (kind.startsWith('billing.')) return navLink('/app/account/billing', 'Billing');
  if (kind.startsWith('reply.')) return navLink('/app/inbox', 'Inbox');
  return null;
}

/* ---------- time ---------- */

function dayKeyFormatter() {
  const { timeZone } = timeDefaults();
  return new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone });
}

/** Calendar day in the person's time zone (`lib/time` defaults), e.g. "2026-09-16". */
export function dayKey(epochSeconds: number) {
  return dayKeyFormatter().format(new Date(epochSeconds * 1000));
}

export function dayLabel(epochSeconds: number, now = Date.now() / 1000) {
  const key = dayKey(epochSeconds);
  const full = formatDate(epochSeconds, { dateStyle: 'full' });
  if (key === dayKey(now)) return { lead: 'Today', full };
  if (key === dayKey(now - 86400)) return { lead: 'Yesterday', full };
  return { lead: null, full };
}

export function timeOfDay(epochSeconds: number) {
  const { locale, timeZone } = timeDefaults();
  return new Intl.DateTimeFormat(locale, { timeStyle: 'short', timeZone }).format(new Date(epochSeconds * 1000));
}

export interface DayGroup {
  key: string;
  at: number;
  events: AuditEvent[];
}

/** Events arrive newest first; groups keep that order. */
export function groupByDay(events: readonly AuditEvent[]): DayGroup[] {
  const groups: DayGroup[] = [];
  const formatter = dayKeyFormatter();
  for (const event of events) {
    const key = formatter.format(new Date(event.at * 1000));
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.events.push(event);
    else groups.push({ key, at: event.at, events: [event] });
  }
  return groups;
}

export function eventKey(event: AuditEvent, index: number) {
  return event.id ?? `${event.kind}-${event.at}-${index}`;
}
