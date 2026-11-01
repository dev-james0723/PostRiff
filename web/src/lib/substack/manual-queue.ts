/** Read-only projection of persisted Substack handoffs. These are never provider jobs. */
export interface SubstackManualEntry {
  id: string;
  draftId: string;
  connectionId: string;
  title: string;
  publicationUrl: string;
  status: 'pending_manual' | 'handoff_prepared';
  scheduledFor: string | null;
  atSeconds: number | null;
  due: boolean;
  href: string;
  autoPublished: false;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record).filter((item): item is Record<string, unknown> => item !== null) : [];
}

function id(value: unknown, prefix: string): value is string {
  return typeof value === 'string' && new RegExp(`^${prefix}_[0-9a-f]{32}$`).test(value);
}

function publication(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 300) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port || url.search || url.hash || !['', '/'].includes(url.pathname)) return null;
    if (!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.substack\.com$/.test(url.hostname)) return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function substackDraftHref(draftId: string): string {
  return id(draftId, 'sd') ? `/app/channels?connect=substack&substackDraft=${encodeURIComponent(draftId)}` : '/app/channels?connect=substack';
}

/**
 * The feature flag comes from the current workspace's server Channels response.
 * Retained state alone must not make a rolled-back feature visible. The explicit
 * workspace check also prevents a prior workspace's cached snapshot appearing.
 * Stored hash equality is a display filter, never permission to approve or publish.
 */
export function substackManualEntries(state: unknown, workspaceId: string, enabled: boolean, nowSeconds: number): SubstackManualEntry[] {
  const root = record(state);
  const workspace = record(root?.workspace);
  if (!enabled || !workspaceId || workspace?.id !== workspaceId || workspace.sample || root?.accountDeletion || root?.accountBlock || !Number.isFinite(nowSeconds)) return [];
  const section = record(root?.substack);
  if (section?.version !== 1) return [];
  const connections = new Map(records(section.connections).map((item) => [item.id, item]));
  const drafts = new Map(records(section.drafts).map((item) => [item.id, item]));
  const entries: SubstackManualEntry[] = [];
  const seen = new Set<string>();
  for (const job of records(section.queue)) {
    if (!id(job.id, 'sq') || !id(job.draftId, 'sd') || !id(job.connectionId, 'sc') || seen.has(job.id)) continue;
    if (job.kind !== 'manual_handoff' || job.autoPublished !== false || !['pending_manual', 'handoff_prepared'].includes(String(job.status))) continue;
    const draft = drafts.get(job.draftId);
    const connection = connections.get(job.connectionId);
    if (!draft || !connection || draft.connectionId !== job.connectionId || connection.mode !== 'public_feed' || connection.status !== 'feed_added') continue;
    if (typeof job.contentHash !== 'string' || !/^[0-9a-f]{64}$/.test(job.contentHash) || draft.contentHash !== job.contentHash || draft.approvedHash !== job.contentHash) continue;
    if ((job.status === 'pending_manual' && draft.status !== 'approved') || (job.status === 'handoff_prepared' && draft.status !== 'handoff_ready')) continue;
    if (draft.scheduledFor !== job.scheduledFor) continue;
    const publicationUrl = publication(connection.publicationUrl);
    if (!publicationUrl) continue;
    const target = job.scheduledFor;
    if (target !== null && (typeof target !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/.test(target))) continue;
    const atSeconds = typeof target === 'string' ? Date.parse(target) / 1000 : null;
    if (atSeconds !== null && !Number.isFinite(atSeconds)) continue;
    seen.add(job.id);
    entries.push({
      id: job.id, draftId: job.draftId, connectionId: job.connectionId,
      title: typeof draft.title === 'string' && draft.title.trim() ? draft.title.trim().slice(0, 300) : 'Substack Note',
      publicationUrl, status: job.status as SubstackManualEntry['status'], scheduledFor: target as string | null,
      atSeconds, due: job.status === 'pending_manual' && (atSeconds === null || atSeconds <= nowSeconds),
      href: substackDraftHref(job.draftId), autoPublished: false
    });
  }
  return entries.toSorted((a, b) => Number(b.due) - Number(a.due) || (a.atSeconds ?? 0) - (b.atSeconds ?? 0) || a.id.localeCompare(b.id));
}

export function substackManualLabel(entry: SubstackManualEntry): string {
  if (entry.status === 'handoff_prepared') return 'Handoff prepared';
  return entry.due ? 'Manual handoff due' : 'Manual handoff target';
}
