'use client';

/**
 * rafii-genui/1 stream client (lane F; 02-CONTRACTS §4, A-DECISIONS D-A6, D-A36, D-A41).
 *
 * - `createSseParser`: an incremental `text/event-stream` parser over raw bytes. Frames may split anywhere, including inside
 *   a multi-byte UTF-8 character: bytes go through one `TextDecoder` with `{stream: true}`, lines are cut on CRLF/LF/CR (a CR
 *   at a chunk edge waits for its LF), and an unfinished frame at end of stream is dropped, as the SSE standard says.
 * - `UiArtifactStream`: one artifact's event stream. It reads the POST /presentations response it is handed, or replays with
 *   `GET …/presentations/{id}/events?after={lastSeq}` (authorized replay + bounded live tail); it NEVER creates a presentation
 *   or starts a generation, on mount or on reconnect. Heartbeats are liveness only and handled before seq de-duplication
 *   (they reuse the last seq, D-A36); older seqs are ignored; a seq gap triggers one replay from the last applied seq (a gap
 *   left by compacted deltas of a finished attempt is accepted once the replay confirms it); reconnects back off; a terminal
 *   event ends it; `setActive(false)` (hidden tab or artifact) stops all network use until shown again; `dispose()` aborts.
 * - Transports implement the frozen `UiTransport`: consumer = Bearer + X-PostRiff-Request (no credentials in URLs); founder =
 *   `__Host-rafii-control` cookie + CSRF, with the control envelope unwrapped so bridges see plain bodies. Paths are full paths
 *   already built from `transport.base` (D-A41); the transport only adds auth and serializes the JSON body.
 */
import { useEffect, useRef, useState } from 'react';
import type { JsonValue, UiEventV1 } from '@/lib/agent-runtime/ui-contracts';
import { isTerminalEvent, uiEventSchema } from '@/lib/agent-runtime/ui-contracts';
import type { UiTransport } from '@/features/agent/generative-ui/bridges/types';

/** The request guard every consumer call carries (same value as `APP_GUARD_HEADER` in lib/api/client.ts). */
export const UI_GUARD_HEADER = { 'X-PostRiff-Request': 'founder-alpha' } as const;
const MAX_LINE_CHARS = 512 * 1024;

export interface SseFrame {
  event: string;
  data: string;
  id: string | null;
  retry: number | null;
}

export interface SseParser {
  push(chunk: Uint8Array): SseFrame[];
  end(): SseFrame[];
}

export function createSseParser(): SseParser {
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let event = '';
  let data: string[] = [];
  let id: string | null = null;
  let retry: number | null = null;
  let hasData = false;

  const line = (text: string, out: SseFrame[]) => {
    if (text === '') {
      if (hasData) out.push({ event: event || 'message', data: data.join('\n'), id, retry });
      event = '';
      data = [];
      hasData = false;
      retry = null;
      return;
    }
    if (text.startsWith(':')) return;
    const colon = text.indexOf(':');
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? '' : text.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') event = value;
    else if (field === 'data') {
      data.push(value);
      hasData = true;
    } else if (field === 'id') {
      if (!value.includes('\u0000')) id = value;
    } else if (field === 'retry') {
      if (/^\d{1,7}$/.test(value)) retry = Number(value);
    }
  };

  const drain = (final: boolean): SseFrame[] => {
    const out: SseFrame[] = [];
    let start = 0;
    for (let i = 0; i < buffer.length; i += 1) {
      const ch = buffer.charCodeAt(i);
      if (ch === 10 || ch === 13) {
        if (ch === 13 && i === buffer.length - 1 && !final) break; // a CR at the edge may be the first half of CRLF
        line(buffer.slice(start, i), out);
        if (ch === 13 && buffer.charCodeAt(i + 1) === 10) i += 1;
        start = i + 1;
      }
    }
    buffer = buffer.slice(start);
    if (buffer.length > MAX_LINE_CHARS) throw new Error('ui_stream_line_too_long');
    return out;
  };

  return {
    push(chunk: Uint8Array) {
      buffer += decoder.decode(chunk, { stream: true });
      return drain(false);
    },
    end() {
      buffer += decoder.decode();
      const out = drain(true);
      // An unterminated frame at end of stream is not dispatched.
      buffer = '';
      event = '';
      data = [];
      hasData = false;
      return out;
    }
  };
}

