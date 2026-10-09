/**
 * Library navigation state in the address (UI spec §5, A051): query, scope, filters, sort, mode, density, selected
 * ids and the open item. Stable ids only — never signed URLs, tokens or anything that looks like one.
 *
 * No '@/' imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

export const LIBRARY_VIEW_MODES = ['gallery', 'list'] as const;
export const LIBRARY_DENSITIES = ['comfortable', 'compact'] as const;
export const LIBRARY_SCOPES = ['all', 'collection', 'selection'] as const;
export const LIBRARY_USAGE = ['all', 'unused', 'used'] as const;
export const LIBRARY_KINDS = ['all', 'image', 'video', 'audio', 'document', 'file'] as const;
export const LIBRARY_SORTS = ['newest', 'stored', 'largest'] as const;
/** Processing state as a filter: ready to use, still being prepared, or needing attention (failed). */
export const LIBRARY_STATUSES = ['all', 'ready', 'processing', 'attention'] as const;
/** Search the Library, or ask it a question; switching keeps each one's state. */
export const LIBRARY_PANELS = ['search', 'ask'] as const;

/** The server's selection cap (`contracts.MAX_SELECTION`). */
export const MAX_SELECTED = 200;
export const MAX_QUERY_LENGTH = 200;

export type LibraryViewMode = (typeof LIBRARY_VIEW_MODES)[number];
export type LibraryDensity = (typeof LIBRARY_DENSITIES)[number];
export type LibraryScopeParam = (typeof LIBRARY_SCOPES)[number];
export type LibraryUsageParam = (typeof LIBRARY_USAGE)[number];
export type LibraryKindParam = (typeof LIBRARY_KINDS)[number];
export type LibrarySortParam = (typeof LIBRARY_SORTS)[number];
export type LibraryStatusParam = (typeof LIBRARY_STATUSES)[number];
export type LibraryPanelParam = (typeof LIBRARY_PANELS)[number];

export interface LibraryUrlState {
  q: string;
  scope: LibraryScopeParam;
  collection: string;
  use: LibraryUsageParam;
  kind: LibraryKindParam;
  status: LibraryStatusParam;
  tag: string;
  sort: LibrarySortParam;
  mode: LibraryViewMode;
  density: LibraryDensity;
  sel: string[];
  asset: string;
  panel: LibraryPanelParam;
  /** A source pack whose saved Library state to restore on the way back from a draft (A051); cleared once applied. */
  pack: string;
}

export const DEFAULT_LIBRARY_STATE: LibraryUrlState = {
  q: '',
  scope: 'all',
  collection: '',
  use: 'all',
  kind: 'all',
  status: 'all',
  tag: '',
  sort: 'newest',
  mode: 'gallery',
  density: 'comfortable',
  sel: [],
  asset: '',
  panel: 'search',
  pack: ''
};

/** Asset and collection ids: UUIDs, 32-hex keys or legacy media ids. No dots, slashes, colons or query characters. */
const ID = /^[A-Za-z0-9_-]{4,64}$/;

export function isSafeId(value: unknown): value is string {
  return typeof value === 'string' && ID.test(value);
}

/** Signed URLs and credentials must never reach the address bar or history. */
const SECRET = /(?:[a-z][a-z0-9+.-]*:\/\/|[?&](?:token|sig|signature|x-amz-[a-z-]+|expires|se|sp|sv|key|access_token)=|\bbearer\s)/i;

export function looksLikeSecret(value: string): boolean {
  return SECRET.test(value);
}

/** The query as it may appear in the address: trimmed, bounded, and dropped entirely if it looks like a link or token. */
export function safeQuery(value: unknown): string {
  if (typeof value !== 'string') return '';
  const text = value.trim().slice(0, MAX_QUERY_LENGTH);
  return looksLikeSecret(text) ? '' : text;
}

