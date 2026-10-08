/**
 * Persisted UI state of one generated view (lane F; 02-CONTRACTS §3 `persist_ui_state`, §7 bounds; D-A42).
 *
 * The browser keeps the person's view state (OpenUI `$vars`, forms, and Rafii's ordered `@selection`) and saves only the
 * fields the server declared for the current revision, debounced (500 ms), at most 16 KiB, with compare-and-swap on
 * `stateRevision`. A conflict (another tab saved first) re-reads the server state and re-applies only this tab's dirty
 * fields, so both tabs' edits survive. Nothing here is a business mutation; secret-looking fields never leave the tab.
 */
import type { JsonValue } from '@/lib/agent-runtime/ui-contracts';
import { BOUNDS, canonicalJson } from '@/lib/agent-runtime/ui-contracts';
import type { UiTransport } from '@/features/agent/generative-ui/bridges/types';

export const SELECTION_KEY = '@selection';
export const SELECTION_MAX_ITEMS = 50;
export const SELECTION_VISIBLE_MAX = 50;
const SECRET = /(pass(word|code|phrase)?|secret|token|api[_-]?key|authorization|cookie|credential|signature|private[_-]?key)/i;
const VAR = /^\$[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const FORM = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const REF_TYPE = /^[a-z][a-z0-9_]{0,31}$/;
const REF_ID = /^[A-Za-z0-9:_.-]{1,80}$/;

export interface DeclaredState {
  stateNames: string[];
  formNames: string[];
}

export interface SelectionItem {
  type: string;
  id: string;
  title?: string;
}

export interface StoredState {
  safeState: Record<string, JsonValue>;
  stateRevision: number;
}

export type StateSaveError = 'ui_state_forbidden' | 'ui_state_too_large' | 'ui_state_field' | 'ui_state_unavailable' | 'ui_state_conflict';

/** The fields of an OpenUI store snapshot (plus `@selection`) that this revision declares and that look safe to keep. */
export function persistableKeys(snapshot: Record<string, unknown>, declared: DeclaredState | null): string[] {
  const names = new Set((declared?.stateNames ?? []).map((n) => (n.startsWith('$') ? n : `$${n}`)));
  const forms = new Set(declared?.formNames ?? []);
  return Object.keys(snapshot).filter((key) => {
    if (key === SELECTION_KEY) return true;
    if (SECRET.test(key)) return false;
    if (VAR.test(key)) return names.has(key);
    return FORM.test(key) && forms.has(key);
  });
}

function same(a: unknown, b: unknown): boolean {
  try {
    return canonicalJson((a ?? null) as JsonValue) === canonicalJson((b ?? null) as JsonValue);
  } catch {
    return false;
  }
}

function plain(value: unknown): JsonValue {
  // OpenUI store values are JSON already; this drops functions/undefined and keeps the shape the server validates.
  return JSON.parse(JSON.stringify(value ?? null)) as JsonValue;
}

/** Clean an ordered selection: what was selected and the list as it was shown (D-A20), ids and types only plus a short title. */
export function selectionValue(listId: string | null, items: SelectionItem[], visible?: SelectionItem[] | null): JsonValue {
  const seen = new Set<string>();
  const clean = items
    .filter((i) => i && REF_TYPE.test(i.type) && REF_ID.test(i.id))
    .filter((i) => (seen.has(`${i.type}:${i.id}`) ? false : (seen.add(`${i.type}:${i.id}`), true)))
    .slice(0, SELECTION_MAX_ITEMS)
    .map((i) => ({ type: i.type, id: i.id, title: (i.title ?? '').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 120) }));
  const out: Record<string, JsonValue> = { items: clean };
  const shown = (visible ?? []).filter((i) => i && REF_TYPE.test(i.type) && REF_ID.test(i.id)).slice(0, SELECTION_VISIBLE_MAX);
  if (shown.length) out.visible = shown.map((i) => ({ type: i.type, id: i.id }));
  if (listId && FORM.test(listId.replace(/^\$/, ''))) out.listId = listId;
  return out;
}

