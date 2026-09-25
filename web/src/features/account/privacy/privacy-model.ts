import { DONE, ENDED, IN_FLIGHT } from '@/lib/jobs';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { DataRequest, SnapshotSource, SnapshotState } from '@/lib/api/types';

/**
 * Everything the Privacy & data page derives from API data, plus its labels. Counts are only ever
 * computed from a snapshot that loaded; a caller with no snapshot shows "Unavailable", never 0.
 */

export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

/* ---------- publication jobs (mirror of `src/postriff_phase2/store.py` TERMINAL / IN_FLIGHT) ---------- */

export const TERMINAL_JOB_STATES: ReadonlySet<string> = new Set([...DONE, ...ENDED]);
/** Already handed to a platform (or unsure whether it was). Deletion refuses while any job is here (`hosted.py` delete_account). */
export const IN_FLIGHT_JOB_STATES: ReadonlySet<string> = IN_FLIGHT;

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
    linkedAccounts: channels.filter((channel) => channel.revoked !== true).length
  };
}

/* ---------- retraction ---------- */

export { activeSources, draftsUsing, isIdeaSource, retractionImpact, retractionLines, type RetractionImpact } from '@/lib/sources';

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

/** Completed requests include their completion timestamp. */
export function completedAt(request: DataRequest): number | null {
  const value = request.completedAt;
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
  time_back: 'Time back estimates',
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

export { needsFreshSignIn } from '@/lib/auth/step-up';
