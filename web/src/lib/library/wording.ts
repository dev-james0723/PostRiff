/**
 * Plain-language wording for the Library (UI spec §3, §5, §6): counts, scope, search coverage, storage, locators,
 * match reasons, annotation origins, purposes and document-cover labels.
 *
 * No '@/' imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

/* --- counts ---------------------------------------------------------------------------------------------------- */

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return Math.abs(count) === 1 ? singular : pluralForm;
}

export function formatCount(count: number): string {
  return Number.isFinite(count) ? Math.round(count).toLocaleString('en-US') : '0';
}

/** "1 item", "0 items", "2 matches" — always the right singular or plural. */
export function countLabel(count: number, singular = 'item', pluralForm?: string): string {
  return `${formatCount(count)} ${plural(count, singular, pluralForm)}`;
}

/**
 * A total the server stated, or the full set once every page has loaded. While more pages exist and the server gave
 * no total, the label says how many are loaded instead of passing the loaded cards off as the Library's size.
 */
export function totalLabel({
  total,
  loaded,
  complete,
  singular = 'item',
  pluralForm
}: {
  total?: number | null;
  loaded: number;
  complete: boolean;
  singular?: string;
  pluralForm?: string;
}): string {
  if (typeof total === 'number' && Number.isFinite(total) && total >= 0) return countLabel(total, singular, pluralForm);
  if (complete) return countLabel(loaded, singular, pluralForm);
  return `${formatCount(loaded)} loaded · more available`;
}

/** The search's own hit count: exact, or a lower bound when a bounded ranking stage reached its limit. */
export function hitTotalLabel(totalHits: { value: number; relation: 'eq' | 'gte' } | null | undefined): string | null {
  if (!totalHits || !Number.isFinite(totalHits.value) || totalHits.value < 0) return null;
  return totalHits.relation === 'gte' ? `${formatCount(totalHits.value)}+ matching items` : countLabel(totalHits.value, 'matching item');
}

/* --- scope ----------------------------------------------------------------------------------------------------- */

export type ScopeKind = 'workspace' | 'collection' | 'selection';

export interface ScopeDescription {
  kind: ScopeKind;
  collectionName?: string | null;
  selectedCount?: number;
}

/** The search scope in ordinary words (UI spec §5): shown beside the search field at every width. */
export function scopeLabel(scope: ScopeDescription): string {
  if (scope.kind === 'collection') return 'This collection';
  if (scope.kind === 'selection') return `Selected ${countLabel(scope.selectedCount ?? 0)}`;
  return 'Entire permitted Library';
}

/** The longer form, for a tooltip or the scope menu. */
export function scopeDetail(scope: ScopeDescription): string {
  if (scope.kind === 'collection' && scope.collectionName) return `This collection: ${scope.collectionName}`;
  return scopeLabel(scope);
}

/* --- coverage -------------------------------------------------------------------------------------------------- */

export interface CoverageLike {
  accessibleAssetCount: number;
  indexedAssetCount: number;
  pendingAssetCount: number;
  failedAssetCount: number;
  partial: boolean;
}

/** "Searched 1,240 of 1,252 permitted items · 12 still being indexed": counts from the server, never from cards. */
export function coverageLabel(coverage: CoverageLike): string {
  const parts = [`Searched ${formatCount(coverage.indexedAssetCount)} of ${countLabel(coverage.accessibleAssetCount, 'permitted item')}`];
  if (coverage.pendingAssetCount > 0) parts.push(`${formatCount(coverage.pendingAssetCount)} still being indexed`);
  if (coverage.failedAssetCount > 0) parts.push(`${formatCount(coverage.failedAssetCount)} couldn’t be indexed`);
  if (coverage.partial && coverage.pendingAssetCount <= 0 && coverage.failedAssetCount <= 0) parts.push('results may be incomplete');
  return parts.join(' · ');
}

/** Processing among the items this page has loaded, said as such. */
export function processingLabel(count: number): string | null {
  return count > 0 ? `${formatCount(count)} still being indexed` : null;
}

/* --- storage --------------------------------------------------------------------------------------------------- */

/** Warn from 85 % of the server's configured limit; below that the indicator stays quiet. */
export const STORAGE_NEAR_RATIO = 0.85;

