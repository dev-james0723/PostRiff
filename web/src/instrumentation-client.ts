import { ensureSentryForPath, sentryRouterTransitionStart } from '@/lib/sentry-client';

// D1/D11: Sentry starts here on boot unless the visit begins on /play; SentryRouteStart (root layout) starts it on the
// first committed non-play route otherwise. See src/lib/sentry-client.ts.
void ensureSentryForPath(window.location.pathname);

export function onRouterTransitionStart(href: string, navigationType: string) {
  sentryRouterTransitionStart(href, navigationType);
}
