/**
 * Task source packs in the Library (engineering spec §5, §10; implementation plan T08; A049–A051).
 *
 * The server (`library_intelligence/source_packs.py`) recommends a pack, keeps evidence and style apart, names gaps
 * and rights notes, and re-checks every ref when the pack is attached to a draft. This module is the host side:
 * the task context, the Library state to come back to (bounded and link-free), the deterministic review props, the
 * envelopes the person's own presses send, and the plain words for what came back.
 *
 * Rights are a constraint to check, never "cleared". Nothing here retries an attach: a conflict is shown with what
 * changed, and only the person refreshes the pack.
 *
 * No '@/' imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

export interface PackAssetRef {
  assetId: string;
  versionId: string;
  sha256: string;
}

type PackScope = { kind: 'workspace' } | { kind: 'collection'; collectionId: string } | { kind: 'selection'; assetRefs: PackAssetRef[] };

export interface PackReturnTo {
  query?: string;
  scope?: PackScope;
  filters?: { kinds?: string[]; tags?: string[]; usage?: string };
  sort?: string;
  density?: string;
  selection?: string[];
  anchor?: string;
  view?: string;
}

/** The Library address state this module reads and restores (a subset of url-state's LibraryUrlState). */
export interface PackLibraryState {
  q: string;
  scope: 'all' | 'collection' | 'selection';
  collection: string;
  use: 'all' | 'unused' | 'used';
  kind: 'all' | 'image' | 'video' | 'audio' | 'document' | 'file';
  tag: string;
  sort: 'newest' | 'stored' | 'largest';
  mode: 'gallery' | 'list';
  density: 'comfortable' | 'compact';
  sel: string[];
  asset: string;
}

export interface PackEvidence {
  purpose: 'evidence';
  selection?: 'user' | 'recommended';
  assetRef: PackAssetRef;
  title: string;
  kind?: string;
  locatorLabel?: string | null;
  review?: 'approved' | 'needs_review';
  rights?: string;
  current?: boolean;
  why?: string[];
  segmentId?: string;
  locator?: Record<string, unknown> | null;
}

export interface PackStyle {
  purpose: 'style';
  polarity: 'positive' | 'negative';
  sampleId: string;
  voiceSourceId?: string | null;
  assetRef: PackAssetRef;
  locator?: Record<string, unknown> | null;
  locatorLabel?: string | null;
  language?: string | null;
}

export interface PackNoteLike {
  code: string;
  message: string;
  assetRef?: Partial<PackAssetRef>;
}

export interface PackLike {
  packId: string;
  revision: number;
  status?: string;
  /** The server's TaskContext (goal, scope, purpose and the optional fields); only the goal is read here. */
  taskContext: { userGoal: string };
  returnTo?: PackReturnTo | null;
  evidenceRefs: PackEvidence[];
  styleRefs: PackStyle[];
  rationale?: PackNoteLike[];
  gaps: PackNoteLike[];
  rightsWarnings: PackNoteLike[];
  warnings?: string[];
}

/* --- limits the server enforces (contracts.py / source_packs.py) ---------------------------------------------------- */

export const PACK_LIMITS = { goal: 1000, audience: 300, channels: 12, channel: 40, selected: 40, evidence: 20, query: 500, returnChars: 4000, selection: 200 } as const;

const KEY = /^[0-9a-f]{32}$/;
const TOKEN = /^[A-Za-z0-9_.:-]{1,60}$/;
const LOCALE = /^[a-z]{2,3}(-[A-Za-z]{2,4})?$/;
/** The server refuses these anywhere in returnTo and in action payloads (`contracts.UNSAFE`). */
const UNSAFE = /(<\s*script|javascript:|\bselect\b[^\n]{0,40}\bfrom\b|\bdrop\s+table\b|https?:\/\/)/i;
/** Links, signed-URL parameters and bearer tokens never travel in the Library state. */
const SECRET = /(?:[a-z][a-z0-9+.-]*:\/\/|[?&](?:token|sig|signature|x-amz-[a-z-]+|expires|se|sp|sv|key|access_token)=|\bbearer\s)/i;

export function isPackSafeText(value: string): boolean {
  return !UNSAFE.test(value) && !SECRET.test(value);
}

function key(id: string): string {
  return id.replace(/-/g, '').toLowerCase();
}

export function packRef(id: string): PackAssetRef {
  return { assetId: key(id), versionId: '', sha256: '' };
}

