'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { IconBell } from '@tabler/icons-react';
import { rafiiMenu } from '@/components/auth/form-styles';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { CallRafii, PhoneWorkspaceSync } from '@/features/rafii-phone/call-rafii';
import { NotificationCenter } from '@/features/notifications/notification-center';
import { adaptAttention, adaptServer } from '@/features/notifications/presentation';
import { useCoworkerFlag, useCoworkerStatus, useMarkNotification, useNotificationCenter } from '@/lib/coworker/hooks';
import { useAttention } from '@/lib/use-attention';
import { cn } from '@/lib/utils';

/** One priority-sorted presentation of attention and durable server notifications. */
export function NotificationBell() {
  const attention = useAttention();
  const server = useNotificationCenter();
  const status = useCoworkerStatus();
  const enabled = useCoworkerFlag('RAFII_NOTIFICATIONS_V2_ENABLED');
  const mark = useMarkNotification();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const serverRequired = enabled === true;
  const partial = attention.unavailable.length > 0 || status.isError || (serverRequired && server.isError);
  const loading = attention.loading || (enabled === null && status.isPending) || (serverRequired && server.isPending);
  const items = useMemo(() => [
    ...attention.items.map(adaptAttention),
    ...(server.data?.items ?? []).map(adaptServer)
  ], [attention.items, server.data?.items]);
  const knownCount = attention.items.length + (server.data?.unread ?? 0);
  const countKnown = !loading && !partial;
  const label = 'Notifications, ' + (countKnown ? knownCount + (knownCount === 1 ? ' item' : ' items')
    : loading && !partial ? knownCount + ' known items; loading' : knownCount + ' known items; some updates unavailable')
    + (open ? ', center open' : ', center closed');
  const close = () => setOpen(false);
  const viewAll = () => {
    close();
    router.push('/app/account/notifications#activity');
  };

  return (
    <>
      <PhoneWorkspaceSync />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger render={<Button variant='ghost' size='icon' aria-label={label} className='relative min-h-11 min-w-11' />}>
          <IconBell className='relative z-10 size-5' aria-hidden='true' />
          {knownCount > 0 && (
            <>
              <span aria-hidden='true' className='absolute right-2 bottom-1.5 left-2 h-2 rounded-sm border border-foreground/40 bg-background/90' />
              {knownCount > 1 && <span aria-hidden='true' className='absolute right-2.5 bottom-0.5 left-2.5 h-2 rounded-sm border border-foreground/30 bg-background/80' />}
              {knownCount > 2 && <span aria-hidden='true' className='absolute right-3 bottom-[-0.15rem] left-3 h-2 rounded-sm border border-foreground/20 bg-background/70' />}
            </>
          )}
        </PopoverTrigger>
        <PopoverContent align='end' className={cn(rafiiMenu, 'max-h-[min(78dvh,42rem)] w-[min(23rem,calc(100vw-1rem))] gap-3 overflow-y-auto p-3 sm:p-4')}
          style={{ background: 'var(--popover)', backdropFilter: 'none' }}>
          <PopoverTitle className='sr-only'>Notification center</PopoverTitle>
          <NotificationCenter
            items={items}
            loading={loading}
            partial={partial}
            onRead={(item) => mark.mutateAsync({ id: item.sourceId, action: 'read' })}
            onArchive={(item) => mark.mutateAsync({ id: item.sourceId, action: 'dismissed' })}
            onViewAll={viewAll}
            onNavigate={close}
          />
          <div className='flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2'>
            <CallRafii />
            <Link href='/app/account/notifications' onClick={close} className='rafii-focus min-h-11 content-center rounded-lg px-2 text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground'>
              Notification settings
            </Link>
          </div>
        </PopoverContent>
      </Popover>
    </>
  );
}
