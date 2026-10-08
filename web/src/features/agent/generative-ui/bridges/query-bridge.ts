/**
 * Lane D — the read-only query bridge of a generated view (rafii-genui/1, D-A12/D-A16/D-A29).
 *
 * Every read a generated subtree makes (OpenUI `Query()` through `toolProvider`, or a Rafii ToolBound* component through
 * `read`) goes through one place that:
 * - knows only the read bindings of the server manifest (own-key lookup in a prototype-free map; a write name, an
 *   unknown name or `constructor`/`__proto__` never reaches the network and reads as `denied`);
 * - exposes nothing until the revision is server-accepted (`toolProvider()` is `null` before), and nothing at all while
 *   the view is hidden, collapsed, historical or disposed (zero requests, no polling);
 * - bounds traffic: 4 concurrent requests per artifact, 60 admissions per minute, the same binding + arguments at most
 *   once per refresh interval (>= 30 s) unless invalidated, 300 ms debounce and abort of superseded text searches,
 *   exponential backoff after failures;
 * - caches by signed-in scope + artifact revision + binding + canonical arguments (+ cursor), cleared on dispose;
 * - keeps an honest per-binding status (`loading` while a request is in flight, otherwise the server's own state).
 *
 * The bridge never invents values. A failure is `unavailable` (or `stale` with the last real result), never an empty
 * list or zero.
 */
import {
  BOUNDS,
  canonicalJson,
  type JsonValue,
  type UiQueryResultV1,
  uiQueryResultSchema,
} from '@/lib/agent-runtime/ui-contracts';
import type { BindingStatus, QueryBridge, UiBridgeArtifact, UiTransport } from './types';

type QueryEntry = UiBridgeArtifact['manifest']['queries'][number];

export interface QueryBridgeTimers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface QueryBridgeOptions {
  transport: UiTransport;
  artifact: UiBridgeArtifact;
  now?: () => number;
  timers?: QueryBridgeTimers;
}

/** Names of a binding's free-text argument: calls that differ in it are debounced and superseded. */
const SEARCH_ARGS = new Set(['q', 'query', 'search', 'text']);
const MAX_BACKOFF_MS = 60_000;
const RATE_WINDOW_MS = 60_000;

interface CacheEntry {
  result: UiQueryResultV1;
  at: number;
  invalidated: boolean;
}

interface Waiter {
  run: () => void;
  cancel: () => void;
}

interface PendingSearch {
  timer: unknown;
  resolve: (value: UiQueryResultV1) => void;
  key: string;
}

