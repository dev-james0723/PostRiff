import { toast } from 'sonner';
import { ApiError } from '@/lib/api/client';

/** `hosted.py` answers an out-of-date expected revision with this 409. Other 409s (a stale approval, a daily limit) carry their own reason. */
const REVISION_CONFLICT = /workspace changed/i;

/**
 * A failed queue action: what happened as the headline (`headline`, e.g. "Couldn't cancel this post"), the server's
 * own words as the detail underneath. When someone else changed the workspace first, the queue reloads by itself
 * instead of asking the person to; any other conflict offers a reload next to the reason.
 */
export function reportActionError(err: unknown, headline: string, reload: () => void) {
  if (err instanceof ApiError && err.status === 409 && REVISION_CONFLICT.test(err.message)) {
    reload();
    toast.error('Something changed. Check the post, then try again.');
    return;
  }
  const description = err instanceof ApiError && err.message ? err.message : undefined;
  if (err instanceof ApiError && err.status === 409) toast.error(headline, { description, action: { label: 'Reload', onClick: reload } });
  else toast.error(headline, { description });
}
