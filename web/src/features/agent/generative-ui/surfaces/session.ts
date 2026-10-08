/**
 * One generated view per (scope, artifact) in this tab (lane F): the snapshot, the event source, the persisted view state and
 * the explicit person-started operations (retry, edit, cancel). Every surface (chat, panel, expanded dialog, phone sheet,
 * founder) renders the SAME session, so expanding never creates a second artifact, conversation or stream, and the state the
 * person typed is the same everywhere.
 *
 * Network rules kept here: a session reads snapshots and replays events; the only POST that can start a generation is
 * `startPresentation` for a fresh turn (with the run's stable key) or an explicit retry/edit the person confirmed. Hidden
 * sessions make no requests. A scope change (sign-out, workspace switch, founder mode) disposes every session of the old scope
 * and aborts what it had in flight.
 */
import type { JsonValue, UiSurface } from '@/lib/agent-runtime/ui-contracts';
import { createUiEventSource, type UiEventSource } from '@/lib/agent-runtime/use-ui-artifact-stream';
import type { UiTransport } from '@/features/agent/generative-ui/bridges/types';
import { INITIAL_ARTIFACT_STATE, reduceArtifact, type ArtifactAction, type ArtifactViewState, type UiArtifactViewV1 } from '../state/artifact-machine';
import { UiStateController, type DeclaredState } from '../state/persisted-state';
import { clearUiContext, newIdempotencyKey, presentationKey, setUiContext } from '../state/registry';

const RELEASE_GRACE_MS = 8_000;   // a panel moving dock ↔ sheet remounts; keep the session (and its stream) across that

export interface SessionOptions {
  transport: UiTransport;
  artifactId: string | null;
  conversationId: string | null;
  supportedLibraryHashes?: readonly string[];
  timers?: { setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (handle: unknown) => void };
}

export type OperationResult = { ok: true } | { ok: false; code: string | null; status: number };

async function errorOf(response: Response): Promise<OperationResult> {
  let code: string | null = null;
  try {
    const body = (await response.json()) as { code?: unknown };
    code = typeof body?.code === 'string' ? body.code : null;
  } catch {
    code = null;
  }
  return { ok: false, code, status: response.status };
}

export class ArtifactSession {
  readonly transport: UiTransport;
  artifactId: string | null;
  conversationId: string | null;
  private state: ArtifactViewState = INITIAL_ARTIFACT_STATE;
  private listeners = new Set<() => void>();
  private source: UiEventSource | null = null;
  private controller: UiStateController | null = null;
  private controllerRevision = -1;
  private visible = new Set<string>();
  private refs = 0;
  private releaseTimer: unknown = null;
  private loading = false;
  private disposed = false;
  private supported: readonly string[] | undefined;
  private timers: NonNullable<SessionOptions['timers']>;
  private pending = new Set<string>();   // operations in flight (no double submit)

