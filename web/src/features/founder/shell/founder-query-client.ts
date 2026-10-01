import { QueryClient } from '@tanstack/react-query';

/**
 * The founder surface's own query cache (never shared with the consumer app). A Control 4xx is a definite answer
 * (validation, scope, step-up, rate limit), so it is never retried: retrying multiplied one refused query into enough
 * requests to trip the per-minute budget for every other panel. Only a 5xx or a network failure gets one more try.
 */
export function isRetryableFounderError(error: unknown): boolean {
  const status = error && typeof error === 'object' ? (error as { status?: unknown }).status : undefined;
  return typeof status !== 'number' || status >= 500;
}

export function makeFounderQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => failureCount < 1 && isRetryableFounderError(error)
      },
      mutations: { retry: false }
    }
  });
}
