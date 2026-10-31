import { isPlayEvent, isPlayPath, isPlayUrl } from '@/lib/play-path';
import { scrubTelemetry } from '@/lib/telemetry';

// D1: the children's /play area sends no telemetry. Booting there never loads the SDK; after a client-side visit to
// /play from another route, the transport drops every envelope (events, transactions, sessions) and the hooks drop
// /play events, so nothing leaves while a /play page is open.
const onPlay = () => isPlayPath(window.location.pathname);

// Disabled/unconfigured deployments must not download or initialize the SDK.
const sdk = !process.env.NEXT_PUBLIC_SENTRY_DISABLED && process.env.NEXT_PUBLIC_SENTRY_DSN && !onPlay()
  ? import('@sentry/nextjs').then((Sentry) => {
      const playSafeTransport: typeof Sentry.makeFetchTransport = (options) => {
        const transport = Sentry.makeFetchTransport(options);
        return { ...transport, send: (envelope) => (onPlay() ? Promise.resolve({}) : transport.send(envelope)) };
      };
      Sentry.init({
        dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
        sendDefaultPii: false,
        tracesSampleRate: 0,
        beforeSend: (event) => (onPlay() || isPlayEvent(event) ? null : scrubTelemetry(event)),
        beforeSendTransaction: (event) => (onPlay() || isPlayEvent(event) ? null : event),
        transport: playSafeTransport,
        debug: false
      });
      return Sentry;
    }).catch(() => null)
  : null;

export function onRouterTransitionStart(href: string, navigationType: string) {
  if (isPlayUrl(href)) return;
  void sdk?.then((Sentry) => Sentry?.captureRouterTransitionStart(href, navigationType));
}