  constructor(opts: SessionOptions) {
    this.transport = opts.transport;
    this.artifactId = opts.artifactId;
    this.conversationId = opts.conversationId;
    this.supported = opts.supportedLibraryHashes;
    this.timers = opts.timers ?? { setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>) };
    if (opts.artifactId) this.state = { ...INITIAL_ARTIFACT_STATE, artifactId: opts.artifactId };
  }

  get scopeKey() {
    return this.transport.scopeKey;
  }

  getState = (): ArtifactViewState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private notify() {
    for (const listener of [...this.listeners]) listener();
  }

  dispatch(action: ArtifactAction) {
    if (this.disposed) return;
    const next = reduceArtifact(this.state, action.type === 'snapshot' ? { ...action, supportedLibraryHashes: action.supportedLibraryHashes ?? this.supported } : action);
    if (next === this.state) return;
    this.state = next;
    this.afterChange();
    this.notify();
  }

  private afterChange() {
    const { view } = this.state;
    if (this.state.needsSnapshot && !this.loading) void this.loadSnapshot();
    if (this.state.needsReplay && this.source) {
      this.state = { ...this.state, needsReplay: false };
      this.source.connect();
    }
    if (view && view.attempt?.live && !this.source && this.artifactId) this.follow();
    if (view && view.display.mode === 'generated' && view.artifact.revision >= 1) {
      this.syncController(view);
      setUiContext(this.scopeKey, this.conversationId, { artifactId: view.artifact.artifactId, artifactRevision: view.artifact.revision,
        stateRevision: this.controller?.current().stateRevision ?? view.artifact.stateRevision });
    }
  }

  private syncController(view: UiArtifactViewV1) {
    const declared: DeclaredState = view.declared ?? { stateNames: [], formNames: [] };
    const stored = { safeState: view.artifact.safeState ?? {}, stateRevision: view.artifact.stateRevision };
    if (!this.controller) {
      this.controller = new UiStateController({ transport: this.transport, artifactId: view.artifact.artifactId, initial: stored, declared,
        canPersist: Boolean(view.access?.canPersistState), timers: this.timers,
        onSaved: (saved) => {
          if (!this.state.view) return;
          setUiContext(this.scopeKey, this.conversationId, { artifactId: view.artifact.artifactId, artifactRevision: this.state.view.artifact.revision, stateRevision: saved.stateRevision });
        } });
      this.controllerRevision = view.artifact.revision;
      return;
    }
    if (view.artifact.revision !== this.controllerRevision || view.artifact.stateRevision > this.controller.current().stateRevision) {
      this.lostFields = this.controller.rebase(stored, declared).lostFields;
      this.controllerRevision = view.artifact.revision;
    }
    this.controller.setAllowed(Boolean(view.access?.canPersistState));
  }

  /** Dirty fields a new revision no longer declares (a native warning offers to restore them). */
  lostFields: string[] = [];

  stateController(): UiStateController | null {
    return this.controller;
  }

  /** Load the authoritative snapshot (never generates). */
  async loadSnapshot(): Promise<void> {
    if (!this.artifactId || this.disposed) return;
    this.loading = true;
    try {
      const response = await this.transport.fetch(`${this.transport.base}/presentations/${encodeURIComponent(this.artifactId)}`, { method: 'GET' });
      if (this.disposed) return;
      if (!response.ok) {
        const failure = await errorOf(response);
        this.dispatch({ type: 'snapshot_failed', status: failure.ok ? 0 : failure.status, code: failure.ok ? null : failure.code });
        return;
      }
      this.dispatch({ type: 'snapshot', view: (await response.json()) as UiArtifactViewV1 });
    } catch {
      this.dispatch({ type: 'snapshot_failed', status: 0, code: 'ui_unreachable' });
    } finally {
      this.loading = false;
      if (this.state.needsSnapshot && !this.disposed) {
        // An event arrived while loading (e.g. ui.ready): read once more.
        this.timers.setTimeout(() => void this.loadSnapshot(), 0);
      }
    }
  }

  /** A snapshot that arrived with the message list (GET messages/{id}). */
  adopt(view: UiArtifactViewV1) {
    if (!this.artifactId) this.artifactId = view.artifact.artifactId;
    this.dispatch({ type: 'snapshot', view });
  }

  private makeSource(): UiEventSource {
    this.source?.dispose();
    const source = createUiEventSource({
      transport: this.transport, artifactId: this.artifactId ?? '', afterSeq: this.state.lastSeq,
      onEvent: (event) => this.dispatch({ type: 'event', event }),
      onArtifact: (id) => {
        if (!this.artifactId) {
          this.artifactId = id;
          this.dispatch({ type: 'artifact', artifactId: id });
          register(this);
        }
      },
      onStatus: (status) => {
        if (status === 'done' || status === 'failed') {
          if (this.source === source) this.source = null;
          if (status === 'failed' && !this.state.view) this.dispatch({ type: 'snapshot_failed', status: 0, code: 'ui_stream_failed' });
          else void this.loadSnapshot();
        }
      },
      timers: this.timers
    });
    this.source = source;
    if (!this.visible.size && this.refs > 0) source.setActive(false);
    return source;
  }

  /** Follow a live attempt with the replay (`events?after=`); no-op when finished. */
  follow() {
    if (this.disposed || !this.artifactId) return;
    this.makeSource().connect();
  }

  /** Read the stream a POST /presentations, /edits or retry returned. */
  consume(response: Response) {
    if (this.disposed) return;
    this.dispatch({ type: 'start' });
    this.makeSource().consume(response);
  }

  /** Visible on screen (IntersectionObserver + page visibility): hidden sessions make no requests and no polling. */
  setVisible(viewId: string, visible: boolean) {
    if (visible) this.visible.add(viewId);
    else this.visible.delete(viewId);
    this.source?.setActive(this.visible.size > 0);
  }

  retain() {
    this.refs += 1;
    if (this.releaseTimer !== null) {
      this.timers.clearTimeout(this.releaseTimer);
      this.releaseTimer = null;
    }
  }

  release() {
    this.refs = Math.max(0, this.refs - 1);
    if (this.refs > 0) return;
    this.releaseTimer = this.timers.setTimeout(() => {
      this.releaseTimer = null;
      if (this.refs === 0) disposeSession(this);
    }, RELEASE_GRACE_MS);
  }

  /** Save the person's view state now (before a follow-up turn reads the selection). */
  flush(): Promise<void> {
    return this.controller?.flush() ?? Promise.resolve();
  }

  private async operation(name: string, run: () => Promise<OperationResult>): Promise<OperationResult> {
    if (this.pending.has(name)) return { ok: false, code: 'ui_in_flight', status: 0 };
    this.pending.add(name);
    this.notify();
    try {
      return await run();
    } finally {
      this.pending.delete(name);
      this.notify();
    }
  }

  busy(name: string): boolean {
    return this.pending.has(name);
  }

  /** Explicit UI-only retry after a stop, with a NEW key; the person has seen the cost note first (02-CONTRACTS §4). */
  retry(parentRunId: string, surface: UiSurface): Promise<OperationResult> {
    return this.operation('retry', async () => {
      const attempt = this.state.view?.attempt;
      if (!attempt || attempt.live) return { ok: false, code: 'ui_retry_not_needed', status: 409 };
      const body: Record<string, JsonValue> = { parentRunId, slot: 'main', idempotencyKey: newIdempotencyKey(), retryOfAttemptId: attempt.attemptId };
      if (this.transport.scope !== 'founder') body.surface = surface === 'founder' ? 'panel' : surface;
      const response = await this.transport.fetch(`${this.transport.base}/presentations`, { method: 'POST', body });
      if (!response.ok) return errorOf(response);
      this.afterStart(response);
      return { ok: true };
    });
  }

  /** Explicit semantic edit ("add a chart"), a separately metered presentation-only patch on the revision the person sees. */
  edit(instruction: string, selection?: Record<string, JsonValue> | null): Promise<OperationResult> {
    return this.operation('edit', async () => {
      const view = this.state.view;
      const text = instruction.trim().slice(0, 2000);
      if (!view || !this.artifactId || !text || view.artifact.revision < 1 || !view.artifact.sourceHash) return { ok: false, code: 'ui_not_ready', status: 409 };
      await this.flush();
      const response = await this.transport.fetch(`${this.transport.base}/presentations/${encodeURIComponent(this.artifactId)}/edits`, {
        method: 'POST', body: { baseRevision: view.artifact.revision, baseSourceHash: view.artifact.sourceHash, instruction: text, idempotencyKey: newIdempotencyKey(),
          ...(selection ? { selection } : {}) }
      });
      if (!response.ok) {
        const failure = await errorOf(response);
        if (!failure.ok && failure.status === 409) void this.loadSnapshot();   // stale base: show the latest; the person asks again
        return failure;
      }
      this.afterStart(response);
      return { ok: true };
    });
  }

  /** Stop a presentation that is still being prepared (the answer above stays; spend settles once on the server). */
  cancel(): Promise<OperationResult> {
    return this.operation('cancel', async () => {
      if (!this.artifactId) return { ok: false, code: 'ui_artifact', status: 404 };
      const response = await this.transport.fetch(`${this.transport.base}/presentations/${encodeURIComponent(this.artifactId)}/cancel`, { method: 'POST', body: {} });
      if (!response.ok) return errorOf(response);
      void this.loadSnapshot();
      return { ok: true };
    });
  }

  private afterStart(response: Response) {
    const type = response.headers.get('content-type') ?? '';
    if (type.includes('text/event-stream')) {
      this.consume(response);
      return;
    }
    // Founder routes answer once with the outcome and the view; progress was visible through the polling replay.
    void response.json().then((body: { view?: UiArtifactViewV1 }) => {
      if (body?.view) this.adopt(body.view);
      else void this.loadSnapshot();
    }).catch(() => void this.loadSnapshot());
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.source?.dispose();
    this.source = null;
    this.controller?.dispose();
    this.controller = null;
    if (this.artifactId) clearUiContext(this.artifactId);
    this.listeners.clear();
  }

  isDisposed() {
    return this.disposed;
  }
}

