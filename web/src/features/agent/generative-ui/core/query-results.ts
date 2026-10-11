/**
 * Read-only query results for generated views (React-free; C04, D-A12, D-A16, D-A40).
 *
 * `wrapReadToolProvider(inner)` sits between D's query bridge and OpenUI's `<Renderer toolProvider>`:
 *   - it always answers in the MCP shape `{content: [], structuredContent}` (OpenUI's `extractToolResult` turns a bare
 *     object without `structuredContent` into `null`), whether the bridge returned a bare `UiQueryResultV1` or MCP;
 *   - it bounds the result before OpenUI materializes it (rows, string length, depth, total size; `__proto__` and
 *     friends dropped) and schema-checks it, so malformed data reads as `unavailable`, never as data;
 *   - it brands the result object (WeakSet) so bound components can tell a genuine server result from a literal the
 *     model typed while the view was still streaming. OpenUI keeps object identity from the provider through
 *     `getResult` → `resolveRef` → prop evaluation, so the brand survives to the component.
 * It never adds bindings: unknown names are the bridge's decision (`denied`), and it never calls a write.
 */
import type { McpClientLike } from '@openuidev/lang-core';
import { BOUNDS, type JsonValue, type UiQueryResultV1, uiQueryResultSchema } from '@/lib/agent-runtime/ui-contracts';

const GENUINE = new WeakSet<object>();

export const RESULT_LIMITS = {
  /** Rows of one list (a page is at most 100; nested series may be daily for a year). */
  arrayItems: 400,
  stringChars: 8192,
  objectKeys: 128,
  depth: 10,
  nodes: 25_000,
} as const;

const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

interface BoundState {
  nodes: number;
  truncated: boolean;
}

function boundValue(value: unknown, depth: number, state: BoundState): JsonValue {
  state.nodes += 1;
  if (state.nodes > RESULT_LIMITS.nodes) {
    state.truncated = true;
    return null;
  }
  if (value === null || typeof value === 'boolean') return value as JsonValue;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string') {
    if (value.length <= RESULT_LIMITS.stringChars) return value;
    state.truncated = true;
    return `${value.slice(0, RESULT_LIMITS.stringChars)}…`;
  }
  if (depth >= RESULT_LIMITS.depth) {
    state.truncated = true;
    return null;
  }
  if (Array.isArray(value)) {
    if (value.length > RESULT_LIMITS.arrayItems) state.truncated = true;
    return value.slice(0, RESULT_LIMITS.arrayItems).map((item) => boundValue(item, depth + 1, state));
  }
  if (typeof value === 'object') {
    const out: Record<string, JsonValue> = {};
    let keys = 0;
    for (const key of Object.keys(value as Record<string, unknown>)) {
      if (FORBIDDEN_KEYS.has(key)) continue;
      if (++keys > RESULT_LIMITS.objectKeys) {
        state.truncated = true;
        break;
      }
      out[key] = boundValue((value as Record<string, unknown>)[key], depth + 1, state);
    }
    return out;
  }
  return null;
}

export function unavailableResult(warning: string): UiQueryResultV1 {
  return {
    state: 'unavailable',
    data: null,
    asOf: null,
    sourceRefs: [],
    revision: null,
    nextCursor: null,
    coverage: { known: null, total: null, note: null },
    warnings: [warning],
  };
}

/** Accept a bare `UiQueryResultV1` or the MCP shape; bound, schema-check and brand it. */
export function normalizeQueryResult(raw: unknown): UiQueryResultV1 {
  let candidate: unknown = raw;
  if (candidate && typeof candidate === 'object' && !Array.isArray(candidate) && 'structuredContent' in candidate) {
    candidate = (candidate as { structuredContent?: unknown }).structuredContent;
  }
  const state: BoundState = { nodes: 0, truncated: false };
  const bounded = boundValue(candidate, 0, state);
  const parsed = uiQueryResultSchema.safeParse(bounded);
  const result: UiQueryResultV1 = parsed.success ? parsed.data : unavailableResult('invalid_result');
  if (parsed.success && state.truncated && !result.warnings.includes('truncated')) result.warnings = [...result.warnings, 'truncated'];
  if (result.data !== null && Array.isArray(result.data) && result.data.length > BOUNDS.queryPageMax) {
    result.data = result.data.slice(0, BOUNDS.queryPageMax);
    if (!result.warnings.includes('truncated')) result.warnings = [...result.warnings, 'truncated'];
  }
  GENUINE.add(result);
  return result;
}

/** True only for a result object produced by `normalizeQueryResult` (a server answer), never a typed literal. */
export function isGenuineQueryResult(value: unknown): value is UiQueryResultV1 {
  return !!value && typeof value === 'object' && GENUINE.has(value as object);
}

type InnerProvider = { callTool(call: { name: string; arguments?: Record<string, JsonValue> }): Promise<unknown> };

/** D's read-only provider → OpenUI's MCP-like client. `null` stays `null` (no reads before acceptance). */
export function wrapReadToolProvider(inner: InnerProvider | null | undefined): McpClientLike | null {
  if (!inner) return null;
  return {
    async callTool(call) {
      const name = typeof call?.name === 'string' ? call.name : '';
      const args = (call?.arguments && typeof call.arguments === 'object' ? call.arguments : {}) as Record<string, JsonValue>;
      let raw: unknown;
      try {
        raw = await inner.callTool({ name, arguments: args });
      } catch (error) {
        // OpenUI logs and surfaces thrown errors; keep the message free of server text.
        if (error && typeof error === 'object' && (error as { name?: string }).name === 'ToolNotFoundError') throw error;
        raw = unavailableResult('read_failed');
      }
      return { content: [], structuredContent: normalizeQueryResult(raw) };
    },
  };
}
