import { QueryClient, defaultShouldDehydrateQuery, isServer } from '@tanstack/react-query';
import { ApiError } from './api/client';
import { releaseCachedMedia } from './api/media';

export function makeQueryClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        // A security step-up (RAPv2) is answered by the person, not by retrying: AppGate shows "Confirm it's you" at once.
        retry: (failures, error) => !(error instanceof ApiError && error.code === 'security_step_up_required') && failures < 3
      },
      dehydrate: {
        shouldDehydrateQuery: (query) =>
          defaultShouldDehydrateQuery(query) || query.state.status === 'pending'
      }
    }
  });
  if (!isServer) releaseCachedMedia(client.getQueryCache());
  return client;
}

let browserQueryClient: QueryClient | undefined = undefined;

export function getQueryClient() {
  if (isServer) {
    return makeQueryClient();
  } else {
    if (!browserQueryClient) browserQueryClient = makeQueryClient();
    return browserQueryClient;
  }
}