// --- the tab's sessions ----------------------------------------------------------------------------------------------------
const sessions = new Map<string, ArtifactSession>();
const starting = new Map<string, Promise<StartResult>>();

function keyOf(scopeKey: string, artifactId: string) {
  return `${scopeKey}|${artifactId}`;
}

function register(session: ArtifactSession) {
  if (session.artifactId) sessions.set(keyOf(session.scopeKey, session.artifactId), session);
}

function disposeSession(session: ArtifactSession) {
  if (session.artifactId && sessions.get(keyOf(session.scopeKey, session.artifactId)) === session) sessions.delete(keyOf(session.scopeKey, session.artifactId));
  session.dispose();
}

/** Dispose every session (and forget every start in flight) that is not in the `keep` scope. */
export function disposeOutOfScope(keep: string) {
  for (const [key, session] of [...sessions.entries()]) {
    if (!key.startsWith(`${keep}|`)) {
      sessions.delete(key);
      session.dispose();
    }
  }
  for (const key of [...starting.keys()]) if (!key.startsWith(`${keep}|`)) starting.delete(key);
}

let activeScope: string | null = null;

/** The surfaces call this with the current transport scope (consumer or founder); null after sign-out disposes everything. */
export function setActiveSessionScope(scopeKey: string | null) {
  if (scopeKey === activeScope) return;
  activeScope = scopeKey;
  disposeOutOfScope(scopeKey ?? '\u0000');
}

