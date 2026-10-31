/**
 * Settling one Agent Runtime turn when its POST response may never arrive.
 *
 * A panel turn is one long POST (45–130 s). In a background tab the response can be lost (a dropped connection, a frozen
 * page) while the run completes on the server; with nothing else to listen to, the panel stayed "Working…" until a reload
 * and the generated view for that answer was never requested. The server answers a resend with the same idempotency key
 * from the stored run (`runtime.turn` → `_stored`), so the turn can always be read back by its key, new conversation or not.
 *
 * Rules:
 * - Nothing polls while the tab is hidden. The read happens when the person can see the tab again (visibilitychange →
 *   visible, focus, online), when the run observer saw the run end, or on a bounded slow check while visible.
 * - A resend is only made once the original is old enough to have opened its run (`minAgeMs`), so it reads the record
 *   instead of racing the original into a second conversation.
 * - Only a finished record settles the turn (`running` keeps it working: that is the truth). The turn settles once; the
 *   lost request is aborted and later wakes are ignored, so everything downstream (a generated view) happens once.
 * - A refusal from the server is not resent; when the record cannot be read either, the original error surfaces.
 */

/** Statuses of a run that has not finished yet. */
const UNSETTLED = new Set(['running', 'queued', 'pending']);
const MIN_AGE_MS = 15_000;
const SLOW_CHECK_MS = 30_000;
const SLOW_CHECK_MAX = 40;

export function isSettled(response: { status?: unknown } | null | undefined): boolean {
  return Boolean(response && typeof response.status === 'string' && !UNSETTLED.has(response.status));
}

/** No answer came from the application: a network failure, an aborted/timed-out request, or a proxy error without its code. */
export function responseLost(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const { status, code } = error as Error & { status?: unknown; code?: unknown };
  if (error.name === 'ApiError' && typeof status === 'number') return [502, 503, 504].includes(status) && !code;
  return error instanceof TypeError || error.name === 'TimeoutError' || error.name === 'AbortError';
}

export interface SettleOptions<T> {
  /** The original request. */
  send: (signal: AbortSignal) => Promise<T>;
  /** The identical request with the same idempotency key: the server answers it from the stored run. */
  replay: () => Promise<T>;
  /** Subscribe to moments worth a read (see `resyncSignals`); returns the unsubscribe. */
  wake: (listener: () => void) => () => void;
  now?: () => number;
  minAgeMs?: number;
  sleep?: (ms: number) => Promise<void>;
}

export function settleAgentTurn<T extends { status?: unknown }>(options: SettleOptions<T>): Promise<T> {
  const { send, replay, wake } = options;
  const now = options.now ?? (() => Date.now());
  const minAgeMs = options.minAgeMs ?? MIN_AGE_MS;
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const startedAt = now();
  const controller = new AbortController();

  return new Promise<T>((resolve, reject) => {
    let done = false;
    let checking = false;
    let lostError: unknown = null;
    let unsubscribe: (() => void) | null = null;

    const finish = (outcome: { value: T } | { error: unknown }) => {
      if (done) return;
      done = true;
      unsubscribe?.();
      if ('value' in outcome) {
        controller.abort();
        resolve(outcome.value);
      } else {
        reject(outcome.error);
      }
    };

    /** Read the turn back by its key; settle only on a finished record. */
    const check = async () => {
      if (done || checking || now() - startedAt < minAgeMs) return;
      checking = true;
      try {
        const record = await replay();
        if (isSettled(record)) finish({ value: record });
      } catch (error) {
        // A read that fails changes nothing while the original may still answer; after a lost original it is the end.
        if (lostError !== null && !responseLost(error)) finish({ error: lostError });
      } finally {
        checking = false;
      }
    };

    unsubscribe = wake(() => void check());

    send(controller.signal).then(
      (value) => finish({ value }),
      async (error) => {
        if (done) return;
        if (!responseLost(error)) return finish({ error });
        lostError = error;
        const wait = minAgeMs - (now() - startedAt);
        if (wait > 0) await sleep(wait);
        if (done || checking) return;   // a read already in flight settles it (or ends it, now that the original is lost)
        try {
          checking = true;
          const record = await replay();
          if (isSettled(record)) finish({ value: record });
          // Still running: keep the turn working; the next visible wake reads it again.
        } catch {
          finish({ error });
        } finally {
          checking = false;
        }
      }
    );
  });
}

/* ---------- moments worth a read ---------- */

const runEndedListeners = new Set<() => void>();

function visible(): boolean {
  return document.visibilityState === 'visible';
}

/** The run observer (`useThinkingState`) saw a run stop running: a pending turn may read its record now. */
export function noteRunEnded() {
  // Deleting from a Set while iterating it is safe: a listener that unsubscribes is simply not visited again.
  for (const listener of runEndedListeners) listener();
}

/**
 * Calls `listener` when the tab becomes visible, regains focus or comes back online (focus/online only while visible), when
 * the run observer reports a finished run, and on a slow check every `intervalMs` while visible (at most `maxTicks`). A
 * hidden tab schedules nothing.
 */
export function resyncSignals(listener: () => void, options: { intervalMs?: number; maxTicks?: number } = {}): () => void {
  const intervalMs = options.intervalMs ?? SLOW_CHECK_MS;
  const maxTicks = options.maxTicks ?? SLOW_CHECK_MAX;
  runEndedListeners.add(listener);
  if (typeof window === 'undefined' || typeof document === 'undefined') return () => void runEndedListeners.delete(listener);
  let ticks = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;
  const clear = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  const arm = () => {
    clear();
    if (stopped || !visible() || ticks >= maxTicks) return;
    timer = setTimeout(() => {
      timer = null;
      ticks += 1;
      listener();
      arm();
    }, intervalMs);
  };
  const onVisibility = () => {
    if (visible()) {
      listener();
      arm();
    } else {
      clear();
    }
  };
  const onWake = () => {
    if (visible()) listener();
  };
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('focus', onWake);
  window.addEventListener('online', onWake);
  arm();
  return () => {
    stopped = true;
    clear();
    runEndedListeners.delete(listener);
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('focus', onWake);
    window.removeEventListener('online', onWake);
  };
}
