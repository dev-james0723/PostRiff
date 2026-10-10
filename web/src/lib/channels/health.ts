/**
 * Connection Health Center (`rafii-connection-health/1`, `postriff_phase2/connection_health.py`).
 *
 * The server decides every state; this module only shapes words and order for the page and the compact panel.
 * Nothing here upgrades a state: a line the server calls unavailable is never shown as working, and "ready" is shown
 * only when the server said so. Pure and import-free (types aside) so `node --test` can load it directly.
 */

export type HealthState =
  | 'expired'
  | 'blocked'
  | 'connected'
  | 'syncing'
  | 'limited'
  | 'authorized'
  | 'ready'
  | 'not_connected'
  | 'unsupported';

export type LineName = 'publishing' | 'analytics' | 'history' | 'comments';
export type LineStatus =
  | 'available'
  | 'on_request'
  | 'private_only'
  | 'assisted'
  | 'not_collected'
  | 'awaiting_review'
  | 'not_enabled'
  | 'not_granted'
  | 'not_offered'
  | 'unavailable';

export interface HealthLine {
  status: LineStatus;
  /** The capability to grant again for this line, through the existing Connect sheet. */
  grant?: string;
  /** Why the line is what it is, when the server knows (for example `awaiting_review` on assisted publishing). */
  detail?: string;
}

export interface HealthAccount {
  channelId: string;
  platform: string;
  account: string;
  accountType?: string | null;
  connectionState: string;
  state: HealthState;
  reasons: string[];
  attention: boolean;
  lines: Record<LineName, HealthLine>;
  missingPermissions: { capability: string; scopes: string[] }[];
  access: { status: 'active' | 'expiring' | 'expired' | 'revoked' | 'reconnect_required' | 'none'; expiresAt: number | null; renewsAutomatically: boolean };
  lastVerifiedAt: number | null;
  sync: { status: 'running' | 'failed' | 'idle' | 'never' | 'not_applicable' | 'unknown'; lastSuccessAt: number | null; lastSuccessKind: 'analytics' | 'history_import' | null; lastProblemAt: number | null };
  freshness: { latestDataAt: number | null; ageSeconds: number | null; band: 'recent' | 'older' | 'none' | 'unknown' };
  authorizationLane: 'standard' | 'agentic' | null;
  /** Capability levels only, so `reconnectCapability` (state.ts) picks what a reconnect asks for again. */
  capabilities: Record<string, { level?: string }>;
  reconnect:
    | { available: true; providerId: string; channelId: string; account: string; grants: string[] }
    | { available: false; reason: 'platform_unavailable' | 'operator_paused' | 'manage_required' };
  pictureDigest?: string | null;
}

export interface HealthPlatform {
  platform: string;
  providerId: string | null;
  state: HealthState;
  connectable: boolean;
  reviewed: boolean;
  accounts: HealthAccount[];
}

export type HealthAutonomy =
  | { source: 'todays_behaviour'; mode: 'off'; href: null }
  | { source: 'unavailable'; mode: string | null; href: null }
  | {
      source: 'agent_permissions';
      mode: 'shadow' | 'enforce';
      preset: 'legacy' | 'none' | 'recommended' | 'full' | 'custom' | null;
      needsChoice: boolean;
      categories: { id: string; mode: 'ask' | 'assist' | null; effective: 'on' | 'asks' | 'off' | 'clipped' | 'unavailable' }[];
      href: string;
    };

export interface ConnectionHealth {
  contract: 'rafii-connection-health/1';
  generatedAt: number;
  liveChecked: false;
  evidence: 'stored_records';
  canManage: boolean;
  counts: Record<HealthState, number>;
  attention: number;
  platforms: HealthPlatform[];
  autonomy: HealthAutonomy;
}

export const HEALTH_HREF = '/app/channels/health';

/** Badge tone per state, in the shared monochrome status grammar (AnimatedBadge statuses). */
export function stateTone(state: HealthState): 'success' | 'warning' | 'neutral' | 'loading' | 'info' {
  switch (state) {
    case 'ready':
      return 'success';
    case 'syncing':
      return 'loading';
    case 'expired':
    case 'blocked':
      return 'warning';
    case 'limited':
    case 'authorized':
      return 'info';
    default:
      return 'neutral';
  }
}

/** The copy key for the headline of an expired account: expired, revoked and "reconnect once" read differently. */
export function badgeKey(account: Pick<HealthAccount, 'state' | 'reasons'>): string {
  if (account.state === 'expired' && account.reasons[0] === 'access_revoked') return 'badge.revoked';
  if (account.state === 'expired' && account.reasons[0] === 'reconnect_required') return 'badge.reconnect';
  return `state.${account.state}`;
}

/** The copy key for one line: per-line wording where it exists, else the shared status wording. */
export function lineKey(name: LineName, line: HealthLine): string {
  if (name === 'publishing' && line.status === 'assisted' && line.detail === 'awaiting_review') return 'status.publishing.assisted_review';
  const specific = `status.${name}.${line.status}`;
  return SPECIFIC_LINES.has(specific) ? specific : `status.${line.status}`;
}

const SPECIFIC_LINES = new Set([
  'status.publishing.available',
  'status.publishing.private_only',
  'status.publishing.assisted',
  'status.analytics.available',
  'status.analytics.on_request',
  'status.history.on_request',
  'status.comments.available',
  'status.comments.on_request'
]);

/** Lines that work now (fully, on request, privately, or with your last step). Everything else is a gap. */
export const USABLE_LINES: ReadonlySet<LineStatus> = new Set(['available', 'on_request', 'private_only', 'assisted']);

export function lineWorks(line: HealthLine) {
  return USABLE_LINES.has(line.status);
}

/** Accounts that need the person, most urgent first, for the compact panel. */
export function attentionAccounts(health: Pick<ConnectionHealth, 'platforms'>, limit = 3): HealthAccount[] {
  const order: HealthState[] = ['expired', 'blocked', 'connected', 'syncing', 'limited', 'authorized', 'ready', 'not_connected', 'unsupported'];
  return health.platforms
    .flatMap((platform) => platform.accounts)
    .filter((account) => account.attention)
    .toSorted((a, b) => order.indexOf(a.state) - order.indexOf(b.state) || a.platform.localeCompare(b.platform) || a.account.localeCompare(b.account))
    .slice(0, limit);
}

/** The three numbers the compact panel shows, straight from the server's counts. */
export function panelNumbers(health: Pick<ConnectionHealth, 'counts' | 'attention'>) {
  return { ready: health.counts.ready ?? 0, limited: (health.counts.limited ?? 0) + (health.counts.authorized ?? 0), attention: health.attention };
}

/** Platforms with accounts first (the server's order), then the rest for the "Other platforms" list. */
export function splitPlatforms(platforms: readonly HealthPlatform[]) {
  return { connected: platforms.filter((p) => p.accounts.length > 0), other: platforms.filter((p) => p.accounts.length === 0) };
}