/** The one session of an artifact in this scope (created on first use). */
export function sessionFor(transport: UiTransport, artifactId: string, conversationId: string | null, supportedLibraryHashes?: readonly string[]): ArtifactSession {
  const key = keyOf(transport.scopeKey, artifactId);
  const known = sessions.get(key);
  if (known && !known.isDisposed()) return known;
  const session = new ArtifactSession({ transport, artifactId, conversationId, supportedLibraryHashes });
  sessions.set(key, session);
  return session;
}

export type StartResult = { session: ArtifactSession } | { session: null; code: string | null; status: number };

/**
 * Start the one presentation of a fresh turn (consumer routes: an SSE stream). The run's stable key makes a remount, a second
 * tab or a reload resend the SAME request, which the server answers with the existing attempt: never a second generation.
 */
export function startPresentation(input: { transport: UiTransport; runId: string; conversationId: string | null; surface: UiSurface;
  supportedLibraryHashes?: readonly string[] }): Promise<StartResult> {
  const flightKey = `${input.transport.scopeKey}|run:${input.runId}`;
  const inFlight = starting.get(flightKey);
  if (inFlight) return inFlight;
  const run = (async (): Promise<StartResult> => {
    const body: Record<string, JsonValue> = { parentRunId: input.runId, slot: 'main', idempotencyKey: presentationKey(input.transport.scopeKey, input.runId) };
    if (input.transport.scope !== 'founder') body.surface = input.surface === 'founder' || input.surface === 'browser_voice' ? 'panel' : input.surface;
    if (input.conversationId) body.conversationId = input.conversationId;
    const response = await input.transport.fetch(`${input.transport.base}/presentations`, { method: 'POST', body });
    if (!response.ok) {
      const failure = await errorOf(response);
      return { session: null, code: failure.ok ? null : failure.code, status: failure.ok ? 0 : failure.status };
    }
    const session = new ArtifactSession({ transport: input.transport, artifactId: null, conversationId: input.conversationId, supportedLibraryHashes: input.supportedLibraryHashes });
    session.consume(response);
    // The first frame names the artifact; until then the session is anonymous (and private to this start).
    await new Promise<void>((resolve) => {
      const stop = session.subscribe(() => {
        if (session.artifactId || session.getState().notice) {
          stop();
          resolve();
        }
      });
      if (session.artifactId) {
        stop();
        resolve();
      }
    });
    if (!session.artifactId) {
      session.dispose();
      return { session: null, code: 'ui_stream_failed', status: 0 };
    }
    const existing = sessions.get(keyOf(input.transport.scopeKey, session.artifactId));
    if (existing && existing !== session && !existing.isDisposed()) {
      session.dispose();
      void existing.loadSnapshot();
      return { session: existing };
    }
    register(session);
    void session.loadSnapshot();
    return { session };
  })();
  starting.set(flightKey, run);
  void run.finally(() => {
    if (starting.get(flightKey) === run) starting.delete(flightKey);
  });
  return run;
}

