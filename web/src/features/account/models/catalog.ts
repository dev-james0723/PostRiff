import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { AgentInfo, ModelOption } from '@/lib/api/types';
import { ROUTE_LABELS } from '@/features/agent/use-model';

/**
 * Pure helpers over `GET /api/ideas/models`. Everything here reads what the API returned;
 * fields the API does not send yet (a probe time, per-route reasoning) are read defensively
 * and simply not shown when absent.
 */

export type RouteKind = 'cli' | 'managed' | 'preview' | 'other';

export const KIND_LABEL: Record<RouteKind, string> = {
  cli: 'Local CLI',
  managed: 'PostRiff managed',
  preview: 'Preview · no model',
  other: 'Other route'
};

/** Which kind of writer an option is. Managed options carry no `route` today, so cost class decides for them. */
export function routeKind(option: ModelOption, agents: AgentInfo[]): RouteKind {
  const route = option.route;
  if (route === 'managed') return 'managed';
  if (route === 'fixture') return 'preview';
  if (route) return agents.some((agent) => agent.id === route) || ROUTE_LABELS[route] ? 'cli' : 'other';
  if (option.costClass === 'paid') return 'managed';
  if (option.costClass === 'none') return 'preview';
  return 'other';
}

/** The readiness badge for a CLI agent: every `authStatus` the API sends, never a blended "Connected". */
export function authState(agent: AgentInfo): { status: AnimatedBadgeStatus; label: string } {
  if (!agent.installed) return { status: 'neutral', label: 'Not installed' };
  switch (agent.authStatus) {
    case 'ok':
      return { status: 'success', label: 'Signed in' };
    case 'missing':
      return { status: 'warning', label: 'Sign-in required' };
    case 'expired':
      return { status: 'warning', label: 'Sign-in expired' };
    case 'unknown':
      return { status: 'neutral', label: 'Status unknown' };
    default:
      return { status: 'neutral', label: `Status: ${agent.authStatus}` };
  }
}

/**
 * A per-run spending cap the API reports. Null (or a legacy zero) means no cap.
 */
export function budgetCap(agent: AgentInfo): number | null {
  const value = agent.execution?.budgetUsd;
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

/** When the server last probed this CLI, in epoch seconds, if the API sends it. */
export function probedAt(agent: AgentInfo): number | null {
  const value = agent.probedAt;
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
  return value > 1e12 ? value / 1000 : value;
}

export interface ReasoningLevel {
  id: string;
  available: boolean;
  detail: string;
}

/**
 * Reasoning levels for one route, only when the API sends them for that route. The catalog's
 * top-level `reasoning` describes the deterministic preview alone, so it is never used for a route.
 */
export function routeReasoning(source: AgentInfo | ModelOption): ReasoningLevel[] | null {
  const value = source.reasoning;
  if (!Array.isArray(value)) return null;
  const levels = value.filter(
    (item): item is ReasoningLevel =>
      typeof item === 'object' && item !== null && typeof (item as ReasoningLevel).id === 'string' && typeof (item as ReasoningLevel).available === 'boolean'
  );
  return levels.length > 0 ? levels.map((level) => ({ ...level, detail: typeof level.detail === 'string' ? level.detail : '' })) : null;
}

/** The gateway or provider a managed option names, if the API sends one. */
export function optionProvider(option: ModelOption): string | null {
  const value = option.provider;
  return typeof value === 'string' && value ? value : null;
}

/** "Sonnet" from "Claude Code · Sonnet": the part after the route's own name. */
export function aliasLabel(option: ModelOption, routeName: string) {
  const prefix = `${routeName} · `;
  return option.label.startsWith(prefix) ? option.label.slice(prefix.length) : option.label;
}

export interface CostCopy {
  badge: string;
  line: string;
}

/** Billing copy generated from the `costClass` the API reports for a route. */
export function costCopy(costClass: string | undefined): CostCopy {
  switch (costClass) {
    case 'none':
      return { badge: 'Free', line: 'No model request and no charge.' };
    case 'subscription':
      return {
        badge: 'Your CLI subscription',
        line: 'The subscription signed in to the CLI pays. PostRiff records the run with a cost of $0.'
      };
    case 'paid':
      return {
        badge: 'Writing batches',
        line: 'Metered to this workspace. A finished run uses one writing batch from your plan; a failed run gives the batch back.'
      };
    case undefined:
    case '':
      return { badge: 'Not reported', line: 'The API did not say how this route is paid for.' };
    default:
      return { badge: costClass, line: `The API reports the cost class “${costClass}”, which this page does not describe yet.` };
  }
}

/**
 * Distinct cost classes of the writers someone can actually pick, in catalog order. Unavailable
 * options are left out: the preview runtime always lists a "PostRiff managed model" placeholder
 * marked not qualified, which would otherwise add "Writing batches" to every deployment.
 */
export function distinctCostClasses(options: ModelOption[]) {
  return Array.from(new Set(options.filter((option) => option.qualified).map((option) => option.costClass ?? '')));
}

/** Plain words for the `host` an agent reports. */
export function hostLabel(host: string | undefined) {
  if (host === 'api-process') return 'The machine that serves the PostRiff API';
  return host ? host : 'Not reported';
}