export function formatStorageBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return 'unknown';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(value) : value >= 10 ? Math.round(value) : Math.round(value * 10) / 10} ${units[unit]}`;
}

export interface StorageNotice {
  level: 'unknown' | 'ok' | 'near' | 'full';
  ratio: number | null;
  /** The quiet indicator text. */
  label: string;
  /** Only near or at the limit. */
  warning: string | null;
}

export function storageNotice(usedBytes: number | null | undefined, limitBytes: number | null | undefined): StorageNotice {
  if (typeof usedBytes !== 'number' || typeof limitBytes !== 'number' || !Number.isFinite(usedBytes) || !Number.isFinite(limitBytes) || limitBytes <= 0) {
    return { level: 'unknown', ratio: null, label: 'Storage use unknown', warning: null };
  }
  const ratio = Math.max(0, usedBytes / limitBytes);
  const label = `${formatStorageBytes(usedBytes)} of ${formatStorageBytes(limitBytes)} used`;
  if (ratio >= 1) {
    return { level: 'full', ratio, label, warning: 'Library storage is full. New uploads will be refused until you delete items or the limit is raised.' };
  }
  if (ratio >= STORAGE_NEAR_RATIO) {
    return { level: 'near', ratio, label, warning: `Library storage is almost full: ${label}.` };
  }
  return { level: 'ok', ratio, label, warning: null };
}

/* --- locators and match reasons ---------------------------------------------------------------------------------- */

/** 83 000 ms → "1:23"; 3 723 000 ms → "1:02:03". */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor((Number.isFinite(ms) ? ms : 0) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export type LocatorLike =
  | { kind: 'page'; page: number; section?: string }
  | { kind: 'time'; startMs: number; endMs: number }
  | { kind: 'text'; start: number; end: number }
  | { kind: 'slide'; slide: number }
  | { kind: 'sheet'; sheetName: string; cellRange: string }
  | { kind: 'imageRegion'; frameTimeMs?: number };

/** A readable label when the server sent a locator without its own label. */
export function locatorLabel(locator: LocatorLike | null | undefined): string {
  if (!locator) return '';
  switch (locator.kind) {
    case 'page':
      return `Page ${locator.page}${locator.section ? ` · ${locator.section}` : ''}`;
    case 'time':
      return `${formatClock(locator.startMs)}–${formatClock(locator.endMs)}`;
    case 'text':
      return `Characters ${locator.start + 1}–${locator.end}`;
    case 'slide':
      return `Slide ${locator.slide}`;
    case 'sheet':
      return `${locator.sheetName} · ${locator.cellRange}`;
    case 'imageRegion':
      return typeof locator.frameTimeMs === 'number' ? `Frame at ${formatClock(locator.frameTimeMs)}` : 'Part of the image';
    default:
      return '';
  }
}

const MATCH_REASON: Record<string, string> = {
  exact: 'Exact match',
  title: 'Title',
  filename: 'File name',
  hash: 'Content fingerprint',
  id: 'Item id',
  dimensions: 'Dimensions',
  phrase: 'Exact phrase',
  lexical: 'Words in the text',
  semantic: 'Similar meaning',
  visual: 'Looks similar',
  tag: 'Tag'
};

export function matchReasonLabel(reason: { kind: string; detail?: string | null }): string {
  const base = MATCH_REASON[reason.kind] ?? 'Match';
  return reason.detail ? `${base}: ${reason.detail}` : base;
}

/** "Matched: Exact phrase · Title". No scores or percentages: a reason is a reason, not a confidence. */
export function matchSummary(reasons: readonly { kind: string; detail?: string | null }[] | null | undefined): string {
  const labels = [...new Set((reasons ?? []).map((reason) => MATCH_REASON[reason.kind] ?? 'Match'))];
  return labels.length ? `Matched: ${labels.join(' · ')}` : '';
}

/* --- provenance and purposes ------------------------------------------------------------------------------------- */

export type AnnotationOrigin = 'extracted' | 'ai_suggested' | 'user_confirmed';

/** Origin in words (and an icon in the component), never colour alone. */
export const ORIGIN_LABEL: Record<AnnotationOrigin, string> = {
  extracted: 'Extracted',
  ai_suggested: 'AI suggestion',
  user_confirmed: 'Confirmed by you'
};

export function originLabel(origin: string | null | undefined): string {
  return ORIGIN_LABEL[origin as AnnotationOrigin] ?? 'Extracted';
}

const PURPOSE_LABEL: Record<string, string> = {
  browse: 'Find and open it in Library',
  answer: 'Answer questions from it',
  draft_evidence: 'Cite it as evidence in drafts',
  voice: 'Learn your writing voice from it',
  memory: 'Keep it in long-term Memory',
  public_use: 'Use it in public posts'
};

const PURPOSE_ORDER = ['browse', 'answer', 'draft_evidence', 'voice', 'memory', 'public_use'];

const REASON_TEXT: Record<string, string> = {
  unavailable: 'this item is unavailable',
  not_granted: 'needs your approval first',
  needs_grant: 'needs your approval first',
  needs_review: 'waiting for source review',
  revoked: 'permission was withdrawn',
  storage_only: 'kept as a stored file only',
  not_author: 'only material you wrote can teach your voice'
};

export function purposeLabel(purpose: string): string {
  return PURPOSE_LABEL[purpose] ?? purpose.replaceAll('_', ' ');
}

export function purposeLines(status: Record<string, { allowed: boolean; reason?: string | null }> | null | undefined): { purpose: string; label: string; allowed: boolean; detail: string }[] {
  if (!status) return [];
  return PURPOSE_ORDER.filter((purpose) => purpose in status).map((purpose) => {
    const entry = status[purpose];
    const reason = entry.reason ? (REASON_TEXT[entry.reason] ?? 'needs your approval first') : null;
    return {
      purpose,
      label: purposeLabel(purpose),
      allowed: Boolean(entry.allowed),
      detail: entry.allowed ? 'Allowed' : `Not allowed${reason ? ` · ${reason}` : ''}`
    };
  });
}

/* --- document covers ------------------------------------------------------------------------------------------- */

/**
 * What a document cover may claim (UI spec §3, A016). Only a genuine rendition of the file may say "first page";
 * a cover built from extracted text says so; an AI summary is never passed off as the document's own words.
 */
export function documentCoverLabel({
  extension,
  hasExtractedText,
  hasSummary,
  genuineRendition
}: {
  extension: string;
  hasExtractedText: boolean;
  hasSummary: boolean;
  genuineRendition: boolean;
}): string {
  const ext = (extension || 'file').toUpperCase();
  if (genuineRendition) return `${ext} · FIRST PAGE`;
  if (hasExtractedText) return 'Extracted text preview';
  if (hasSummary) return 'AI summary preview';
  return `${ext} file`;
}

/** The matching phrase for a card's accessible name. */
export function documentPreviewPhrase(input: Parameters<typeof documentCoverLabel>[0]): string {
  if (input.genuineRendition) return 'first-page preview';
  if (input.hasExtractedText) return 'extracted text preview';
  if (input.hasSummary) return 'AI summary preview';
  return `${(input.extension || 'file').toUpperCase()} file`;
}

/* --- audio ------------------------------------------------------------------------------------------------------- */

/**
 * Real amplitude peaks (understanding card `media.peaks`) folded into `count` bars between 0 and 1. Anything that is
 * not a usable peak series returns null, and the cover shows a neutral audio symbol instead of a pretend waveform.
 */
export function peaksToBars(peaks: unknown, count: number): number[] | null {
  if (!Array.isArray(peaks) || peaks.length < 2 || !Number.isInteger(count) || count < 1) return null;
  const values = peaks.map((value) => Math.abs(Number(value))).filter((value) => Number.isFinite(value));
  if (values.length < 2) return null;
  const max = Math.max(...values);
  if (!(max > 0)) return null;
  const bars: number[] = [];
  for (let index = 0; index < count; index += 1) {
    const start = Math.floor((index * values.length) / count);
    const end = Math.max(start + 1, Math.floor(((index + 1) * values.length) / count));
    let peak = 0;
    for (let cursor = start; cursor < end && cursor < values.length; cursor += 1) peak = Math.max(peak, values[cursor]);
    bars.push(Math.round((peak / max) * 1000) / 1000);
  }
  return bars;
}

export type MomentCheck = { ok: true; startMs: number; endMs: number } | { ok: false; reason: string };

/** A saved moment is a real, in-bounds interval of the recording (A021). */
export function momentInterval(startSeconds: number | null | undefined, endSeconds: number | null | undefined, durationSeconds?: number | null): MomentCheck {
  if (typeof startSeconds !== 'number' || typeof endSeconds !== 'number' || !Number.isFinite(startSeconds) || !Number.isFinite(endSeconds)) {
    return { ok: false, reason: 'Set a start and an end first.' };
  }
  const startMs = Math.round(startSeconds * 1000);
  const endMs = Math.round(endSeconds * 1000);
  if (startMs < 0) return { ok: false, reason: 'The moment can’t start before the recording.' };
  if (endMs <= startMs) return { ok: false, reason: 'The moment must end after it starts.' };
  if (typeof durationSeconds === 'number' && Number.isFinite(durationSeconds) && durationSeconds > 0 && endMs > Math.round(durationSeconds * 1000)) {
    return { ok: false, reason: 'The moment ends after the recording.' };
  }
  return { ok: true, startMs, endMs };
}