/**
 * Founder routes cannot stream: the POST blocks until the presentation ends. While it runs, the message's views are read
 * (the artifact row exists from the claim) and the durable events are polled, so the founder sees it build.
 */
export function startFounderPresentation(input: { transport: UiTransport; runId: string; messageId: string; conversationId: string | null;
  supportedLibraryHashes?: readonly string[]; pollMs?: number }): Promise<StartResult> {
  const flightKey = `${input.transport.scopeKey}|run:${input.runId}`;
  const inFlight = starting.get(flightKey);
  if (inFlight) return inFlight;
  const run = (async (): Promise<StartResult> => {
    let found: ArtifactSession | null = null;
    let done = false;
    const post = input.transport.fetch(`${input.transport.base}/presentations`, { method: 'POST',
      body: { parentRunId: input.runId, slot: 'main', idempotencyKey: presentationKey(input.transport.scopeKey, input.runId) } }).finally(() => { done = true; });
    const discover = async () => {
      for (let i = 0; i < 60 && !done && !found; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, input.pollMs ?? 1200));
        const views = await loadMessageViews(input.transport, input.messageId, input.conversationId, input.supportedLibraryHashes).catch(() => []);
        if (views.length) found = views[0];
      }
    };
    void discover();
    const response = await post;
    if (!response.ok) {
      const failure = await errorOf(response);
      return { session: null, code: failure.ok ? null : failure.code, status: failure.ok ? 0 : failure.status };
    }
    const body = (await response.json().catch(() => ({}))) as { view?: UiArtifactViewV1 };
    if (!body.view) return found ? { session: found } : { session: null, code: 'ui_stream_failed', status: 0 };
    const session = found ?? sessionFor(input.transport, body.view.artifact.artifactId, input.conversationId, input.supportedLibraryHashes);
    session.adopt(body.view);
    return { session };
  })();
  starting.set(flightKey, run);
  void run.finally(() => {
    if (starting.get(flightKey) === run) starting.delete(flightKey);
  });
  return run;
}

/** The views of one assistant message (reload): snapshots only, zero provider attempts. */
export async function loadMessageViews(transport: UiTransport, messageId: string, conversationId: string | null, supportedLibraryHashes?: readonly string[]): Promise<ArtifactSession[]> {
  const response = await transport.fetch(`${transport.base}/messages/${encodeURIComponent(messageId)}`, { method: 'GET' });
  if (!response.ok) return [];
  const body = (await response.json()) as { artifacts?: UiArtifactViewV1[] };
  return (body.artifacts ?? []).filter((view) => view?.artifact?.artifactId).map((view) => {
    const session = sessionFor(transport, view.artifact.artifactId, conversationId, supportedLibraryHashes);
    session.adopt(view);
    return session;
  });
}

/** Save every view state of this conversation before a follow-up turn (bounded wait; a slow save never blocks sending). */
export async function flushConversation(scopeKey: string | null, conversationId: string | null, timeoutMs = 800): Promise<void> {
  if (!scopeKey) return;
  const pending = [...sessions.values()].filter((s) => s.scopeKey === scopeKey && s.conversationId === conversationId).map((s) => s.flush().catch(() => undefined));
  if (!pending.length) return;
  await Promise.race([Promise.all(pending), new Promise((resolve) => setTimeout(resolve, timeoutMs))]);
}

/** Test helper: how many sessions this tab holds (no private values). */
export function sessionCount() {
  return sessions.size;
}
