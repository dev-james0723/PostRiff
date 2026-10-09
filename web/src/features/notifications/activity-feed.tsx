'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { StateMessage } from '@/components/rafii';
import { Icons } from '@/components/icons';
import { useCoworkerFlag, useCoworkerStatus, useNotificationHistory } from '@/lib/coworker/hooks';
import { adaptServer, chooseSurfaces } from './presentation';

export function NotificationActivityFeed() {
  const history = useNotificationHistory();
  const status = useCoworkerStatus();
  const enabled = useCoworkerFlag('RAFII_NOTIFICATIONS_V2_ENABLED');
  const items = useMemo(() => {
    const seen = new Set<string>();
    return (history.data?.pages.flatMap((page) => page.items) ?? [])
      .filter((item) => !seen.has(item.id) && Boolean(seen.add(item.id)))
      .map(adaptServer)
      .filter((item) => chooseSurfaces(item).includes('activity'))
      .toSorted((a, b) => b.createdAt - a.createdAt);
  }, [history.data?.pages]);
  const unavailable = status.isError || history.isError;

  return (
    <section id='activity' aria-labelledby='notification-activity-heading' className='scroll-mt-20'>
      <div className='mb-3 flex flex-wrap items-end justify-between gap-2'>
        <div>
          <h2 id='notification-activity-heading' className='text-lg font-semibold'>Activity feed</h2>
          <p className='text-sm text-muted-foreground'>Completed work and earlier notifications stay here.</p>
        </div>
      </div>
      {enabled === false ? (
        <StateMessage kind='unsupported' layout='inline' title='Notification history is off for this workspace.' />
      ) : unavailable ? (
        <StateMessage kind='partial' layout='inline' title='Activity could not load.' description='Try again when the connection is available.' />
      ) : history.isPending ? (
        <StateMessage kind='loading' layout='inline' title='Loading activity…' />
      ) : items.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No activity yet' />
      ) : (
        <ol className='space-y-1.5'>
          {items.map((item) => (
            <li key={item.id} className='min-w-0'>
              <div className='flex min-w-0 items-start gap-3 rounded-xl border border-border/60 bg-background/70 px-3 py-3'>
                <span aria-hidden='true' className='mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-muted'>
                  {item.kind === 'critical' || item.kind === 'security' || item.kind === 'warning' ? <Icons.warning className='size-4' /> : <Icons.check className='size-4' />}
                </span>
                <div className='min-w-0 flex-1'>
                  <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
                    <span className='text-sm font-medium text-foreground'>{item.title}</span>
                    {item.unread && <span className='rounded-full border border-border px-1.5 text-[10px] font-medium'>Unread</span>}
                  </div>
                  {item.description && <p className='text-xs leading-relaxed text-muted-foreground'>{item.description}</p>}
                  <time dateTime={new Date(item.createdAt).toISOString()} className='text-[11px] text-muted-foreground'>{new Date(item.createdAt).toLocaleString()}</time>
                </div>
                {item.href && <Link href={item.href} className='rafii-focus min-h-11 shrink-0 content-center rounded-lg px-2 text-xs font-medium underline underline-offset-4'>Open</Link>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {history.hasNextPage && (
        <button type='button' onClick={() => void history.fetchNextPage()} disabled={history.isFetchingNextPage}
          className='rafii-focus mt-3 min-h-11 rounded-xl border border-border px-4 text-sm font-medium'>
          {history.isFetchingNextPage ? 'Loading…' : 'Load older activity'}
        </button>
      )}
    </section>
  );
}