export interface UiStateControllerOptions {
  transport: UiTransport;
  artifactId: string;
  initial: StoredState;
  declared: DeclaredState | null;
  /** Writes are allowed for this caller (snapshot access.canPersistState). */
  canPersist: boolean;
  debounceMs?: number;
  timers?: { setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (handle: unknown) => void };
  onSaved?: (state: StoredState) => void;
  onError?: (code: StateSaveError) => void;
}

export class UiStateController {
  private opts: UiStateControllerOptions;
  private local: Record<string, JsonValue>;
  private persisted: StoredState;
  private dirty = new Set<string>();
  private timer: unknown = null;
  private saving: Promise<void> | null = null;
  private disposed = false;
  private declared: DeclaredState | null;
  private allowed: boolean;

  constructor(opts: UiStateControllerOptions) {
    this.opts = opts;
    this.persisted = { safeState: { ...opts.initial.safeState }, stateRevision: opts.initial.stateRevision };
    this.local = { ...opts.initial.safeState };
    this.declared = opts.declared;
    this.allowed = opts.canPersist;
  }

  private get timers() {
    return this.opts.timers ?? { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>) };
  }

  /** The state to hand OpenUI as `initialState`: what the server holds, with this tab's unsaved fields on top. */
  initialState(): Record<string, JsonValue> {
    return { ...this.local };
  }

  current(): StoredState {
    return { safeState: { ...this.persisted.safeState }, stateRevision: this.persisted.stateRevision };
  }

  dirtyFields(): string[] {
    return [...this.dirty].sort();
  }

  /** OpenUI `onStateUpdate(snapshot)`: remember declared fields that changed, then save after the debounce. */
  update(snapshot: Record<string, unknown>): void {
    if (this.disposed || !snapshot || typeof snapshot !== 'object') return;
    for (const key of persistableKeys(snapshot, this.declared)) {
      if (key === SELECTION_KEY) continue; // selections arrive through recordSelection only
      const value = plain(snapshot[key]);
      if (same(value, this.local[key])) continue;
      this.local[key] = value;
      this.dirty.add(key);
    }
    this.schedule();
  }

  recordSelection(listId: string | null, items: SelectionItem[], visible?: SelectionItem[] | null): void {
    if (this.disposed) return;
    const value = selectionValue(listId, items, visible);
    if (same(value, this.local[SELECTION_KEY])) return;
    this.local[SELECTION_KEY] = value;
    this.dirty.add(SELECTION_KEY);
    this.schedule();
  }

  private schedule() {
    if (!this.allowed || !this.dirty.size) return;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, this.opts.debounceMs ?? BOUNDS.stateDebounceMs);
  }

  /** Save now (before a follow-up turn, so the server reads the selection the person just made). */
  flush(): Promise<void> {
    if (this.timer !== null) {
      this.timers.clearTimeout(this.timer);
      this.timer = null;
    }
    if (!this.allowed || this.disposed || !this.dirty.size) return this.saving ?? Promise.resolve();
    const run = (this.saving ?? Promise.resolve()).then(() => this.save(0));
    this.saving = run.finally(() => {
      if (this.saving === run) this.saving = null;
    });
    return this.saving;
  }

  private patch(): Record<string, JsonValue> {
    const out: Record<string, JsonValue> = {};
    for (const key of this.dirty) out[key] = key in this.local ? this.local[key] : null;
    return out;
  }

  private async save(attempt: number): Promise<void> {
    if (this.disposed || !this.dirty.size) return;
    const patch = this.patch();
    const merged = { ...this.persisted.safeState, ...patch };
    if (new TextEncoder().encode(canonicalJson(merged as JsonValue)).length > BOUNDS.stateBytes) {
      this.opts.onError?.('ui_state_too_large');
      return;
    }
    const base = this.opts.transport.base;
    let response: Response;
    try {
      response = await this.opts.transport.fetch(`${base}/presentations/${encodeURIComponent(this.opts.artifactId)}/state`, {
        method: 'POST', body: { expectedStateRevision: this.persisted.stateRevision, patch }
      });
    } catch {
      this.opts.onError?.('ui_state_unavailable');
      return;
    }
    if (this.disposed) return;
    let body: Record<string, unknown> = {};
    try {
      body = (await response.json()) as Record<string, unknown>;
    } catch {
      body = {};
    }
    if (response.ok) {
      const saved = body as unknown as StoredState;
      this.persisted = { safeState: { ...(saved.safeState ?? merged) }, stateRevision: Number(saved.stateRevision ?? this.persisted.stateRevision + 1) };
      for (const key of Object.keys(patch)) if (same(patch[key], this.local[key] ?? null)) this.dirty.delete(key);
      this.opts.onSaved?.(this.current());
      if (this.dirty.size) this.schedule(); // typed more while saving
      return;
    }
    if (response.status === 409 && attempt < 3) {
      // Another tab saved first: take its state, keep this tab's own unsaved fields on top, try once more.
      const current = (body.current as StoredState | undefined) ?? (await this.reread());
      if (!current) {
        this.opts.onError?.('ui_state_conflict');
        return;
      }
      this.persisted = { safeState: { ...current.safeState }, stateRevision: current.stateRevision };
      this.local = { ...current.safeState, ...Object.fromEntries([...this.dirty].map((k) => [k, this.local[k] ?? null])) };
      return this.save(attempt + 1);
    }
    // 400 (a field this revision doesn't declare), 403 (not allowed), 404 (gone or disabled): keep it local, stop saving.
    this.allowed = false;
    const code = typeof body.code === 'string' ? body.code : '';
    this.opts.onError?.(response.status === 403 ? 'ui_state_forbidden' : code === 'ui_state_too_large' ? 'ui_state_too_large' : response.status === 400 ? 'ui_state_field' : 'ui_state_unavailable');
  }

  private async reread(): Promise<StoredState | null> {
    try {
      const response = await this.opts.transport.fetch(`${this.opts.transport.base}/presentations/${encodeURIComponent(this.opts.artifactId)}`, { method: 'GET' });
      if (!response.ok) return null;
      const view = (await response.json()) as { artifact?: { safeState?: Record<string, JsonValue>; stateRevision?: number } };
      if (!view.artifact) return null;
      return { safeState: view.artifact.safeState ?? {}, stateRevision: Number(view.artifact.stateRevision ?? 0) };
    } catch {
      return null;
    }
  }

  /**
   * A newer accepted revision arrived (an edit, or another tab's state): take its state and declaration, keep this tab's dirty
   * fields that the new revision still declares, and report the ones it no longer declares so a native warning can offer them.
   */
  rebase(next: StoredState, declared: DeclaredState | null): { initialState: Record<string, JsonValue>; lostFields: string[] } {
    const result = applyUiPatch({ safeState: this.local }, next, this.dirtyFields(), declared);
    this.declared = declared;
    this.persisted = { safeState: { ...next.safeState }, stateRevision: next.stateRevision };
    this.local = { ...result.initialState };
    this.dirty = new Set([...this.dirty].filter((k) => !result.lostFields.includes(k)));
    this.schedule();
    return result;
  }

  setAllowed(allowed: boolean) {
    this.allowed = allowed;
    if (allowed) this.schedule();
  }

  dispose() {
    this.disposed = true;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }
}

/**
 * `applyUiPatch(artifact, validatedPatch, localDirtyFields)` (02-CONTRACTS §3): the state-preserving merge when a validated
 * revision replaces the current one. The server's state is the base; this tab's dirty fields stay on top when the new
 * revision still declares them; the others are returned as `lostFields` (never silently dropped: the surface warns and can
 * restore them). The old revision stays available to the caller on failure because nothing here mutates its input.
 */
export function applyUiPatch(current: { safeState: Record<string, JsonValue> }, next: StoredState, localDirtyFields: string[], declared: DeclaredState | null) {
  const keep = new Set(persistableKeys(Object.fromEntries(localDirtyFields.map((k) => [k, true])), declared));
  const initialState: Record<string, JsonValue> = { ...next.safeState };
  const lostFields: string[] = [];
  for (const key of localDirtyFields) {
    if (keep.has(key)) initialState[key] = current.safeState[key] ?? null;
    else lostFields.push(key);
  }
  return { initialState, lostFields: lostFields.sort() };
}
