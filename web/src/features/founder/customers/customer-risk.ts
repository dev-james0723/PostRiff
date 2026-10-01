import type { FounderMode } from './kit/types';
import { count, minor, ratio, stateLabel, usdMicro, whenDate } from './kit/format';

/**
 * Customer risk from `GET /customers/risk?mode=&view=` (CONTRACTS §8.C; PRD §7.4, §5.3): explainable, versioned rules
 * evaluated on the server over the whole population (bounded to 200 workspaces per view). Each flag carries its rule,
 * trigger, evidence and since; flags sit side by side and are never folded into a score. At-risk is the one inferred
 * flag and is labelled a hypothesis. This module only types, joins and words what the server sent.
 */

/** The saved views (PRD §5.3) and the server view each one asks for (founder_risk.VIEWS). */
export const RISK_VIEWS = [
  { id: 'high_value', label: 'High value', rule: 'high_value' },
  { id: 'high_ai_cost', label: 'High AI cost', rule: 'high_ai_cost' },
  { id: 'quota_80', label: 'Quota ≥80%', rule: 'quota_near_limit' },
  { id: 'inactive_30d', label: 'Inactive 30d', rule: 'inactive' },
  { id: 'payment_risk', label: 'Payment risk', rule: 'payment_risk' },
  { id: 'at_risk', label: 'At-risk', rule: 'at_risk' }
] as const;

export type RiskViewId = (typeof RISK_VIEWS)[number]['id'];
/** Every view the server answers; `flagged` (any flag) feeds the chips on the tables. */
export type ServerRiskView = RiskViewId | 'connection_risk' | 'unknown_cost' | 'flagged';
export type SavedViewId = 'all' | RiskViewId;

export const SAVED_VIEW_IDS = ['all', ...RISK_VIEWS.map((view) => view.id)] as [SavedViewId, ...SavedViewId[]];

/** Earlier spellings of the saved views (`?view=inactive`, `?view=quota`) keep landing on the same list. */
export const VIEW_ALIASES: Record<string, RiskViewId> = { inactive: 'inactive_30d', quota: 'quota_80', quota_near_limit: 'quota_80' };

export function resolveSavedView(raw: string | null | undefined): SavedViewId {
  if (!raw) return 'all';
  if ((SAVED_VIEW_IDS as readonly string[]).includes(raw)) return raw as SavedViewId;
  return VIEW_ALIASES[raw] ?? 'all';
}

export function riskView(id: RiskViewId) {
  return RISK_VIEWS.find((view) => view.id === id) ?? RISK_VIEWS[0];
}

export interface ServerRiskFlag {
  id: string;
  version: string;
  label: string;
  basis: 'observed' | 'hypothesis' | (string & {});
  trigger: string;
  since: string | null;
  evidence: Record<string, unknown>;
}

export interface RiskWorkspace {
  workspaceId: string;
  name: string | null;
  ownerId: string | null;
  plan: string | null;
  status: string | null;
  createdAt: string | null;
  flags: ServerRiskFlag[];
  flagCount: number;
}

export interface RiskRule {
  id: string;
  label: string;
  basis: string;
  trigger: string;
  source: string;
  version: string;
  state: 'measured' | 'partial' | 'unavailable' | 'not_evaluated' | (string & {});
  reason?: string;
  fallback?: string;
  truncated?: boolean;
}

export interface CustomerRiskData {
  mode: FounderMode;
  view: ServerRiskView;
  asOf: string;
  timeZone: string;
  rulesVersion: string;
  rules: RiskRule[];
  rows: RiskWorkspace[];
  total: number;
  truncated: boolean;
  limit: number;
  basis: string;
}

/** Capabilities the route checks (founder_risk.customers_risk): Live also reads workspaces. */
export function canReadRisk(capabilities: readonly string[], mode: FounderMode): boolean {
  const needed = ['customers.read', ...(mode === 'live' ? ['workspaces.read'] : [])];
  return needed.every((capability) => capabilities.includes(capability));
}

export function riskPath(mode: FounderMode, view: ServerRiskView): string {
  return `/customers/risk?${new URLSearchParams({ mode, view }).toString()}`;
}

/** The answer must be for the mode and view asked, with rows and rules; anything else is not shown. */
export function verifyRisk(data: unknown, mode: FounderMode, view: ServerRiskView): CustomerRiskData {
  const value = data as Partial<CustomerRiskData> | null;
  if (!value || value.mode !== mode || value.view !== view || !Array.isArray(value.rows) || !Array.isArray(value.rules) || typeof value.total !== 'number') {
    throw new Error('The risk list could not be verified. Retry.');
  }
  return value as CustomerRiskData;
}

/* ---------- joining flags onto table rows ---------- */

export type FlagIndex = ReadonlyMap<string, readonly ServerRiskFlag[]>;

export function flagIndex(rows: readonly RiskWorkspace[] | undefined): FlagIndex {
  return new Map((rows ?? []).map((row) => [row.workspaceId, row.flags ?? []]));
}

export interface JoinedFlag {
  flag: ServerRiskFlag;
  /** The workspaces (of this customer) that carry the flag. */
  workspaceIds: string[];
}

/**
 * The flags on a set of workspaces (a customer's `workspaceIds`, or one workspace id), one entry per rule with the
 * workspaces that raise it, in the server's rule order. A join only: nothing is scored or counted into a number.
 */
