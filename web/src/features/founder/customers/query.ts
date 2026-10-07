import { PAYMENT_RISK_STATUSES, type RiskFlagId } from './risk-flags';

/**
 * Saved views for the Customers list (PRD §5.3). A view either narrows the server query (a status the source
 * reports) or applies an observed risk rule to the rows the server returned for the current page. The second kind
 * is labelled "on this page" in the UI until the Live query grows risk filters (054 views, P1); it never pretends
 * to have searched the whole population.
 */
export type SavedViewId = 'all' | 'payment_risk' | 'quota' | 'inactive' | 'at_risk';

export interface SavedView {
  id: SavedViewId;
  label: string;
  /** `status`: send a status the server reports; `flag`: keep rows whose flags include `flag`; `all`: no narrowing. */
  mode: 'all' | 'status' | 'flag';
  flag?: RiskFlagId;
  description: string;
}

export const SAVED_VIEWS: readonly SavedView[] = [
  { id: 'all', label: 'All', mode: 'all', description: 'Every customer the source returns.' },
  { id: 'payment_risk', label: 'Payment risk', mode: 'status', description: 'A status the source reports as past due, unpaid or ending.' },
  { id: 'quota', label: 'Quota ≥80%', mode: 'flag', flag: 'quota_near_limit', description: 'Workspaces with 20% or less of their credits left (rule v1, this page).' },
  { id: 'inactive', label: 'Inactive 30d', mode: 'flag', flag: 'inactive', description: 'No recorded activity for 30 days (rule v1, this page).' },
  { id: 'at_risk', label: 'At-risk', mode: 'flag', flag: 'at_risk', description: 'Inactive and a payment or connection risk — a hypothesis, not a score.' }
];

export const SAVED_VIEW_IDS = SAVED_VIEWS.map((view) => view.id) as [SavedViewId, ...SavedViewId[]];

export function savedView(id: string): SavedView {
  return SAVED_VIEWS.find((view) => view.id === id) ?? SAVED_VIEWS[0];
}

/** The status a view sends to the server: the first risk status the source reports, else the chosen filter. */
export function serverStatusForView(view: SavedView, statuses: readonly string[], chosen: string): string {
  if (view.mode !== 'status') return chosen || 'all';
  if (chosen && chosen !== 'all' && PAYMENT_RISK_STATUSES.has(chosen)) return chosen;
  return statuses.find((status) => PAYMENT_RISK_STATUSES.has(status)) ?? chosen ?? 'all';
}

/** Whether the source reports any status a payment-risk view can ask for. */
export function paymentRiskAvailable(statuses: readonly string[]): boolean {
  return statuses.some((status) => PAYMENT_RISK_STATUSES.has(status));
}

/** Plan names seen on the loaded page, for the Demo plan filter (the server validates by id or name). */
export function observedPlans(rows: readonly Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    const plan = row.plan;
    if (typeof plan === 'string' && plan) seen.add(plan);
  }
  return Array.from(seen).toSorted((a, b) => a.localeCompare(b));
}