/** A frame's UiEventV1, or null when it is not one (comments, probes, malformed JSON, schema mismatch). */
export function parseUiEvent(frame: SseFrame): UiEventV1 | null {
  if (!frame.data) return null;
  try {
    const parsed = uiEventSchema.safeParse(JSON.parse(frame.data));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export type UiStreamStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'paused' | 'done' | 'failed' | 'closed';

export interface UiArtifactStreamOptions {
  transport: UiTransport;
  artifactId: string;
  afterSeq?: number;
  /** Ordered, de-duplicated events (no heartbeats). */
  onEvent: (event: UiEventV1) => void;
  onStatus?: (status: UiStreamStatus, detail?: { code?: string | null; httpStatus?: number }) => void;
  onHeartbeat?: () => void;
  /** Called when the artifact id becomes known from a POST /presentations stream. */
  onArtifact?: (artifactId: string) => void;
  maxReconnects?: number;
  timers?: { setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (handle: unknown) => void };
  random?: () => number;
}

const TERMINAL_STATUSES = new Set<UiStreamStatus>(['done', 'failed', 'closed']);

export class UiArtifactStream {
  private opts: UiArtifactStreamOptions;
  private controller: AbortController | null = null;
  private timer: unknown = null;
  private attempts = 0;
  private active = true;
  private terminalSeen = new Set<string>();
  /** A replay connection reads the durable log in seq order: what it returns is complete (gaps are compacted or rolled-back seqs). */
  private replaying = false;
  status: UiStreamStatus = 'idle';
  lastSeq: number;
  artifactId: string;

  constructor(opts: UiArtifactStreamOptions) {
    this.opts = opts;
    this.artifactId = opts.artifactId;
    this.lastSeq = Math.max(0, Math.floor(opts.afterSeq ?? 0));
  }

  private set(status: UiStreamStatus, detail?: { code?: string | null; httpStatus?: number }) {
    this.status = status;
    this.opts.onStatus?.(status, detail);
  }

  private get timers() {
    return this.opts.timers ?? { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>) };
  }

  /** Replay + live tail of an existing artifact. Never creates or regenerates anything. */
  connect(): void {
    if (TERMINAL_STATUSES.has(this.status)) return;
    if (!this.artifactId) {
      // A POST stream that ended before naming its artifact has nothing to replay.
      this.set('failed', { code: 'ui_stream_empty' });
      return;
    }
    if (!this.active) {
      this.set('paused');
      return;
    }
    this.abortCurrent();
    const controller = new AbortController();
    this.controller = controller;
    this.replaying = true;
    this.set(this.attempts > 0 ? 'reconnecting' : 'connecting');
    const path = `${this.opts.transport.base}/presentations/${encodeURIComponent(this.artifactId)}/events?after=${this.lastSeq}`;
    void this.opts.transport
      .fetch(path, { method: 'GET', signal: controller.signal })
      .then((response) => this.read(response, controller))
      .catch((error: unknown) => this.onDisconnect(controller, error, false));
  }

  /** Read a stream someone already opened (the one POST /presentations of a fresh turn). */
  consume(response: Response): void {
    if (TERMINAL_STATUSES.has(this.status)) return;
    this.abortCurrent();
    const controller = new AbortController();
    this.controller = controller;
    this.replaying = false;
    this.set('connecting');
    void this.read(response, controller).catch((error: unknown) => this.onDisconnect(controller, error, false));
  }

  setActive(active: boolean): void {
    if (this.active === active) return;
    this.active = active;
    if (!active) {
      this.abortCurrent();
      if (!TERMINAL_STATUSES.has(this.status)) this.set('paused');
    } else if (this.status === 'paused' && this.artifactId) {
      this.attempts = 0;
      this.connect();
    }
  }

  dispose(): void {
    this.abortCurrent();
    if (this.status !== 'done' && this.status !== 'failed') this.set('closed');
  }

  private abortCurrent() {
    if (this.timer !== null) {
      this.timers.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
  }

  private async read(response: Response, controller: AbortController): Promise<void> {
    if (controller.signal.aborted) return;
    if (!response.ok) {
      let code: string | null = null;
      try {
        const body = (await response.json()) as { code?: unknown };
        code = typeof body?.code === 'string' ? body.code : null;
      } catch {
        /* no body */
      }
      // Authorization and scope refusals end the stream; only transient failures retry.
      const transient = response.status >= 500 || response.status === 429 || response.status === 408;
      if (!transient) {
        this.set('failed', { code, httpStatus: response.status });
        return;
      }
      this.onDisconnect(controller, new Error(`http_${response.status}`), false);
      return;
    }
    const type = response.headers.get('content-type') ?? '';
    if (!type.includes('text/event-stream') || !response.body) {
      this.set('failed', { code: 'ui_stream_type', httpStatus: response.status });
      return;
    }
    this.set('open');
    const reader = response.body.getReader();
    const parser = createSseParser();
    let progressed = false;
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (controller.signal.aborted) return;
        const frames = done ? parser.end() : parser.push(value ?? new Uint8Array());
        for (const frame of frames) {
          const outcome = this.apply(frame);
          if (outcome === 'progress') progressed = true;
          if (outcome === 'gap') {
            controller.abort();
            this.controller = null;
            this.attempts = 0;
            this.connect();
            return;
          }
          if (this.status === 'done') {
            controller.abort();
            return;
          }
        }
        if (done) break;
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {
        /* already released */
      }
    }
    this.onDisconnect(controller, null, progressed);
  }

  /** One frame: heartbeat first (liveness only), then seq de-duplication and gap detection, then the event. */
  private apply(frame: SseFrame): 'progress' | 'ignored' | 'gap' {
    const event = parseUiEvent(frame);
    if (!event) return 'ignored';
    if (event.kind === 'ui.heartbeat') {
      this.opts.onHeartbeat?.();
      return 'progress';
    }
    if (!this.artifactId) {
      this.artifactId = event.artifactId;
      this.opts.onArtifact?.(event.artifactId);
    }
    if (event.artifactId !== this.artifactId) return 'ignored';
    const terminalKey = isTerminalEvent(event.kind) ? `${event.attemptId ?? ''}:${event.kind}` : null;
    if (event.seq <= this.lastSeq) {
      // An unpersisted terminal frame may reuse the last seq (the producer could not write it): apply it once.
      if (terminalKey && !this.terminalSeen.has(terminalKey) && event.seq === this.lastSeq) {
        this.terminalSeen.add(terminalKey);
        this.opts.onEvent(event);
        this.finishIfTerminal(event);
        return 'progress';
      }
      return 'ignored';
    }
    if (!this.replaying && this.lastSeq > 0 && event.seq > this.lastSeq + 1) {
      // A producer stream skipped seqs (another tab's state change, a repair's bookkeeping): replay the durable log from here.
      return 'gap';
    }
    this.lastSeq = event.seq;
    if (terminalKey) this.terminalSeen.add(terminalKey);
    this.opts.onEvent(event);
    this.finishIfTerminal(event);
    return 'progress';
  }

  private finishIfTerminal(event: UiEventV1) {
    if (!isTerminalEvent(event.kind)) return;
    // A repair follows a failed attempt inside the same stream; the stream ends only on its own close or a final ready.
    if (event.kind === 'ui.failed' && (event.payload as { repairing?: JsonValue })?.repairing === true) return;
    this.abortCurrent();
    this.set('done');
  }

  private onDisconnect(controller: AbortController, error: unknown, progressed: boolean) {
    if (controller.signal.aborted && this.controller !== controller) return;
    if (TERMINAL_STATUSES.has(this.status)) return;
    if (!this.active) {
      this.set('paused');
      return;
    }
    if (error && (error as { name?: string }).name === 'AbortError') return;
    if (progressed) this.attempts = 0;
    this.attempts += 1;
    const max = this.opts.maxReconnects ?? 8;
    if (this.attempts > max) {
      this.set('failed', { code: 'ui_stream_unreachable' });
      return;
    }
    // A replay tail that closed normally reconnects promptly; failures back off exponentially with jitter, capped at 15 s.
    const base = progressed ? 250 : Math.min(15_000, 500 * 2 ** (this.attempts - 1));
    const jitter = Math.floor((this.opts.random ?? Math.random)() * 250);
    this.set('reconnecting');
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      this.connect();
    }, base + jitter);
  }
}

