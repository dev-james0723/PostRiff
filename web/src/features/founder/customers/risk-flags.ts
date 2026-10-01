import type { RecordRow } from './kit/types';

/**
 * Customer risk flags (PRD §7.4): explainable, versioned rules evaluated on fields the server already returned.
 * Flags are shown side by side with their evidence and never folded into one score. A rule whose input the source
 * does not carry raises no flag (unknown is not "fine" and not "at risk"). `at_risk` is the one inference and is
 * labelled a hypothesis. Server-computed flags (`riskFlags` on the row) take precedence and are passed through.
 */
export type RiskFlagId = 'payment_risk' | 'quota_near_limit' | 'inactive' | 'connection_risk' | 'unknown_cost' | 'at_risk';

export interface RiskFlag {
  id: RiskFlagId;
  label: string;
  kind: 'observed' | 'hypothesis';
  evidence: string;
  rule: 'v1' | 'server';
}

export const RULE_VERSION = 'v1';

export const PAYMENT_RISK_STATUSES = new Set(['past_due', 'unpaid', 'grace', 'cancel_at_period_end', 'incomplete', 'payment_failed', 'top_up_failed']);
export const CONNECTION_RISK_STATES = new Set(['token_expired', 'reauthorization_required', 'scope_missing', 'expired', 'blocked']);
export const INACTIVE_DAYS = 30;
/** `remaining / quota ≤ 20 %`, compared without a division so the inputs stay the server's integers. */
const QUOTA_REMAINING_FRACTION = 5;

const LABEL: Record<RiskFlagId, string> = {
  payment_risk: 'Payment risk',
  quota_near_limit: 'Quota near limit',
  inactive: `Inactive ${INACTIVE_DAYS}d`,
  connection_risk: 'Connection risk',
  unknown_cost: 'Unknown cost holds',
  at_risk: 'At-risk'
};

function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function serverFlags(row: RecordRow): RiskFlag[] {
  const raw = row.riskFlags;
  if (!Array.isArray(raw)) return [];
  const out: RiskFlag[] = [];
  for (const item of raw) {
    const id = typeof item === 'string' ? item : item && typeof item === 'object' ? text((item as { id?: unknown }).id) : null;
    if (!id || !(id in LABEL)) continue;
    const evidence = item && typeof item === 'object' ? (text((item as { evidence?: unknown }).evidence) ?? 'Server rule') : 'Server rule';
    out.push({ id: id as RiskFlagId, label: LABEL[id as RiskFlagId], kind: id === 'at_risk' ? 'hypothesis' : 'observed', evidence, rule: 'server' });
  }
  return out;
}

function paymentRisk(customer: RecordRow, workspaces: RecordRow[]): RiskFlag | null {
  const candidates = [text(customer.status), text(customer.subscriptionStatus), ...workspaces.map((workspace) => text(workspace.status))];
  const hit = candidates.find((status) => status && PAYMENT_RISK_STATUSES.has(status));
  return hit ? { id: 'payment_risk', label: LABEL.payment_risk, kind: 'observed', evidence: `status ${hit.replaceAll('_', ' ')}`, rule: 'v1' } : null;
}

function quotaNearLimit(workspaces: RecordRow[]): RiskFlag | null {
  for (const workspace of workspaces) {
    const quota = num(workspace.creditsQuota);
    const remaining = num(workspace.creditsRemaining);
    if (quota === null || remaining === null || quota <= 0) continue;
    if (remaining * QUOTA_REMAINING_FRACTION <= quota) {
      const used = num(workspace.creditsUsed);
      return { id: 'quota_near_limit', label: LABEL.quota_near_limit, kind: 'observed', evidence: used !== null ? `${used.toLocaleString()} of ${quota.toLocaleString()} credits used` : `${remaining.toLocaleString()} of ${quota.toLocaleString()} credits left`, rule: 'v1' };
    }
  }
  return null;
}

