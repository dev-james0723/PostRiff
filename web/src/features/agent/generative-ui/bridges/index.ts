/**
 * Lane D — `createUiBridges` (rafii-genui/1, D-A29/D-A40): one query bridge + one action bridge per
 * (transport.scopeKey, artifactId, revision, accepted). The caller disposes the old instance when any of those change.
 *
 * Transport paths: the bridges call `transport.fetch(`${transport.base}/queries`)`, `…/actions/activate` and
 * `…/actions` — full paths built from `transport.base`; the transport adds auth headers only.
 */
import type { ContinueRequest, CreateUiBridges, UiBridges } from './types';
import { createActionBridge } from './action-bridge';
import { createQueryBridge } from './query-bridge';

const MAX_CONTINUE_CHARS = 2000;

export const createUiBridges: CreateUiBridges = ({ transport, artifact, onContinue, now }): UiBridges => {
  const query = createQueryBridge({ transport, artifact, now });
  const action = createActionBridge({
    transport,
    artifact,
    now,
    onResult: (result) => query.invalidate(result.invalidationKeys),
  });
  const dispose = { query: query.dispose, action: action.dispose };
  // Disposing either side stops both: a view that is gone makes no reads and no writes.
  query.dispose = () => {
    dispose.query();
    dispose.action();
  };
  action.dispose = () => {
    dispose.action();
    dispose.query();
  };
  let disposed = false;
  return {
    query,
    action,
    dispose() {
      // Stops both bridges: in-flight reads/writes aborted, debounce timers cleared, caches and listeners dropped.
      if (disposed) return;
      disposed = true;
      query.dispose();
      action.dispose();
    },
    onContinue(request: ContinueRequest) {
      if (disposed) return;
      // A generated follow-up is the person's labeled request through the existing turn path; ids come from the
      // artifact this bridge belongs to, never from the generated control.
      const message = typeof request?.message === 'string' ? request.message.trim().slice(0, MAX_CONTINUE_CHARS) : '';
      if (!message) return;
      const stateRevision =
        typeof request.stateRevision === 'number' && Number.isInteger(request.stateRevision) && request.stateRevision >= 0
          ? request.stateRevision
          : 0;
      onContinue({ message, artifactId: artifact.artifactId, artifactRevision: artifact.revision, stateRevision });
    },
  };
};

export { createActionBridge, newIdempotencyKey } from './action-bridge';
export { createQueryBridge, localResult } from './query-bridge';
export {
  UiBridgesProvider,
  useBindingStatus,
  useRafiiActionBridge,
  useRafiiActionState,
  useRafiiQueryBridge,
  useUiBridges,
} from './context';
export type * from './types';
