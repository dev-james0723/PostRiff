import type { Icons } from '@/components/icons';

/**
 * Founder admin navigation (PRD §5.1): the Overview plus eight sections, grouped for the sidebar and ⌘K, the four
 * phone tab-bar destinations, and the redirect map from the retired `/control/*` preview. Pure data, no React, so
 * `tests/founder-nav.test.cjs` loads it directly.
 */

export const FOUNDER_SECTION_IDS = ['overview', 'customers', 'revenue', 'product', 'ai-cost', 'operations', 'support', 'settings', 'advanced'] as const;
export type FounderSectionId = (typeof FOUNDER_SECTION_IDS)[number];
/** The sections `app/founder/[section]/page.tsx` serves; the Overview has its own page. */
export type RoutedSectionId = Exclude<FounderSectionId, 'overview'>;

export interface FounderSection {
  id: FounderSectionId;
  title: string;
  /** Tab-bar label; the title when short enough. */
  shortTitle: string;
  url: string;
  icon: keyof typeof Icons;
  /** The page's core question (PRD §5.3), used as its description. */
  question: string;
  shortcut?: [string, string];
  /** The `?tab=` ids the page answers to, in order (PRD §5.1): real tabs on Settings/Advanced, panel anchors elsewhere (`customers/kit/tabs.tsx`). */
  tabs: string[];
}

export const FOUNDER_SECTIONS: Record<FounderSectionId, FounderSection> = {
  overview: { id: 'overview', title: 'Overview', shortTitle: 'Overview', url: '/founder', icon: 'dashboard', question: 'What changed, what needs me, and what is my next step.', shortcut: ['o', 'o'], tabs: ['today', 'follow-ups', 'reports'] },
  customers: { id: 'customers', title: 'Customers', shortTitle: 'Customers', url: '/founder/customers', icon: 'teams', question: 'Which customers are high value, high cost, near their quota or inactive.', shortcut: ['c', 'c'], tabs: ['list', 'workspaces'] },
  revenue: { id: 'revenue', title: 'Revenue & billing', shortTitle: 'Revenue', url: '/founder/revenue', icon: 'billing', question: 'How revenue moved, how much cash arrived, who upgraded, churned or failed to pay.', shortcut: ['r', 'r'], tabs: ['mrr-bridge', 'cash', 'subscriptions', 'payments', 'refunds'] },
  product: { id: 'product', title: 'Product', shortTitle: 'Product', url: '/founder/product', icon: 'sparkles', question: 'Whether people get value, and which features are really reused.', shortcut: ['p', 'p'], tabs: ['active', 'publishing', 'time-back', 'features', 'activation', 'retention'] },
  'ai-cost': { id: 'ai-cost', title: 'AI & API cost', shortTitle: 'AI cost', url: '/founder/ai-cost', icon: 'bolt', question: 'Where the money goes, what a useful result costs, and which plans or customers run at a loss.', shortcut: ['a', 'a'], tabs: ['budget', 'coverage', 'by-feature', 'by-model', 'by-plan', 'reconcile'] },
  operations: { id: 'operations', title: 'Operations', shortTitle: 'Operations', url: '/founder/operations', icon: 'listCheck', question: 'What broke, how many people it touched, for how long, and whether it recovered.', shortcut: ['g', 'o'], tabs: ['incidents', 'health', 'publishing', 'notifications', 'calls', 'connections'] },
  support: { id: 'support', title: 'Support', shortTitle: 'Support', url: '/founder/support', icon: 'inbox', question: 'How much is waiting, how long it has waited, and which questions repeat.', shortcut: ['s', 's'], tabs: ['inbox', 'aging', 'status'] },
  settings: { id: 'settings', title: 'Settings', shortTitle: 'Settings', url: '/founder/settings', icon: 'settings', question: 'Contact policy, report schedules, notifications, budgets and operators.', tabs: ['contact', 'reports', 'notifications'] },
  advanced: { id: 'advanced', title: 'Advanced', shortTitle: 'Advanced', url: '/founder/advanced', icon: 'terminal', question: 'Data health, receipts, audit, engineering checks and investigations.', tabs: ['audit', 'receipts', 'data-health'] }
};

