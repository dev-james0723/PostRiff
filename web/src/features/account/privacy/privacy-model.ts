import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { DataRequest, SnapshotSource, SnapshotState, SnapshotVariant } from '@/lib/api/types';

/**
 * Everything the Privacy & data page derives from API data, plus its labels. Counts are only ever
 * computed from a snapshot that loaded; a caller with no snapshot shows "Unavailable", never 0.
 */

export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/* ---------- publication jobs (mirror of `src/postriff_phase2/store.py` TERMINAL / IN_FLIGHT) ---------- */

export const TERMINAL_JOB_STATES: ReadonlySet<string> = new Set(['verified', 'failed', 'canceled']);
/** Already handed to a platform (or unsure whether it was). Deletion refuses while any job is here (`hosted.py` delete_account). */
export const IN_FLIGHT_JOB_STATES: ReadonlySet<string> = new Set(['submitting', 'provider_accepted', 'published', 'uncertain']);

export interface JobCounts {
  /** Sent, or possibly sent, and not yet confirmed or marked failed. Blocks deletion. */
  inFlight: number;
  /** Approved but not sent yet (scheduled, held). Deleting the workspace removes them unpublished. */
  waiting: number;
}

export function jobCounts(state: SnapshotState): JobCounts {
  let inFlight = 0;
  let waiting = 0;
  for (const job of state.phase2?.jobs ?? []) {
    if (IN_FLIGHT_JOB_STATES.has(job.state)) inFlight += 1;
    else if (!TERMINAL_JOB_STATES.has(job.state)) waiting += 1;
  }
  return { inFlight, waiting };
}

/* ---------- what the workspace holds ---------- */

export interface Holdings {
  sources: number;
  withdrawnSources: number;
  drafts: number;
  blockedDrafts: number;
  media: number;
  /** Accounts not disconnected: a disconnect flags the record `revoked` and wipes its token. */
  linkedAccounts: number;
}

export function holdingsFrom(state: SnapshotState): Holdings {
  const sources = state.sources ?? [];
  const variants = state.variants ?? [];
  const channels = state.phase2?.channels ?? [];
  return {
    sources: sources.filter((source) => source.active).length,
    withdrawnSources: sources.filter((source) => !source.active).length,
    drafts: variants.length,
    blockedDrafts: variants.filter((variant) => variant.blockedByRetraction).length,
    media: (state.phase2?.assets ?? []).filter((asset) => !asset.deleted).length,
    linkedAccounts: channels.filter((channel) => (channel as { revoked?: boolean }).revoked !== true).length
  };
}

/* ---------- retraction ---------- */

export function activeSources(state: SnapshotState): SnapshotSource[] {
  return (state.sources ?? []).filter((source) => source.active);
}

export function draftsUsing(state: SnapshotState, sourceId: string): SnapshotVariant[] {
  return (state.variants ?? []).filter((variant) => (variant.sourceIds ?? []).includes(sourceId));
}

/** `retract_source` resets the brief's idea when the retracted source is the one the idea came from (`domain.py`). */
export function isIdeaSource(state: SnapshotState, sourceId: string) {
  const brief = state.brief as { ideaSourceId?: string } | undefined;
  return brief?.ideaSourceId === sourceId;
}

/** Job states `store.py` invalidate() re-checks after every command; a job whose approval no longer matches is held. */
const HOLDABLE_JOB_STATES: ReadonlySet<string> = new Set(['scheduled', 'approved', 'claimed']);

/**
 * What a retraction does, counted from the snapshot it will be checked against (`expectedRevision`).
 *
 * `retract_source` blocks the drafts that list the source, then bumps the brief revision and runs `_mark_stale`
 * (`postriff_alpha/domain.py`). That second step reaches the whole workspace: every draft gets `needsReview` and
 * loses its proposed update, and review and scheduling refuse any draft whose `briefRevision` is behind
 * (`store.py` variant_review and scheduling) until it is drafted again. Approvals carry the brief revision too, so
 * `invalidate` holds every scheduled post.
 */
