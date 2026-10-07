/**
 * Browser client for the founder admin API (`/api/control/v2/*`, CONTRACTS §3 and §6).
 *
 * Boundaries it keeps: the `__Host-rafii-control` cookie travels with `credentials: 'same-origin'` and nothing else
 * identifies the operator; every non-GET carries the CSRF token read once from `GET /session`; agent turns carry an
 * `Idempotency-Key`; a 401 sends the person to `/founder/sign-in`; and every failure surfaces fixed copy from
 * `errors.ts`, never a server-written sentence. Nothing here computes a number: values arrive with their unit,
 * coverage and receipt and are only displayed.
 */
import { CONTROL_COOKIE, FOUNDER_HOME, FOUNDER_SIGN_IN_PATH, FounderApiError, founderErrorMessage } from './errors';
import type {
  BriefingSchedule,
  BriefingScheduleBody,
  ContactPolicy,
  DemoActionBody,
  DemoActionResult,
  Envelope,
  FollowUpWriteBody,
  FounderAgentRun,
  FounderAgentTurnRequest,
  FounderAgentTurnResponse,
  FounderConversationState,
  FounderFollowUp,
  FounderIncident,
  FounderMode,
  FounderSession,
  FounderWorkspaceData,
  MetricQueryBody,
  MetricQueryResult,
  MetricReceipt,
  Overview,
  OverviewPeriod,
  UnknownUsage
} from './types';

export { CONTROL_COOKIE, FOUNDER_HOME, FOUNDER_SIGN_IN_PATH };