export interface FounderNavGroup {
  label: string;
  items: FounderSectionId[];
}

export const FOUNDER_NAV_GROUPS: FounderNavGroup[] = [
  { label: 'Business', items: ['overview', 'customers', 'revenue', 'product'] },
  { label: 'Cost & reliability', items: ['ai-cost', 'operations', 'support'] },
  { label: 'Founder', items: ['settings', 'advanced'] }
];

/** Phone tab bar (PRD §5.2): Overview, Customers, AI cost, Operations, then the Rafii slot the bar adds itself. */
export const FOUNDER_TAB_BAR: FounderSectionId[] = ['overview', 'customers', 'ai-cost', 'operations'];

export interface FounderRedirect {
  source: string;
  destination: string;
  permanent: false;
}

/**
 * The retired preview's `/control/*` addresses and the two merged sections (PRD §5.1). Mirrored verbatim in
 * `web/next.config.ts` (which cannot import TypeScript); the nav test keeps the two lists identical.
 */
export const FOUNDER_REDIRECTS: FounderRedirect[] = [
  { source: '/control/command', destination: '/founder', permanent: false },
  { source: '/control/billing', destination: '/founder/revenue', permanent: false },
  { source: '/control/connections', destination: '/founder/operations?tab=connections', permanent: false },
  { source: '/control/workspaces', destination: '/founder/customers?tab=workspaces', permanent: false },
  { source: '/control/:tab(evidence|engineering|founder|audit|infrastructure)', destination: '/founder/advanced?tab=:tab', permanent: false },
  { source: '/control', destination: '/founder', permanent: false },
  { source: '/control/:section', destination: '/founder/:section', permanent: false },
  { source: '/founder/connections', destination: '/founder/operations?tab=connections', permanent: false },
  { source: '/founder/workspaces', destination: '/founder/customers?tab=workspaces', permanent: false }
];

export function isFounderSectionId(value: unknown): value is FounderSectionId {
  return typeof value === 'string' && (FOUNDER_SECTION_IDS as readonly string[]).includes(value);
}

export function isRoutedSectionId(value: unknown): value is RoutedSectionId {
  return isFounderSectionId(value) && value !== 'overview';
}

/** A founder link that keeps the data mode: `?mode=demo` travels, Live (the default) adds nothing. */
export function founderHref(section: FounderSectionId, mode: 'live' | 'demo' = 'live', params: Record<string, string | undefined> = {}): string {
  const search = new URLSearchParams();
  if (mode === 'demo') search.set('mode', 'demo');
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') search.set(key, value);
  const query = search.toString();
  return `${FOUNDER_SECTIONS[section].url}${query ? `?${query}` : ''}`;
}

export function sectionForPathname(pathname: string): FounderSectionId | null {
  const path = pathname.split(/[?#]/)[0];
  if (path === '/founder' || path === '/founder/') return 'overview';
  const segment = path.split('/')[2];
  return isFounderSectionId(segment) ? segment : null;
}

export function isActiveFounderPath(pathname: string, url: string): boolean {
  if (url === '/founder') return pathname === '/founder' || pathname === '/founder/';
  return pathname === url || pathname.startsWith(`${url}/`);
}

export interface FounderBreadcrumb {
  title: string;
  link: string;
}

/** `Founder › Section`; the Overview is the root crumb alone. Record ids never appear as crumbs. */
export function founderBreadcrumbs(pathname: string): FounderBreadcrumb[] {
  const section = sectionForPathname(pathname);
  const root: FounderBreadcrumb = { title: 'Founder', link: '/founder' };
  if (!section || section === 'overview') return [root];
  return [root, { title: FOUNDER_SECTIONS[section].title, link: FOUNDER_SECTIONS[section].url }];
}