export interface RetractionImpact {
  /** Drafts that list this source. */
  using: number;
  /** Of those, the ones not blocked yet. */
  newlyBlocked: number;
  /** Every draft in the workspace, whether or not it used the source. */
  allDrafts: number;
  /** Replacement drafts waiting to be accepted; they are discarded. */
  pendingUpdates: number;
  /** Posts waiting in the Queue (scheduled, approved or claimed); they are held until approved again. */
  heldPosts: number;
  /** The current idea came from this source and is reset. */
  resetsIdea: boolean;
}

export function retractionImpact(state: SnapshotState, sourceId: string): RetractionImpact {
  const variants = state.variants ?? [];
  const using = draftsUsing(state, sourceId);
  return {
    using: using.length,
    newlyBlocked: using.filter((variant) => !variant.blockedByRetraction).length,
    allDrafts: variants.length,
    pendingUpdates: variants.filter((variant) => variant.proposedUpdate != null).length,
    heldPosts: (state.phase2?.jobs ?? []).filter((job) => HOLDABLE_JOB_STATES.has(job.state)).length,
    resetsIdea: isIdeaSource(state, sourceId)
  };
}

/** One sentence per consequence, in the order they matter. Shared by the preview list and the success toast. */
export function retractionLines(impact: RetractionImpact): string[] {
  const lines: string[] = [];
  const { using, newlyBlocked, allDrafts, pendingUpdates, heldPosts } = impact;
  const alreadyBlocked = using - newlyBlocked;
  if (using === 0) lines.push('No draft uses this source, so none is blocked by it.');
  else if (newlyBlocked === 0)
    lines.push(
      `${using === 1 ? 'The draft that uses this source is already blocked and stays' : `All ${using} drafts that use this source are already blocked and stay`} blocked until drafted again.`
    );
  else if (alreadyBlocked > 0)
    lines.push(
      `${plural(using, 'draft')} ${using === 1 ? 'uses' : 'use'} this source: ${newlyBlocked} will be newly blocked (${alreadyBlocked} already ${alreadyBlocked === 1 ? 'is' : 'are'}) until drafted again. They keep their text.`
    );
  else
    lines.push(
      `${plural(using, 'draft')} ${using === 1 ? 'uses' : 'use'} this source and will be blocked until drafted again. ${using === 1 ? 'It keeps its' : 'They keep their'} text.`
    );
  const others = allDrafts - using;
  if (allDrafts === 1)
    lines.push(`This workspace's only draft must be drafted again before it can be reviewed or scheduled${using === 0 ? ', even though it does not use this source' : ''}.`);
  else if (allDrafts > 1)
    lines.push(
      `${allDrafts === 2 ? 'Both' : `All ${allDrafts}`} drafts in this workspace must be drafted again before they can be reviewed or scheduled${
        using === 0 ? ', even though none of them uses this source' : others > 0 ? `, including ${others} that ${others === 1 ? 'does' : 'do'} not use it` : ''
      }.`
    );
  if (pendingUpdates > 0) lines.push(`${plural(pendingUpdates, 'proposed update')} waiting to be accepted will be discarded.`);
  if (heldPosts > 0) lines.push(`${plural(heldPosts, 'post')} waiting in the Queue will be held until approved again.`);
  return lines;
}

/** Same words as the Ideas page (`features/ideas/use-sources.ts` KIND_LABEL). */
const SOURCE_KIND_LABEL: Record<string, string> = { idea: 'Idea', text: 'Text', document: 'File', link: 'Link', sample: 'Sample' };

export function sourceKindLabel(kind: string) {
  return SOURCE_KIND_LABEL[kind] ?? kind.replace(/[_-]/g, ' ');
}

export function sourceName(source: SnapshotSource) {
  return source.title?.trim() || `${sourceKindLabel(source.kind)} source`;
}

/* ---------- data requests ---------- */