export function sanitizeIds(values: unknown): string[] {
  const list = Array.isArray(values) ? values : typeof values === 'string' ? values.split(',') : [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of list) {
    const id = typeof value === 'string' ? value.trim() : '';
    if (!isSafeId(id) || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
    if (out.length >= MAX_SELECTED) break;
  }
  return out;
}

function literal<T extends string>(options: readonly T[], value: unknown, fallback: T): T {
  return typeof value === 'string' && (options as readonly string[]).includes(value) ? (value as T) : fallback;
}

function read(params: URLSearchParams | Record<string, string | null | undefined>, key: string): string | null {
  if (typeof (params as URLSearchParams).get === 'function') return (params as URLSearchParams).get(key);
  const value = (params as Record<string, string | null | undefined>)[key];
  return typeof value === 'string' ? value : null;
}

export function parseLibraryState(params: URLSearchParams | Record<string, string | null | undefined>): LibraryUrlState {
  const d = DEFAULT_LIBRARY_STATE;
  const collection = read(params, 'collection') ?? '';
  const asset = read(params, 'asset') ?? '';
  const pack = read(params, 'pack') ?? '';
  const tag = (read(params, 'tag') ?? '').slice(0, 80);
  return {
    q: safeQuery(read(params, 'q') ?? ''),
    scope: literal(LIBRARY_SCOPES, read(params, 'scope'), d.scope),
    collection: isSafeId(collection) ? collection : '',
    use: literal(LIBRARY_USAGE, read(params, 'use'), d.use),
    kind: literal(LIBRARY_KINDS, read(params, 'kind'), d.kind),
    status: literal(LIBRARY_STATUSES, read(params, 'status'), d.status),
    tag: looksLikeSecret(tag) ? '' : tag,
    sort: literal(LIBRARY_SORTS, read(params, 'sort'), d.sort),
    mode: literal(LIBRARY_VIEW_MODES, read(params, 'mode'), d.mode),
    density: literal(LIBRARY_DENSITIES, read(params, 'density'), d.density),
    sel: sanitizeIds(read(params, 'sel') ?? ''),
    asset: isSafeId(asset) ? asset : '',
    panel: literal(LIBRARY_PANELS, read(params, 'panel'), d.panel),
    pack: isSafeId(pack) ? pack : ''
  };
}

/** Only non-default values, in a fixed order, so equal states give equal addresses. */
export function serializeLibraryState(state: Partial<LibraryUrlState>): Record<string, string> {
  const full = { ...DEFAULT_LIBRARY_STATE, ...state };
  const out: Record<string, string> = {};
  const q = safeQuery(full.q);
  if (q) out.q = q;
  if (full.scope !== DEFAULT_LIBRARY_STATE.scope) out.scope = full.scope;
  if (isSafeId(full.collection)) out.collection = full.collection;
  if (full.use !== DEFAULT_LIBRARY_STATE.use) out.use = full.use;
  if (full.kind !== DEFAULT_LIBRARY_STATE.kind) out.kind = full.kind;
  if (full.status !== DEFAULT_LIBRARY_STATE.status) out.status = full.status;
  if (full.tag && !looksLikeSecret(full.tag)) out.tag = full.tag.slice(0, 80);
  if (full.sort !== DEFAULT_LIBRARY_STATE.sort) out.sort = full.sort;
  if (full.mode !== DEFAULT_LIBRARY_STATE.mode) out.mode = full.mode;
  if (full.density !== DEFAULT_LIBRARY_STATE.density) out.density = full.density;
  const sel = sanitizeIds(full.sel);
  if (sel.length) out.sel = sel.join(',');
  if (isSafeId(full.asset)) out.asset = full.asset;
  if (full.panel !== DEFAULT_LIBRARY_STATE.panel) out.panel = full.panel;
  if (isSafeId(full.pack)) out.pack = full.pack;
  return out;
}

export function libraryHref(state: Partial<LibraryUrlState>, base = '/app/library'): string {
  const query = new URLSearchParams(serializeLibraryState(state)).toString();
  return query ? `${base}?${query}` : base;
}

/** The dash-free lowercase key the intelligence routes use for an asset id. */
export function normalizeKey(id: string): string {
  return id.replace(/-/g, '').toLowerCase();
}

/**
 * An AssetRef for an item known only from the deterministic list. An empty versionId and sha256 let the server
 * resolve the version it holds for that id; a ref from an understanding card or search hit is preferred when present.
 */
export function assetRefFor(id: string): { assetId: string; versionId: string; sha256: string } {
  return { assetId: normalizeKey(id), versionId: '', sha256: '' };
}

/**
 * Keep the selection the person can still reach. An id can only be judged gone once the full list has loaded, or
 * when the server said so (`gone`); otherwise it stays. The caller explains removals generically, never by name.
 */
export function reconcileSelection(selected: readonly string[], available: Iterable<string>, complete: boolean, gone: Iterable<string> = []): { kept: string[]; dropped: number } {
  const known = new Set([...available].map(normalizeKey));
  const removed = new Set([...gone].map(normalizeKey));
  const kept = selected.filter((id) => {
    const key = normalizeKey(id);
    if (removed.has(key)) return false;
    return complete ? known.has(key) : true;
  });
  return { kept, dropped: selected.length - kept.length };
}

/** The opener of the detail panel, found again after the list re-renders (focus restore). */
export function openerSelector(id: string): string | null {
  return isSafeId(id) ? `[data-library-open="${id}"]` : null;
}

/** Where a view's scroll position is kept for the return trip (per workspace, per view, without selection or pack). */
export function scrollKey(workspaceId: string, state: Partial<LibraryUrlState>): string {
  return `rafii-library-scroll:${workspaceId}:${libraryHref({ ...state, sel: [], asset: '', pack: '' })}`;
}

/** Which status bucket an item's processing state falls in (items without one, such as photos, are ready). */
export function statusBucket(processing: string | null | undefined): Exclude<LibraryStatusParam, 'all'> {
  const value = processing ?? '';
  if (['pending', 'queued', 'processing'].includes(value)) return 'processing';
  if (value === 'failed') return 'attention';
  return 'ready';
}
