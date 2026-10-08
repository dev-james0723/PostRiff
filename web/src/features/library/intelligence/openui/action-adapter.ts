'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ActionEnvelope } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import { READ_ONLY_ACTION_TYPES, type LibraryAssetRef, type LibraryLocator } from '@/lib/library/openui-schemas';
import {
  checkActivation,
  collectIssuedActions,
  collectIssuedOwners,
  collectServerRefs,
  createLibraryDispatcher,
  createReadBudget,
  refKey,
  type ActivationEventLike,
  type ActivationToken,
  type DispatchOutcome,
  type IssuedEnvelopeLike,
  type SurfacePhase,
  type ValidatedTaskNode
} from '@/lib/library/openui-policy';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryOnAction } from './components';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isRef(value: unknown): value is LibraryAssetRef {
  return Boolean(value) && typeof value === 'object' && typeof (value as LibraryAssetRef).assetId === 'string' && typeof (value as LibraryAssetRef).versionId === 'string';
}

/**
 * The host side of a generated Library task result (UI spec §8). `onAction` is what the descriptors' components call:
 *   - library.select / library.open stay in the browser and only accept refs this result was issued;
 *   - server actions must name an envelope this result carries and need the person's trusted press on that action's
 *     own control, inside the component that was issued it, on a finished result. Each activation gets a new
 *     idempotency key; after a failure the control becomes "Retry", which re-sends the same activation (same key);
 *     they run one at a time and are never retried automatically.
 * `dispatchLibraryAction(envelope, token)` is the single path to `api.libraryAction`.
 */
export function useLibraryActionAdapter({
  nodes,
  phase,
  knownRevision = null,
  onSelect,
  onOpen,
  onOutcome
}: {
  nodes: readonly ValidatedTaskNode[];
  phase: SurfacePhase;
  knownRevision?: number | null;
  onSelect: (ref: LibraryAssetRef, selected: boolean) => void;
  onOpen: (ref: LibraryAssetRef, locator: LibraryLocator | null) => void;
  /** Announce an outcome (one polite live region on the page). */
  onOutcome?: (actionId: string, outcome: DispatchOutcome) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const dispatcher = useMemo(
    () =>
      createLibraryDispatcher({
        send: (envelope) => api.libraryAction(workspaceId, envelope as unknown as ActionEnvelope),
        newKey: () => newIdempotencyKey('lib-ui', randomKey),
        readOnlyTypes: READ_ONLY_ACTION_TYPES
      }),
    [api, workspaceId]
  );
  const serverRefs = useMemo(() => collectServerRefs(nodes), [nodes]);
  const issued = useMemo(() => collectIssuedActions(nodes), [nodes]);
  const owners = useMemo(() => collectIssuedOwners(nodes), [nodes]);
  const readBudget = useRef(createReadBudget());
  const [outcomes, setOutcomes] = useState<Record<string, DispatchOutcome>>({});
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const tokens = useRef<Record<string, ActivationToken>>({});

  // A new result is a new render cycle for the read budget.
  useEffect(() => {
    readBudget.current.reset();
  }, [nodes]);

  const record = useCallback(
    (actionId: string, outcome: DispatchOutcome) => {
      setOutcomes((current) => ({ ...current, [actionId]: outcome }));
      onOutcome?.(actionId, outcome);
    },
    [onOutcome]
  );

  const dispatchLibraryAction = useCallback(
    async (envelope: IssuedEnvelopeLike, token: ActivationToken | null, retry = false) => {
      setBusyActionId(envelope.actionId);
      try {
        const outcome = await dispatcher.dispatch(envelope, { token, serverRefs, knownRevision, retry, readBudget: readBudget.current });
        record(envelope.actionId, outcome);
        return outcome;
      } finally {
        setBusyActionId(null);
      }
    },
    [dispatcher, serverRefs, knownRevision, record]
  );

  const onAction: LibraryOnAction = useCallback(
    (actionId: string, inputs: Record<string, unknown>, event?: ActivationEventLike | null) => {
      if (actionId === 'library.select' || actionId === 'library.open') {
        const ref = inputs.assetRef;
        if (!isRef(ref) || !serverRefs.has(refKey(ref))) {
          record(actionId, { status: 'denied', message: 'That item isn’t part of this result.', local: true, retryable: false });
          return;
        }
        if (actionId === 'library.select') onSelect(ref, inputs.selected !== false);
        else onOpen(ref, (inputs.locator as LibraryLocator | undefined) ?? null);
        return;
      }
      const envelope = typeof inputs.actionId === 'string' ? issued.get(inputs.actionId) : undefined;
      if (!envelope || envelope.actionType !== actionId) {
        record(typeof inputs.actionId === 'string' ? inputs.actionId : actionId, { status: 'denied', message: 'This action isn’t part of this result.', local: true, retryable: false });
        return;
      }
      let token: ActivationToken | null = null;
      if (!READ_ONLY_ACTION_TYPES.includes(envelope.actionType)) {
        // Only the trusted press on this action's own control, inside the component that was issued it, counts.
        const activation = dispatcher.activate({ event, actionId: envelope.actionId, owner: owners.get(envelope.actionId), phase });
        if (!activation.ok) {
          const message =
            activation.reason === 'streaming'
              ? 'Wait until the result has finished.'
              : activation.reason === 'no-user-activation'
                ? 'Changes need a press from you.'
                : activation.reason === 'not-owner'
                  ? 'Use the button on this result to make this change.'
                  : 'Refresh the result to act on it.';
          record(envelope.actionId, { status: 'refused', message, retryable: false });
          return;
        }
        token = activation.token;
        tokens.current[envelope.actionId] = token;
      }
      void dispatchLibraryAction(envelope, token);
    },
    [dispatcher, dispatchLibraryAction, issued, onOpen, onSelect, owners, phase, record, serverRefs]
  );

  /**
   * "Retry" on the control after a failure: the same activation and idempotency key, so a write that committed while
   * its response was lost is answered from its receipt instead of applied twice. Still needs a press on that control.
   */
  const retry = useCallback(
    (actionId: string, event?: ActivationEventLike | null) => {
      const envelope = issued.get(actionId);
      const token = tokens.current[actionId];
      if (!envelope || !token || outcomes[actionId]?.status !== 'failed') return;
      if (!checkActivation(event, actionId, owners.get(actionId)).ok) {
        record(actionId, { status: 'failed', message: 'Press Retry on this result to send it again.', retryable: true });
        return;
      }
      void dispatchLibraryAction(envelope, token, true);
    },
    [dispatchLibraryAction, issued, outcomes, owners, record]
  );

  return { onAction, dispatchLibraryAction, retry, outcomes, busyActionId, writesEnabled: phase === 'live' };
}
