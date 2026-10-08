'use client';
/**
 * RafiiGenerativeMessage — one generated view inside an existing Rafii answer (lane C; D-A29, D-A40, D-A21).
 *
 * The native answer (`nativeResult`: text, warnings, proposals, receipts) and every native control (status line,
 * confirmation sheet, receipts, conflict warning) render OUTSIDE the generated subtree, so they keep working when the
 * view fails. Inside, OpenUI's `<Renderer>` draws Rafii components from:
 *   - the server-accepted canonical source (reads and actions on), or
 *   - while a first generation streams, the untrusted candidate source (no reads, no actions, `aria-busy`).
 * During an edit the last accepted revision stays on screen; when the new revision arrives it replaces the old one in
 * the same Renderer (state and focus kept). If it would remove fields the person edited, a native warning asks first
 * (`[data-rafii-dirty-conflict]`). Failures keep the last accepted revision, else the native answer only. An artifact
 * from an unsupported library version shows its stored fallback without any model call.
 *
 * Inputs from other lanes: D's bridges (`createUiBridges`), F's transport, render model (`renderOf`) and view-state
 * context (`useUiArtifactState`). Nothing here talks to a model; reopening or reloading never generates.
 * Evidence hooks: `[data-rafii-generated][data-artifact-id][data-generation-state]` on the frame and the
 * `rafii-genui:first-component` / `rafii-genui:ready` performance marks.
 */
import {
  Component,
  type ErrorInfo,
  type JSX,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Button } from '@/components/ui/button';
import type { GenerationState, UiArtifactV1, UiPublicManifestV1, UiSurface } from '@/lib/agent-runtime/ui-contracts';
import { cn } from '@/lib/utils';
import { createUiBridges } from './bridges';
import { UiBridgesProvider } from './bridges/context';
import type { ActionState, ContinueRequest, UiBridges, UiTransport } from './bridges/types';
import { ActionConfirmation } from './core/action-confirmation';
import { createHostActionHandler } from './core/actions';
import { useAnnouncer } from './core/announcer';
import { defaultGenUiLocale, GenUiLocaleProvider, type GenUiMessageKey } from './core/locale';
import { createParser, type Library, type ParseResult, Renderer } from './core/openui';
import { markFirstComponent, markReady } from './core/perf';
import { wrapReadToolProvider } from './core/query-results';
import { GenUiRuntimeProvider, type GenUiRuntime } from './core/runtime-context';
import { collectFieldHosts, dirtyFieldsRemoved, type FieldHost, swapInitialState } from './core/state';
import { checkSource, WATCHDOG, type WatchdogReason } from './core/watchdog';
import { previewRouteAllowed } from './components/primitives/asset-preview';
import assets from './generated/openui-assets.json';
import { CONSUMER_LIBRARY } from './library';
import type { ArtifactRender } from './state/artifact-machine';
import { useUiArtifactState } from './state/context';

type LibraryName = 'consumer' | 'founder';

/** Library hashes this build renders (current + declared compatible). F passes these to its snapshot reducer. */
export function supportedLibraryHashes(name: LibraryName): string[] {
  const entry = assets.libraries[name] as { libraryHash: string; compatibleLibraryHashes?: string[] };
  return [entry.libraryHash, ...(entry.compatibleLibraryHashes ?? [])];
}

const FIELD_HOSTS: Record<LibraryName, Readonly<Record<string, string>>> = {
  consumer: (assets.libraries.consumer as { fieldHosts?: Record<string, string> }).fieldHosts ?? {},
  founder: (assets.libraries.founder as { fieldHosts?: Record<string, string> }).fieldHosts ?? {},
};