/**
 * The founder transport cannot stream (the control app answers one JSON body, D-A22): poll the durable replay
 * `GET …/presentations/{id}/events?after=` once a second while the view is visible and not finished. Same ordering rules as the
 * stream (older seqs ignored, terminal ends it); never creates or regenerates anything.
 */
export class UiArtifactPoller {
  private opts: UiArtifactStreamOptions & { intervalMs?: number };
  private controller: AbortController | null = null;
  private timer: unknown = null;
  private failures = 0;
  private active = true;
  status: UiStreamStatus = 'idle';
  lastSeq: number;
  artifactId: string;

  constructor(opts: UiArtifactStreamOptions & { intervalMs?: number }) {
    this.opts = opts;
    this.artifactId = opts.artifactId;
    this.lastSeq = Math.max(0, Math.floor(opts.afterSeq ?? 0));
  }

  private get timers() {
    return this.opts.timers ?? { setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms), clearTimeout: (h: unknown) => clearTimeout(h as ReturnType<typeof setTimeout>) };
  }

  private set(status: UiStreamStatus, detail?: { code?: string | null; httpStatus?: number }) {
    this.status = status;
    this.opts.onStatus?.(status, detail);
  }

  connect(): void {
    if (TERMINAL_STATUSES.has(this.status) || !this.artifactId) return;
    if (!this.active) {
      this.set('paused');
      return;
    }
    this.stop();
    const controller = new AbortController();
    this.controller = controller;
    if (this.status === 'idle') this.set('connecting');
    const path = `${this.opts.transport.base}/presentations/${encodeURIComponent(this.artifactId)}/events?after=${this.lastSeq}`;
    void this.opts.transport.fetch(path, { method: 'GET', signal: controller.signal }).then(async (response) => {
      if (controller.signal.aborted) return;
      const body = (await response.json().catch(() => ({}))) as { events?: unknown[]; done?: boolean; code?: string };
      if (!response.ok) {
        if (response.status >= 500 || response.status === 429) return this.again(controller, false);
        this.set('failed', { code: typeof body.code === 'string' ? body.code : null, httpStatus: response.status });
        return;
      }
      this.set('open');
      for (const raw of body.events ?? []) {
        const parsed = uiEventSchema.safeParse(raw);
        if (!parsed.success || parsed.data.kind === 'ui.heartbeat' || parsed.data.seq <= this.lastSeq) continue;
        this.lastSeq = parsed.data.seq;
        this.opts.onEvent(parsed.data);
        if (isTerminalEvent(parsed.data.kind)) {
          this.set('done');
          return;
        }
      }
      if (body.done) {
        this.set('done');
        return;
      }
      this.again(controller, true);
    }).catch((error: unknown) => {
      if ((error as { name?: string })?.name === 'AbortError') return;
      this.again(controller, false);
    });
  }

  private again(controller: AbortController, ok: boolean) {
    if (this.controller !== controller || TERMINAL_STATUSES.has(this.status)) return;
    this.failures = ok ? 0 : this.failures + 1;
    if (this.failures > (this.opts.maxReconnects ?? 8)) {
      this.set('failed', { code: 'ui_stream_unreachable' });
      return;
    }
    const delay = ok ? (this.opts.intervalMs ?? 1000) : Math.min(15_000, 1000 * 2 ** this.failures);
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }

  /** A founder POST answers JSON, never a stream: release it and poll the durable replay instead. */
  consume(response: Response): void {
    void response.body?.cancel().catch(() => undefined);
    this.connect();
  }

  setActive(active: boolean): void {
    if (this.active === active) return;
    this.active = active;
    if (!active) {
      this.stop();
      if (!TERMINAL_STATUSES.has(this.status)) this.set('paused');
    } else if (this.status === 'paused') this.connect();
  }

  private stop() {
    if (this.timer !== null) {
      this.timers.clearTimeout(this.timer);
      this.timer = null;
    }
    this.controller?.abort();
    this.controller = null;
  }

  dispose(): void {
    this.stop();
    if (this.status !== 'done' && this.status !== 'failed') this.set('closed');
  }
}

