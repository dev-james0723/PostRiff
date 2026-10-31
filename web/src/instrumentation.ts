import * as Sentry from '@sentry/nextjs';
import { isPlayEvent, isPlayUrl } from '@/lib/play-path';
import { scrubTelemetry } from '@/lib/telemetry';

const sentryOptions: Sentry.NodeOptions | Sentry.EdgeOptions = {
  // Sentry DSN
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

  // Enable Spotlight in development
  spotlight: false,

  // Adds request headers and IP for users, for more info visit
  sendDefaultPii: false,

  // Adjust this value in production, or use tracesSampler for greater control
  tracesSampleRate: 0,
  // D1: nothing from the children's /play area is sent; other routes keep the existing scrubbing.
  beforeSend: (event) => (isPlayEvent(event) ? null : scrubTelemetry(event)),
  beforeSendTransaction: (event) => (isPlayEvent(event) ? null : event),

  // Setting this option to true will print useful information to the console while you're setting up Sentry.
  debug: false
};

export async function register() {
  if (!process.env.NEXT_PUBLIC_SENTRY_DISABLED && process.env.NEXT_PUBLIC_SENTRY_DSN) {
    if (process.env.NEXT_RUNTIME === 'nodejs') {
      // Node.js Sentry configuration
      Sentry.init(sentryOptions);
    }

    if (process.env.NEXT_RUNTIME === 'edge') {
      // Edge Sentry configuration
      Sentry.init(sentryOptions);
    }
  }
}

export const onRequestError: typeof Sentry.captureRequestError = (error, request, context) => {
  if (isPlayUrl(request.path)) return;
  return Sentry.captureRequestError(error, request, context);
};