/* --- rights and gaps: plain words, never "cleared" ------------------------------------------------------------------- */

/** Words for the rights a pack reports. There is no "cleared": the best is what the person approved. */
export const RIGHTS_WORDS: Record<string, string> = {
  approved_public: 'Public use approved in Ideas',
  needs_review: 'Public use not approved yet',
  internal: 'Internal reference only',
  unknown: 'Rights unknown'
};

/** Any other value reads as unknown, so generated or future text can never claim more. */
export function rightsLabel(code: string | null | undefined): string {
  return (code && RIGHTS_WORDS[code]) || RIGHTS_WORDS.unknown;
}

/** Wording a pack never uses about rights or facts. */
export const CLEARED_WORDING = /\b(?:cleared|clearance|all clear|rights[- ]free|copyright[- ]free)\b/i;

export function gapMessages(pack: Pick<PackLike, 'gaps'>): string[] {
  return pack.gaps.map((gap) => gap.message).filter(Boolean);
}

/* --- task context ------------------------------------------------------------------------------------------------ */

export interface PackTaskInput {
  goal: string;
  audience?: string;
  channels?: string[];
  locale?: string;
  personaId?: string;
  scope: PackScope;
  selected: PackAssetRef[];
}

/** What is wrong with the task as typed, in words, or null. The server's own limits, checked before sending. */
export function taskProblem(input: Pick<PackTaskInput, 'goal' | 'audience' | 'locale' | 'channels'> & { selected?: PackAssetRef[] }): string | null {
  const goal = input.goal.trim();
  if (!goal) return 'Say what you’re making first.';
  if (goal.length > PACK_LIMITS.goal) return `Keep the goal under ${PACK_LIMITS.goal.toLocaleString('en-US')} characters.`;
  if (!isPackSafeText(goal) || !isPackSafeText(input.audience ?? '')) return 'Leave links out of the goal and audience, and avoid “select … from” phrasing: the server refuses it as code.';
  if ((input.audience ?? '').trim().length > PACK_LIMITS.audience) return `Keep the audience under ${PACK_LIMITS.audience} characters.`;
  if (input.locale && !LOCALE.test(input.locale)) return 'Choose a language from the list.';
  if ((input.channels ?? []).length > PACK_LIMITS.channels) return `Choose up to ${PACK_LIMITS.channels} channels.`;
  return null;
}

/**
 * TaskContext with an explicit scope (a pack never defaults to the whole Library) and only the optional fields set.
 * Up to 20 chosen items go in as the person's own selections; with more, the scope holds them and the server picks
 * the best matches among them (a pack never carries more than 20 evidence refs).
 */
export function packTaskContext(input: PackTaskInput) {
  const audience = input.audience?.trim();
  const channels = (input.channels ?? []).map((channel) => channel.trim()).filter((channel) => channel && channel.length <= PACK_LIMITS.channel);
  return {
    userGoal: input.goal.trim().slice(0, PACK_LIMITS.goal),
    ...(audience ? { audience: audience.slice(0, PACK_LIMITS.audience) } : {}),
    ...(channels.length ? { channels: [...new Set(channels)].slice(0, PACK_LIMITS.channels) } : {}),
    ...(input.locale && LOCALE.test(input.locale) ? { locale: input.locale } : {}),
    ...(input.personaId ? { personaId: input.personaId.slice(0, 80) } : {}),
    selectedSourceRefs: input.selected.length <= PACK_LIMITS.evidence ? input.selected.map((assetRef) => ({ assetRef })) : [],
    scope: input.scope,
    purpose: 'draft_evidence' as const
  };
}

/* --- the Library state to come back to (A051) ------------------------------------------------------------------ */

const KINDS = ['image', 'video', 'audio', 'document', 'file'];

/**
 * The Library state at the moment of leaving, as the server stores it: query, scope, filters, sort, density,
 * selection, anchor and view. Stable keys only — a query or tag that looks like a link, token or code is left out
 * rather than sent, and nothing else (no URL, no signed address, no workspace or actor) is ever included.
 */
