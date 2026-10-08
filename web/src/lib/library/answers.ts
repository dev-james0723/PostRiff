/**
 * Ask Library in plain words (answers.py, citations.py; PRD R08; A032–A036).
 *
 *   - every question names its scope: the whole permitted Library, a collection or the selected items;
 *   - answering needs an explicit `answer` purpose grant; AI summaries additionally need the owner's cloud/llm grant;
 *   - the answer text is built only from verified claims, quotations are labelled as quotations, and an abstention
 *     says so with the scope and what could not be read;
 *   - a citation opens its own (possibly older) version at its locator through a fresh viewer link, never a stored URL.
 *
 * No imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

export interface ScopeLike {
  kind: 'workspace' | 'collection' | 'selection';
  collectionId?: string;
  assetRefs?: { assetId: string; versionId: string; sha256: string }[];
}

/** POST answer body: the scope is always explicit. */
export function answerRequest<S extends ScopeLike>(question: string, scope: S) {
  return { question: question.trim(), search: { query: '', scope } };
}

export interface GrantLike {
  grantType: 'purpose' | 'processing';
  scopeKind: 'workspace' | 'asset' | 'collection';
  scopeKey: string;
  purpose: string | null;
  location: string | null;
  category: string | null;
}

/** Whether answers (quotations) and AI summaries are allowed for this scope by the grants that exist now. */
export function answerPermission(grants: readonly GrantLike[], scope: ScopeLike): { answers: boolean; summaries: boolean } {
  const covers = (grant: GrantLike) => grant.scopeKind === 'workspace' || (scope.kind === 'collection' && grant.scopeKind === 'collection' && grant.scopeKey === scope.collectionId);
  return {
    answers: grants.some((grant) => grant.grantType === 'purpose' && grant.purpose === 'answer' && covers(grant)),
    summaries: grants.some((grant) => grant.grantType === 'processing' && grant.location === 'cloud' && grant.category === 'llm' && covers(grant))
  };
}

export const ANSWER_GRANT = { grantType: 'purpose', scope: { kind: 'workspace' }, purpose: 'answer' } as const;
export const SUMMARY_GRANT = { grantType: 'processing', scope: { kind: 'workspace' }, location: 'cloud', category: 'llm' } as const;

export function answerModeLabel(mode: string | undefined): string {
  if (mode === 'llm') return 'What the sources say, summarised by AI and checked against exact quotations';
  if (mode === 'extractive') return 'Verbatim quotations from the sources (no AI summary)';
  return 'No answer';
}

export interface CoverageLike {
  scopeDescription: string;
  accessibleAssetCount: number;
  pendingAssetCount: number;
  failedAssetCount: number;
}

/** The abstention, said plainly with the scope and what could not be read. */
export function abstentionLines(result: { scope?: string; coverage: CoverageLike; scopeCoverage?: CoverageLike }): string[] {
  const coverage = result.coverage;
  const scope = result.scopeCoverage ?? coverage;
  const pending = Math.max(coverage.pendingAssetCount, scope.pendingAssetCount);
  const failed = Math.max(coverage.failedAssetCount, scope.failedAssetCount);
  const lines = ['The selected material doesn’t support an answer.', `Searched: ${result.scope || coverage.scopeDescription}.`];
  if (pending) lines.push(`${pending.toLocaleString('en-US')} ${pending === 1 ? 'item is' : 'items are'} still being processed and may help later.`);
  if (failed) lines.push(`${failed.toLocaleString('en-US')} ${failed === 1 ? 'item' : 'items'} could not be read fully.`);
  return lines;
}

export function supportLabel(claim: { support: string; kind?: string }): string {
  if (claim.kind === 'conflict' || claim.support === 'conflicting') return 'Sources disagree';
  if (claim.kind === 'quotation') return 'Quotation';
  if (claim.support === 'insufficient') return 'Not enough evidence';
  return 'Stated by the cited sources';
}

export interface CitedRef {
  assetRef: { assetId: string; versionId: string; sha256: string };
  segmentId?: string;
  locator?: Record<string, unknown> & { kind: string };
  quoteHash?: string;
  displayTitle?: string;
  excerpt?: string;
  locatorLabel?: string;
}

/** Only the identity fields travel back to the server (the viewer refuses anything else). */
export function sourceRefOnly(ref: CitedRef) {
  return {
    assetRef: { assetId: ref.assetRef.assetId, versionId: ref.assetRef.versionId, sha256: ref.assetRef.sha256 },
    ...(ref.segmentId ? { segmentId: ref.segmentId } : {}),
    ...(ref.locator ? { locator: ref.locator } : {}),
    ...(ref.quoteHash ? { quoteHash: ref.quoteHash } : {})
  };
}

/** A stable key to find a citation again from what a SourceCitation control reports (asset version + locator). */
export function citationKey(assetRef: { versionId: string; assetId: string }, locator: unknown): string {
  return `${assetRef.versionId || assetRef.assetId}|${locator ? canonical(locator) : ''}`;
}

/** JSON with sorted keys, so the same locator matches whatever order its fields arrived in. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).filter((key) => record[key] !== undefined).toSorted().map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export interface ViewerLike {
  isCurrentVersion: boolean;
  versionNo: number;
  mime?: string | null;
  kind?: string | null;
  locator: (Record<string, unknown> & { kind: string }) | null;
  target: { kind: 'signedUrl' | 'proxy'; url?: string; href?: string; expiresAt?: number };
}

/**
 * How to open one viewer response, right now. The link is used once and dropped; opening again asks the server again
 * (signed links last at most five minutes). An older cited version opens as itself, with the newer one only mentioned.
 */
export function viewerOpenPlan(viewer: ViewerLike, now: number = Date.now() / 1000) {
  const expired = typeof viewer.target.expiresAt === 'number' && viewer.target.expiresAt <= now;
  const locator = viewer.locator;
  const media = viewer.kind === 'audio' || viewer.kind === 'video' || /^(audio|video)\//.test(viewer.mime ?? '');
  const startAt = locator && locator.kind === 'time' && typeof locator.startMs === 'number' ? locator.startMs / 1000 : null;
  const page = locator && locator.kind === 'page' && typeof locator.page === 'number' ? locator.page : null;
  const pdf = (viewer.mime ?? '').toLowerCase() === 'application/pdf';
  const base = viewer.target.kind === 'signedUrl' ? viewer.target.url ?? null : null;
  return {
    expired,
    /** Signed private link (with a PDF page fragment when the citation names a page). */
    href: base && !expired ? `${base.split('#')[0]}${pdf && page ? `#page=${page}` : ''}` : null,
    /** Legacy photos: the authenticated media proxy, read through the app's own client. */
    proxy: viewer.target.kind === 'proxy',
    playFrom: media && base && !expired ? startAt ?? 0 : null,
    newerVersion: !viewer.isCurrentVersion,
    versionNote: viewer.isCurrentVersion ? null : `This citation points to version ${viewer.versionNo}. A newer version exists; this view stays on the cited version.`
  };
}
