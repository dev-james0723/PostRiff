/**
 * Starts the browser Sentry SDK on confirmed (committed) non-play routes only (decisions D1, D11).
 * One import in flight at most, at most one init, and no deadline: after the import resolves, the CURRENT path is
 * checked again, and if the page is on /play the start stays pending until the next committed non-play route.
 * Pure (no imports) so node's test runner can load it directly (`web/tests/sentry-starter.test.mjs`).
 */

export type SentryStarter<M> = {
  /** Call on boot and on every committed route. Resolves the SDK once initialised, else null. */
  ensure(pathname: string): Promise<M | null>;
  started(): boolean;
  /** The initialised SDK, or null. */
  current(): M | null;
};

export function createSentryStarter<M>(deps: {
  enabled: boolean;
  isPlay: (pathname: string) => boolean;
  currentPath: () => string;
  load: () => Promise<M>;
  init: (sdk: M) => void;
}): SentryStarter<M> {
  let loading: Promise<M | null> | null = null;
  let initialised: M | null = null;

  return {
    async ensure(pathname) {
      if (initialised) return initialised;
      if (!deps.enabled || deps.isPlay(pathname)) return null;
      loading ??= deps.load().catch(() => null);
      const sdk = await loading;
      // Re-check where the page is NOW: the child may have gone back to /play while the chunk was loading.
      if (!initialised && sdk && !deps.isPlay(deps.currentPath())) {
        deps.init(sdk);
        initialised = sdk;
      }
      return initialised;
    },
    started: () => initialised !== null,
    current: () => initialised
  };
}