export function buildReturnTo(state: PackLibraryState): PackReturnTo {
  const out: PackReturnTo = {};
  const query = state.q.trim().slice(0, PACK_LIMITS.query);
  if (query && isPackSafeText(query)) out.query = query;
  const selection = [...new Set(state.sel.map(key).filter((value) => KEY.test(value)))].slice(0, PACK_LIMITS.selection);
  const collection = key(state.collection);
  if (state.scope === 'selection' && selection.length) out.scope = { kind: 'selection', assetRefs: selection.map((value) => ({ assetId: value, versionId: '', sha256: '' })) };
  else if (state.collection && KEY.test(collection)) out.scope = { kind: 'collection', collectionId: collection };
  else out.scope = { kind: 'workspace' };
  const filters: NonNullable<PackReturnTo['filters']> = {};
  if (KINDS.includes(state.kind)) filters.kinds = [state.kind];
  const tag = state.tag.trim();
  if (tag && tag.length <= 40 && isPackSafeText(tag)) filters.tags = [tag];
  if (state.use === 'used' || state.use === 'unused') filters.usage = state.use;
  if (Object.keys(filters).length) out.filters = filters;
  if (TOKEN.test(state.sort)) out.sort = state.sort;
  if (TOKEN.test(state.density)) out.density = state.density;
  if (TOKEN.test(state.mode)) out.view = state.mode;
  if (selection.length) out.selection = selection;
  const anchor = key(state.asset);
  if (KEY.test(anchor)) out.anchor = anchor;
  // Bounded like the server (4,000 characters): the selection is what grows, so it is what gives way.
  while (serverLength(out) > PACK_LIMITS.returnChars && out.selection?.length) {
    out.selection = out.selection.slice(0, Math.floor(out.selection.length / 2));
    if (out.scope?.kind === 'selection') out.scope = out.selection.length ? { kind: 'selection', assetRefs: out.selection.map((value) => ({ assetId: value, versionId: '', sha256: '' })) } : { kind: 'workspace' };
  }
  return out;
}

/** The length the server measures (Python's json.dumps adds a space after each ':' and ','): counted generously. */
export function serverLength(value: unknown): number {
  const text = JSON.stringify(value) ?? '';
  return text.length + (text.match(/[:,]/g) ?? []).length;
}

function one<T extends string>(options: readonly T[], value: unknown): T | undefined {
  return typeof value === 'string' && (options as readonly string[]).includes(value) ? (value as T) : undefined;
}

/**
 * The Library address state for a returnTo the server sent back (already without items that became inaccessible).
 * Ids the current address already holds keep their own spelling; anything unrecognized is ignored, never guessed.
 */
export function restoreLibraryState(back: PackReturnTo | null | undefined, current: PackLibraryState): Partial<PackLibraryState> {
  if (!back || typeof back !== 'object') return {};
  const patch: Partial<PackLibraryState> = {};
  if (typeof back.query === 'string' && isPackSafeText(back.query)) patch.q = back.query.slice(0, 200);
  const spelled = new Map(current.sel.map((id) => [key(id), id]));
  const selection = Array.isArray(back.selection) ? back.selection.filter((value): value is string => typeof value === 'string' && KEY.test(key(value))) : [];
  patch.sel = selection.map((value) => spelled.get(key(value)) ?? key(value));
  const scope = back.scope;
  if (scope?.kind === 'collection' && typeof scope.collectionId === 'string' && KEY.test(key(scope.collectionId))) {
    patch.scope = 'collection';
    patch.collection = key(current.collection) === key(scope.collectionId) ? current.collection : key(scope.collectionId);
  } else if (scope?.kind === 'selection') {
    patch.scope = patch.sel.length ? 'selection' : 'all';
    patch.collection = '';
  } else if (scope?.kind === 'workspace') {
    patch.scope = 'all';
    patch.collection = '';
  }
  const filters = back.filters ?? {};
  patch.kind = one(['image', 'video', 'audio', 'document', 'file'] as const, filters.kinds?.[0]) ?? 'all';
  const tag = filters.tags?.[0];
  // A tag that was left out as unsafe stays as the address has it; otherwise the saved state decides.
  if (typeof tag === 'string' && isPackSafeText(tag)) patch.tag = tag.slice(0, 80);
  else if (!current.tag || isPackSafeText(current.tag)) patch.tag = '';
  patch.use = one(['used', 'unused'] as const, filters.usage) ?? 'all';
  const sort = one(['newest', 'stored', 'largest'] as const, back.sort);
  if (sort) patch.sort = sort;
  const density = one(['comfortable', 'compact'] as const, back.density);
  if (density) patch.density = density;
  const view = one(['gallery', 'list'] as const, back.view);
  if (view) patch.mode = view;
  if (typeof back.anchor === 'string' && KEY.test(key(back.anchor))) patch.asset = key(current.asset) === key(back.anchor) ? current.asset : key(back.anchor);
  return patch;
}

