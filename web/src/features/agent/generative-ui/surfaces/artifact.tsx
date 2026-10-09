'use client';

/**
 * One generated view on one surface (lane F). It subscribes to the shared ArtifactSession, reports whether it is on screen
 * (hidden views make no requests), provides the persisted view-state bridge to C's renderer, and keeps the person's controls
 * native: stop while preparing, "Try again" after a stop (with its cost note, a new key, only on request), "Change this view"
 * (an explicit, separately billed edit on the revision shown, for the person who asked only), expand (same artifact in a
 * full-height dialog, never a new conversation) and the warning when an update would drop values the person typed. Nothing
 * here scrolls the conversation.
 *
 * The edit field offers up to 4 suggestions computed in this tab from the view itself (edit-suggestions.ts: no request, no
 * model). A tap only fills the field; "Update view" stays the one billed step, and the request body is unchanged.
 */
import { useCallback, useEffect, useId, useMemo, useReducer, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import type { JsonValue, UiSurface } from '@/lib/agent-runtime/ui-contracts';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { createImeGuard } from '@/lib/ime';
import { useAnnouncer } from '../core/announcer';
import { useGenUiLocale, type GenUiMessageKey } from '../core/locale';
import { renderOf, statusLine, type ArtifactViewState, type UiArtifactViewV1 } from '../state/artifact-machine';
import { UiArtifactStateContext, type UiArtifactStateBridge } from '../state/context';
import { noteUiInteraction } from '../state/registry';
import { canRestore, editAccess, editFieldReducer, editProblemOf, EMPTY_FIELD, liveSelection, type OlderRevision } from './edit-form';
import type { EditSuggestion } from './edit-suggestions';
import { QuietButton } from './frame';
import { canExpand } from './plan';
import { GeneratedRenderer } from './renderer-adapter';
import type { ArtifactSession } from './session';

const FAILURE_RETRYABLE = new Set(['provider_error', 'provider_timeout', 'client_gone', 'lease_expired', 'canceled_by_user', 'internal_error', 'validation_unavailable',
  'repair_exhausted', 'parse_rejected']);

export function generationStateOf(state: ArtifactViewState): string | null {
  if (state.phase === 'starting') return 'queued';
  if (state.phase === 'streaming' || state.phase === 'pending') return state.view?.attempt?.state ?? 'streaming';
  if (state.view) return state.view.artifact.generationState;
  if (state.notice) return state.notice.kind === 'canceled' ? 'canceled' : state.notice.kind === 'interrupted' ? 'interrupted' : 'failed';
  return null;
}

function useOnScreen(session: ArtifactSession) {
  const ref = useRef<HTMLDivElement>(null);
  const viewId = useId();
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const node = ref.current;
    let onScreen = true;
    let pageVisible = typeof document === 'undefined' || document.visibilityState !== 'hidden';
    const update = () => {
      const now = onScreen && pageVisible;
      session.setVisible(viewId, now);
      setVisible(now);
    };
    const observer = node && typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver((entries) => {
        onScreen = entries.some((entry) => entry.isIntersecting);
        update();
      }, { rootMargin: '200px 0px' })
      : null;
    if (node) observer?.observe(node);
    const onVisibility = () => {
      pageVisible = document.visibilityState !== 'hidden';
      update();
    };
    document.addEventListener('visibilitychange', onVisibility);
    update();
    return () => {
      observer?.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      session.setVisible(viewId, false);
    };
  }, [session, viewId]);
  return { ref, visible };
}

export interface GeneratedArtifactProps {
  session: ArtifactSession;
  surface: UiSurface;
  /** The parent run, for an explicit "Try again". */
  runId: string | null;
  onContinue?: (request: ContinueRequest) => void;
  onExpand?: () => void;
  onNavigate?: (path: string) => void;
  nativeResult?: ReactNode;
}

