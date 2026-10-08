/**
 * Local view state of a generated artifact (React-free; C03, C06, C08, D-A42, 02-CONTRACTS §7).
 *
 * OpenUI keeps view state in one store: `$variables` as top-level keys, form fields under their Form name as
 * `{field: {value, componentType}}`, and fields outside a Form under their own name. This module:
 *   - `declaredNames(parse)`: the persistable names of a revision (its `$variables` and Form names), the same rule the
 *     trusted validator reports as `stateNames`/`formNames` and F persists (D-A42);
 *   - `persistableState(snapshot, names)`: only declared, JSON-safe values, at most 16 KiB (larger → nothing persisted);
 *   - `collectFieldHosts(root, fieldHosts)` + `dirtyFieldsRemoved(...)`: which inputs the person edited that an
 *     accepted edit would remove, so the native warning can protect them before the new revision is shown.
 * Nothing here is sent to the model; selections reach the conversation only through `uiContext` (server-resolved).
 */
import { BOUNDS, type JsonValue } from '@/lib/agent-runtime/ui-contracts';
import { isElementLike } from './props';

export interface DeclaredNames {
  stateNames: string[];
  formNames: string[];
}

const STATE_NAME = /^\$[A-Za-z_][A-Za-z0-9_]{0,62}$/;
const FORM_NAME = /^[A-Za-z_][A-Za-z0-9_-]{0,63}$/;
const MAX_STATE = 200;
const MAX_FORMS = 100;

interface ParseLike {
  root?: unknown;
  stateDeclarations?: Record<string, unknown>;
}

function walkElements(node: unknown, visit: (el: { typeName: string; props: Record<string, unknown> }, form: string | null) => void, form: string | null = null, depth = 0): void {
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

export function declaredNames(parse: ParseLike | null | undefined): DeclaredNames {
  const stateNames = Object.keys(parse?.stateDeclarations ?? {})
    .filter((name) => STATE_NAME.test(name))
    .sort()
    .slice(0, MAX_STATE);
  const forms = new Set<string>();
  walkElements(parse?.root, (el) => {
    if (el.typeName === 'Form' && typeof el.props.name === 'string' && FORM_NAME.test(el.props.name)) forms.add(el.props.name);
  });
  return { stateNames, formNames: [...forms].sort().slice(0, MAX_FORMS) };
}

function jsonSafe(value: unknown, depth = 0): JsonValue | undefined {
  if (depth > BOUNDS.inputDepth) return undefined;
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return value as JsonValue;
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (Array.isArray(value)) {
    const out: JsonValue[] = [];
    for (const item of value) {
      const safe = jsonSafe(item, depth + 1);
      if (safe !== undefined) out.push(safe);
    }
    return out;
  }
  if (typeof value === 'object') {
    const out: Record<string, JsonValue> = {};
    for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
      const safe = jsonSafe(inner, depth + 1);
      if (safe !== undefined) out[key] = safe;
    }
    return out;
  }
  return undefined;
}

export function stateBytes(state: Record<string, JsonValue>): number {
  return new TextEncoder().encode(JSON.stringify(state)).length;
}

/** Declared keys only, JSON-safe; `null` when nothing is declared or the result would exceed 16 KiB. */
export function persistableState(snapshot: Record<string, unknown> | null | undefined, names: DeclaredNames): Record<string, JsonValue> | null {
  if (!snapshot) return null;
  const allowed = new Set([...names.stateNames, ...names.formNames]);
  if (!allowed.size) return null;
  const out: Record<string, JsonValue> = {};
  for (const key of Object.keys(snapshot).sort()) {
    if (!allowed.has(key)) continue;
    const safe = jsonSafe(snapshot[key]);
    if (safe !== undefined) out[key] = safe;
  }
  if (!Object.keys(out).length) return null;
  return stateBytes(out) <= BOUNDS.stateBytes ? out : null;
}

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

/** Input fields of a parsed tree, using the library's field-host map (component → name prop). */
export function collectFieldHosts(root: unknown, fieldHosts: Readonly<Record<string, string>>): FieldHost[] {
  const out: FieldHost[] = [];
  walkElements(root, (el, form) => {
    const nameProp = fieldHosts[el.typeName];
    if (!nameProp) return;
    const name = el.props[nameProp];
    if (typeof name !== 'string' || !name) return;
    const bound = el.props.value;
    const stateKey =
      bound && typeof bound === 'object' && (bound as { __reactive?: unknown }).__reactive === 'assign' && typeof (bound as { target?: unknown }).target === 'string'
        ? ((bound as { target: string }).target)
        : null;
    const label = typeof el.props.label === 'string' && el.props.label ? el.props.label : name;
    out.push({ key: form ? `${form}/${name}` : name, label, stateKey, form, name });
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

/** Fields the person changed (vs. the state the view opened with) that are absent from the next revision. */
export function dirtyFieldsRemoved(options: {
  previous: FieldHost[];
  next: FieldHost[];
  initial: Record<string, unknown>;
  current: Record<string, unknown>;
}): FieldHost[] {
  const nextKeys = new Set(options.next.map((host) => host.key));
  return options.previous.filter(
    (host) => !nextKeys.has(host.key) && !same(fieldValue(options.initial, host), fieldValue(options.current, host)) && fieldValue(options.current, host) !== undefined,
  );
}

/**
 * The `initialState` to hand OpenUI when a new accepted revision is swapped in. OpenUI re-applies `initialState`
 * whenever the revision's declarations change (openui-package.md §5); passing the person's latest snapshot keeps what
 * they typed and picked instead of reverting it to the load-time values.
 */
export function nextInitialState(latest: Record<string, unknown> | null, persisted: Record<string, JsonValue> | null): Record<string, unknown> {
  return latest ? { ...latest } : { ...(persisted ?? {}) };
}