/** The generic notice for items that left the selection while away (never which ones). */
export function removedNotice(count: number | undefined): string | null {
  if (!count || count < 1) return null;
  return count === 1 ? 'One selected item is no longer available, so it was removed from your selection.' : 'Some selected items are no longer available, so they were removed from your selection.';
}

/* --- review: evidence and style, kept apart ---------------------------------------------------------------------- */

/** One review entry's identity: purpose, version, then the passage (evidence) or the voice sample (style). */
export function reviewEntryKey(purpose: 'evidence' | 'style', sourceRef: { assetRef: { assetId: string; versionId: string }; segmentId?: string; locator?: unknown }, sampleId?: string | null): string {
  const base = `${purpose}:${sourceRef.assetRef.assetId}:${sourceRef.assetRef.versionId}`;
  return purpose === 'style' ? `${base}:${sampleId ?? ''}` : `${base}:${sourceRef.segmentId ?? ''}:${sourceRef.locator ? JSON.stringify(sourceRef.locator) : ''}`;
}

export function packEntryKey(entry: PackEvidence | PackStyle): string {
  return entry.purpose === 'style'
    ? reviewEntryKey('style', { assetRef: entry.assetRef }, entry.sampleId)
    : reviewEntryKey('evidence', { assetRef: entry.assetRef, segmentId: entry.segmentId, locator: entry.locator ?? undefined });
}

/** Everything starts kept; the person leaves out what they don't want. */
export function allEntryKeys(pack: Pick<PackLike, 'evidenceRefs' | 'styleRefs'>): string[] {
  return [...pack.evidenceRefs.map(packEntryKey), ...pack.styleRefs.map(packEntryKey)];
}

function notesFor(pack: Pick<PackLike, 'rightsWarnings'>, ref: PackAssetRef): string[] {
  return pack.rightsWarnings.filter((note) => note.assetRef && note.assetRef.versionId === ref.versionId && note.assetRef.assetId === ref.assetId).map((note) => note.message);
}

function sourceRefOf(entry: PackEvidence | PackStyle) {
  return {
    assetRef: { assetId: entry.assetRef.assetId, versionId: entry.assetRef.versionId, sha256: entry.assetRef.sha256 },
    ...('segmentId' in entry && entry.segmentId ? { segmentId: entry.segmentId } : {}),
    ...(entry.locator ? { locator: entry.locator } : {})
  };
}

