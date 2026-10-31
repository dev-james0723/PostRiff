import { isPlayEvent, isPlayPath, isPlayUrl } from '@/lib/play-path';
import { scrubTelemetry } from '@/lib/telemetry';

// D1: the children's /play area sends no telemetry. Booting there never loads the SDK; after a client-side visit to
// /play from another route, the transport drops every envelope (events, transactions, sessions) and the hooks drop
// /play events, so nothing leaves while a /play page is open.
// Next calls onRouterTransitionStart before a client-side navigation changes the address bar, and Sentry starts the
// next session from its pushState hook at that same moment, so the destination has to count as "on /play" too.
let headingToPlay = false;
const onPlay = () => headingToPlay || isPlayPath(window.location.pathname);

// Sentry tallies the events its beforeSend drops and reports the tally later in a client_report, possibly from another
// page. Drops caused by /play are counted here and taken back out, so not even a count of the child's visit leaves.
const playDrops: Record<string, number> = {};
function dropForPlay(category: string): null {
  playDrops[category] = (playDrops[category] ?? 0) + 1;
  return null;
}

type Discard = { reason: string; category: string; quantity: number };
type EnvelopeItem = [{ type?: string }, unknown];

/** Removes /play's own before_send drops from client_report items; returns null when nothing is left to send. */
function withoutPlayDrops<E>(envelope: E): E | null {
  if (!Object.values(playDrops).some(Boolean)) return envelope;
  const [headers, items] = envelope as unknown as [unknown, EnvelopeItem[]];
  const kept = items.flatMap((item): EnvelopeItem[] => {
    if (item[0].type !== 'client_report') return [item];
    const report = item[1] as { discarded_events?: Discard[] };
    const discarded = (report.discarded_events ?? []).flatMap((entry) => {
      if (entry.reason !== 'before_send' || !playDrops[entry.category]) return [entry];
      const taken = Math.min(playDrops[entry.category], entry.quantity);
      playDrops[entry.category] -= taken;
      return entry.quantity > taken ? [{ ...entry, quantity: entry.quantity - taken }] : [];
    });
    return discarded.length ? [[item[0], { ...report, discarded_events: discarded }]] : [];
  });
  return kept.length ? ([headers, kept] as unknown as E) : null;
}

type SentryModule = typeof import('@sentry/nextjs');

// Disabled/unconfigured deployments must not download or initialize the SDK.
const enabled = !process.env.NEXT_PUBLIC_SENTRY_DISABLED && Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN);
let sdk: Promise<SentryModule | null> | null = null;

/** Loads and initialises Sentry once, with the same options whether the visit began on /play or not. */
function startSentry(): Promise<SentryModule | null> | null {
  if (!enabled) return null;
  sdk ??= import('@sentry/nextjs').then((Sentry) => {
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
    return Sentry;
  }).catch(() => null);
  return sdk;
}

/** Resolves true once the address bar has left /play (checked per frame, up to ~5 s); false if heading back in. */
function afterLeavingPlay(): Promise<boolean> {
  return new Promise((resolve) => {
    let frames = 0;
    const check = () => {
      if (!isPlayPath(window.location.pathname)) resolve(true);
      else if (headingToPlay || frames++ > 300) resolve(false);
      else requestAnimationFrame(check);
    };
    check();
  });
}

// A visit that begins on /play never loads Sentry while there (see onRouterTransitionStart for leaving).
if (!onPlay()) startSentry();

export function onRouterTransitionStart(href: string, navigationType: string) {
  headingToPlay = isPlayUrl(href);
  if (headingToPlay) return;
  if (sdk) {
    void sdk.then((Sentry) => Sentry?.captureRouterTransitionStart(href, navigationType));
    return;
  }
  // The visit began on /play, so Sentry was never started. Leaving for a normal page starts it there, as a direct
  // visit to that page would, once the address bar shows it: nothing is initialised or sent while still on /play.
  void afterLeavingPlay().then((left) => {
    if (left) startSentry();
  });
}
