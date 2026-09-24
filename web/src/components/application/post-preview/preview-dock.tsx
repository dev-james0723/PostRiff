'use client';

import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ChannelIcon } from '@/components/channel-icon';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

export type DockStatus = 'pending' | 'error';

export interface DockItem {
  /** Matches the deck item it selects. */
  key: string;
  /** Channel directory slug, for the brand mark. */
  channel: string;
  /** Short visible name: the app, or the account when two accounts share an app. */
  name: string;
  /** A dot for a draft still on its way or one that failed; nothing for a ready one. */
  status?: DockStatus;
  /** Accessible name; defaults to "Preview {name} on iPhone". */
  label?: string;
}

export interface PreviewDockProps {
  items: DockItem[];
  activeKey: string | null;
  onChange: (key: string) => void;
  /** Accessible name of the group. */
  label: string;
  /** Buttons per row before wrapping; equal widths within a row. */
  columns?: number;
  className?: string;
}

const STATUS_TEXT: Record<DockStatus, string> = { pending: 'draft on its way', error: 'draft failed' };
const KEYS = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];

/**
 * The channel dock under a preview deck (DNA §10.4, §18.5): one `aria-pressed` button per item with the
 * app's mark and a short name, one selection lens that glides to the pressed button (520ms on the phone
 * curve) instead of each button lighting up, and arrow/Home/End keys that move and select. Rows hold up to
 * six equal columns and wrap beyond. This is the keyboard path to the deck; the stage itself takes no focus.
 */
export function PreviewDock({ items, activeKey, onChange, label, columns = 6, className }: PreviewDockProps) {
  const group = useRef<HTMLDivElement>(null);
  const [lens, setLens] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const { reduced } = useMotionPreference();

  useLayoutEffect(() => {
    const host = group.current;
    if (!host) return;
    const measure = () => {
      const pressed = host.querySelector<HTMLElement>('button[aria-pressed="true"]');
      if (!pressed) {
        setLens(null);
        return;
      }
      setLens({ x: pressed.offsetLeft, y: pressed.offsetTop, w: pressed.offsetWidth, h: pressed.offsetHeight });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    host.querySelectorAll<HTMLElement>('button').forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [activeKey, items.length]);

  // Arrow keys move along the dock and select as they go; Home and End jump to its ends.
  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!KEYS.includes(event.key)) return;
    const buttons = Array.from(group.current?.querySelectorAll<HTMLButtonElement>('button[data-key]') ?? []);
    const current = buttons.indexOf(event.currentTarget);
    if (current < 0) return;
    event.preventDefault();
    const last = buttons.length - 1;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? last : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    const target = buttons[next];
    target.focus({ preventScroll: true });
    const key = target.dataset.key;
    if (key && key !== activeKey) onChange(key);
  }

  const perRow = Math.max(1, Math.min(columns, items.length || 1));

  return (
    <div
      ref={group}
      role='group'
      aria-label={label}
      className={cn('relative isolate grid w-full gap-1.5', className)}
      style={{ gridTemplateColumns: `repeat(${perRow}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden
        className={cn(
          'rafii-lens pointer-events-none absolute top-0 left-0 z-0 rounded-[19px]',
          !reduced && '[transition:transform_520ms_var(--rafii-ease-phone),width_420ms_var(--rafii-ease-phone),height_420ms_var(--rafii-ease-phone)]'
        )}
        style={lens ? { transform: `translate(${lens.x}px, ${lens.y}px)`, width: lens.w, height: lens.h, opacity: 1 } : { opacity: 0 }}
      />
      {items.map((item) => {
        const pressed = item.key === activeKey;
        const name = item.label ?? `Preview ${item.name} on iPhone`;
        return (
          <button
            key={item.key}
            type='button'
            data-key={item.key}
            aria-pressed={pressed}
            aria-label={item.status ? `${name}, ${STATUS_TEXT[item.status]}` : name}
            onClick={() => !pressed && onChange(item.key)}
            onKeyDown={onKeyDown}
            className={cn(
              'rafii-focus relative z-10 flex min-h-[4.25rem] min-w-0 flex-col items-center justify-center gap-1.5 rounded-[19px] px-1 py-2.5 text-xs leading-tight font-medium',
              'transition-[color,transform] duration-200 ease-[var(--rafii-ease-ui)] motion-reduce:transition-none',
              pressed ? 'text-foreground' : 'text-muted-foreground hover:text-foreground hover:-translate-y-[3px] motion-reduce:hover:translate-y-0',
              'active:translate-y-px active:scale-[0.96]'
            )}
          >
            <ChannelIcon slug={item.channel} name={item.name} size='sm' />
            <span className='max-w-full truncate'>{item.name}</span>
            {item.status && (
              <span
                aria-hidden
                data-status={item.status}
                className={cn(
                  'bg-foreground absolute top-2.5 right-2 size-[5px] rounded-full',
                  item.status === 'pending' && 'rafii-decorative-motion animate-pulse motion-reduce:animate-none',
                  item.status === 'error' && 'outline-foreground outline-1 outline-offset-2'
                )}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
