import * as Sentry from '@sentry/nextjs';
import { isPlayAssetRequest, isPlayEvent, isPlayUrl } from '@/lib/play-path';
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
  beforeSend: (event) => (isPlayEvent(event) || inPlayRequest() ? null : scrubTelemetry(event)),
  beforeSendTransaction: (event) => (isPlayEvent(event) || inPlayRequest() ? null : event),

  // Setting this option to true will print useful information to the console while you're setting up Sentry.
  debug: false
};

type RequestInfo = { url?: string; headers?: Record<string, string | string[] | undefined> };

/** /play traffic: the page itself, or an asset/metadata file a /play page loads (its Referer is /play, D12). */
function isPlayRequest(request: RequestInfo | undefined): boolean {
  const referer = request?.headers?.referer;
  return isPlayUrl(request?.url) || isPlayAssetRequest(request?.url, Array.isArray(referer) ? referer[0] : referer);
}

/** True while handling /play traffic: the request's isolation scope carries its URL and headers. */
function inPlayRequest(): boolean {
  return isPlayRequest(Sentry.getIsolationScope().getScopeData().sdkProcessingMetadata.normalizedRequest as RequestInfo | undefined);
}

/**
 * D1: nothing derived from a /play request leaves the server, including the two things beforeSend never sees.
 * - Request sessions: core counts a request when its response closes, only if `requestSession` is still set on the
 *   request's isolation scope, so it is cleared for /play as the request starts (`httpServerRequest`).
 * - Client reports: outcomes (dropped by beforeSend, sampled out, …) are not recorded while handling /play, so no
 *   tally of the request reaches a later client_report. Every other route reports exactly as before.
 */
function excludePlayRequests() {
  const client = Sentry.getClient();
  if (!client) return;
  client.on('httpServerRequest', (_request, _response, normalizedRequest) => {
    if (isPlayRequest(normalizedRequest)) Sentry.getIsolationScope().setSDKProcessingMetadata({ requestSession: undefined });
  });
  const record = client.recordDroppedEvent.bind(client);
  client.recordDroppedEvent = (...args: Parameters<typeof record>) => {
    if (!inPlayRequest()) record(...args);
  };
}

export async function register() {
  if (!process.env.NEXT_PUBLIC_SENTRY_DISABLED && process.env.NEXT_PUBLIC_SENTRY_DSN) {
    if (process.env.NEXT_RUNTIME === 'nodejs') {
      // Node.js Sentry configuration
      Sentry.init(sentryOptions);
      excludePlayRequests();
    }

    if (process.env.NEXT_RUNTIME === 'edge') {
      // Edge Sentry configuration
      Sentry.init(sentryOptions);
      excludePlayRequests();
    }
  }
}

export const onRequestError: typeof Sentry.captureRequestError = (error, request, context) => {
  if (isPlayUrl(request.path)) return;
  return Sentry.captureRequestError(error, request, context);
};