export interface RafiiGenerativeMessageProps {
  /** Latest server snapshot of the artifact; null while the presentation is still being created. */
  artifact: UiArtifactV1 | null;
  /** The authoritative native answer. Rendered first, outside the generated subtree. */
  nativeResult?: ReactNode;
  /** A labeled follow-up from the view, through the existing turn path (`uiContext` = the artifact ids). */
  onContinue: (request: ContinueRequest) => void;
  surface: UiSurface;
  transport: UiTransport;
  /** The artifact's public manifest (F: `view.manifest`). Without it reads and actions stay off. */
  manifest?: UiPublicManifestV1 | null;
  /** What to draw (F: `renderOf(state)`). Omitted: derived from `artifact` alone (a persisted snapshot). */
  render?: ArtifactRender | null;
  /** Native one-line status (F: `statusLine(state)`); never DSL. */
  status?: string | null;
  /** F: `view.access.historical`. Saved as-of data until the person asks for current data. */
  historical?: boolean;
  /** False while hidden or collapsed: zero reads and no polling. Default true. */
  active?: boolean;
  /** In-app navigation for `@OpenUrl("/app/…")` (the panel closes itself, for example). */
  onNavigate?: (path: string) => void;
  /** Explicit, separately metered UI-only retry offered after a failure (F/B decide cost and consent). */
  onRetry?: (() => void) | null;
  /** Open the same artifact in the expanded surface (desktop/tablet). */
  onExpand?: (() => void) | null;
  className?: string;
}

export function RafiiGenerativeMessage(props: RafiiGenerativeMessageProps): JSX.Element {
  // Browser voice speaks `speakableSummary` only; no visual mount (D-A21).
  if (props.surface === 'browser_voice') return <>{props.nativeResult ?? null}</>;
  const key = `${props.transport.scopeKey}:${props.artifact?.artifactId ?? 'pending'}`;
  return <GenerativeMessage key={key} {...props} />;
}

/* ------------------------------------------------------------------------------------------------------------------ */

function deriveRender(artifact: UiArtifactV1 | null): ArtifactRender {
  if (!artifact) return { mode: 'pending' };
  if (artifact.validationState === 'accepted' && artifact.canonicalSource && artifact.revision >= 1) {
    return { mode: 'generated', artifact, accepted: true, updating: false };
  }
  const terminal: GenerationState[] = ['failed', 'canceled', 'interrupted'];
  if (terminal.includes(artifact.generationState) || artifact.validationState === 'rejected') {
    return { mode: 'fallback', text: artifact.fallbackText, reason: artifact.generationState };
  }
  return { mode: 'pending' };
}

const parsers = new WeakMap<Library, { parse(input: string): ParseResult }>();
function parseWith(library: Library, source: string): ParseResult | null {
  let parser = parsers.get(library);
  if (!parser) {
    parser = createParser(library.toJSONSchema(), 'RafiiRoot');
    parsers.set(library, parser);
  }
  try {
    return parser.parse(source);
  } catch {
    return null;
  }
}

function useLibrary(name: LibraryName): { library: Library | null; failed: boolean } {
  const [founder, setFounder] = useState<Library | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (name !== 'founder' || founder) return;
    let alive = true;
    import('./founder-library')
      .then((module) => alive && setFounder(module.FOUNDER_LIBRARY))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [name, founder]);
  return name === 'founder' ? { library: founder, failed } : { library: CONSUMER_LIBRARY, failed: false };
}

/** Hand the streaming parser a new text at most every WATCHDOG.streamUpdateMs (it re-parses everything each time). */
function useThrottled(value: string | null, enabled: boolean): string | null {
  const [current, setCurrent] = useState(value);
  const last = useRef(0);
  useEffect(() => {
    if (!enabled) {
      setCurrent(value);
      return;
    }
    const wait = Math.max(0, WATCHDOG.streamUpdateMs - (Date.now() - last.current));
    const timer = setTimeout(() => {
      last.current = Date.now();
      setCurrent(value);
    }, wait);
    return () => clearTimeout(timer);
  }, [value, enabled]);
  return enabled ? current : value;
}