function clip(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

const POLARITY: Record<PackStyle['polarity'], string> = {
  positive: 'Write like this',
  negative: 'Don’t write like this'
};

/**
 * Props for the SourcePackReview component in deterministic mode. Evidence and style stay in separate lists; each
 * ref carries its locator label, why it is there, its rights in fixed words and its own notes. Notes about items
 * that are not in the lists (for example a source that was left out by its policy) stay in the pack-level list.
 */
export function packReviewProps(pack: PackLike, titleOf: (assetId: string) => string | null = () => null) {
  const listed = [...pack.evidenceRefs, ...pack.styleRefs].map((entry) => `${entry.assetRef.assetId}:${entry.assetRef.versionId}`);
  return {
    packId: pack.packId,
    revision: pack.revision,
    goal: clip(pack.taskContext.userGoal, 300),
    evidence: pack.evidenceRefs.map((entry) => ({
      sourceRef: sourceRefOf(entry),
      title: clip(entry.title || titleOf(entry.assetRef.assetId) || 'Untitled item', 160),
      rationale: clip((entry.why ?? []).join(' · '), 400),
      rights: entry.rights && RIGHTS_WORDS[entry.rights] ? entry.rights : 'unknown',
      locatorLabel: clip(entry.locatorLabel || 'whole item', 80),
      warnings: notesFor(pack, entry.assetRef).map((message) => clip(message, 240)).slice(0, 6)
    })),
    style: pack.styleRefs.map((entry) => ({
      sourceRef: sourceRefOf(entry),
      title: clip(titleOf(entry.assetRef.assetId) || 'Voice example', 160),
      rationale: POLARITY[entry.polarity] ?? POLARITY.positive,
      locatorLabel: clip(entry.locatorLabel || 'whole item', 80),
      polarity: entry.polarity === 'negative' ? ('negative' as const) : ('positive' as const),
      sampleId: entry.sampleId
    })),
    gaps: gapMessages(pack).map((message) => clip(message, 200)).slice(0, 20),
    rightsWarnings: pack.rightsWarnings
      .filter((note) => !note.assetRef || !listed.includes(`${note.assetRef.assetId}:${note.assetRef.versionId}`))
      .map((note) => clip(note.message, 240))
      .slice(0, 20),
    actions: [] as never[]
  };
}

/* --- envelopes from the person's own presses -------------------------------------------------------------------- */

export interface PackEnvelope {
  actionId: string;
  uiInstanceId: string;
  actionType: 'source_pack.create' | 'source_pack.attach';
  targetRefs: PackAssetRef[];
  expectedRevision: number | null;
  payload: Record<string, unknown>;
}

/**
 * source_pack.create from exactly what the person kept: the evidence refs (each also sent as a target, as the server
 * requires) and the voice sample ids. Nothing is searched again; the new pack starts at revision 1.
 */
export function createPackEnvelope(pack: PackLike, kept: ReadonlySet<string>, returnTo: PackReturnTo | null, uiInstanceId = 'library-pack'): PackEnvelope {
  const evidence = pack.evidenceRefs.filter((entry) => kept.has(packEntryKey(entry))).map(sourceRefOf);
  const styleSampleIds = [...new Set(pack.styleRefs.filter((entry) => kept.has(packEntryKey(entry))).map((entry) => entry.sampleId))];
  const targets = new Map<string, PackAssetRef>();
  for (const entry of evidence) targets.set(`${entry.assetRef.assetId}:${entry.assetRef.versionId}`, entry.assetRef);
  // The chosen evidence travels once, in `evidence`; the task keeps its goal, scope and the rest.
  const task = { ...pack.taskContext, selectedSourceRefs: [] };
  return {
    actionId: `pack-create-${pack.packId}`,
    uiInstanceId,
    actionType: 'source_pack.create',
    targetRefs: [...targets.values()],
    expectedRevision: null,
    payload: {
      taskContext: task,
      ...(returnTo ? { returnTo } : {}),
      evidence,
      styleSampleIds
    }
  };
}

/** source_pack.attach to one draft; expectedRevision is the pack's revision, so a changed pack is a conflict. */
export function attachEnvelope(pack: Pick<PackLike, 'packId' | 'revision'>, draftId: string, uiInstanceId = 'library-pack'): PackEnvelope {
  return {
    actionId: `pack-attach-${pack.packId}`,
    uiInstanceId,
    actionType: 'source_pack.attach',
    targetRefs: [],
    expectedRevision: pack.revision,
    payload: { packId: pack.packId, draftId }
  };
}

/** A digest of what a press would send, so the same request keeps its idempotency key and a different one gets a new key. */
export function envelopeDigest(envelope: Pick<PackEnvelope, 'actionType' | 'targetRefs' | 'expectedRevision' | 'payload'>): string {
  return JSON.stringify([envelope.actionType, envelope.targetRefs, envelope.expectedRevision, envelope.payload]);
}

/* --- what came back ---------------------------------------------------------------------------------------------- */

export interface PackChangeLike {
  purpose: string;
  assetRef?: Partial<PackAssetRef>;
  change: string;
  after?: { reason?: string | null; message?: string | null } | null;
  message?: string;
}

const CHANGE_WORDS: Record<string, string> = {
  permission_narrowed: 'its permission was narrowed',
  unavailable: 'it is no longer available',
  version_changed: 'a different version is now current',
  passage_changed: 'the passage was corrected',
  voice_example_missing: 'the voice example is missing',
  voice_example_withdrawn: 'the voice example was withdrawn',
  pack_revoked: 'a permission this pack relied on was withdrawn'
};

/** One change in plain words: which ref (by its title in this pack, when known), what changed and the server's reason. */
export function describeChange(change: PackChangeLike, titleOf: (versionId: string) => string | null = () => null): string {
  const what = CHANGE_WORDS[change.change] ?? 'it changed';
  if (change.purpose === 'pack') return change.message || `This pack can’t be attached: ${what}.`;
  const title = change.assetRef?.versionId ? titleOf(change.assetRef.versionId) : null;
  const subject = `${change.purpose === 'style' ? 'Voice example' : 'Source'}${title ? ` “${clip(title, 80)}”` : ''}`;
  const reason = change.after?.message ? ` ${change.after.message}` : '';
  return `${subject}: ${what}.${reason}`;
}

export type AttachReading =
  | { kind: 'applied'; composer: { draftId: string; sourcePackId: string; sourceIds: string[]; voiceMode: 'personalized' | 'neutral'; voiceSourceIds: string[] } | null; warnings: string[]; alreadyAttached: boolean }
  | { kind: 'conflict'; changes: string[]; message: string }
  | { kind: 'refused'; message: string };

/**
 * Read a source_pack.attach action result. A conflict lists what changed and is never retried from here: the only
 * way forward is the person's "Refresh pack".
 */
export function readAttachResult(
  result: { status?: string; result?: unknown; warnings?: readonly string[] } | null | undefined,
  titleOf: (versionId: string) => string | null = () => null
): AttachReading {
  const body = (result?.result ?? {}) as { composer?: unknown; warnings?: string[]; alreadyAttached?: boolean; changes?: PackChangeLike[] };
  if (result?.status === 'applied') {
    const composer = body.composer && typeof body.composer === 'object' ? (body.composer as Extract<AttachReading, { kind: 'applied' }>['composer']) : null;
    return { kind: 'applied', composer, warnings: [...new Set([...(result.warnings ?? []), ...(body.warnings ?? [])])], alreadyAttached: Boolean(body.alreadyAttached) };
  }
  if (result?.status === 'conflict') {
    const changes = (body.changes ?? []).map((change) => describeChange(change, titleOf));
    return { kind: 'conflict', changes: changes.length ? changes : ['Something this pack relies on changed.'], message: result.warnings?.[0] ?? 'Permissions or sources changed since this pack was made.' };
  }
  if (result?.status === 'denied') return { kind: 'refused', message: result.warnings?.[0] ?? 'Not allowed for your role or these items.' };
  return { kind: 'refused', message: result?.warnings?.[0] ?? 'This needs your confirmation first.' };
}

/* --- the drafting composer -------------------------------------------------------------------------------------- */

export interface PackDraft {
  id: string;
  platform: string;
  language: string;
  channelId?: string;
}

/**
 * The turn the existing writer takes (`ideas.turn`), built only from the attach result's composer fields: the Ideas
 * source ids, the voice mode and voice samples, and a rework reference to exactly the draft the pack was attached to.
 */
export function composerTurn(composer: { draftId: string; sourceIds: string[]; voiceMode: 'personalized' | 'neutral'; voiceSourceIds: string[] }, draft: PackDraft, goal: string) {
  const personalized = composer.voiceMode === 'personalized' && composer.voiceSourceIds.length > 0;
  return {
    text: goal.trim().slice(0, PACK_LIMITS.goal),
    sourceIds: [...composer.sourceIds],
    references: [{ kind: 'post' as const, id: composer.draftId, role: 'rework' as const }],
    destinations: [{ platform: draft.platform, ...(draft.channelId ? { channelId: draft.channelId } : {}), language: draft.language }],
    language: draft.language,
    voiceMode: personalized ? ('personalized' as const) : ('neutral' as const),
    voiceSourceIds: personalized ? [...composer.voiceSourceIds] : []
  };
}

/* --- what this environment has switched on ---------------------------------------------------------------------- */

export interface PackGate {
  enabled: boolean;
  /** Plain explanation when it is off; null when on. */
  reason: string | null;
}

/**
 * The Library intelligence flags (`GET …/status`) as entry points: what to hide or disable, and why, in words. The
 * deterministic Library works either way.
 */
export function libraryGates(flags: Record<string, boolean | undefined>, reachable: boolean) {
  const gate = (on: boolean, reason: string): PackGate => (on ? { enabled: true, reason: null } : { enabled: false, reason });
  const off = 'Library intelligence isn’t available here. Browsing, search by name and uploads still work.';
  return {
    packs: gate(reachable, off),
    ask: reachable ? gate(flags.retrieval === true, 'Ask isn’t available here: Library search is turned off in this environment. Search by name still works.') : gate(false, off),
    recommendations: reachable ? gate(flags.retrieval === true, 'Library search is turned off here, so a pack uses only the items you chose.') : gate(false, off),
    voice: reachable ? gate(flags.voice === true, 'Voice examples are turned off here, so packs carry evidence only and drafts use a neutral voice.') : gate(false, off),
    artifacts: reachable ? gate(flags.artifacts === true, 'Accepted drafts aren’t saved back to the Library here.') : gate(false, off),
    taskUi: reachable ? gate(flags.task_ui === true, 'Generated layouts are turned off here, so results use the standard view.') : gate(false, off)
  };
}

export type LibraryGates = ReturnType<typeof libraryGates>;
