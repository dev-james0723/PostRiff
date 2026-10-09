'use client';

import { Component, useCallback, useEffect, useMemo, useState, type ComponentType, type ErrorInfo, type ReactNode } from 'react';
import { StateMessage } from '@/components/rafii';
import { PanelButton as Button } from '../../ui/controls';
import { Skeleton } from '@/components/ui/skeleton';
import { parseLibraryProps, type LibraryAssetRef, type LibraryLocator } from '@/lib/library/openui-schemas';
import { applyStreamFrame, canRepair, fallbackItems, initialSurfaceState, surfacePhase, type StreamFrame, type TaskSurfaceState, type ValidatedTaskNode } from '@/lib/library/openui-policy';
import { normalizeKey } from '@/lib/library/url-state';
import { useLibraryActionAdapter } from './action-adapter';
import { LibraryTaskHostContext, SourceScope, type LibraryOnAction, type LibraryTaskHost } from './components';
import { LIBRARY_OPENUI_DESCRIPTORS, libraryDescriptor, type LibraryOpenUiDescriptor } from './descriptors';

/** Catches a renderer or component failure and shows the deterministic view of the same validated data instead. */
export class LibraryOpenUiErrorBoundary extends Component<
  { fallback: ReactNode; resetKey?: string; onError?: (error: Error) => void; children: ReactNode },
  { failed: boolean; resetKey?: string }
