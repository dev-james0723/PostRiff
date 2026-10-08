/**
 * View-state helpers of the renderer (React-free; C03, C06, G10).
 *
 * Persistence belongs to lane F (`state/` — `UiArtifactStateContext`: declared fields only, debounced, CAS). The renderer
 * keeps two rules of its own:
 *   - `swapInitialState`: when a new accepted revision replaces the shown one, OpenUI re-applies `initialState` if the
 *     revision's declarations changed (openui-package.md §5). Handing it the person's latest snapshot on top of F's
 *     initial state keeps what they typed and picked instead of reverting to load-time values.
 *   - `collectFieldHosts` + `dirtyFieldsRemoved`: input fields the person edited that the new revision would no longer
 *     show. Those need the native warning before the swap (spec §5: an edit cannot silently erase dirty form state).
 */
import { isElementLike } from './props';

export interface FieldHost {
  /** `form/field` inside a Form, `field` outside. */
  key: string;
  /** The field's visible label (for the native warning). */
  label: string;
  /** The `$variable` its value is bound to, if any. */
  stateKey: string | null;
  form: string | null;
  name: string;
}

type Visit = (el: { typeName: string; props: Record<string, unknown> }, form: string | null) => void;

function walkElements(node: unknown, visit: Visit, form: string | null = null, depth = 0): void {
  if (depth > 64 || node === null || node === undefined) return;
  if (Array.isArray(node)) {
    for (const item of node) walkElements(item, visit, form, depth + 1);
    return;
  }
  if (!isElementLike(node)) return;
  visit(node, form);
  const nextForm = node.typeName === 'Form' && typeof node.props.name === 'string' ? node.props.name : form;
  for (const value of Object.values(node.props ?? {})) {
    if (Array.isArray(value) || isElementLike(value)) walkElements(value, visit, nextForm, depth + 1);
    else if (value && typeof value === 'object') {
      for (const inner of Object.values(value as Record<string, unknown>)) walkElements(inner, visit, nextForm, depth + 1);
    }
  }
}

/** The `$variable` a value prop is bound to: an evaluated ReactiveAssign or a parse-time StateRef node. */
function boundState(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as { __reactive?: unknown; target?: unknown; k?: unknown; n?: unknown };
  if (v.__reactive === 'assign' && typeof v.target === 'string') return v.target;
  if (v.k === 'StateRef' && typeof v.n === 'string') return v.n;
  return null;
}

/** Input fields of a parsed or evaluated tree, using the library's field-host map (component → name prop). */
export function collectFieldHosts(root: unknown, fieldHosts: Readonly<Record<string, string>>): FieldHost[] {
  const out: FieldHost[] = [];
  walkElements(root, (el, form) => {
    const nameProp = fieldHosts[el.typeName];
    if (!nameProp) return;
    const name = el.props[nameProp];
    if (typeof name !== 'string' || !name) return;
    const label = typeof el.props.label === 'string' && el.props.label ? el.props.label : name;
    out.push({ key: form ? `${form}/${name}` : name, label, stateKey: boundState(el.props.value), form, name });
  });
  return out;
}

function fieldValue(snapshot: Record<string, unknown>, host: FieldHost): unknown {
  if (host.stateKey) return snapshot[host.stateKey];
  const container = host.form ? snapshot[host.form] : snapshot;
  if (!container || typeof container !== 'object') return undefined;
  const entry = (container as Record<string, unknown>)[host.name];
  return entry && typeof entry === 'object' && 'value' in (entry as Record<string, unknown>) ? (entry as { value: unknown }).value : entry;
}

function same(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  try {
    return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  } catch {
    return false;
  }
}

/**
 * Fields shown in `previous` but not in `next` that the person changed: either their value differs from the state the
 * view opened with, or lane F still holds them as unsaved (`dirtyKeys`: `$variables` and Form names).
 */
export function dirtyFieldsRemoved(options: {
  previous: FieldHost[];
  next: FieldHost[];
  initial: Record<string, unknown>;
  current: Record<string, unknown>;
  dirtyKeys?: readonly string[];
}): FieldHost[] {
  const nextKeys = new Set(options.next.map((host) => host.key));
  const unsaved = new Set(options.dirtyKeys ?? []);
  return options.previous.filter((host) => {
    if (nextKeys.has(host.key)) return false;
    const storeKey = host.stateKey ?? host.form ?? host.name;
    if (unsaved.has(storeKey)) return true;
    const now = fieldValue(options.current, host);
    return now !== undefined && now !== null && now !== '' && !same(fieldValue(options.initial, host), now);
  });
}

/** OpenUI `initialState` at the moment a new accepted revision is swapped in (see the module header). */
export function swapInitialState(base: Record<string, unknown> | null | undefined, latest: Record<string, unknown> | null | undefined): Record<string, unknown> {
  return { ...base, ...latest };
}
