/**
 * Runtime prop validation for generated components (React-free).
 *
 * OpenUI 0.3.2 validates props shallowly at parse time and never validates values that come from `$variables`, Query
 * results or expressions (openui-package.md §0.4). Optional positional arguments may also arrive as `null`. Every Rafii
 * renderer therefore re-validates its props with its own spec schema: top-level `null`s become "not given", then the
 * schema's `safeParse` decides. A failure renders a quiet native state, never a crash and never raw model text.
 */
import type { z } from 'zod';

export type SafeProps<T> = { ok: true; value: T } | { ok: false; issues: string[] };

const MAX_ISSUES = 5;

export function withoutNulls(props: unknown): Record<string, unknown> {
  if (!props || typeof props !== 'object' || Array.isArray(props)) return {};
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props as Record<string, unknown>)) {
    if (value === null || value === undefined) continue;
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    out[key] = value;
  }
  return out;
}

export function safeProps<S extends z.ZodType>(schema: S, props: unknown): SafeProps<z.infer<S>> {
  const parsed = schema.safeParse(withoutNulls(props));
  if (parsed.success) return { ok: true, value: parsed.data as z.infer<S> };
  return {
    ok: false,
    issues: parsed.error.issues.slice(0, MAX_ISSUES).map((issue) => `${issue.path.join('.') || 'props'}:${issue.code}`),
  };
}

/** A child value OpenUI hands a container: an element node, a string, or an array of them. */
export interface ElementLike {
  type: 'element';
  typeName: string;
  statementId?: string;
  props: Record<string, unknown>;
}

export function isElementLike(value: unknown): value is ElementLike {
  return (
    !!value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    (value as { type?: unknown }).type === 'element' &&
    typeof (value as { typeName?: unknown }).typeName === 'string'
  );
}

/** Stable React key for a child: its statement id (never the array index alone, which remounts on insertion). */
export function childKey(value: unknown, index: number): string {
  if (isElementLike(value) && value.statementId) return `s:${value.statementId}`;
  if (isElementLike(value)) return `i:${value.typeName}:${index}`;
  return `v:${index}`;
}

/** Plain text of a prop that should be text; anything else (objects, element nodes) is dropped. */
export function plainText(value: unknown, max = 4000): string {
  if (typeof value === 'string') return value.length > max ? `${value.slice(0, max)}…` : value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
}
