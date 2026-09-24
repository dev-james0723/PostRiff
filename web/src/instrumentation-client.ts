import { scrubTelemetry } from '@/lib/telemetry';

// Disabled/unconfigured deployments must not download or initialize the SDK.
const sdk = !process.env.NEXT_PUBLIC_SENTRY_DISABLED && process.env.NEXT_PUBLIC_SENTRY_DSN
  ? import('@sentry/nextjs').then((Sentry) => {
      Sentry.init({
        dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
        sendDefaultPii: false,
        tracesSampleRate: 0,
        beforeSend: scrubTelemetry,
        debug: false
      });
      return Sentry;
    }).catch(() => null)
  : null;

export function onRouterTransitionStart(href: string, navigationType: string) {
  void sdk?.then((Sentry) => Sentry?.captureRouterTransitionStart(href, navigationType));
}