export const FOUNDER_API_BASE = '/api/control/v2';
/** The exchange route is the only call that sends a bearer token; this header marks it (http.py `/session/exchange`). */
export const CONTROL_EXCHANGE_HEADER = { 'X-Control-Exchange': '1' } as const;

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface FounderFetchInit {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export interface FounderApiOptions {
  fetch?: FetchLike;
  /** Called with the sign-in href on a 401; the default replaces the page. */
  onUnauthorized?: (href: string) => void;
  /** The current path for the sign-in `next` parameter; the default reads `window.location`. */
  currentPath?: () => string;
  newKey?: () => string;
}

/** Only founder pages are valid return targets after sign-in; anything else lands on the Overview. */
export function safeFounderNext(input: string | null | undefined): string {
  if (!input || !input.startsWith('/founder') || input.startsWith('//') || /[\s\\]/.test(input)) return FOUNDER_HOME;
  if (input === FOUNDER_SIGN_IN_PATH || input.startsWith(`${FOUNDER_SIGN_IN_PATH}?`)) return FOUNDER_HOME;
  const rest = input.slice('/founder'.length);
  if (rest && !/^[/?#]/.test(rest)) return FOUNDER_HOME;
  return input;
}

export function signInHref(current?: string | null): string {
  const next = safeFounderNext(current);
  return next === FOUNDER_HOME ? FOUNDER_SIGN_IN_PATH : `${FOUNDER_SIGN_IN_PATH}?next=${encodeURIComponent(next)}`;
}

export function randomKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function defaultPath(): string {
  return typeof window === 'undefined' ? FOUNDER_HOME : `${window.location.pathname}${window.location.search}`;
}

function defaultUnauthorized(href: string) {
  if (typeof window !== 'undefined') window.location.assign(href);
}

/** The control envelope, or a bare payload (a 201/202 answer) wrapped so callers see one shape. */
function unwrap<T>(json: unknown, fallbackState: Envelope<T>['dataState'] = 'measured'): Envelope<T> {
  if (json && typeof json === 'object' && 'data' in json && 'requestId' in json) return json as Envelope<T>;
  return { requestId: '', environment: 'local', asOf: '', dataState: fallbackState, receiptIds: [], data: json as T };
}

const CSRF_CODES = new Set(['CSRF_REQUIRED', 'CSRF_INVALID']);

async function readJson(res: Response): Promise<Record<string, unknown>> {
  try {
    const body = (await res.json()) as unknown;
    return body && typeof body === 'object' ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function modeQuery(mode: FounderMode, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({ mode, ...extra });
  return `?${params.toString()}`;
}

export function createFounderApi(options: FounderApiOptions = {}) {
  const doFetch: FetchLike = options.fetch ?? ((input, init) => fetch(input, init));
  const onUnauthorized = options.onUnauthorized ?? defaultUnauthorized;
  const currentPath = options.currentPath ?? defaultPath;
  const newKey = options.newKey ?? randomKey;

  /** The CSRF token is read once per page from `GET /session` and shared by every mutation. */
  let csrf: Promise<string> | null = null;
  /** A mutation retried with the same payload reuses its request id, so the server can answer idempotently. */
  const pending = new Map<string, { signature: string; key: string }>();

  async function fail(res: Response): Promise<never> {
    const body = await readJson(res);
    const code = typeof body.code === 'string' ? body.code : undefined;
    const requestId = typeof body.requestId === 'string' ? body.requestId : undefined;
    const blocker = typeof body.blocker === 'string' ? body.blocker : undefined;
    if (res.status === 401) {
      csrf = null;
      onUnauthorized(signInHref(currentPath()));
    }
    if (code && CSRF_CODES.has(code)) csrf = null;
    throw new FounderApiError(founderErrorMessage(res.status, code), res.status, code, requestId, blocker);
  }

  async function raw(method: string, path: string, body?: unknown, extra: Record<string, string> = {}, init: RequestInit = {}): Promise<Response> {
    const headers: Record<string, string> = { ...extra };
    const unsafe = method !== 'GET';
    if (unsafe) {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = await csrfToken();
    }
    return doFetch(FOUNDER_API_BASE + path, {
      ...init,
      method,
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
      ...(unsafe ? { body: JSON.stringify(body ?? {}) } : {})
    });
  }

  async function request<T>(method: string, path: string, body?: unknown, extra: Record<string, string> = {}, init: RequestInit = {}): Promise<Envelope<T>> {
    const res = await raw(method, path, body, extra, init);
    if (!res.ok) return fail(res);
    if (res.status === 204) return unwrap<T>(undefined);
    return unwrap<T>(await res.json());
  }

  /** `GET /session` is the only unauthenticated-looking read: it is what proves the cookie and hands out the CSRF token. */
  async function session(): Promise<Envelope<FounderSession>> {
    const res = await doFetch(`${FOUNDER_API_BASE}/session`, { method: 'GET', credentials: 'same-origin', cache: 'no-store' });
    if (!res.ok) return fail(res);
    const envelope = unwrap<FounderSession>(await res.json());
    csrf = Promise.resolve(envelope.data.csrfToken);
    return envelope;
  }

  function csrfToken(): Promise<string> {
    if (!csrf) {
      csrf = session().then((envelope) => envelope.data.csrfToken);
      csrf.catch(() => {
        csrf = null;
      });
    }
    return csrf;
  }

  /** The request id for an idempotent mutation: stable while the same payload is retried, new once it changes. */
  function stableKey(operation: string, payload: unknown): string {
    const signature = JSON.stringify(payload);
    const current = pending.get(operation);
    if (current && current.signature === signature) return current.key;
    const key = newKey();
    pending.set(operation, { signature, key });
    return key;
  }

  return {
    session,
    /** Forget the cached CSRF token (after sign-out, or when a test needs a fresh session read). */
    resetSession() {
      csrf = null;
    },
    overview: (mode: FounderMode, period: OverviewPeriod = '30d', init?: RequestInit) => request<Overview>('GET', `/overview${modeQuery(mode, { period })}`, undefined, {}, init),
    workspace: (mode: FounderMode, init?: RequestInit) => request<FounderWorkspaceData>('GET', `/workspace/${mode}`, undefined, {}, init),
    /** Demo-only state changes (scenario, reset): the revision proves what the person saw; a retry reuses its request id. */
    async demoAction(action: string, targetId: string, value: string, revision: number) {
      const payload = { action, targetId, value, revision };
      const body: DemoActionBody = { ...payload, requestId: stableKey(`demo:${action}:${targetId}`, payload) };
      const result = await request<DemoActionResult>('POST', '/workspace/demo/action', body);
      if (result.data.mode !== 'demo' || typeof result.data.revision !== 'number' || result.data.revision <= revision) {
        throw new FounderApiError('The save response could not be verified. Retry the same action.', 409, 'UNVERIFIED_RESPONSE', result.requestId);
      }
      pending.delete(`demo:${action}:${targetId}`);
      return result;
    },
    /** `POST /metrics/query` answers with the receipt body itself (no envelope); returned as sent. */
    async metricsQuery(body: MetricQueryBody, mode: FounderMode, init?: RequestInit): Promise<MetricQueryResult> {
      const res = await raw('POST', `/metrics/query${modeQuery(mode)}`, body, {}, init);
      if (!res.ok) return fail(res);
      return (await res.json()) as MetricQueryResult;
    },
    /**
     * Raw fetch for callers that want the JSON exactly as the server sent it (envelope or receipt body): JSON bodies,
     * CSRF on non-GET, same-origin credentials, 401 → sign-in, fixed error copy. Used by the domain pages' hooks.
     */
    async fetch<T>(path: string, init: FounderFetchInit = {}): Promise<T> {
      const method = init.method ?? (init.body === undefined ? 'GET' : 'POST');
      const res = await raw(method, path, init.body, init.headers ?? {}, init.signal ? { signal: init.signal } : {});
      if (!res.ok) return fail(res);
      if (res.status === 204) return undefined as T;
      return (await res.json()) as T;
    },
    receipt: (id: string, init?: RequestInit) => request<{ receipt: MetricReceipt }>('GET', `/metrics/receipts/${encodeURIComponent(id)}`, undefined, {}, init),
    usageUnknown: (mode: FounderMode, init?: RequestInit) => request<UnknownUsage>('GET', `/usage/unknown${modeQuery(mode)}`, undefined, {}, init),
    incidents: (mode: FounderMode, init?: RequestInit) => request<{ incidents: FounderIncident[] }>('GET', `/incidents${modeQuery(mode)}`, undefined, {}, init),
    /**
     * Acknowledges one exact incident version (stops escalation; not "resolved"). The data mode travels in the query, the
     * only place the server reads it (`http.query_mode`); a Demo ack is answered 400 there rather than written to Live.
     */
    ackIncident: (id: string, version: number, mode: FounderMode) => request<{ incident: FounderIncident }>('POST', `/incidents/${encodeURIComponent(id)}/ack${modeQuery(mode)}`, { version }),
    followUps: (init?: RequestInit) => request<{ followUps: FounderFollowUp[] }>('GET', '/follow-ups', undefined, {}, init),
    createFollowUp: (body: FollowUpWriteBody) => request<{ followUp: FounderFollowUp }>('POST', '/follow-ups', body),
    updateFollowUp: (id: string, body: FollowUpWriteBody) => request<{ followUp: FounderFollowUp }>('POST', `/follow-ups/${encodeURIComponent(id)}`, body),
    contactPolicy: (init?: RequestInit) => request<{ policy: ContactPolicy }>('GET', '/contact-policy', undefined, {}, init),
    saveContactPolicy: (body: Partial<ContactPolicy> & { revision: number }) => request<{ policy: ContactPolicy }>('PUT', '/contact-policy', body),
    briefingSchedules: (init?: RequestInit) => request<{ schedules: BriefingSchedule[] }>('GET', '/briefing-schedules', undefined, {}, init),
    createBriefingSchedule: (body: BriefingScheduleBody) => request<{ schedule: BriefingSchedule }>('POST', '/briefing-schedules', body),
    deleteBriefingSchedule: (id: string) => request<{ deleted: boolean }>('DELETE', `/briefing-schedules/${encodeURIComponent(id)}`),
    /** Always answers 409 POLICY_DISABLED until live delivery is enabled and a provider is configured. */
    testCall: (body: { requestId: string }) => request<{ attempt: { id: string; state: string; phoneCallId: string | null }; replayed: boolean }>('POST', '/calls/test', body),
    /** One founder turn; the `Idempotency-Key` equals the body's key so a resend of the same message is one run. */
    agentTurn: (body: FounderAgentTurnRequest, init?: RequestInit) => request<FounderAgentTurnResponse>('POST', '/agent/turns', body, { 'Idempotency-Key': body.idempotencyKey }, init),
    agentRun: (runId: string, init?: RequestInit) => request<FounderAgentRun>('GET', `/agent/runs/${encodeURIComponent(runId)}`, undefined, {}, init),
    conversationState: (conversationId: string, init?: RequestInit) => request<FounderConversationState>('GET', `/agent/conversations/${encodeURIComponent(conversationId)}/state`, undefined, {}, init),
    cancelRun: (runId: string) => request<{ cancelled: boolean }>('POST', `/agent/runs/${encodeURIComponent(runId)}/cancel`),
    async logout() {
      const result = await request<{ loggedOut: boolean }>('POST', '/session/logout');
      csrf = null;
      return result;
    }
  };
}

export type FounderApi = ReturnType<typeof createFounderApi>;

/** One client per page load, shared by the shell's session provider and the domain pages' hooks. */
let defaultApi: FounderApi | null = null;
export function founderApi(): FounderApi {
  if (!defaultApi) defaultApi = createFounderApi();
  return defaultApi;
}

/** `founderFetch<T>(path, init?)`: the shared client's raw fetch (CSRF, credentials, 401 → sign-in, fixed copy). */
export function founderFetch<T>(path: string, init?: FounderFetchInit): Promise<T> {
  return founderApi().fetch<T>(path, init);
}

/** React Query keys: `['founder', mode, environment, …]` so a mode or environment switch never shares cache. */
export const founderKeys = {
  session: ['founder', 'session'] as const,
  overview: (mode: FounderMode, environment: string, period: OverviewPeriod) => ['founder', mode, environment, 'overview', period] as const,
  workspace: (mode: FounderMode, environment: string) => ['founder', mode, environment, 'workspace'] as const,
  metrics: (mode: FounderMode, environment: string, body: MetricQueryBody) => ['founder', mode, environment, 'metrics', body] as const,
  receipt: (environment: string, id: string) => ['founder', 'receipt', environment, id] as const,
  usageUnknown: (mode: FounderMode, environment: string) => ['founder', mode, environment, 'usage-unknown'] as const,
  incidents: (mode: FounderMode, environment: string) => ['founder', mode, environment, 'incidents'] as const,
  followUps: (environment: string) => ['founder', 'follow-ups', environment] as const,
  contactPolicy: (environment: string) => ['founder', 'contact-policy', environment] as const,
  briefingSchedules: (environment: string) => ['founder', 'briefing-schedules', environment] as const,
  conversationState: (mode: FounderMode, environment: string, id: string) => ['founder', mode, environment, 'conversation', id] as const
};
