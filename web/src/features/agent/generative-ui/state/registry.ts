/**
 * Tab-local registries of generated views (lane F), all keyed by scope (principal + workspace, or founder + mode) and cleared
 * on a scope switch or sign-out:
 *
 * - presentation keys: one idempotency key per (scope, parent run) kept in sessionStorage, so a reload or remount re-sends the
 *   SAME key (the server answers with the existing attempt; nothing is generated or charged twice);
 * - fresh turns: runs answered in this tab session that may start a presentation. Only a fresh turn ever POSTs
 *   /presentations; history read back from the server (reload, another tab, an old message) never does;
 * - the view in use: the artifact (and its revisions) the person last looked at or touched per conversation, sent as
 *   `uiContext` with the next text or voice turn so both modalities resolve "this", "the second one" the same way.
 */
import type { UiTurnContextV1 } from '@/lib/agent-runtime/ui-contracts';

const KEYS_STORAGE = 'rafii.genui.presentationKeys';
const MAX_KEYS = 200;

interface Entry {
  scopeKey: string;
  conversationId: string | null;
  context: UiTurnContextV1;
  at: number;
}

const fresh = new Map<string, number>();
const inUse = new Map<string, Entry>();          // `${scopeKey}|${conversationId}` → view
const byArtifact = new Map<string, Entry>();     // artifactId → view (for interactions reported by components)
let activeScope: string | null = null;
const listeners = new Set<() => void>();

function storage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function readKeys(): Record<string, string> {
  try {
    const raw = storage()?.getItem(KEYS_STORAGE);
    const parsed = raw ? (JSON.parse(raw) as unknown) : {};
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function writeKeys(keys: Record<string, string>) {
  try {
    const entries = Object.entries(keys).slice(-MAX_KEYS);
    storage()?.setItem(KEYS_STORAGE, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    /* private mode or full storage: the in-memory key still dedupes this page */
  }
}

const memoryKeys = new Map<string, string>();

export function newIdempotencyKey(random: () => number = Math.random): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return `ui_${crypto.randomUUID().replace(/-/g, '')}`;
  let out = 'ui_';
  const alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i += 1) out += alphabet[Math.floor(random() * alphabet.length)];
  return out;
}

/** The one idempotency key of a presentation of this run in this scope (stable across reloads in this tab). */
export function presentationKey(scopeKey: string, runId: string): string {
  const id = `${scopeKey}|${runId}`;
  const known = memoryKeys.get(id) ?? readKeys()[id];
  if (known) {
    memoryKeys.set(id, known);
    return known;
  }
  const key = newIdempotencyKey();
  memoryKeys.set(id, key);
  writeKeys({ ...readKeys(), [id]: key });
  return key;
}

/** A turn answered in this tab: it may start its presentation (once). */
export function markFresh(scopeKey: string, runId: string) {
  fresh.set(`${scopeKey}|${runId}`, Date.now());
}

export function isFresh(scopeKey: string, runId: string | null | undefined): boolean {
  return Boolean(runId && fresh.has(`${scopeKey}|${runId}`));
}

/** The view the person is using in a conversation (a visible ready view, or the one they last touched). */
export function setUiContext(scopeKey: string, conversationId: string | null, context: UiTurnContextV1) {
  const entry = { scopeKey, conversationId, context, at: Date.now() };
  inUse.set(`${scopeKey}|${conversationId ?? ''}`, entry);
  byArtifact.set(context.artifactId, entry);
  for (const listener of listeners) listener();
}

/** A component reported an interaction (selection, filter): that view becomes the one in use for its conversation. */
export function noteUiInteraction(artifactId: string) {
  const entry = byArtifact.get(artifactId);
  if (!entry) return;
  entry.at = Date.now();
  inUse.set(`${entry.scopeKey}|${entry.conversationId ?? ''}`, entry);
}

/** `uiContext` for the next turn of this conversation in this scope, or undefined. */
export function currentUiContext(scopeKey: string | null, conversationId: string | null): UiTurnContextV1 | undefined {
  if (!scopeKey) return undefined;
  return inUse.get(`${scopeKey}|${conversationId ?? ''}`)?.context;
}

export function clearUiContext(artifactId: string) {
  const entry = byArtifact.get(artifactId);
  if (!entry) return;
  byArtifact.delete(artifactId);
  const key = `${entry.scopeKey}|${entry.conversationId ?? ''}`;
  if (inUse.get(key) === entry) inUse.delete(key);
}

/**
 * The signed-in principal or workspace (or founder mode) changed: forget every other scope's views, fresh marks and keys so no
 * private state follows the person into another workspace. Returns true when the scope actually changed.
 */
export function enterUiScope(scopeKey: string | null): boolean {
  if (scopeKey === activeScope) return false;
  activeScope = scopeKey;
  for (const map of [fresh, inUse]) for (const key of [...map.keys()]) if (!key.startsWith(`${scopeKey ?? '\u0000'}|`)) map.delete(key);
  for (const [artifactId, entry] of [...byArtifact.entries()]) if (entry.scopeKey !== scopeKey) byArtifact.delete(artifactId);
  for (const key of [...memoryKeys.keys()]) if (!key.startsWith(`${scopeKey ?? '\u0000'}|`)) memoryKeys.delete(key);
  writeKeys(Object.fromEntries(Object.entries(readKeys()).filter(([key]) => scopeKey && key.startsWith(`${scopeKey}|`))));
  for (const listener of listeners) listener();
  return true;
}

export function onUiScopeChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Test helper: the registries' sizes (no private values). */
export function registrySizes() {
  return { fresh: fresh.size, inUse: inUse.size, byArtifact: byArtifact.size, keys: memoryKeys.size };
}