function inactive(customer: RecordRow, workspaces: RecordRow[], now: Date): RiskFlag | null {
  const stamps = [customer.lastActiveAt, customer.lastActivityAt, ...workspaces.flatMap((workspace) => [workspace.lastActiveAt, workspace.lastActivityAt])].map(text).filter((value): value is string => value !== null);
  if (stamps.length === 0) return null;
  const latest = Math.max(...stamps.map((stamp) => Date.parse(stamp)).filter((value) => Number.isFinite(value)));
  if (!Number.isFinite(latest)) return null;
  const days = Math.floor((now.getTime() - latest) / 86_400_000);
  return days >= INACTIVE_DAYS ? { id: 'inactive', label: LABEL.inactive, kind: 'observed', evidence: `last activity ${days} days ago`, rule: 'v1' } : null;
}

function connectionRisk(customer: RecordRow, workspaces: RecordRow[]): RiskFlag | null {
  const states: string[] = [];
  for (const row of [customer, ...workspaces]) {
    const connections = row.connections ?? row.connectionStates;
    if (Array.isArray(connections)) {
      for (const connection of connections) {
        const state = typeof connection === 'string' ? connection : connection && typeof connection === 'object' ? text((connection as { state?: unknown }).state) : null;
        if (state && CONNECTION_RISK_STATES.has(state)) states.push(state);
      }
    }
    if (row.connectionRisk === true) states.push('flagged');
  }
  return states.length ? { id: 'connection_risk', label: LABEL.connection_risk, kind: 'observed', evidence: states[0].replaceAll('_', ' '), rule: 'v1' } : null;
}

function unknownCost(customer: RecordRow, workspaces: RecordRow[]): RiskFlag | null {
  const holds = [customer, ...workspaces].map((row) => num(row.unknownCostRows)).find((value) => value !== null && value > 0);
  if (holds !== undefined && holds !== null) return { id: 'unknown_cost', label: LABEL.unknown_cost, kind: 'observed', evidence: `${holds} usage ${holds === 1 ? 'row' : 'rows'} without a recorded cost`, rule: 'v1' };
  if ([customer, ...workspaces].some((row) => text(row.costState) === 'estimated_unknown')) return { id: 'unknown_cost', label: LABEL.unknown_cost, kind: 'observed', evidence: 'cost state estimated unknown', rule: 'v1' };
  return null;
}

/** Workspaces linked to a customer, from the page's `workspaces` list (keyed by id) and the row's `workspaceIds`. */
export function linkedWorkspaces(customer: RecordRow, workspaces: readonly RecordRow[]): RecordRow[] {
  const ids = Array.isArray(customer.workspaceIds) ? (customer.workspaceIds as unknown[]).filter((id): id is string => typeof id === 'string') : [];
  const byId = new Map(workspaces.map((workspace) => [workspace.id, workspace]));
  return ids.map((id) => byId.get(id)).filter((workspace): workspace is RecordRow => workspace !== undefined);
}

export function riskFlags(customer: RecordRow, workspaces: readonly RecordRow[], now: Date = new Date()): RiskFlag[] {
  const fromServer = serverFlags(customer);
  if (fromServer.length) return fromServer;
  const linked = linkedWorkspaces(customer, workspaces);
  const flags = [paymentRisk(customer, linked), quotaNearLimit(linked), inactive(customer, linked, now), connectionRisk(customer, linked), unknownCost(customer, linked)].filter((flag): flag is RiskFlag => flag !== null);
  const has = (id: RiskFlagId) => flags.some((flag) => flag.id === id);
  if (has('inactive') && (has('payment_risk') || has('connection_risk'))) {
    flags.push({ id: 'at_risk', label: LABEL.at_risk, kind: 'hypothesis', evidence: `inactive and ${has('payment_risk') ? 'payment risk' : 'connection risk'}`, rule: 'v1' });
  }
  return flags;
}
