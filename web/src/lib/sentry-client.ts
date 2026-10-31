import { createSentryStarter } from '@/lib/sentry-starter';
import { isPlayEvent, isPlayPath, isPlayUrl } from '@/lib/play-path';
import { scrubTelemetry } from '@/lib/telemetry';

/**
 * Browser Sentry for Rafii, with the children's /play area excluded (decisions D1, D8, D11).
 * - Started only on confirmed non-play routes: on boot, and on every committed route (SentryRouteStart). The current
 *   path is re-checked after the SDK chunk loads, so it never initialises while the page shows /play.
 * - Once running, the transport drops every envelope while on /play or heading there, beforeSend drops /play events,
 *   and drops caused by /play are taken back out of later client_reports.
 * State lives on one global object so a duplicated copy of this module can never init twice or split the gate.
 */

type SentryModule = typeof import('@sentry/nextjs');
type Discard = { reason: string; category: string; quantity: number };
type EnvelopeItem = [{ type?: string }, unknown];
type Shared = {
  /** Set by Next's onRouterTransitionStart before the address bar changes (Sentry's pushState hook fires then too). */
  headingToPlay: boolean;
  /** Events dropped because of /play, by category, still to be removed from a later client_report. */
  playDrops: Record<string, number>;
  starter: ReturnType<typeof createSentryStarter<SentryModule>> | null;
};

const KEY = Symbol.for('rafii.sentry');
const store = globalThis as unknown as Record<symbol, Shared | undefined>;
const shared: Shared = (store[KEY] ??= { headingToPlay: false, playDrops: {}, starter: null });

const onPlay = () => shared.headingToPlay || isPlayPath(window.location.pathname);

function dropForPlay(category: string): null {
  shared.playDrops[category] = (shared.playDrops[category] ?? 0) + 1;
  return null;
}

/** Removes /play's own before_send drops from client_report items; returns null when nothing is left to send. */
function withoutPlayDrops<E>(envelope: E): E | null {
  const drops = shared.playDrops;
  if (!Object.values(drops).some(Boolean)) return envelope;
  const [headers, items] = envelope as unknown as [unknown, EnvelopeItem[]];
  const kept = items.flatMap((item): EnvelopeItem[] => {
    if (item[0].type !== 'client_report') return [item];
    const report = item[1] as { discarded_events?: Discard[] };
    const discarded = (report.discarded_events ?? []).flatMap((entry) => {
      if (entry.reason !== 'before_send' || !drops[entry.category]) return [entry];
      const taken = Math.min(drops[entry.category], entry.quantity);
      drops[entry.category] -= taken;
      return entry.quantity > taken ? [{ ...entry, quantity: entry.quantity - taken }] : [];
    });
    return discarded.length ? [[item[0], { ...report, discarded_events: discarded }]] : [];
  });
  return kept.length ? ([headers, kept] as unknown as E) : null;
}

/** The normal Rafii browser Sentry setup (same options on every start). */
function initSentry(Sentry: SentryModule) {
  const playSafeTransport: typeof Sentry.makeFetchTransport = (options) => {
    const transport = Sentry.makeFetchTransport(options);
    return {
      ...transport,
      send: (envelope) => {
        const outgoing = onPlay() ? null : withoutPlayDrops(envelope);
        return outgoing ? transport.send(outgoing) : Promise.resolve({});
      }
    };
  };
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeSend: (event) => (onPlay() || isPlayEvent(event) ? dropForPlay('error') : scrubTelemetry(event)),
    beforeSendTransaction: (event) => (onPlay() || isPlayEvent(event) ? dropForPlay('transaction') : event),
    transport: playSafeTransport,
    debug: false
  });
}

// Disabled/unconfigured deployments must not download or initialize the SDK.
shared.starter ??= createSentryStarter<SentryModule>({
  enabled: !process.env.NEXT_PUBLIC_SENTRY_DISABLED && Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN),
  isPlay: isPlayPath,
  currentPath: () => window.location.pathname,
  load: () => import('@sentry/nextjs'),
  init: initSentry
});

/** Starts Sentry if `pathname` (a committed route) and the current location are not /play. Idempotent. */
export function ensureSentryForPath(pathname: string) {
  return shared.starter!.ensure(pathname);
}

/** Next's onRouterTransitionStart: remember a /play destination; record transitions only to other routes. */
export function sentryRouterTransitionStart(href: string, navigationType: string) {
  shared.headingToPlay = isPlayUrl(href);
  if (shared.headingToPlay) return;
  shared.starter!.current()?.captureRouterTransitionStart(href, navigationType);
}
