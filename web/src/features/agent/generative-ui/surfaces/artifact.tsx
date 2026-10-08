'use client';

/**
 * One generated view on one surface (lane F). It subscribes to the shared ArtifactSession, reports whether it is on screen
 * (hidden views make no requests), provides the persisted view-state bridge to C's renderer, and keeps the person's controls
 * native: stop while preparing, "Try again" after a stop (with its cost note, a new key, only on request), "Change this view"
 * (an explicit, separately billed edit on the revision shown), expand (same artifact in a full-height dialog, never a new
 * conversation) and the warning when an update would drop values the person typed. Nothing here scrolls the conversation.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent, type ReactNode } from 'react';
import type { JsonValue, UiSurface } from '@/lib/agent-runtime/ui-contracts';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { createImeGuard } from '@/lib/ime';
import { renderOf, statusLine, type ArtifactViewState } from '../state/artifact-machine';
import { UiArtifactStateContext, type UiArtifactStateBridge } from '../state/context';
import { noteUiInteraction } from '../state/registry';
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
  const canEdit = Boolean(access?.canEdit && accepted && !live);
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
          nativeResult={nativeResult} />
      </UiArtifactStateContext.Provider>
      {access?.revokedRefs?.length ? <p role='note' className='text-muted-foreground text-xs'>Some items in this view were removed or are no longer shared, so they are left out.</p> : null}
      {problem && <p role='alert' className='text-destructive text-xs'>{problem}</p>}
      {(live && access?.isActor && view?.artifact.artifactId) || (canEdit && !editing) ? (
        <div className='flex flex-wrap items-center gap-2'>
          {live && access?.isActor && view?.artifact.artifactId ? <QuietButton onClick={() => void session.cancel()} disabled={session.busy('cancel')}>Stop building</QuietButton> : null}
          {canEdit && !editing ? <QuietButton onClick={() => setEditing(true)}>Change this view</QuietButton> : null}
        </div>
      ) : null}
      {confirmRetry && (
        <div role='group' aria-label='Try again' className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
          <p>Build this view again? It runs a new presentation and is billed like the original answer. Nothing else is repeated.</p>
          <div className='flex flex-wrap gap-2'>
            <QuietButton onClick={() => void retry()} disabled={session.busy('retry')}>Build again</QuietButton>
            <QuietButton onClick={() => setConfirmRetry(false)}>Not now</QuietButton>
          </div>
        </div>
      )}
      {editing && <EditView session={session} onDone={() => setEditing(false)} />}
    </div>
  );
}

function EditView({ session, onDone }: { session: ArtifactSession; onDone: () => void }) {
  const [text, setText] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const ime = useRef(createImeGuard());
  const inputId = useId();
  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const instruction = text.trim();
    if (!instruction) return;
    const selection = session.getState().view?.artifact.safeState?.['@selection'] as JsonValue | undefined;
    const result = await session.edit(instruction, selection && typeof selection === 'object' && !Array.isArray(selection) ? { selection } : null);
    if (result.ok) {
      setText('');
      onDone();
      return;
    }
    setProblem(result.status === 409 ? 'This view changed since you looked at it. The latest version is shown; ask again.' : result.status === 404
      ? 'Changing views isn’t available here.' : 'That change couldn’t be started. The current view is kept.');
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && ime.current.composing(event)) event.preventDefault();
    if (event.key === 'Escape') {
      event.stopPropagation();
      onDone();
    }
  };
  return (
    <form onSubmit={(event) => void submit(event)} className='rafii-quiet mt-2 flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      <label htmlFor={inputId} className='flex flex-col gap-2 text-sm font-medium'>
        What should change?
        <input id={inputId} aria-label='What should change?' value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown}
          onCompositionStart={() => ime.current.onCompositionStart()} onCompositionEnd={() => ime.current.onCompositionEnd()}
          placeholder='For example: add a chart, compare the selected two, show last month'
          className='rafii-field rafii-focus min-h-11 rounded-[var(--rafii-radius-control)] px-3 text-base font-normal' />
      </label>
      <p className='text-muted-foreground text-xs'>Updating the view is billed separately. The answer and anything you approved stay as they are.</p>
      {problem && <p role='alert' className='text-destructive text-xs'>{problem}</p>}
      <div className='flex flex-wrap gap-2'>
        <button type='submit' disabled={!text.trim() || session.busy('edit')} className='rafii-action rafii-focus min-h-9 rounded-[var(--rafii-radius-control)] px-3 text-sm disabled:opacity-60'>
          Update view
        </button>
        <QuietButton onClick={onDone}>Cancel</QuietButton>
      </div>
    </form>
  );
}
