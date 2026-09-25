'use client';

import Link from 'next/link';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { isFeatureDisabled } from '@/lib/coworker/api';
import { useMarkNotification, useNotificationCenter } from '@/lib/coworker/hooks';
import { safeAppHref } from '@/lib/coworker/safe-href';
import type { ServerNotification } from '@/lib/coworker/types';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { eventLabel } from './labels';

/** Unread server notifications for the bell's count; 0 while the notification centre is off or unreadable. */
export function useServerUnread(): number {
  const center = useNotificationCenter();
  return center.data?.unread ?? 0;
}

function describe(item: ServerNotification): string {
  const p = item.payload ?? {};
  if (typeof p.reason === 'string' && p.reason) return p.reason;
  if (typeof p.why === 'string' && p.why) return p.why;
  if (typeof p.count === 'number') {
    const noun = ['weekly', 'campaigns', 'approvals', 'publishing'].includes(item.category) ? 'post' : 'item';
    return `${p.count} ${noun}${p.count === 1 ? '' : 's'}`;
  }
  if (typeof p.platform === 'string' && p.platform) return p.platform;
  return '';
}

/**
 * The server notification centre inside the bell popover: newest first, unread marked in words as well as a dot,
 * each opening its in-app link (same-origin `/app` paths only) and marked read on the way.
 */
export function BellNotificationList({ onNavigate }: { onNavigate: () => void }) {
  const center = useNotificationCenter();
  const mark = useMarkNotification();
  if (center.isPending || isFeatureDisabled(center.error)) return null;
  if (center.isError) return <StateMessage kind='partial' layout='inline' title='Recent notifications are unavailable.' />;
  const items = center.data.items.slice(0, 12);
  const unread = items.filter((item) => item.status === 'delivered');
  const now = Date.now() / 1000;

  async function markAll() {
    const results = await Promise.allSettled(unread.map((item) => mark.mutateAsync({ id: item.id, action: 'read' })));
    const failed = results.filter((r) => r.status === 'rejected' || (r.status === 'fulfilled' && !r.value.verified)).length;
    if (failed) toast.warning(`${failed} notification${failed === 1 ? '' : 's'} could not be marked as read.`);
  }

  return (
    <section aria-labelledby='bell-recent-heading' className='flex flex-col gap-1'>
      <div className='flex items-center justify-between gap-2'>
        <h3 id='bell-recent-heading' className='text-foreground text-sm font-medium'>
          Recent
          {center.data.unread > 0 && <span className='text-muted-foreground font-normal'> · {center.data.unread} unread</span>}
        </h3>
        {unread.length > 0 && (
          <button type='button' onClick={() => void markAll()} disabled={mark.isPending} className='rafii-focus text-muted-foreground hover:text-foreground min-h-8 rounded-sm px-1 text-xs underline underline-offset-4'>
            Mark all read
          </button>
        )}
      </div>
      {items.length === 0 ? (
        <p className='text-muted-foreground py-1 text-xs'>No notifications yet.</p>
      ) : (
        <ul className='flex flex-col gap-0.5'>
          {items.map((item) => {
            const isUnread = item.status === 'delivered';
            const detail = describe(item);
            const weekOf = typeof item.payload?.weekOf === 'string' ? item.payload.weekOf : null;
            return (
              <li key={item.id}>
                <Link
                  href={safeAppHref(item.payload?.href)}
                  onClick={() => {
                    if (isUnread) mark.mutate({ id: item.id, action: 'read' });
                    onNavigate();
                  }}
                  className='rafii-quiet rafii-focus hover:rafii-glass-selected flex min-h-11 items-start gap-2.5 rounded-[var(--rafii-radius-control)] px-3 py-2.5 transition-colors'
                >
                  <span aria-hidden className={cn('mt-1.5 size-2 shrink-0 rounded-full', isUnread ? 'bg-foreground' : 'border-muted-foreground/50 border')} />
                  <span className='min-w-0 flex-1'>
                    <span className={cn('block text-sm', isUnread ? 'text-foreground font-medium' : 'text-muted-foreground')}>
                      {isUnread && <span className='sr-only'>Unread: </span>}
                      {typeof item.payload?.title === 'string' && item.payload.title ? item.payload.title : eventLabel(item.type)}
                      {weekOf ? ` · week of ${weekOf}` : ''}
                    </span>
                    {detail && <span className='text-muted-foreground block text-xs leading-relaxed'>{detail}</span>}
                    <span className='text-muted-foreground block text-[11px]'>{relativeTime(item.createdAt, now)}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
