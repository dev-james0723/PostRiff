import { toast } from 'sonner';
import { ApiError } from '@/lib/api/client';

/** `hosted.py` answers an out-of-date expected revision with this 409. Other 409s (a stale approval, a daily limit) carry their own reason. */
const REVISION_CONFLICT = /workspace changed/i;

/**
 * The server's own words for a failed queue action. When someone else changed the workspace first, the queue reloads
 * by itself instead of asking the person to; any other conflict offers a reload next to the reason.
 */
export function reportActionError(err: unknown, fallback: string, reload: () => void) {
  if (err instanceof ApiError && err.status === 409 && REVISION_CONFLICT.test(err.message)) {
    reload();
    toast.error('The workspace changed, so the queue is reloading. Check the post, then try again.');
    return;
  }
  const message = err instanceof ApiError ? err.message : fallback;
  if (err instanceof ApiError && err.status === 409) toast.error(message, { action: { label: 'Reload', onClick: reload } });
  else toast.error(message);
}
