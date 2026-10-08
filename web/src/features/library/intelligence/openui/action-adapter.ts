'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ActionEnvelope } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import { READ_ONLY_ACTION_TYPES, type LibraryAssetRef, type LibraryLocator } from '@/lib/library/openui-schemas';
import {
  collectIssuedActions,
  collectServerRefs,
  createLibraryDispatcher,
  createReadBudget,
  refKey,
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

/** A trusted pointer or key press within this window counts as the person's activation (fallback for older engines). */
const ACTIVATION_WINDOW_MS = 1500;

function isRef(value: unknown): value is LibraryAssetRef {
  return Boolean(value) && typeof value === 'object' && typeof (value as LibraryAssetRef).assetId === 'string' && typeof (value as LibraryAssetRef).versionId === 'string';
}

/**
 * The host side of a generated Library task result (UI spec §8). `onAction` is what the descriptors' components call:
 *   - library.select / library.open stay in the browser and only accept refs this result was issued;
 *   - server actions must name an envelope this result carries, need a fresh user activation on a finished result,
 *     get a new idempotency key per activation, run one at a time, and are never retried automatically.
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
  const readBudget = useRef(createReadBudget());
  const [outcomes, setOutcomes] = useState<Record<string, DispatchOutcome>>({});
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const tokens = useRef<Record<string, ActivationToken>>({});
  const lastTrustedPress = useRef(0);

  // A new result is a new render cycle for the read budget.
  useEffect(() => {
    readBudget.current.reset();
  }, [nodes]);

  // Trusted presses only (synthetic events from generated code have isTrusted === false).
  useEffect(() => {
    const mark = (event: Event) => {
      if (event.isTrusted) lastTrustedPress.current = Date.now();
    };
    document.addEventListener('pointerdown', mark, true);
    document.addEventListener('keydown', mark, true);
    return () => {
      document.removeEventListener('pointerdown', mark, true);
      document.removeEventListener('keydown', mark, true);
    };
  }, []);

  const record = useCallback(
    (actionId: string, outcome: DispatchOutcome) => {
      setOutcomes((current) => ({ ...current, [actionId]: outcome }));
      onOutcome?.(actionId, outcome);
    },
    [onOutcome]
  );

  const userActivation = useCallback(() => {
    const live = typeof navigator !== 'undefined' && navigator.userActivation ? navigator.userActivation.isActive : false;
    return live || Date.now() - lastTrustedPress.current < ACTIVATION_WINDOW_MS;
  }, []);

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
    (actionId: string, inputs: Record<string, unknown>) => {
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
        const activation = dispatcher.activate({ userActivation: userActivation(), phase });
        if (!activation.ok) {
          const message =
            activation.reason === 'streaming' ? 'Wait until the result has finished.' : activation.reason === 'no-user-activation' ? 'Changes need a press from you.' : 'Refresh the result to act on it.';
          record(envelope.actionId, { status: 'refused', message, retryable: false });
          return;
        }
        token = activation.token;
        tokens.current[envelope.actionId] = token;
      }
      void dispatchLibraryAction(envelope, token);
    },
    [dispatcher, dispatchLibraryAction, issued, onOpen, onSelect, phase, record, serverRefs, userActivation]
  );

  /** An explicit retry of the same activation after a failure: same idempotency key, never automatic. */
  const retry = useCallback(
    (actionId: string) => {
      const envelope = issued.get(actionId);
      const token = tokens.current[actionId];
      if (!envelope || !token || outcomes[actionId]?.status !== 'failed') return;
      void dispatchLibraryAction(envelope, token, true);
    },
    [dispatchLibraryAction, issued, outcomes]
  );

  return { onAction, dispatchLibraryAction, retry, outcomes, busyActionId, writesEnabled: phase === 'live' };
}