/** Visible on screen and the tab is visible (no observer support → visible). */
function useVisible(ref: { current: Element | null }): boolean {
  const [inView, setInView] = useState(true);
  const [tabVisible, setTabVisible] = useState(true);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => setInView(entries.some((e) => e.isIntersecting)), { rootMargin: '400px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const update = () => setTabVisible(document.visibilityState !== 'hidden');
    update();
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return inView && tabVisible;
}

class GeneratedBoundary extends Component<{ resetKey: string; fallback: ReactNode; onError(): void; children: ReactNode }, { failedKey: string | null }> {
  state = { failedKey: null as string | null };
  static getDerivedStateFromError(): Partial<{ failedKey: string | null }> {
    return { failedKey: '__pending__' };
  }
  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // No source text or stack in logs: the native answer stays complete and the failure is a presentation one.
    this.setState({ failedKey: this.props.resetKey });
    this.props.onError();
  }
  componentDidUpdate(prev: { resetKey: string }): void {
    if (prev.resetKey !== this.props.resetKey && this.state.failedKey !== null) this.setState({ failedKey: null });
  }
  render(): ReactNode {
    return this.state.failedKey !== null ? this.props.fallback : this.props.children;
  }
}

interface Shown {
  revision: number;
  source: string;
}

interface Conflict extends Shown {
  fields: FieldHost[];
}

const CHART_TOKENS =
  '[.rafii-chat_&]:[--chart-1:oklch(0.82_0.11_292)] [.rafii-chat_&]:[--chart-2:oklch(0.80_0.10_200)] [.rafii-chat_&]:[--chart-3:oklch(0.83_0.12_150)] [.rafii-chat_&]:[--chart-4:oklch(0.85_0.11_80)] [.rafii-chat_&]:[--chart-5:oklch(0.78_0.13_20)]';