export function GeneratedArtifact({ session, surface, runId, onContinue, onExpand, onNavigate, nativeResult }: GeneratedArtifactProps) {
  const state = useSyncExternalStore(session.subscribe, session.getState, session.getState);
  const { ref, visible } = useOnScreen(session);
  useEffect(() => {
    session.retain();
    return () => session.release();
  }, [session]);

  const view = state.view;
  const render = renderOf(state);
  const status = statusLine(state);
  const revision = view?.artifact.revision ?? 0;
  const controller = session.stateController();

  // OpenUI initialState must stay referentially stable for a revision (openui-package §5): rebuild only on a new revision.
  const bridge = useMemo<UiArtifactStateBridge | null>(() => {
    if (!view || !controller || revision < 1) return null;
    return {
      artifactId: view.artifact.artifactId, revision, stateRevision: controller.current().stateRevision,
      initialState: controller.initialState(),
      onStateUpdate: (snapshot) => {
        controller.update(snapshot);
        noteUiInteraction(view.artifact.artifactId);
      },
      recordSelection: (listId, items, visibleOrder) => controller.recordSelection(listId, items, visibleOrder),
      dirtyFields: () => controller.dirtyFields(),
      declared: view.declared ?? { stateNames: [], formNames: [] },
      canPersist: Boolean(view.access?.canPersistState)
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a new object per revision only
  }, [controller, revision, view?.artifact.artifactId]);

  const continueWith = useCallback((request: ContinueRequest) => {
    if (!onContinue) return;
    void session.flush().finally(() => onContinue({ ...request, stateRevision: controller?.current().stateRevision ?? request.stateRevision }));
  }, [controller, onContinue, session]);

  const attempt = view?.attempt ?? null;
  const access = view?.access;
  const live = Boolean(attempt?.live) || state.phase === 'starting' || state.phase === 'streaming';
  const accepted = render.mode === 'generated';
  const reason = state.notice?.reason ?? attempt?.reason ?? null;
  const stopped = !live && attempt !== null && ['failed', 'canceled', 'interrupted'].includes(attempt.state);
  const canRetry = Boolean(runId && access?.canRetry && access.isActor && stopped && !accepted && (!reason || FAILURE_RETRYABLE.has(reason)));
  const l = useGenUiLocale();
  // C reports when the revision on screen is older than the latest (the dirty-field warning): an edit would change the latest.
  const [older, setOlder] = useState<OlderRevision>(null);
  // Only the person who asked may change the view (the server refuses anyone else), never while it is being built or updated.
  const { canEdit, note: editNote } = editAccess({ access, accepted, live, older });
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const retry = async () => {
    if (!runId) return;
    setConfirmRetry(false);
    const result = await session.retry(runId, surface);
    setProblem(result.ok ? null : result.code === 'ui_not_eligible' ? 'This answer can’t get a new interactive view.' : 'The view couldn’t be started again. The answer above is complete.');
  };

  return (
    <div ref={ref} data-rafii-generated-host='' data-surface={surface} data-generation-phase={generationStateOf(state) ?? undefined} className='flex min-w-0 flex-col gap-2'>
      <UiArtifactStateContext.Provider value={bridge}>
        <GeneratedRenderer render={render} view={view} transport={session.transport} surface={surface} status={status} active={visible} onContinue={continueWith}
          onRetry={canRetry && !confirmRetry ? () => setConfirmRetry(true) : null} onExpand={onExpand && canExpand(surface) ? onExpand : null} onNavigate={onNavigate}
          nativeResult={nativeResult} onOlderRevision={setOlder} />
      </UiArtifactStateContext.Provider>
      {access?.revokedRefs?.length ? <p role='note' className='text-muted-foreground text-xs'>Some items in this view were removed or are no longer shared, so they are left out.</p> : null}
      {problem && <p role='alert' className='text-destructive text-xs'>{problem}</p>}
      {(live && access?.isActor && view?.artifact.artifactId) || (canEdit && !editing) ? (
        <div className='flex flex-wrap items-center gap-2'>
          {live && access?.isActor && view?.artifact.artifactId ? <QuietButton onClick={() => void session.cancel()} disabled={session.busy('cancel')}>Stop building</QuietButton> : null}
          {canEdit && !editing ? <QuietButton onClick={() => { void preloadEditSuggestions(); setEditing(true); }}>{l.t('changeView')}</QuietButton> : null}
        </div>
      ) : null}
      {editNote && !editing ? <p role='note' className='text-muted-foreground text-xs'>{l.t(editNote)}</p> : null}
      {confirmRetry && (
        <div role='group' aria-label='Try again' className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
          <p>Build this view again? It runs a new presentation and is billed like the original answer. Nothing else is repeated.</p>
          <div className='flex flex-wrap gap-2'>
            <QuietButton onClick={() => void retry()} disabled={session.busy('retry')}>Build again</QuietButton>
            <QuietButton onClick={() => setConfirmRetry(false)}>Not now</QuietButton>
          </div>
        </div>
      )}
      {editing && <EditView session={session} view={view} blocked={editNote} onDone={() => setEditing(false)} />}
    </div>
  );
}

type Suggester = typeof import('./edit-suggestions');
let suggester: Suggester | null = null;

/**
 * The chip deriver loads when the person opens the edit field, not with every answer (D14); the parser split it uses ships
 * with the renderer already. Resolves null when it can't load: then there are no chips and typing still works.
 */
export function preloadEditSuggestions(): Promise<Suggester | null> {
  if (suggester) return Promise.resolve(suggester);
  return import('./edit-suggestions')
    .then((deriver) => {
      suggester = deriver;
      return deriver;
    })
    .catch(() => null);
}

function useSuggester(enabled: boolean): Suggester | null {
  const [loaded, setLoaded] = useState<Suggester | null>(suggester);
  useEffect(() => {
    if (!enabled || loaded) return;
    let alive = true;
    void preloadEditSuggestions().then((deriver) => {
      if (alive && deriver) setLoaded(deriver);
    });
    return () => {
      alive = false;
    };
  }, [enabled, loaded]);
  return loaded;
}

export interface SuggestionChipsProps {
  suggestions: readonly EditSuggestion[];
  /** The chip whose words are in the field. */
  pressed: string | null;
  caption: string;
  captionId: string;
  onPick: (suggestion: EditSuggestion) => void;
}

/**
 * The suggestion row: a labelled group of `type="button"` chips (QuietButton), so a tap or Enter never submits the form.
 * Wraps on narrow screens (no truncation: CJK labels stay whole); 44 px targets on coarse pointers; a short fade-in that stops
 * under reduced motion (the OS setting and Rafii's own).
 */
export function SuggestionChips({ suggestions, pressed, caption, captionId, onPick }: SuggestionChipsProps) {
  if (!suggestions.length) return null;
  return (
    <div role='group' aria-labelledby={captionId} data-rafii-edit-suggestions='' className='flex min-w-0 flex-col gap-1.5'>
      <span id={captionId} className='text-muted-foreground text-xs'>{caption}</span>
      <div className='rafii-decorative-motion flex min-w-0 max-w-full flex-wrap gap-2'>
        {suggestions.map((suggestion, index) => (
          <QuietButton key={suggestion.id} pressed={pressed === suggestion.id} onClick={() => onPick(suggestion)} onKeyDown={ignoreRepeat}
            style={{ animationDelay: `${index * 40}ms`, animationFillMode: 'backwards' }}
            className='animate-in fade-in-0 slide-in-from-bottom-1 duration-150 motion-reduce:animate-none max-w-full whitespace-normal text-left pointer-coarse:min-h-11'>
            {suggestion.label}
          </QuietButton>
        ))}
      </div>
    </div>
  );
}

const NONE: readonly EditSuggestion[] = [];
const noSelection = () => () => undefined;

/** A coarse pointer (phone/tablet): the soft keyboard would cover the suggestions, so the field is not focused on open. */
function coarsePointer(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
}

/** A held Enter/Space on a chip repeats; only the first press counts (a repeat never re-toggles, and nothing submits). */
function ignoreRepeat(event: KeyboardEvent<HTMLButtonElement>) {
  if (event.repeat && (event.key === 'Enter' || event.key === ' ')) event.preventDefault();
}

export interface EditViewProps {
  session: ArtifactSession;
  view: UiArtifactViewV1 | null;
  /** Why changing is off right now (an older revision is on screen); chips are hidden and nothing is sent. */
  blocked: GenUiMessageKey | null;
  onDone: () => void;
}

export function EditView({ session, view, blocked, onDone }: EditViewProps) {
  const l = useGenUiLocale();
  const [field, dispatch] = useReducer(editFieldReducer, EMPTY_FIELD);
  const [problem, setProblem] = useState<GenUiMessageKey | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const { announcer, region } = useAnnouncer();
  const ime = useRef(createImeGuard());
  const inputId = useId();
  const captionId = useId();
  const input = useRef<HTMLInputElement>(null);
  // The field takes focus when it opens (the button that opened it is gone), so typing goes straight into the request.
  useEffect(() => {
    if (!coarsePointer()) input.current?.focus();
  }, []);

  // The selection the person sees in this tab (saved or not). Chips count it and the request carries the same object.
  const controller = session.stateController();
  const subscribe = useMemo(() => (controller ? controller.subscribeSelection : noSelection), [controller]);
  const readLocal = useCallback(() => controller?.selection() ?? null, [controller]);
  const local = useSyncExternalStore(subscribe, readLocal, readLocal);
  const selectionNow = useCallback(() => liveSelection(controller?.selection(), session.getState().view?.artifact.safeState), [controller, session]);
  const selection = useMemo(() => liveSelection(local, view?.artifact.safeState), [local, view?.artifact.safeState]);

  const deriver = useSuggester(!blocked);
  const source = view?.artifact.canonicalSource ?? null;
  const queries = view?.manifest?.queries;
  const journeys = useMemo(() => [...new Set([...(view?.journeyIds ?? []), ...(view?.manifest?.journeyIds ?? [])])], [view?.journeyIds, view?.manifest?.journeyIds]);
  const derive = useCallback((pickedSelection: Record<string, JsonValue> | null, now: number): readonly EditSuggestion[] => {
    if (!deriver || blocked || !source) return NONE;
    try {
      return deriver.suggestEdits({ source, queries, journeyIds: journeys, selection: pickedSelection, language: l.language, timeZone: l.timeZone, now });
    } catch {
      return NONE;
    }
  }, [deriver, blocked, source, queries, journeys, l.language, l.timeZone]);
  const suggestions = useMemo(() => derive(selection, clock), [derive, selection, clock]);

  const pick = (suggestion: EditSuggestion) => {
    setProblem(null);
    const again = field.filled?.id === suggestion.id;
    dispatch({ type: 'pick', suggestion: { id: suggestion.id, rule: suggestion.rule, instruction: suggestion.instruction } });
    if (!again) announcer.announce(l.t('chipAdded'));   // focus stays on the chip: a second Enter never submits
  };

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (blocked || session.busy('edit')) return;
    const instruction = field.text.trim();
    if (!instruction) return;
    // The stored selection travels as the edit's `selection` ({items, visible, listId}), so "compare the selected two" means them:
    // read now, from this tab, so a pick made a moment ago is included.
    const current = selectionNow();
    if (field.filled && field.text === field.filled.instruction && deriver) {
      // A suggestion describes the view as it was when it was offered: re-check it against now (selection, day, revision).
      const now = Date.now();
      const stale = deriver.staleSuggestion(field.filled, derive(current, now));
      if (stale) {
        setClock(now);
        dispatch({ type: 'unfill' });
        setProblem(stale === 'selection' ? 'selectionChanged' : 'suggestionStale');
        return;   // nothing was sent, nothing is charged
      }
    }
    const result = await session.edit(instruction, current);
    if (result.ok) {
      dispatch({ type: 'reset' });
      onDone();
      return;
    }
    setProblem(editProblemOf(result));
  };
  const onInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && ime.current.composing(event)) event.preventDefault();
  };
  const onFormKeyDown = (event: KeyboardEvent<HTMLFormElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onDone();
    }
  };
  const chips = blocked ? NONE : suggestions;
  return (
    <form onSubmit={(event) => void submit(event)} onKeyDown={onFormKeyDown} className='rafii-quiet mt-2 flex min-w-0 max-w-full flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      <label htmlFor={inputId} className='flex flex-col gap-2 text-sm font-medium'>
        {l.t('whatShouldChange')}
        <input ref={input} id={inputId} aria-label={l.t('whatShouldChange')} value={field.text} maxLength={2000} onChange={(event) => dispatch({ type: 'type', text: event.target.value })}
          onKeyDown={onInputKeyDown} onCompositionStart={() => ime.current.onCompositionStart()} onCompositionEnd={() => ime.current.onCompositionEnd()}
          placeholder={l.t('editPlaceholder')}
          className='rafii-field rafii-focus min-h-11 rounded-[var(--rafii-radius-control)] px-3 text-base font-normal' />
      </label>
      <SuggestionChips suggestions={chips} pressed={field.filled?.id ?? null} caption={l.t('suggestions')} captionId={captionId} onPick={pick} />
      {canRestore(field) ? (
        <div className='flex'>
          <QuietButton onClick={() => dispatch({ type: 'restore' })} className='pointer-coarse:min-h-11'>{l.t('restoreText')}</QuietButton>
        </div>
      ) : null}
      <p className='text-muted-foreground text-xs'>{l.t('editBilling')}</p>
      {blocked ? <p role='note' className='text-muted-foreground text-xs'>{l.t(blocked)}</p> : null}
      {problem && <p role='alert' className='text-destructive text-xs'>{l.t(problem)}</p>}
      <div className='flex flex-wrap gap-2'>
        <button type='submit' disabled={!field.text.trim() || session.busy('edit') || Boolean(blocked)}
          className='rafii-action rafii-focus min-h-9 rounded-[var(--rafii-radius-control)] px-3 text-sm disabled:opacity-60 pointer-coarse:min-h-11'>
          {l.t('updateView')}
        </button>
        <QuietButton onClick={onDone} className='pointer-coarse:min-h-11'>{l.t('cancel')}</QuietButton>
      </div>
      {region}
    </form>
  );
}
