'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { useFounderScope } from '@/features/founder/customers/kit/api';
import { useMarkNoticeRead, useNotices } from '@/features/founder/settings/comms-hooks';
import { NotificationCenter } from './notification-center';
import { adaptFounder } from './presentation';

/** Founder notices keep their own authenticated policy and read endpoint. */
export function FounderNotificationBell() {
  const scope = useFounderScope();
  // Demo has no in-app notice stream; avoid a request from every Demo page header.
  const demo = scope.mode === 'demo';
  const query = useNotices({ enabled: !demo, staleTime: 30_000 });
  const mark = useMarkNoticeRead();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const partial = !demo && (query.isError || query.data?.installed === false);
  const items = useMemo(() => (query.data?.mode === 'live' ? query.data.notices.map(adaptFounder) : []), [query.data]);
  const label = 'Founder notifications, ' + (partial ? 'status unavailable' : demo ? 'unavailable in Demo'
    : query.data ? query.data.unread + ' unread' : 'loading') + (open ? ', open' : ', closed');
  const close = () => setOpen(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={<Button type='button' variant='ghost' size='icon' aria-label={label} className='relative min-h-11 min-w-11' />}>
        <Icons.notification className='size-5' aria-hidden='true' />
        {query.data?.mode === 'live' && query.data.unread > 0 && <span aria-hidden='true' className='absolute right-2 bottom-1 left-2 h-1.5 rounded-full border border-foreground/40 bg-background' />}
      </PopoverTrigger>
      <PopoverContent align='end' className='max-h-[78dvh] w-[min(23rem,calc(100vw-1rem))] overflow-y-auto p-3 sm:p-4'>
        <PopoverTitle className='sr-only'>Founder notification center</PopoverTitle>
        {demo ? <StateMessage kind='unsupported' layout='inline' title='Demo has no founder notices.' /> : (
          <NotificationCenter
            items={items}
            loading={!demo && query.isPending}
            partial={partial}
            onRead={async (item) => {
              const result = await mark.mutateAsync(item.sourceId);
              return { verified: result.notice.read, status: result.notice.read ? 'read' : null };
            }}
            onViewAll={() => { close(); router.push('/founder/settings?tab=notifications'); }}
            onNavigate={close}
          />
        )}
      </PopoverContent>
    </Popover>
  );
}
