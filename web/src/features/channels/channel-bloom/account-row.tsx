'use client';

import { IconCheck } from '@tabler/icons-react';
import { ChannelIcon } from '@/components/channel-icon';
import { cn } from '@/lib/utils';

export interface AccountRowProps {
  id: string;
  platform: string;
  /** Handle or display name as the provider reports it. */
  account: string;
  /** Provider-reported readiness ("Ready for posting", "Finish setup", "Reconnect", "Connect"). */
  state?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Why the row cannot be picked; shown on the row and read to screen readers. */
  reason?: string | null;
  /** A note that does not disable the row (the editor lets any connected account join a folder). */
  hint?: string | null;
  /** What the checkbox edits: the staged destinations, or a folder's members in the editor. */
  kind?: 'destination' | 'member';
  /** Marks the brand icon so the inspector can stagger it into view. */
  peek?: boolean;
  className?: string;
}

/**
 * One account as a compact row (v9 addendum §2): the brand mark, the platform, the handle and
 * its connection state, and a check. The whole row is the hit area; the native checkbox
 * carries the semantics, focus and keyboard behaviour.
 */
export function AccountRow({ id, platform, account, state, checked, onCheckedChange, reason, hint, kind = 'destination', peek = false, className }: AccountRowProps) {
  const disabled = Boolean(reason);
  const note = reason ?? hint ?? null;
  const label = `${platform}, ${account}${state ? `, ${state}` : ''}${note ? `. ${note}` : ''}`;
  return (
    <label className={cn('relative block min-w-0', disabled ? 'cursor-default' : 'cursor-pointer', className)}>
      <input
        type='checkbox'
        className='peer sr-only'
        checked={checked}
        disabled={disabled}
        aria-label={label}
        data-account-select={kind === 'destination' ? id : undefined}
        data-folder-member={kind === 'member' ? id : undefined}
        onChange={(event) => onCheckedChange(event.target.checked)}
      />
      <span
        className={cn(
          'flex min-h-[3.75rem] items-center gap-3 rounded-[15px] px-3 py-2.5 transition-colors duration-200',
          'peer-focus-visible:outline-foreground peer-focus-visible:outline-2 peer-focus-visible:outline-offset-1',
          checked ? 'bg-[rgb(var(--rafii-highlight-rgb)/0.075)]' : 'bg-[rgb(var(--rafii-highlight-rgb)/0.022)]',
          !disabled && !checked && 'hover:bg-[rgb(var(--rafii-highlight-rgb)/0.045)]',
          disabled && 'opacity-55'
        )}
      >
        <span data-peek={peek ? '' : undefined} className='flex shrink-0'>
          <ChannelIcon platform={platform} name={platform} size='md' className='rounded-[10px]' />
        </span>
        <span className='flex min-w-0 flex-1 flex-col gap-0.5 text-left'>
          <span className='text-foreground text-[13px] leading-snug font-medium'>{platform}</span>
          <span className='text-muted-foreground truncate text-xs leading-snug'>
            {account}
            {state && <span> · {state}</span>}
          </span>
          {note && <span className='text-muted-foreground text-xs leading-snug'>{note}</span>}
        </span>
        <span aria-hidden className={cn('flex size-5 shrink-0 items-center justify-center rounded-full transition-colors duration-200', checked ? 'bg-foreground text-background' : 'bg-[rgb(var(--rafii-highlight-rgb)/0.07)] text-transparent')}>
          <IconCheck className='size-3' stroke={2.5} />
        </span>
      </span>
    </label>
  );
}
