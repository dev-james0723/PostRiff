/**
 * Consented continuation from the anonymous Post Doctor into a workspace (PRD R-FWR-01).
 *
 * Nothing leaves the browser before the person explicitly chooses "Continue with this draft". The selected text then
 * lives only in this tab's sessionStorage for at most 24 hours, keyed by an opaque random nonce. Only the nonce travels
 * in the URL (never text, email or brand details), and the nonce authorizes nothing: after sign-in the person confirms
 * the destination workspace and the server imports through the normal authorized command. The record is cleared after
 * a successful import, an explicit discard, or on the first access after it expired.
 *
 * Pure module (no React, no path aliases) so `node --test` can import it directly.
 */

export const CONTINUATION_TTL_MS = 24 * 60 * 60 * 1000;
export const CONTINUATION_MAX_TEXT = 8000;
const PREFIX = 'rafii.continue.v1.';
const PENDING = 'rafii.continue.pending';
const NONCE = /^[A-Za-z0-9_-]{16,80}$/;
export const CONTINUATION_PLATFORMS = ['Threads', 'Instagram', 'LinkedIn', 'X', 'Bluesky', 'Mastodon'] as const;
export const CONTINUATION_LANGUAGES = ['en', 'zh-HK', 'zh-CN', 'other'] as const;

export type ContinuationKind = 'original' | 'edited';
export interface ContinuationItem {
  kind: ContinuationKind;
  text: string;
}
export interface ContinuationResult {
  helping: string[];
  hurting: string[];
  change: string[];
  status: string | null;
}
export interface ContinuationRecord {
  v: 1;
  nonce: string;
  createdAt: number;
  expiresAt: number;
  origin: 'post_doctor';
  platform: (typeof CONTINUATION_PLATFORMS)[number];
  language: (typeof CONTINUATION_LANGUAGES)[number];
  items: ContinuationItem[];
  result: ContinuationResult | null;
}

/** The minimal Storage surface we use; sessionStorage in the browser, a fake in tests. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  /** Enumeration (as `Storage` has it), used to clear every kept record; without it only the known keys are cleared. */
  readonly length?: number;
  key?(index: number): string | null;
}

const FAMILY = 'rafii.continue';

export type ReadOutcome =
  | { status: 'ready'; record: ContinuationRecord }
  | { status: 'missing' }
  | { status: 'expired' }
  | { status: 'unavailable' }
  | { status: 'invalid' };

export function newNonce(random: () => string = defaultRandom): string {
  const value = random().replace(/[^A-Za-z0-9_-]/g, '');
  if (!NONCE.test(value)) throw new Error('Could not create a continuation nonce.');
  return value;
}

function defaultRandom(): string {
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function strings(value: unknown, max: number): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string').map((v) => v.slice(0, 300)).slice(0, max) : [];
}

/** Only the qualitative feedback the public page already showed; never scores, ids or costs. */
export function summarizeResult(result: unknown): ContinuationResult | null {
  if (!result || typeof result !== 'object') return null;
  const value = result as Record<string, unknown>;
  return {
    helping: strings(value.helping, 6),
    hurting: strings(value.hurting, 6),
    change: strings(value.change, 4),
    status: typeof value.status === 'string' ? value.status.slice(0, 20) : null
  };
}

export function buildRecord(input: {
  nonce: string;
  now: number;
  platform: string;
  language: string;
  original: string;
  edited?: string | null;
  select: { original: boolean; edited: boolean };
  result?: unknown;
}): ContinuationRecord {
  if (!NONCE.test(input.nonce)) throw new Error('Invalid continuation nonce.');
  const items: ContinuationItem[] = [];
  const original = input.original.trim();
  const edited = (input.edited ?? '').trim();
  if (input.select.original && original) items.push({ kind: 'original', text: original });
  if (input.select.edited && edited && edited !== original) items.push({ kind: 'edited', text: edited });
  if (!items.length) throw new Error('Choose the original or the edited draft.');
  if (items.some((item) => item.text.length > CONTINUATION_MAX_TEXT))
    throw new Error(`A draft can be up to ${CONTINUATION_MAX_TEXT.toLocaleString('en')} characters.`);
  const platform = (CONTINUATION_PLATFORMS as readonly string[]).includes(input.platform) ? input.platform : 'Threads';
  const language = (CONTINUATION_LANGUAGES as readonly string[]).includes(input.language) ? input.language : 'en';
  return {
    v: 1,
    nonce: input.nonce,
    createdAt: input.now,
    expiresAt: input.now + CONTINUATION_TTL_MS,
    origin: 'post_doctor',
    platform: platform as ContinuationRecord['platform'],
    language: language as ContinuationRecord['language'],
    items,
    result: summarizeResult(input.result)
  };
}