function hasOwn(object: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

/** A result the bridge makes up locally is always a non-data state with a reason; never `available`/`empty`. */
export function localResult(state: 'denied' | 'unavailable', warning: string): UiQueryResultV1 {
  return {
    state,
    data: null,
    asOf: null,
    sourceRefs: [],
    revision: null,
    nextCursor: null,
    coverage: { known: null, total: null, note: null },
    warnings: [warning],
  };
}

function asStale(result: UiQueryResultV1, warning: string): UiQueryResultV1 {
  if (result.state === 'denied' || result.state === 'unavailable') return result;
  return { ...result, state: 'stale', warnings: [...result.warnings, warning].slice(0, 10) };
}

/** OpenUI's MCP-like tool result: `extractToolResult` prefers `structuredContent`. */
function wrap(result: UiQueryResultV1) {
  return { content: [] as never[], structuredContent: result };
}

const STATUS_MESSAGES: Record<number, string> = {
  400: 'This view asked for data in a way Rafii does not accept.',
  403: 'You no longer have access to this data.',
  404: 'This data is not available in this workspace.',
  409: 'This view changed since it was opened. Reload it to see current data.',
  413: 'This request was too large.',
  429: 'Too many updates at once. Rafii will try again shortly.',
};

function refreshMs(entry: QueryEntry): number {
  return Math.max(BOUNDS.refreshMinSeconds, entry.refreshMinSeconds ?? BOUNDS.refreshMinSeconds) * 1000;
}

async function parse(response: Response): Promise<UiQueryResultV1 | null> {
  try {
    const body: unknown = await response.json();
    const parsed = uiQueryResultSchema.safeParse(body);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export function createQueryBridge(options: QueryBridgeOptions): QueryBridge {
  const { transport, artifact } = options;
  const now = options.now ?? (() => Date.now());
  const timers: QueryBridgeTimers = options.timers ?? {
    setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
    clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>),
  };
  const scopeKey = transport.scopeKey;

  // Prototype-free read map: `Query("constructor")` or `Query("toString")` finds nothing.
  const bindings: Record<string, QueryEntry> = Object.create(null) as Record<string, QueryEntry>;
  for (const entry of artifact.manifest.queries) {
    if (typeof entry?.name === 'string' && /^[a-z][a-z0-9_]{1,63}$/.test(entry.name)) bindings[entry.name] = entry;
  }

  const cache = new Map<string, CacheEntry>();
  const inflight = new Map<string, Promise<UiQueryResultV1>>();
  const controllers = new Map<string, AbortController>();
  const searchControllers = new Map<string, AbortController>();
  const pendingSearch = new Map<string, PendingSearch>();
  const statuses = new Map<string, BindingStatus>();
  const failures = new Map<string, { count: number; until: number }>();
  const admissions: number[] = [];
  const queue: Waiter[] = [];
  const listeners = new Set<() => void>();
  let running = 0;
  let active = !artifact.historical;
  let disposed = false;

  const emit = () => {
    for (const listener of Array.from(listeners)) {
      try {
        listener();
      } catch {
        // A listener error never breaks the bridge.
      }
    }
  };

  const setStatus = (name: string, status: BindingStatus) => {
    if (statuses.get(name) === status) return;
    statuses.set(name, status);
    emit();
  };

  const binding = (name: string): QueryEntry | undefined => (hasOwn(bindings, name) ? bindings[name] : undefined);

  const searchArg = (entry: QueryEntry): string | null => {
    const schema = entry.argsSchema;
    const properties =
      schema && typeof schema === 'object' && !Array.isArray(schema) ? (schema as Record<string, JsonValue>).properties : null;
    if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return null;
    for (const key of Object.keys(properties)) {
      const spec = (properties as Record<string, JsonValue>)[key];
      if (SEARCH_ARGS.has(key) && spec && typeof spec === 'object' && !Array.isArray(spec) && spec.type === 'string') return key;
    }
    return null;
  };

  const cacheKey = (name: string, inputs: Record<string, JsonValue>, cursor: string | null) =>
    [scopeKey, artifact.artifactId, String(artifact.revision), name, canonicalJson(inputs), cursor ?? ''].join('\u0000');

  const scopeChanged = () => transport.scopeKey !== scopeKey;

  const admitRate = (): boolean => {
    const t = now();
    while (admissions.length && t - admissions[0] >= RATE_WINDOW_MS) admissions.shift();
    if (admissions.length >= BOUNDS.queryPerMinute) return false;
    admissions.push(t);
    return true;
  };

  /** Wait for one of the 4 concurrency slots (FIFO). Resolves false when the bridge stops first. */
  const slot = (): Promise<boolean> =>
    new Promise((resolve) => {
      const run = () => {
        running += 1;
        resolve(true);
      };
      if (running < BOUNDS.queryConcurrentPerArtifact) run();
      else queue.push({ run, cancel: () => resolve(false) });
    });

  const release = () => {
    running = Math.max(0, running - 1);
    const next = queue.shift();
    if (next) next.run();
  };

  const fallback = (key: string, warning: string): UiQueryResultV1 => {
    const hit = cache.get(key);
    return hit ? asStale(hit.result, warning) : localResult('unavailable', warning);
  };

  const recordFailure = (key: string, status: number | null) => {
    const prior = failures.get(key)?.count ?? 0;
    const count = prior + 1;
    const delay = status === 429 ? MAX_BACKOFF_MS : Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (count - 1));
    failures.set(key, { count, until: now() + delay });
  };

  const fetchOnce = async (
    name: string,
    key: string,
    inputs: Record<string, JsonValue>,
    cursor: string | null,
    outer?: AbortSignal,
    search?: boolean,
  ): Promise<UiQueryResultV1> => {
    if (!admitRate()) {
      recordFailure(key, 429);
      return fallback(key, 'Too many updates at once. Rafii will try again shortly.');
    }
    const ok = await slot();
    if (!ok) return fallback(key, 'This view is paused.');
    const controller = new AbortController();
    controllers.set(key, controller);
    if (search) searchControllers.set(name, controller);
    const onOuterAbort = () => controller.abort();
    outer?.addEventListener('abort', onOuterAbort, { once: true });
    setStatus(name, 'loading');
    try {
      if (disposed || !active || scopeChanged()) return fallback(key, 'This view is paused.');
      const body: JsonValue = {
        artifactId: artifact.artifactId,
        artifactRevision: artifact.revision,
        bindingId: name,
        inputs,
        cursor,
      };
      const response = await transport.fetch(`${transport.base}/queries`, { method: 'POST', body, signal: controller.signal });
      if (disposed || scopeChanged()) return localResult('unavailable', 'This view is no longer open.');
      if (!response.ok) {
        if (response.status === 404 || response.status === 403) {
          const denied = localResult('denied', STATUS_MESSAGES[response.status]);
          cache.set(key, { result: denied, at: now(), invalidated: false });
          return denied;
        }
        if (response.status === 409) return fallback(key, STATUS_MESSAGES[409]);
        recordFailure(key, response.status);
        return fallback(key, STATUS_MESSAGES[response.status] ?? 'Rafii could not load this data right now.');
      }
      const result = await parse(response);
      if (!result) {
        recordFailure(key, null);
        return fallback(key, 'Rafii received data it could not read.');
      }
      failures.delete(key);
      cache.set(key, { result, at: now(), invalidated: false });
      return result;
    } catch (error) {
      if (controller.signal.aborted) return fallback(key, 'This request was replaced by a newer one.');
      void error;
      recordFailure(key, null);
      return fallback(key, 'Rafii could not reach the server. It will try again shortly.');
    } finally {
      outer?.removeEventListener('abort', onOuterAbort);
      if (controllers.get(key) === controller) controllers.delete(key);
      if (search && searchControllers.get(name) === controller) searchControllers.delete(name);
      release();
    }
  };

  const settle = (name: string, result: UiQueryResultV1) => {
    setStatus(name, result.state);
    return result;
  };

  const track = (key: string, promise: Promise<UiQueryResultV1>) => {
    inflight.set(key, promise);
    promise
      .finally(() => {
        if (inflight.get(key) === promise) inflight.delete(key);
      })
      .catch(() => undefined);
  };

  const read = async (
    name: string,
    rawInputs: Record<string, JsonValue>,
    readOptions: { cursor?: string | null; signal?: AbortSignal } = {},
  ): Promise<UiQueryResultV1> => {
    const entry = binding(name);
    if (!entry) {
      // A write tool, an unknown name or an inherited property: denied locally, nothing is sent.
      return localResult('denied', 'This view asked for data it is not allowed to read.');
    }
    if (scopeChanged()) {
      dispose();
      return localResult('unavailable', 'You switched workspace or signed out.');
    }
    if (disposed || !artifact.accepted) {
      return localResult('unavailable', disposed ? 'This view is no longer open.' : 'This view is still being prepared.');
    }
    const inputs: Record<string, JsonValue> =
      rawInputs && typeof rawInputs === 'object' && !Array.isArray(rawInputs) ? rawInputs : {};
    let canonical: string;
    try {
      canonical = canonicalJson(inputs);
    } catch {
      return localResult('unavailable', 'This view asked for data in a way Rafii does not accept.');
    }
    if (new TextEncoder().encode(canonical).length > BOUNDS.inputBytes) {
      return localResult('unavailable', 'This request was too large.');
    }
    const cursor = readOptions.cursor ?? null;
    const key = cacheKey(name, inputs, cursor);
    const hit = cache.get(key);
    if (!active) {
      // Hidden, collapsed or historical: zero network. The last real result (if any) is shown as stale.
      return hit ? asStale(hit.result, 'Paused while this view is not visible.') : localResult('unavailable', 'This view is paused.');
    }
    if (hit && !hit.invalidated && now() - hit.at < refreshMs(entry)) return settle(name, hit.result);
    const backoff = failures.get(key);
    if (backoff && now() < backoff.until) return settle(name, fallback(key, 'Rafii will try again shortly.'));
    const pendingRead = inflight.get(key);
    if (pendingRead) return pendingRead;

    const search = searchArg(entry);
    if (search) {
      // Text search: debounce 300 ms per binding and abort the superseded request.
      const prior = pendingSearch.get(name);
      if (prior) {
        timers.clearTimeout(prior.timer);
        pendingSearch.delete(name);
        prior.resolve(fallback(prior.key, 'This request was replaced by a newer one.'));
      }
      const previous = searchControllers.get(name);
      if (previous && controllers.get(key) !== previous) previous.abort();
      const promise = new Promise<UiQueryResultV1>((resolve) => {
        const timer = timers.setTimeout(() => {
          pendingSearch.delete(name);
          if (disposed || !active) {
            resolve(fallback(key, 'This view is paused.'));
            return;
          }
          fetchOnce(name, key, inputs, cursor, readOptions.signal, true).then((result) => resolve(settle(name, result)));
        }, BOUNDS.searchDebounceMs);
        pendingSearch.set(name, { timer, resolve, key });
      });
      track(key, promise);
      return promise;
    }

    const promise = fetchOnce(name, key, inputs, cursor, readOptions.signal, false).then((result) => settle(name, result));
    track(key, promise);
    return promise;
  };

  const abortAll = (reason: string) => {
    for (const pending of pendingSearch.values()) {
      timers.clearTimeout(pending.timer);
      pending.resolve(fallback(pending.key, reason));
    }
    pendingSearch.clear();
    for (const controller of controllers.values()) controller.abort();
    controllers.clear();
    searchControllers.clear();
    while (queue.length) queue.shift()?.cancel();
  };

  function dispose() {
    if (disposed) return;
    disposed = true;
    abortAll('This view is no longer open.');
    cache.clear();
    inflight.clear();
    failures.clear();
    statuses.clear();
    emit();
    listeners.clear();
  }

  const provider = {
    async callTool(call: { name: string; arguments?: Record<string, JsonValue> }) {
      const name = call && typeof call.name === 'string' ? call.name : '';
      return wrap(await read(name, call?.arguments ?? {}));
    },
  };

  return {
    toolProvider() {
      return artifact.accepted && !disposed ? provider : null;
    },
    read,
    status(name: string) {
      return hasOwn(bindings, name) ? statuses.get(name) : undefined;
    },
    subscribe(listener: () => void) {
      if (disposed) return () => undefined;
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setActive(next: boolean) {
      if (disposed || active === next) return;
      active = next;
      if (!active) abortAll('Paused while this view is not visible.');
      emit();
    },
    invalidate(keys: string[]) {
      if (disposed) return;
      const names = new Set((Array.isArray(keys) ? keys : []).filter((k): k is string => typeof k === 'string'));
      const all = names.has('*');
      for (const [key, entry] of cache) {
        const name = key.split('\u0000')[3];
        if (all || names.has(name)) {
          entry.invalidated = true;
          failures.delete(key);
        }
      }
      emit();
    },
    dispose,
  };
}
