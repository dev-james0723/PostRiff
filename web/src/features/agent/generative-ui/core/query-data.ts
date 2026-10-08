/**
 * Reading bound data inside components (React-free; shared by lane C primitives and lane E journey components).
 *
 * `readQuery(source, rowsField)` turns whatever OpenUI passed as a `source` prop into an honest view model:
 *   - `null`/`undefined` (the Query has not answered yet, or the view is still streaming) → `loading`;
 *   - a value that is not a genuine server result (for example a literal the model typed before validation) → `waiting`,
 *     with no rows: bound components never display typed figures as data;
 *   - a genuine result → its own state, rows, as-of time, coverage and warnings, exactly as the server sent them.
 * Unknown stays unknown: a missing value is `undefined`, never 0.
 */
import type { JsonValue, UiQueryResultV1 } from '@/lib/agent-runtime/ui-contracts';
import { isGenuineQueryResult } from './query-results';

export type ReadState = UiQueryResultV1['state'] | 'waiting';
export type Row = Record<string, JsonValue>;

export interface QueryView {
  state: ReadState;
  genuine: boolean;
  data: JsonValue | undefined;
  rows: Row[];
  /** True when `rows` came from a list (so an empty list really means "nothing matched"). */
  hasList: boolean;
  asOf: string | null;
  coverage: UiQueryResultV1['coverage'] | null;
  warnings: string[];
  nextCursor: string | null;
  sourceRefs: string[];
}

const FORBIDDEN = new Set(['__proto__', 'constructor', 'prototype']);
const MAX_PATH_PARTS = 6;

/** Own-property dotted path lookup (`"totals.reach"`, `"items.0.title"`); undefined when any step is missing. */
export function getPath(value: unknown, path: string | null | undefined): JsonValue | undefined {
  if (path === null || path === undefined || path === '') return value as JsonValue | undefined;
  const parts = String(path).split('.').slice(0, MAX_PATH_PARTS + 1);
  if (parts.length > MAX_PATH_PARTS) return undefined;
  let current: unknown = value;
  for (const part of parts) {
    if (current === null || typeof current !== 'object' || FORBIDDEN.has(part)) return undefined;
    if (!Object.prototype.hasOwnProperty.call(current, part)) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current as JsonValue | undefined;
}

function isRow(value: unknown): value is Row {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** The list inside `data`: `rowsField` when given, the data itself when it is a list, else its only list property. */
export function rowsOf(data: unknown, rowsField?: string | null): { rows: Row[]; hasList: boolean } {
  let list: unknown;
  if (rowsField) list = getPath(data, rowsField);
  else if (Array.isArray(data)) list = data;
  else if (isRow(data)) {
    const lists = Object.keys(data).filter((key) => Array.isArray((data as Row)[key]));
    if (lists.length === 1) list = (data as Row)[lists[0]];
  }
  if (!Array.isArray(list)) return { rows: [], hasList: false };
  return { rows: list.filter(isRow), hasList: true };
}

const LOADING: QueryView = {
  state: 'loading',
  genuine: false,
  data: undefined,
  rows: [],
  hasList: false,
  asOf: null,
  coverage: null,
  warnings: [],
  nextCursor: null,
  sourceRefs: [],
};

export function readQuery(source: unknown, rowsField?: string | null): QueryView {
  if (source === null || source === undefined) return LOADING;
  if (!isGenuineQueryResult(source)) return { ...LOADING, state: 'waiting' };
  const { rows, hasList } = rowsOf(source.data, rowsField);
  return {
    state: source.state,
    genuine: true,
    data: source.data,
    rows,
    hasList,
    asOf: source.asOf,
    coverage: source.coverage,
    warnings: source.warnings,
    nextCursor: source.nextCursor,
    sourceRefs: source.sourceRefs,
  };
}

/** States in which rows may be shown (partial and stale are shown with a note). */
export function showsData(view: QueryView): boolean {
  return view.genuine && (view.state === 'available' || view.state === 'partial' || view.state === 'stale');
}

/** A number from data, or undefined when it is missing or not a finite number (never coerced to 0). */
export function numberAt(value: unknown, path?: string | null): number | undefined {
  const found = getPath(value, path);
  if (typeof found === 'number' && Number.isFinite(found)) return found;
  if (found && typeof found === 'object' && !Array.isArray(found)) {
    const inner = (found as Row).value;
    if (typeof inner === 'number' && Number.isFinite(inner)) return inner;
  }
  return undefined;
}

/** A row's stable id: `idField` when given, else `id`, `ref`, then common domain id names. */
export function rowId(row: Row, idField?: string | null): string | undefined {
  const fields = idField ? [idField] : ['id', 'ref', 'draftId', 'itemId', 'campaignId', 'eventId', 'sourceId'];
  for (const field of fields) {
    const value = getPath(row, field);
    if (typeof value === 'string' && value) return value;
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return undefined;
}
