/**
 * Version stacks, comparison and replacement in plain words (comparison.py, relations.py; PRD R10, D3; T06).
 *
 *   - a comparison says what the server could compare, and says "not supported" honestly for other pairs;
 *   - replacing a cited version is always one person's confirmed choice for one draft, source pack or post, never
 *     automatic, and approval of the old version never carries over;
 *   - near duplicates are suggestions: there is no merge or delete here.
 *
 * No imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

export interface RefLike {
  assetId: string;
  versionId: string;
  sha256: string;
}

export interface ComparisonLike {
  mode: 'text' | 'image' | 'media' | 'unsupported';
  supported: boolean;
  message?: string;
  text?: { summary: { added: number; removed: number; changed: number; unchanged: number }; available: boolean; truncated: boolean };
  image?: { sameDimensions: boolean | null };
  media?: { durationDeltaMs: number | null };
}

export const UNSUPPORTED_COMPARISON = 'Comparison of these two formats is not supported. Their details are compared below.';

function lines(count: number, word: string) {
  return `${count} ${count === 1 ? 'line' : 'lines'} ${word}`;
}

/** One honest line for the comparison. Unsupported pairs never claim differences. */
export function comparisonHeadline(result: ComparisonLike): { supported: boolean; line: string } {
  if (!result.supported || result.mode === 'unsupported') return { supported: false, line: result.message || UNSUPPORTED_COMPARISON };
  if (result.mode === 'text') {
    const summary = result.text?.summary;
    if (!summary || !result.text?.available) return { supported: true, line: result.message || 'Neither version has extracted text yet, so only their details are compared.' };
    const parts = [summary.added ? lines(summary.added, 'added') : null, summary.removed ? lines(summary.removed, 'removed') : null, summary.changed ? lines(summary.changed, 'changed') : null].filter(Boolean);
    return { supported: true, line: parts.length ? `${parts.join(' · ')}${result.text.truncated ? ' (long text compared up to a limit)' : ''}` : 'No text differences.' };
  }
  if (result.mode === 'image') {
    const same = result.image?.sameDimensions;
    return { supported: true, line: `Shown side by side${same === true ? ' · same dimensions' : same === false ? ' · different dimensions' : ''}. Rafii does not judge which is better.` };
  }
  const delta = result.media?.durationDeltaMs;
  if (typeof delta !== 'number') return { supported: true, line: 'Lengths compared where known; timed passages listed for each version.' };
  const seconds = Math.round(Math.abs(delta) / 1000);
  return { supported: true, line: delta === 0 ? 'Same length.' : `The newer version is ${seconds} s ${delta > 0 ? 'longer' : 'shorter'}.` };
}

export interface DiffLineLike {
  text: string;
  locator?: unknown;
}

export type DiffHunkLike = { op: 'equal'; count: number } | { op: 'replace' | 'delete' | 'insert'; left: DiffLineLike[]; right: DiffLineLike[]; clipped?: boolean };

export type DiffRow = { type: 'same'; count: number } | { type: 'removed' | 'added'; text: string; locator?: unknown } | { type: 'clipped' };

/** Hunks as rows to read top to bottom: unchanged runs collapsed, removed lines then added lines. */
export function diffRows(hunks: readonly DiffHunkLike[]): DiffRow[] {
  const rows: DiffRow[] = [];
  for (const hunk of hunks) {
    if (hunk.op === 'equal') {
      rows.push({ type: 'same', count: hunk.count });
      continue;
    }
    for (const line of hunk.left) rows.push({ type: 'removed', text: line.text, locator: line.locator });
    for (const line of hunk.right) rows.push({ type: 'added', text: line.text, locator: line.locator });
    if (hunk.clipped) rows.push({ type: 'clipped' });
  }
  return rows;
}

export interface AffectedLike {
  kind: 'draft' | 'post' | 'source_pack' | 'idea';
  key: string;
  label: string;
  citesVersion: RefLike;
  currentVersion: RefLike;
  flagged: boolean;
}

const DEPENDENT_WORD: Record<AffectedLike['kind'], string> = { draft: 'draft', post: 'post', source_pack: 'source pack', idea: 'imported source' };

export interface ReplacementPlan {
  /** Always true: replacement waits for the person's explicit confirmation. */
  requiresConfirmation: true;
  title: string;
  consequences: string[];
  targetRefs: [RefLike, RefLike];
  payload: { dependentKind: AffectedLike['kind']; dependentKey: string };
  /** Which revision the server checks: the source pack's own, or the workspace organization revision. */
  revisionSource: 'source_pack' | 'organization';
}

export function replacementPlan(entry: AffectedLike, versions: { versionNo: number; assetRef: RefLike }[]): ReplacementPlan {
  const number = (ref: RefLike) => versions.find((version) => version.assetRef.versionId === ref.versionId)?.versionNo;
  const from = number(entry.citesVersion);
  const to = number(entry.currentVersion);
  const word = DEPENDENT_WORD[entry.kind];
  const consequences = [
    `Only this ${word} changes. Nothing else is updated automatically.`,
    'Approval of the old version does not carry over: review the new version’s facts before relying on it.',
    entry.kind === 'post'
      ? 'A published post is not changed.'
      : entry.kind === 'source_pack'
        ? 'Passages chosen in the old version must be chosen again in the new one.'
        : 'The draft text is not changed; the new version is offered as its source for review.'
  ];
  return {
    requiresConfirmation: true,
    title: `Use ${to ? `version ${to}` : 'the newer version'} instead of ${from ? `version ${from}` : 'the older version'} in “${entry.label}”?`,
    consequences,
    targetRefs: [entry.citesVersion, entry.currentVersion],
    payload: { dependentKind: entry.kind, dependentKey: entry.key },
    revisionSource: entry.kind === 'source_pack' ? 'source_pack' : 'organization'
  };
}

/** The version.accept_replacement envelope — only once the person has confirmed this exact plan. */
export function replacementEnvelope(plan: ReplacementPlan, options: { confirmed: boolean; expectedRevision: number | null; actionId: string }) {
  if (!options.confirmed || typeof options.expectedRevision !== 'number') return null;
  return {
    actionId: options.actionId,
    uiInstanceId: 'library-versions',
    actionType: 'version.accept_replacement' as const,
    targetRefs: [...plan.targetRefs],
    expectedRevision: options.expectedRevision,
    payload: { ...plan.payload }
  };
}

/** version.link (version_of): this newer item becomes the next version of the older one. */
export function linkVersionEnvelope(newer: RefLike, older: RefLike, organizationRevision: number | null, actionId: string) {
  if (newer.assetId === older.assetId) return null;
  return {
    actionId,
    uiInstanceId: 'library-versions',
    actionType: 'version.link' as const,
    targetRefs: [newer, older],
    expectedRevision: organizationRevision,
    payload: { relation: 'version_of' }
  };
}

const RELATION_WORDS: Record<string, { out: string; in: string }> = {
  derived_from: { out: 'Made from', in: 'Used to make' },
  version_of: { out: 'Newer version of', in: 'Has a newer version' },
  supersedes: { out: 'Replaces', in: 'Replaced by' },
  used_in: { out: 'Used in', in: 'Uses' },
  similar_to: { out: 'Possibly similar to', in: 'Possibly similar to' }
};

export function relationLabel(relation: string, direction: 'out' | 'in'): string {
  return RELATION_WORDS[relation]?.[direction] ?? relation.replaceAll('_', ' ');
}