/** Save the consented record. Returns false (and stores nothing) when the browser blocks storage. A new record
 *  replaces any earlier one kept in this tab (going back and continuing again leaves no orphaned draft). */
export function saveContinuation(storage: StorageLike | null | undefined, record: ContinuationRecord): boolean {
  if (!storage) return false;
  clearAllContinuations(storage);
  try {
    storage.setItem(PREFIX + record.nonce, JSON.stringify(record));
    storage.setItem(PENDING, record.nonce);
    return true;
  } catch {
    try {
      storage.removeItem(PREFIX + record.nonce);
    } catch {
      /* nothing more to clean */
    }
    return false;
  }
}

function decode(raw: string | null, nonce: string): ContinuationRecord | null {
  if (!raw || raw.length > 40000) return null;
  try {
    const value = JSON.parse(raw) as Partial<ContinuationRecord>;
    if (value.v !== 1 || value.nonce !== nonce || value.origin !== 'post_doctor') return null;
    if (typeof value.createdAt !== 'number' || typeof value.expiresAt !== 'number') return null;
    if (!Array.isArray(value.items) || !value.items.length || value.items.length > 2) return null;
    const items = value.items.filter(
      (item): item is ContinuationItem =>
        !!item && (item.kind === 'original' || item.kind === 'edited') && typeof item.text === 'string' && !!item.text.trim() && item.text.length <= CONTINUATION_MAX_TEXT
    );
    if (items.length !== value.items.length) return null;
    if (!(CONTINUATION_PLATFORMS as readonly string[]).includes(String(value.platform))) return null;
    return {
      v: 1,
      nonce,
      createdAt: value.createdAt,
      expiresAt: value.expiresAt,
      origin: 'post_doctor',
      platform: value.platform as ContinuationRecord['platform'],
      language: (CONTINUATION_LANGUAGES as readonly string[]).includes(String(value.language)) ? (value.language as ContinuationRecord['language']) : 'en',
      items,
      result: summarizeResult(value.result)
    };
  } catch {
    return null;
  }
}

/** Read a record by nonce (or the tab's pending one). Expired or damaged records are removed on access. */
export function readContinuation(storage: StorageLike | null | undefined, nonce: string | null, now: number): ReadOutcome {
  if (!storage) return { status: 'unavailable' };
  let key = nonce;
  try {
    key = key ?? storage.getItem(PENDING);
  } catch {
    return { status: 'unavailable' };
  }
  if (!key) return { status: 'missing' };
  if (!NONCE.test(key)) return { status: 'invalid' };
  let raw: string | null;
  try {
    raw = storage.getItem(PREFIX + key);
  } catch {
    return { status: 'unavailable' };
  }
  if (raw === null) return { status: 'missing' };
  const record = decode(raw, key);
  if (!record) {
    clearContinuation(storage, key);
    return { status: 'invalid' };
  }
  if (record.expiresAt <= now || record.createdAt > now + 60_000) {
    clearContinuation(storage, key);
    return { status: 'expired' };
  }
  return { status: 'ready', record };
}

/** After a successful import or an explicit discard: nothing of the draft stays in the browser. */
export function clearContinuation(storage: StorageLike | null | undefined, nonce: string): void {
  if (!storage) return;
  try {
    storage.removeItem(PREFIX + nonce);
    if (storage.getItem(PENDING) === nonce) storage.removeItem(PENDING);
  } catch {
    /* storage went away; nothing to clear */
  }
}

/**
 * Every `rafii.continue*` record this tab holds (each kept draft and the pending pointer), not only the one in hand:
 * a person who went back and continued again left earlier nonces behind. Used on import and discard.
 */
export function clearAllContinuations(storage: StorageLike | null | undefined, nonce?: string | null): void {
  if (!storage) return;
  try {
    const keys: string[] = [];
    if (typeof storage.length === 'number' && typeof storage.key === 'function') {
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key && key.startsWith(FAMILY)) keys.push(key);
      }
    }
    const pending = storage.getItem(PENDING);
    for (const known of [nonce, pending]) if (known) keys.push(PREFIX + known);
    keys.push(PENDING);
    for (const key of new Set(keys)) storage.removeItem(key);
  } catch {
    /* storage went away; nothing to clear */
  }
}

/** Where the public page sends the person: only the opaque nonce travels, inside the existing same-site `next`. */
export function signUpHref(nonce: string, signedIn: boolean): string {
  const target = `/app/weekly?continue=${encodeURIComponent(nonce)}`;
  return signedIn ? target : `/auth/sign-up?next=${encodeURIComponent(target)}`;
}

/** The server request for `continue_source` (the nonce doubles as the idempotency key; text goes in the body only). */
export function importBody(record: ContinuationRecord) {
  return { idempotencyKey: record.nonce, consent: true as const, platform: record.platform, language: record.language, items: record.items };
}
