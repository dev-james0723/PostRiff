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
import { formatDateTime } from '@/lib/time';
import { renderOf, statusLine, type ArtifactViewState } from '../state/artifact-machine';
import { UiArtifactStateContext, type UiArtifactStateBridge } from '../state/context';
import { noteUiInteraction } from '../state/registry';
import { GeneratedFrame, QuietButton } from './frame';
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
  useEffect(() => {
    const node = ref.current;
    let onScreen = true;
    let pageVisible = typeof document === 'undefined' || document.visibilityState !== 'hidden';
    const update = () => session.setVisible(viewId, onScreen && pageVisible);
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
  return ref;
}

export interface GeneratedArtifactProps {
  session: ArtifactSession;
  surface: UiSurface;
  /** The parent run, for an explicit "Try again". */
  runId: string | null;
  onContinue?: (request: ContinueRequest) => void;
  onExpand?: () => void;
  nativeResult?: ReactNode;
}

export function GeneratedArtifact({ session, surface, runId, onContinue, onExpand, nativeResult }: GeneratedArtifactProps) {
  const state = useSyncExternalStore(session.subscribe, session.getState, session.getState);
  const ref = useOnScreen(session);
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
      recordSelection: (listId, items, visible) => controller.recordSelection(listId, items, visible),
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

  const notices: ReactNode[] = [];
  if (access?.historical && view?.artifact.asOf) {
    notices.push(<p key='asof' className='text-muted-foreground text-xs'>Shown as of {formatDateTime(Date.parse(view.artifact.asOf) / 1000)}. Live data needs a fresh answer.</p>);
  }
  if (access?.revokedRefs?.length) {
    notices.push(<p key='revoked' role='note' className='text-muted-foreground text-xs'>Some items in this view were removed or are no longer shared, so they are left out.</p>);
  }
  if (session.lostFields.length) {
    notices.push(<LostFields key='lost' session={session} />);
  }
  if (problem) notices.push(<p key='problem' role='alert' className='text-destructive text-xs'>{problem}</p>);

  const controls: ReactNode[] = [];
  if (live && access?.isActor && state.view?.artifact.artifactId) {
    controls.push(<QuietButton key='stop' onClick={() => void session.cancel()} disabled={session.busy('cancel')}>Stop building</QuietButton>);
  }
  if (canRetry && !confirmRetry) controls.push(<QuietButton key='retry' onClick={() => setConfirmRetry(true)}>Try again</QuietButton>);
  if (canEdit && !editing) controls.push(<QuietButton key='edit' onClick={() => setEditing(true)}>Change this view</QuietButton>);
  if (accepted && onExpand && canExpand(surface)) controls.push(<QuietButton key='expand' label='Expand interactive view' onClick={onExpand}>Expand</QuietButton>);

  return (
    <div ref={ref} className='min-w-0'>
      <GeneratedFrame surface={surface} busy={live} status={status} artifactId={view?.artifact.artifactId ?? session.artifactId} generationState={generationStateOf(state)}
        notices={notices.length ? <>{notices}</> : null} controls={controls.length ? <>{controls}</> : null}>
        {(render.mode === 'generated' || render.mode === 'preview') && (
          <UiArtifactStateContext.Provider value={bridge}>
            <GeneratedRenderer render={render} transport={session.transport} surface={surface} onContinue={continueWith} nativeResult={nativeResult} />
          </UiArtifactStateContext.Provider>
        )}
      </GeneratedFrame>
      {confirmRetry && (
        <div role='group' aria-label='Try again' className='rafii-quiet mt-2 flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
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
        <input id={inputId} value={text} maxLength={2000} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown}
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

/** A newer revision no longer has fields the person typed into: say so and keep the values readable (never silently lost). */
function LostFields({ session }: { session: ArtifactSession }) {
  const values = session.lostValues;
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;
  return (
    <div data-rafii-dirty-conflict='' role='alertdialog' aria-label='Values not in the updated view' className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3 text-xs'>
      <p>The updated view doesn’t have {session.lostFields.length === 1 ? 'one field' : `${session.lostFields.length} fields`} you typed into. Your values are kept here until you leave.</p>
      <details>
        <summary className='rafii-focus cursor-pointer rounded'>Show what you typed</summary>
        <ul className='mt-1 flex flex-col gap-0.5'>
          {session.lostFields.map((field) => (
            <li key={field} className='break-words'><span className='font-medium'>{field.replace(/^\$/, '')}</span>: {String(typeof values[field] === 'object' ? JSON.stringify(values[field]) : values[field] ?? '')}</li>
          ))}
        </ul>
      </details>
      <QuietButton onClick={() => setDismissed(true)}>OK</QuietButton>
    </div>
  );
}