export type UiEventSource = Pick<UiArtifactStream, 'connect' | 'consume' | 'setActive' | 'dispose' | 'status' | 'lastSeq' | 'artifactId'>;

/** The event source for a transport: SSE for consumer routes, polling replay for founder routes. */
export function createUiEventSource(opts: UiArtifactStreamOptions): UiEventSource {
  return opts.transport.scope === 'founder' ? new UiArtifactPoller(opts) : new UiArtifactStream(opts);
}

// --- transports (frozen UiTransport) -------------------------------------------------------------------------------------
type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** Consumer transport: `/api/workspaces/{id}/agent/ui`, Bearer token from the session, the request guard, no cookies needed. */
export function createConsumerUiTransport(options: { workspaceId: string; principal: string | null; getToken: () => Promise<string | null>; fetch?: FetchLike }): UiTransport {
  const doFetch: FetchLike = options.fetch ?? ((input, init) => fetch(input, init));
  return {
    base: `/api/workspaces/${encodeURIComponent(options.workspaceId)}/agent/ui`,
    scope: 'workspace',
    scopeKey: `workspace:${options.principal ?? 'anon'}:${options.workspaceId}`,
    async fetch(path, init) {
      const token = await options.getToken();
      if (!token) return new Response(JSON.stringify({ error: 'Your session ended. Sign in again.', code: 'unauthenticated' }), { status: 401, headers: { 'content-type': 'application/json' } });
      const headers: Record<string, string> = { ...UI_GUARD_HEADER, Authorization: `Bearer ${token}` };
      if (init.body !== undefined) headers['Content-Type'] = 'application/json';
      return doFetch(path, { method: init.method, headers, cache: 'no-store', credentials: 'same-origin', signal: init.signal,
        ...(init.body !== undefined ? { body: JSON.stringify(init.body) } : {}) });
    }
  };
}

