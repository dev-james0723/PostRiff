/**
 * Pure `?tab=` resolution for the founder pages (no React): the ids a page answers to come from
 * `config/founder-nav.ts`; older or alternate spellings (the retired `/control/*` redirects, the Overview's earlier
 * hrefs) resolve through the aliases. An unknown value resolves to nothing, never silently to another tab.
 */
export const TAB_ALIASES: Record<string, string> = {
  sources: 'data-health',
  infrastructure: 'data-health',
  evidence: 'receipts',
  engineering: 'audit',
  founder: 'audit',
  failures: 'payments',
  mrr: 'mrr-bridge',
  requests: 'inbox',
  heartbeat: 'health'
};

export function resolveTab(raw: string | null | undefined, tabs: readonly string[], aliases: Record<string, string> = TAB_ALIASES): string | null {
  if (!raw) return null;
  const candidate = tabs.includes(raw) ? raw : aliases[raw];
  return candidate && tabs.includes(candidate) ? candidate : null;
}

export function tabAnchorId(section: string, tab: string): string {
  return `founder-${section}-${tab}`;
}
