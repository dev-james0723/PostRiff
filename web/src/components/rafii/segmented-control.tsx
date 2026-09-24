'use client';

import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

export interface SegmentOption<V extends string> {
  value: V;
  label: ReactNode;
  /** Accessible name when the label is an icon or abbreviation. */
  ariaLabel?: string;
  disabled?: boolean;
  title?: string;
}

interface SegmentedControlProps<V extends string> {
  options: SegmentOption<V>[];
  value: V;
  onChange: (value: V) => void;
  /** `radio` for a mutually exclusive setting, `tabs` when the segments switch associated panels (DNA §10.4). */
  pattern?: 'radio' | 'tabs';
  label: string;
  size?: 'sm' | 'md' | 'lg';
  /** Equal-width segments by default; `content` lets uneven labels size themselves. */
  widths?: 'equal' | 'content';
  className?: string;
  /** Ids of the panels each tab controls, in option order (tabs pattern). */
  panelIds?: string[];
}

const SIZE = {
  sm: 'min-h-9 px-3 text-[13px]',
  md: 'min-h-11 px-3.5 text-sm',
  lg: 'min-h-12 px-4 text-sm'
} as const;

/**
 * A segmented control with one persistent selection lens (DNA §10.4, §18.5). The lens belongs
 * to the group and glides between segments; the segments never remount. Arrow keys move the
 * selection in the radio pattern and the focus in the tabs pattern.
 */
export function SegmentedControl<V extends string>({ options, value, onChange, pattern = 'radio', label, size = 'md', widths = 'equal', className, panelIds }: SegmentedControlProps<V>) {
  const id = useId();
  const group = useRef<HTMLDivElement>(null);
  const [lens, setLens] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const { reduced } = useMotionPreference();

  useLayoutEffect(() => {
    const host = group.current;
    if (!host) return;
    const measure = () => {
      const active = host.querySelector<HTMLElement>(`[data-value="${CSS.escape(value)}"]`);
      if (!active) {
        setLens(null);
        return;
      }
      setLens({ x: active.offsetLeft, y: active.offsetTop, w: active.offsetWidth, h: active.offsetHeight });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    host.querySelectorAll<HTMLElement>('[data-value]').forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [value, options.length]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    const enabled = options.filter((o) => !o.disabled);
    const focused = document.activeElement as HTMLElement | null;
    const currentValue = (focused?.dataset.value as V | undefined) ?? value;
    const index = Math.max(0, enabled.findIndex((o) => o.value === currentValue));
    const last = enabled.length - 1;
    const next =
      event.key === 'Home' ? 0 : event.key === 'End' ? last : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? (index + 1) % enabled.length : (index - 1 + enabled.length) % enabled.length;
    event.preventDefault();
    const target = enabled[next];
    group.current?.querySelector<HTMLElement>(`[data-value="${CSS.escape(target.value)}"]`)?.focus();
    if (pattern === 'radio') onChange(target.value);
  }

  return (
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- the role is set from `pattern` (tablist or radiogroup); arrow keys bubble up from the focusable segments
    <div
      ref={group}
      role={pattern === 'tabs' ? 'tablist' : 'radiogroup'}
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn('rafii-quiet scrollbar-hide relative isolate max-w-full overflow-x-auto rounded-[var(--rafii-radius-segment)] p-1', widths === 'equal' ? 'grid auto-cols-fr grid-flow-col' : 'inline-flex', className)}
    >
      <span
        aria-hidden
        className={cn('rafii-lens pointer-events-none absolute top-0 left-0 z-0 rounded-[calc(var(--rafii-radius-segment)-4px)]', !reduced && 'transition-[transform,width,height] duration-[440ms] ease-[var(--rafii-ease-soft)]')}
        style={lens ? { transform: `translate(${lens.x}px, ${lens.y}px)`, width: lens.w, height: lens.h, opacity: 1 } : { opacity: 0 }}
      />
      {options.map((option, index) => {
        const active = option.value === value;
        const shared = {
          'data-value': option.value,
          disabled: option.disabled,
          title: option.title,
          'aria-label': option.ariaLabel,
          onClick: () => !active && onChange(option.value),
          className: cn(
            'rafii-focus relative z-10 inline-flex min-w-0 items-center justify-center gap-1.5 rounded-[calc(var(--rafii-radius-segment)-4px)] font-medium whitespace-nowrap transition-colors duration-200 disabled:opacity-40',
            SIZE[size],
            active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
          )
        } as const;
        return pattern === 'tabs' ? (
          <button key={option.value} type='button' role='tab' id={`${id}-${index}`} aria-selected={active} aria-controls={panelIds?.[index]} tabIndex={active ? 0 : -1} {...shared}>
            {option.label}
          </button>
        ) : (
          <button key={option.value} type='button' role='radio' aria-checked={active} tabIndex={active ? 0 : -1} {...shared}>
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