const CSRF_CODES = new Set(['CSRF_REQUIRED', 'CSRF_INVALID']);

/** Founder transport: `/api/control/v2/agent/ui`, the control cookie plus CSRF on every POST; the control envelope's `data` is
 * returned as the body (errors as `{error, code, blocker}`), so the same bridges and state code read both scopes. */
export function createFounderUiTransport(options: { mode: string; environment: string | null; principal: string | null; csrf: () => Promise<string>; resetCsrf?: () => void;
  fetch?: FetchLike }): UiTransport {
  const doFetch: FetchLike = options.fetch ?? ((input, init) => fetch(input, init));
  return {
    base: '/api/control/v2/agent/ui',
    scope: 'founder',
    scopeKey: `founder:${options.principal ?? 'operator'}:${options.mode}:${options.environment ?? ''}`,
    async fetch(path, init) {
      const headers: Record<string, string> = {};
      if (init.method !== 'GET') {
        headers['Content-Type'] = 'application/json';
        headers['X-CSRF-Token'] = await options.csrf();
      }
      const response = await doFetch(path, { method: init.method, headers, credentials: 'same-origin', cache: 'no-store', signal: init.signal,
        ...(init.method !== 'GET' ? { body: JSON.stringify(init.body ?? {}) } : {}) });
      let json: Record<string, unknown> = {};
      try {
        json = (await response.json()) as Record<string, unknown>;
      } catch {
        json = {};
      }
      if (!response.ok) {
        if (typeof json.code === 'string' && CSRF_CODES.has(json.code)) options.resetCsrf?.();
        return new Response(JSON.stringify({ error: typeof json.message === 'string' ? json.message : 'Founder request failed', code: json.code ?? null, blocker: json.blocker ?? null }),
          { status: response.status, headers: { 'content-type': 'application/json' } });
      }
      const data = json && typeof json === 'object' && 'data' in json && 'requestId' in json ? json.data : json;
      return new Response(JSON.stringify(data ?? {}), { status: response.status, headers: { 'content-type': 'application/json' } });
    }
  };
}

// --- hook ----------------------------------------------------------------------------------------------------------------
export interface UseUiArtifactStreamOptions {
  artifactId: string | null;
  workspaceId: string | null;
  afterSeq?: number;
  enabled: boolean;
  transport: UiTransport | null;
  /** The artifact is on screen (IntersectionObserver + page visibility); hidden views make no requests. */
  active?: boolean;
  onEvent: (event: UiEventV1) => void;
  /** A fresh turn's POST /presentations response to read instead of a replay (consumed once). */
  initialResponse?: Response | null;
  onArtifact?: (artifactId: string) => void;
}

/**
 * Follow one artifact's events while it is enabled and visible. It replays with `events?after=` (or reads the one POST stream
 * of a fresh turn it is handed); it never starts a presentation. Changing the scope (workspace, principal, founder mode) or the
 * artifact aborts everything in flight.
 */
export function useUiArtifactStream({ artifactId, workspaceId, afterSeq = 0, enabled, transport, active = true, onEvent, initialResponse, onArtifact }: UseUiArtifactStreamOptions) {
  const [status, setStatus] = useState<UiStreamStatus>('idle');
  const stream = useRef<UiArtifactStream | null>(null);
  const handlers = useRef({ onEvent, onArtifact });
  handlers.current = { onEvent, onArtifact };
  const after = useRef(afterSeq);
  after.current = Math.max(after.current, afterSeq);
  const scopeKey = transport?.scopeKey ?? null;

  useEffect(() => {
    if (!enabled || !transport || (!artifactId && !initialResponse)) return;
    const current = new UiArtifactStream({
      transport, artifactId: artifactId ?? '', afterSeq: after.current,
      onEvent: (event) => {
        after.current = Math.max(after.current, event.seq);
        handlers.current.onEvent(event);
      },
      onArtifact: (id) => handlers.current.onArtifact?.(id),
      onStatus: (next) => setStatus(next)
    });
    stream.current = current;
    if (initialResponse && !initialResponse.bodyUsed) current.consume(initialResponse);
    else if (artifactId) current.connect();
    return () => {
      current.dispose();
      if (stream.current === current) stream.current = null;
    };
    // The stream restarts only for another artifact, scope or enablement; afterSeq advances inside it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactId, workspaceId, scopeKey, enabled, initialResponse]);

  useEffect(() => {
    stream.current?.setActive(active);
  }, [active]);

  return { status, lastSeq: after.current };
}