> {
  state: { failed: boolean; resetKey?: string } = { failed: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  /** A new input (another task, revision or node) gets a fresh attempt; the same input stays on its fallback. */
  static getDerivedStateFromProps(props: { resetKey?: string }, state: { failed: boolean; resetKey?: string }) {
    return props.resetKey !== state.resetKey ? { failed: false, resetKey: props.resetKey } : null;
  }

  componentDidCatch(error: Error, _info: ErrorInfo) {
    this.props.onError?.(error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** The plainest honest view: the titled items the result names, each openable. Needs nothing that could fail. */
function PlainItems({ nodes, onAction }: { nodes: readonly ValidatedTaskNode[]; onAction: LibraryOnAction }) {
  const items = fallbackItems(nodes);
  if (!items.length) return null;
  return (
    <ul aria-label='Items in this result' className='flex flex-col gap-1'>
      {items.map((item) => (
        <li key={`${item.path}-${item.ref.assetId}-${item.ref.versionId}`} className='flex min-h-11 items-center justify-between gap-2 text-sm'>
          <span className='min-w-0 truncate'>{item.title}</span>
          <Button variant='quiet' size='lg' className='h-11 shrink-0' onClick={(event) => onAction('library.open', { assetRef: { assetId: item.ref.assetId, versionId: item.ref.versionId, sha256: item.ref.sha256 ?? '' } }, event)}>
            Open
          </Button>
        </li>
      ))}
    </ul>
  );
}

/**
 * The deterministic renderer: each validated node through its descriptor's component (the Library's own pieces),
 * each behind its own boundary so one failing part falls back to plain items while the rest stays usable. Each node's
 * wrapper names its path, so a write only counts from a control inside the node that was issued the action.
 */
export function DeterministicTaskView({ nodes, onAction }: { nodes: readonly ValidatedTaskNode[]; onAction: LibraryOnAction }) {
  return (
    <div className='flex min-w-0 flex-col gap-3'>
      {nodes.map((node) => {
        const descriptor = libraryDescriptor(node.component);
        if (!descriptor) return null;
        const Rendered = descriptor.component;
        return (
          <div key={node.path} data-task-component={node.component} data-task-node={node.path} className='flex min-w-0 flex-col gap-3'>
            <LibraryOpenUiErrorBoundary resetKey={node.path} fallback={<PlainItems nodes={[node]} onAction={onAction} />}>
              <Rendered {...node.props} onAction={onAction} />
            </LibraryOpenUiErrorBoundary>
            {node.children.length ? (
              <div className='border-foreground/10 border-l pl-3'>
                <DeterministicTaskView nodes={node.children} onAction={onAction} />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/** What a site-wide OpenUI renderer receives when the runtime owner mounts it here. */
export interface LibraryTaskRendererProps {
  nodes: readonly ValidatedTaskNode[];
  descriptors: readonly LibraryOpenUiDescriptor[];
  onAction: LibraryOnAction;
  streaming: boolean;
  /** Always false: the OpenUI renderer mounted here must not publish observability (rafii-genui/1, D-A3). */
  publishObservability: false;
}

export interface LibraryTaskResult {
  taskId: string;
  frame: StreamFrame;
}

/**
 * The task-result region (UI spec §7–8). It validates every frame against the allowlist, keeps scope, selection and
 * drafts across partial and invalid frames, asks for at most one repair, enables writes only on a finished result
 * after a person's press, and falls back to the deterministic view when no renderer is mounted or it errors.
 */
export function LibraryTaskSurface({
  result,
  scope,
  collectionName,
  selection,
  onSelectionChange,
  onOpen,
  knownRevision = null,
  replay = false,
  renderer: Renderer,
  onRepair,
  onAnnounce,
  generated = true
}: {
  result: LibraryTaskResult | null;
  scope: TaskSurfaceState['scope'];
  collectionName?: string | null;
  selection: readonly string[];
  onSelectionChange: (ids: string[]) => void;
  onOpen: (ref: LibraryAssetRef, locator: LibraryLocator | null) => void;
  knownRevision?: number | null;
  replay?: boolean;
  renderer?: ComponentType<LibraryTaskRendererProps>;
  onRepair?: () => void;
  onAnnounce?: (message: string) => void;
  /** The task_ui flag: when off, a mounted renderer is not used and the result shows in the standard view. */
  generated?: boolean;
}) {
  const [state, setState] = useState<TaskSurfaceState>(() => initialSurfaceState(scope, [...selection]));
  const [hydrated, setHydrated] = useState(false);
  const [rendererFailed, setRendererFailed] = useState(false);
  useEffect(() => setHydrated(true), []);

  // Frames change what is shown; they never touch scope, selection or drafts.
  const frame = result?.frame ?? null;
  useEffect(() => {
    if (frame) setState((current) => applyStreamFrame(current, frame, parseLibraryProps));
  }, [frame]);
  const taskId = result?.taskId ?? '';
  useEffect(() => {
    setRendererFailed(false);
  }, [taskId]);
  const repairing = canRepair(state);
  useEffect(() => {
    if (repairing) onRepair?.();
  }, [repairing, onRepair]);

  const phase = surfacePhase(state, { hydrated, replay });
  const selected = useMemo(() => new Set(selection.map(normalizeKey)), [selection]);
  const onSelect = useCallback(
    (ref: LibraryAssetRef, on: boolean) => {
      const key = normalizeKey(ref.assetId);
      const rest = selection.filter((id) => normalizeKey(id) !== key);
      onSelectionChange(on ? [...rest, ref.assetId] : rest);
    },
    [selection, onSelectionChange]
  );
  const adapter = useLibraryActionAdapter({
    nodes: state.nodes,
    phase,
    knownRevision,
    onSelect,
    onOpen,
    onOutcome: (_actionId, outcome) => onAnnounce?.(outcome.status === 'applied' ? 'Done.' : (outcome.message ?? 'The action didn’t finish.'))
  });

  const host: LibraryTaskHost = {
    isSelected: (ref) => selected.has(normalizeKey(ref.assetId)),
    retry: adapter.retry,
    writesEnabled: adapter.writesEnabled,
    busyActionId: adapter.busyActionId,
    outcomeOf: (actionId) => adapter.outcomes[actionId],
    draft: (key, initial) => state.drafts[key] ?? initial,
    setDraft: (key, value) => setState((current) => ({ ...current, drafts: { ...current.drafts, [key]: value } }))
  };

  const deterministic = <DeterministicTaskView nodes={state.nodes} onAction={adapter.onAction} />;
  const streaming = state.status === 'streaming' || state.status === 'repairing';

  return (
    <LibraryTaskHostContext.Provider value={host}>
      <section aria-label='Task result' aria-busy={streaming || undefined} className='flex min-w-0 flex-col gap-3'>
        <SourceScope kind={scope.kind} selectedCount={scope.selectedCount ?? selection.length} collectionName={collectionName ?? undefined} onAction={adapter.onAction} />
        {state.status === 'error' ? (
          <StateMessage
            kind='error'
            layout='inline'
            title='Part of this result couldn’t be shown safely'
            description={state.nodes.length ? 'Showing the last checked version. Your selection and scope are unchanged.' : 'Your selection and scope are unchanged. Ask again, or keep browsing the Library.'}
          />
        ) : null}
        {state.status === 'repairing' ? <p className='text-muted-foreground text-xs'>Checking the result again…</p> : null}
        {streaming && state.nodes.length === 0 ? (
          <div role='status' aria-label='Preparing the result' className='flex flex-col gap-2'>
            <Skeleton className='h-24 w-full rounded-[var(--rafii-radius-card)]' />
            <Skeleton className='h-24 w-full rounded-[var(--rafii-radius-card)]' />
          </div>
        ) : Renderer && generated && !rendererFailed ? (
          <LibraryOpenUiErrorBoundary resetKey={taskId} fallback={deterministic} onError={() => setRendererFailed(true)}>
            <Renderer nodes={state.nodes} descriptors={LIBRARY_OPENUI_DESCRIPTORS} onAction={adapter.onAction} streaming={streaming} publishObservability={false} />
          </LibraryOpenUiErrorBoundary>
        ) : (
          deterministic
        )}
        {!streaming && state.status !== 'error' && state.nodes.length === 0 && result ? <p className='text-muted-foreground text-sm'>This result has no items.</p> : null}
      </section>
    </LibraryTaskHostContext.Provider>
  );
}