export function joinFlags(workspaceIds: unknown, index: FlagIndex): JoinedFlag[] {
  const ids = Array.isArray(workspaceIds) ? workspaceIds.filter((id): id is string => typeof id === 'string') : typeof workspaceIds === 'string' ? [workspaceIds] : [];
  const joined = new Map<string, JoinedFlag>();
  for (const id of ids) {
    for (const flag of index.get(id) ?? []) {
      const entry = joined.get(flag.id);
      if (entry) {
        if (!entry.workspaceIds.includes(id)) entry.workspaceIds.push(id);
      } else {
        joined.set(flag.id, { flag, workspaceIds: [id] });
      }
    }
  }
  return Array.from(joined.values());
}

export function isHypothesisFlag(flag: Pick<ServerRiskFlag, 'basis'>): boolean {
  return flag.basis === 'hypothesis';
}

/* ---------- words for evidence and rule states ---------- */

const EVIDENCE_LABEL: Record<string, string> = {
  plan: 'plan',
  tierPriceMinor: 'tier price',
  highestTier: 'highest-priced plan',
  cashMtdMinor: 'cash this month',
  p90CashMtdMinor: '90th percentile',
  cashPopulation: 'workspaces with cash',
  aiCost30dUsdMicro: 'AI cost, 30 days',
  p95AiCost30dUsdMicro: '95th percentile',
  costPopulation: 'workspaces with cost',
  cash30dUsdMinor: 'cash, 30 days',
  negativeMargin: 'cost above cash',
  usedUsdMicro: 'budget used',
  stopUsdMicro: 'budget stop',
  usedShare: 'used',
  creditsUsed: 'credits used',
  creditsQuota: 'credit quota',
  lastActiveAt: 'last active',
  daysInactive: 'days inactive',
  lastActivityLookbackDays: 'no activity found in days',
  subscriptionStatus: 'subscription',
  cancelAtPeriodEnd: 'cancels at period end',
  failedPayments30d: 'failed payments, 30 days',
  paymentKind: 'payment',
  connections: 'connections',
  states: 'states',
  openReconnectEvents: 'open reconnect notices',
  unknownRows: 'usage rows without a cost',
  unknownEstimateUsdMicro: 'estimate',
  because: 'because',
  source: 'source'
};

const FLAG_WORDS: Record<string, string> = {
  high_value: 'high value',
  high_ai_cost: 'high AI cost',
  quota_near_limit: 'quota near limit',
  inactive: 'inactive',
  payment_risk: 'payment risk',
  connection_risk: 'connection risk',
  unknown_cost_holds: 'unknown cost holds',
  at_risk: 'at-risk'
};

function words(value: string): string {
  return FLAG_WORDS[value] ?? stateLabel(value);
}

function evidenceValue(key: string, value: unknown, currency: string | null): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'boolean') return value ? '' : null;
  if (Array.isArray(value)) {
    const items = value.filter((item) => typeof item === 'string' || typeof item === 'number').map((item) => words(String(item)));
    return items.length ? items.join(', ') : null;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    if (key.endsWith('UsdMicro')) return usdMicro(value);
    if (key.endsWith('UsdMinor')) return minor(value, 'USD');
    if (key.endsWith('Minor')) return minor(value, currency ?? 'USD');
    if (key.endsWith('Share')) return ratio(value);
    return count(value);
  }
  if (typeof value === 'string') return key.endsWith('At') ? whenDate(value) : words(value);
  return null;
}

/** The evidence a flag carries, written out (`AI cost, 30 days $12.34 · 95th percentile $8.10`). Formatting only. */
export function evidenceText(flag: Pick<ServerRiskFlag, 'evidence'>): string {
  const evidence = flag.evidence && typeof flag.evidence === 'object' ? flag.evidence : {};
  const currency = typeof evidence.currency === 'string' && evidence.currency ? evidence.currency : null;
  const parts: string[] = [];
  for (const [key, value] of Object.entries(evidence)) {
    if (key === 'currency') continue;
    const shown = evidenceValue(key, value, currency);
    if (shown === null) continue;
    const label = EVIDENCE_LABEL[key] ?? stateLabel(key.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase());
    parts.push(shown === '' ? label : `${label} ${shown}`);
  }
  return parts.join(' · ');
}

/** A rule's state in words, so a view whose source is missing says so instead of looking empty. */
export function ruleStateText(rule: Pick<RiskRule, 'state' | 'reason' | 'fallback' | 'truncated'>): string {
  const notes: string[] = [];
  if (rule.fallback === 'reconnect_events') notes.push('read from reconnect notices until connection health is collected');
  if (rule.truncated) notes.push('the source returned more rows than one evaluation reads');
  const reason = rule.reason === 'demo_not_simulated' ? 'not simulated in the Demo dataset' : rule.reason === 'source_not_configured' ? 'its source is not configured' : rule.reason ? stateLabel(rule.reason) : null;
  let head: string;
  switch (rule.state) {
    case 'measured':
      head = 'Evaluated on every workspace';
      break;
    case 'partial':
      head = reason ? `Partly evaluated: ${reason}` : 'Partly evaluated';
      break;
    case 'unavailable':
      head = reason ? `Not available: ${reason}` : 'Not available';
      break;
    case 'not_evaluated':
      head = 'Not evaluated for this list';
      break;
    default:
      head = stateLabel(rule.state);
  }
  return notes.length ? `${head}; ${notes.join('; ')}.` : `${head}.`;
}