function GenerativeMessage(props: RafiiGenerativeMessageProps): JSX.Element {
  const { artifact, surface, transport } = props;
  const libraryName: LibraryName = surface === 'founder' ? 'founder' : 'consumer';
  const { library, failed: libraryFailed } = useLibrary(libraryName);
  const l = defaultGenUiLocale();
  const { announcer, region } = useAnnouncer();
  const frameRef = useRef<HTMLDivElement | null>(null);
  const visible = useVisible(frameRef);
  const stateBridge = useUiArtifactState();
  const stateBridgeRef = useRef(stateBridge);
  stateBridgeRef.current = stateBridge;
  const onContinueRef = useRef(props.onContinue);
  onContinueRef.current = props.onContinue;
  const transportRef = useRef(transport);
  transportRef.current = transport;

  const draw: ArtifactRender = props.render ?? deriveRender(artifact);
  const supported = !artifact || artifact.revision < 1 || supportedLibraryHashes(libraryName).includes(artifact.libraryHash);

  /* ---- which accepted revision is on screen (swap rule + dirty-field protection) ---- */
  const lastParse = useRef<ParseResult | null>(null);
  const latestSnapshot = useRef<Record<string, unknown> | null>(null);
  const initialState = useRef<Record<string, unknown> | null>(null);
  if (initialState.current === null) initialState.current = { ...(stateBridge?.initialState ?? artifact?.safeState) };
  const openedWith = useRef<Record<string, unknown>>(initialState.current);

  const incoming: Shown | null =
    draw.mode === 'generated' && supported && draw.artifact.canonicalSource
      ? { revision: draw.artifact.revision, source: draw.artifact.canonicalSource }
      : null;
  const [shown, setShown] = useState<Shown | null>(incoming);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [kept, setKept] = useState<number | null>(null);
  const incomingKey = incoming ? `${incoming.revision}:${incoming.source.length}` : null;
  const [seen, setSeen] = useState<string | null>(incomingKey);
  if (incoming && incomingKey !== seen && library) {
    setSeen(incomingKey);
    if (!shown) {
      setShown(incoming);
    } else if (incoming.revision > shown.revision && kept !== incoming.revision) {
      const removed = dirtyFieldsRemoved({
        previous: collectFieldHosts(lastParse.current?.root ?? null, FIELD_HOSTS[libraryName]),
        next: collectFieldHosts(parseWith(library, incoming.source)?.root ?? null, FIELD_HOSTS[libraryName]),
        initial: openedWith.current,
        current: latestSnapshot.current ?? {},
        dirtyKeys: stateBridge?.dirtyFields() ?? [],
      });
      if (removed.length) {
        setConflict({ ...incoming, fields: removed });
      } else {
        initialState.current = swapInitialState(stateBridge?.initialState, latestSnapshot.current);
        setConflict(null);
        setShown(incoming);
      }
    } else if (incoming.revision === shown.revision && incoming.source !== shown.source) {
      setShown(incoming); // same revision re-read (canonical text is authoritative)
    }
  }
  const acceptConflict = useCallback(() => {
    if (!conflict) return;
    initialState.current = swapInitialState(stateBridgeRef.current?.initialState, latestSnapshot.current);
    setShown({ revision: conflict.revision, source: conflict.source });
    setConflict(null);
  }, [conflict]);
  const keepEarlier = useCallback(() => {
    if (!conflict) return;
    setKept(conflict.revision);
    setConflict(null);
  }, [conflict]);

  /* ---- what the Renderer gets ---- */
  const previewSource = draw.mode === 'preview' && !shown ? draw.source : null;
  const streaming = previewSource !== null;
  const throttled = useThrottled(previewSource, streaming);
  const rawSource = shown ? shown.source : throttled;
  const watchdog: WatchdogReason | null = checkSource(rawSource);
  const source = watchdog ? null : rawSource;
  const accepted = !!shown && !streaming && !watchdog;
  const revision = shown?.revision ?? artifact?.revision ?? 0;
  const [live, setLive] = useState(false);
  const historical = !!props.historical && !live;
  const active = props.active !== false && visible;

  /* ---- bridges: once per (scope, artifact, revision, accepted) ---- */
  const [bridges, setBridges] = useState<UiBridges | null>(null);
  const artifactId = artifact?.artifactId ?? null;
  const manifest = props.manifest ?? null;
  useEffect(() => {
    if (!artifactId || !manifest) {
      setBridges(null);
      return;
    }
    const created = createUiBridges({
      transport: transportRef.current,
      artifact: { artifactId, revision, accepted, historical, manifest },
      onContinue: (request) => onContinueRef.current(request),
    });
    setBridges(created);
    return () => created.dispose();
    // The manifest identity is its id + binding version; a new object with the same identity keeps the bridges.
  }, [transport.scopeKey, artifactId, revision, accepted, historical, manifest?.manifestId, manifest?.bindingVersion]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    bridges?.query.setActive(active);
  }, [bridges, active]);
  const toolProvider = useMemo(() => (accepted && bridges ? wrapReadToolProvider(bridges.query.toolProvider()) : null), [accepted, bridges]);
  const inert = useMemo(() => inertBridges(), []);

  /* ---- host actions (follow-ups and in-app links only) ---- */
  const stateRevision = artifact?.stateRevision ?? 0;
  const onAction = useMemo(
    () =>
      createHostActionHandler({
        origin: typeof window !== 'undefined' ? window.location.origin : null,
        onFollowUp: (message) => {
          if (!artifactId) return;
          const request: ContinueRequest = { message, artifactId, artifactRevision: revision, stateRevision };
          if (bridges) bridges.onContinue(request);
          else onContinueRef.current(request);
        },
        onNavigate: (path) => {
          if (props.onNavigate) props.onNavigate(path);
          else if (typeof window !== 'undefined') window.location.assign(path);
        },
        onBlocked: () => announcer.announce(l.t('linkBlocked')),
      }),
    [artifactId, revision, stateRevision, bridges, props.onNavigate, announcer, l],
  );

  /* ---- view state (lane F) ---- */
  const onStateUpdate = useCallback(
    (snapshot: Record<string, unknown>) => {
      latestSnapshot.current = snapshot;
      if (accepted) stateBridgeRef.current?.onStateUpdate(snapshot);
    },
    [accepted],
  );
  const onParseResult = useCallback((result: ParseResult | null) => {
    if (result) lastParse.current = result;
  }, []);

  /* ---- previews through the message's own workspace transport ---- */
  const previewPrefix = transport.scope === 'workspace' ? transport.base.replace(/\/agent\/ui\/?$/, '') : null;
  const fetchPreview = useMemo(() => {
    if (!accepted || !previewPrefix) return null;
    return (path: string, signal: AbortSignal) => {
      if (!previewRouteAllowed(path, previewPrefix)) return Promise.reject(new Error('preview_scope'));
      return transportRef.current.fetch(path, { method: 'GET', signal });
    };
  }, [accepted, previewPrefix]);

  /* ---- runtime facts, marks and announcements ---- */
  const firstMarked = useRef(false);
  const runtime = useMemo<GenUiRuntime>(
    () => ({
      artifactId: artifactId ?? '',
      revision,
      accepted,
      historical,
      surface,
      library: libraryName,
      compact: surface === 'panel' || surface === 'mobile',
      onFirstComponent: () => {
        if (firstMarked.current || !artifactId) return;
        firstMarked.current = true;
        markFirstComponent(artifactId, revision);
      },
      fetchPreview,
    }),
    [artifactId, revision, accepted, historical, surface, libraryName, fetchPreview],
  );
  useEffect(() => {
    if (accepted && artifactId && shown) markReady(artifactId, shown.revision);
  }, [accepted, artifactId, shown]);

  const boundaryKey = `${revision}:${source?.length ?? 0}`;
  const [renderFailedKey, setRenderFailedKey] = useState<string | null>(null);
  const renderFailed = renderFailedKey === boundaryKey;
  const updating = draw.mode === 'generated' && draw.updating;
  const failedNow = draw.mode === 'fallback' || renderFailed || libraryFailed;
  const announcement: GenUiMessageKey | null = watchdog
    ? 'viewTooLarge'
    : !supported
      ? 'viewOutdated'
      : renderFailed || (failedNow && !shown)
        ? 'viewFailed'
        : updating
          ? 'updating'
          : accepted
            ? 'ready'
            : streaming || draw.mode === 'pending'
              ? 'preparing'
              : null;
  useEffect(() => {
    if (announcement) announcer.announce(l.t(announcement));
  }, [announcement, announcer, l]);

  /* ---- layout ---- */
  // While an edit streams the accepted view stays on screen, but the frame reports `streaming` until the edit lands.
  const generationState: string = streaming || updating ? 'streaming' : accepted ? 'ready' : artifact?.generationState ?? 'queued';
  const showGenerated = !!library && !!source && !(failedNow && !shown);
  const busy = streaming || updating || (draw.mode === 'pending' && !shown);
  const statusText =
    props.status ??
    (watchdog
      ? l.t('viewTooLarge')
      : !supported
        ? l.t('viewOutdated')
        : renderFailed || (failedNow && !shown)
          ? l.t('viewFailed')
          : updating
            ? l.t('updating')
            : busy
              ? l.t('preparing')
              : null);

  const frame = (
    <div
      ref={frameRef}
      data-rafii-generated=""
      data-artifact-id={artifactId ?? undefined}
      data-generation-state={generationState}
      data-surface={surface}
      aria-busy={busy || undefined}
      className={cn('@container relative grid min-w-0 gap-3', CHART_TOKENS)}
    >
      {historical && accepted ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{l.t('savedView', { time: l.formatDateTime(artifact?.asOf ?? artifact?.updatedAt ?? null) })}</span>
          <Button type="button" size="xs" variant="quiet" onClick={() => setLive(true)}>
            {l.t('showCurrent')}
          </Button>
        </div>
      ) : null}
      {conflict ? (
        <div role="alertdialog" aria-labelledby={`${artifactId}-conflict`} data-rafii-dirty-conflict="" className="grid gap-2 rounded-[var(--rafii-radius-card,0.875rem)] border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          <p id={`${artifactId}-conflict`}>{l.t('dirtyRemoved', { fields: conflict.fields.map((f) => f.label).join(', ') })}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" variant="outline" onClick={keepEarlier}>
              {l.t('keepEarlier')}
            </Button>
            <Button type="button" size="sm" onClick={acceptConflict}>
              {l.t('useUpdate')}
            </Button>
          </div>
        </div>
      ) : null}
      {showGenerated ? (
        <GeneratedBoundary resetKey={boundaryKey} fallback={null} onError={() => setRenderFailedKey(boundaryKey)}>
          <Renderer
            response={source}
            library={library}
            isStreaming={!accepted}
            toolProvider={toolProvider}
            initialState={initialState.current ?? undefined}
            onStateUpdate={onStateUpdate}
            onParseResult={onParseResult}
            onAction={onAction}
            onError={noErrors}
            publishObservability={false}
            queryLoader={<span aria-hidden="true" className="absolute top-1 right-1 size-3 animate-spin rounded-full border-2 border-muted border-t-primary motion-reduce:animate-none" />}
          />
        </GeneratedBoundary>
      ) : busy && !failedNow ? (
        <div aria-hidden="true" className="grid gap-2">
          <div className="t-skel-pulse h-4 w-2/5 rounded-md bg-muted" />
          <div className="t-skel-pulse h-20 w-full rounded-md bg-muted" />
        </div>
      ) : null}
      {draw.mode === 'fallback' && !shown && !props.nativeResult && draw.text ? (
        <p dir="auto" className="text-sm whitespace-pre-line">
          {draw.text}
        </p>
      ) : null}
      {props.onExpand && surface !== 'expanded' && surface !== 'mobile' && accepted ? (
        <div className="flex justify-end">
          <Button type="button" size="xs" variant="quiet" onClick={props.onExpand}>
            {l.t('expand')}
          </Button>
        </div>
      ) : null}
    </div>
  );

  return (
    <GenUiLocaleProvider value={l}>
      <GenUiRuntimeProvider value={runtime}>
        <div className={cn('grid min-w-0 gap-3', props.className)} data-rafii-genui-message="">
          {props.nativeResult ?? null}
          {/* Always the same provider element, so creating the real bridges never remounts the generated subtree. */}
          <UiBridgesProvider bridges={bridges ?? inert}>
            {frame}
            <ActionConfirmation frame={frameRef} />
          </UiBridgesProvider>
          {statusText ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" data-rafii-genui-status-line="">
              <span>{statusText}</span>
              {failedNow && props.onRetry ? (
                <Button type="button" size="xs" variant="quiet" onClick={props.onRetry}>
                  {l.t('retryView')}
                </Button>
              ) : null}
            </div>
          ) : null}
          {region}
        </div>
      </GenUiRuntimeProvider>
    </GenUiLocaleProvider>
  );
}

