import { ApiError } from '@/lib/api/client';

/** New servers provide a code; the message fallback is only for older deployments. */
export function needsFreshSignIn(error: unknown) {
  return error instanceof ApiError && (error.code === 'step_up_required' || (!error.code && error.status === 403 && /sign in again/i.test(error.message)));
}
