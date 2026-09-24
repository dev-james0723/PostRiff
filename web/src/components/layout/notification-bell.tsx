'use client';
import { useState } from 'react';
import Link from 'next/link';
import { IconBell } from '@tabler/icons-react';
import { rafiiMenu } from '@/components/auth/form-styles';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from '@/components/ui/popover';
import { useAttention } from '@/lib/use-attention';
import { cn } from '@/lib/utils';

/** What needs attention, in an elevated glass popover (DNA §21.17); opening an item routes to it. */
export function NotificationBell() {
  const attention = useAttention();
  const [open, setOpen] = useState(false);
  const readable = !attention.loading && attention.unavailable.length === 0;
  const label = readable ? `Notifications, ${attention.items.length} need attention` : 'Notifications, status unavailable';
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={<Button variant='ghost' size='icon' aria-label={label} className='relative' />}>
        <IconBell className='size-5' />
        {readable && attention.items.length > 0 && (
          <span className='bg-foreground text-background absolute -top-0.5 -right-0.5 min-w-4.5 rounded-full px-1 text-[11px] leading-[1.125rem] font-semibold tabular-nums'>{attention.items.length}</span>
        )}
      </PopoverTrigger>
      <PopoverContent align='end' className={cn(rafiiMenu, 'max-h-[70dvh] w-80 max-w-[calc(100vw-2rem)] gap-3 overflow-y-auto p-4')}>
        <PopoverTitle className='text-foreground text-sm font-medium'>Needs your attention</PopoverTitle>
        {attention.loading && <StateMessage kind='loading' layout='inline' title='Loading current status…' />}
        {attention.unavailable.length > 0 && <StateMessage kind='partial' layout='inline' title='Some status is unavailable.' description='Open the Overview to retry.' />}
        {readable && attention.items.length === 0 && <StateMessage kind='empty' layout='inline' title='Nothing needs your attention right now.' />}
        {attention.items.map((item) => (
          <Link
            key={item.id}
            href={item.href}
            onClick={() => setOpen(false)}
            className='rafii-quiet rafii-focus hover:rafii-glass-selected flex min-h-11 flex-col justify-center gap-0.5 rounded-[var(--rafii-radius-control)] px-3 py-2.5 transition-colors'
          >
            <span className='text-foreground block text-sm font-medium'>{item.title}</span>
            <span className='text-muted-foreground block text-xs leading-relaxed'>{item.description}</span>
          </Link>
        ))}
        <Link href='/app/account/notifications' onClick={() => setOpen(false)} className='rafii-focus text-muted-foreground hover:text-foreground self-start rounded-sm text-xs underline underline-offset-4'>
          Notification settings
        </Link>
      </PopoverContent>
    </Popover>
  );
}