/** One constant snapshot (useSyncExternalStore needs a cached value). */
const IDLE_ACTION: ActionState = { phase: 'idle', request: null, activation: null, result: null, error: null };

/** Bridges that do nothing (before D's bridges exist or without a manifest): no reads, no actions, no follow-ups. */
function inertBridges(): UiBridges {
  const none = () => () => undefined;
  return {
    query: {
      toolProvider: () => null,
      read: async () => ({
        state: 'unavailable',
        data: null,
        asOf: null,
        sourceRefs: [],
        revision: null,
        nextCursor: null,
        coverage: { known: null, total: null, note: null },
        warnings: ['not_ready'],
      }),
      status: () => undefined,
      subscribe: none,
      setActive: () => undefined,
      invalidate: () => undefined,
      dispose: () => undefined,
    },
    action: {
      writesEnabled: () => false,
      binding: () => undefined,
      request: () => undefined,
      confirm: async () => null,
      cancel: () => undefined,
      state: () => IDLE_ACTION,
      subscribe: none,
      dispose: () => undefined,
    },
    onContinue: () => undefined,
  };
}

/** OpenUI reports structured errors after streaming; repairs are decided by the server, so the client only drops them
 *  (passing a handler also stops OpenUI from logging each error, which could include generated text). */
function noErrors(): void {}