const REQUEST_LABEL: Record<string, string> = {
  export: 'Workspace export',
  diagnostics: 'Diagnostics package created',
  retraction: 'Source retracted',
  deletion: 'Account deletion requested'
};

export function requestLabel(request: Pick<DataRequest, 'kind'>) {
  return REQUEST_LABEL[request.kind] ?? request.kind;
}

export function requestStatus(status: string): { label: string; tone: AnimatedBadgeStatus } {
  switch (status) {
    case 'completed':
      return { label: 'Completed', tone: 'success' };
    case 'requested':
      return { label: 'Requested', tone: 'warning' };
    case 'failed':
      return { label: 'Failed', tone: 'danger' };
    default:
      return { label: status, tone: 'neutral' };
  }
}

/** The list endpoint returns `completedAt` (`privacy.py` DataRequests.list); the shared type does not declare it yet. */
export function completedAt(request: DataRequest): number | null {
  const value = (request as { completedAt?: number | null }).completedAt;
  return typeof value === 'number' ? value : null;
}

const DIAGNOSTIC_FIELD_LABEL: Record<string, string> = {
  sources: 'sources',
  variants: 'drafts',
  channels: 'linked accounts',
  jobs: 'publications',
  assets: 'media files'
};

export function diagnosticFieldLabel(field: string) {
  return DIAGNOSTIC_FIELD_LABEL[field] ?? field.replace(/_/g, ' ');
}

export interface ExportReceipt {
  bytes?: number;
  sha256?: string;
}

export function exportReceipt(request: DataRequest): ExportReceipt {
  const receipt = (request.receipt ?? {}) as { bytes?: unknown; sha256?: unknown };
  return {
    bytes: typeof receipt.bytes === 'number' ? receipt.bytes : undefined,
    sha256: typeof receipt.sha256 === 'string' ? receipt.sha256 : undefined
  };
}

export function diagnosticFields(request: DataRequest): string[] {
  const fields = (request.receipt as { fields?: unknown } | undefined)?.fields;
  return Array.isArray(fields) ? fields.filter((field): field is string => typeof field === 'string') : [];
}

/* ---------- privacy notice ---------- */

/** Plain names for the notice's retention keys (`privacy.py` RETENTION_CLASSES), worded like the public pages. */
const RETENTION_LABEL: Record<string, string> = {
  drafts: 'Drafts and revision history',
  sources: 'Sources you add',
  generated_media: 'Generated media',
  provider_tokens: 'Account access tokens',
  account_pictures: 'Account profile pictures',
  approvals_receipts: 'Approval receipts',
  analytics_observations: 'Post metrics',
  audience_comments: 'Audience comments',
  logs_traces: 'Logs and traces',
  backups: 'Backups'
};

export function retentionLabel(key: string) {
  const label = RETENTION_LABEL[key];
  if (label) return label;
  const words = key.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Sentence case for the notice's short lowercase strings ("in use", "export your workspace"). */
export function sentence(text: string) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/* ---------- file fingerprints ---------- */

/** SHA-256 of the bytes the browser received, as lowercase hex. `null` where the browser cannot hash (no secure context). */
export async function sha256Hex(blob: Blob): Promise<string | null> {
  if (typeof crypto === 'undefined' || !crypto.subtle) return null;
  try {
    const hash = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
    return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('');
  } catch {
    // The file is already saved; a failed hash only means no fingerprint is shown.
    return null;
  }
}

/** "a1b2c3d4 e5f6…" groups keep a 64-character hash readable and wrap on a phone. */
export function groupHex(hex: string, size = 8) {
  return hex.match(new RegExp(`.{1,${size}}`, 'g'))?.join(' ') ?? hex;
}

/** Step-up and "not the owner" both answer 403; only the message tells them apart (`hosted.py` assert_fresh). */
export function needsFreshSignIn(error: { status?: number; message: string }) {
  return error.status === 403 && /sign in again/i.test(error.message);
}
