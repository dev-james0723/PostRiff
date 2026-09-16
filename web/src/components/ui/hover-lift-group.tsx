'use client';

import { Children, useRef, type PointerEvent, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

function readNumber(styles: CSSStyleDeclaration, name: string, fallback: number) {
  const value = parseFloat(styles.getPropertyValue(name));
  return Number.isFinite(value) ? value : fallback;
}

/**
 * transitions.dev avatar group hover for any horizontal row of chips: the hovered
 * item lifts and its neighbours follow with a distance falloff, then everything
 * springs back when the pointer leaves. Keyboard focus lifts the same way. Timing
 * and distances come from the `--avatar-*` tokens in `src/styles/transitions.css`.
 */
function HoverLiftGroup({
  children,
  className,
  itemClassName
}: {
  children: ReactNode;
  className?: string;
  itemClassName?: string;
}) {
  const root = useRef<HTMLDivElement>(null);

  // The timing function is written before the variables on purpose: the browser
  // uses whichever one is current when the transform changes, which gives a quick
  // lift on the way in and the bouncy return on the way out.
  function setShifts(active: number | null, phase: 'in' | 'out') {
    const items = root.current?.querySelectorAll<HTMLElement>(':scope > .t-avatar');
    if (!items) return;
    const styles = getComputedStyle(document.documentElement);
    const lift = readNumber(styles, '--avatar-lift', -4);
    const falloff = readNumber(styles, '--avatar-falloff', 0.45);
    const scale = readNumber(styles, '--avatar-scale', 1.05);
    const ease =
      styles.getPropertyValue(phase === 'out' ? '--avatar-ease-out' : '--avatar-ease-in').trim() ||
      'cubic-bezier(0.22, 1, 0.36, 1)';
    items.forEach((item, index) => {
      item.style.transitionTimingFunction = ease;
      if (active === null) {
        item.style.setProperty('--shift', '0px');
        item.style.setProperty('--scale-active', '1');
        return;
      }
      const distance = Math.abs(index - active);
      item.style.setProperty('--shift', `${(lift * Math.pow(falloff, distance)).toFixed(3)}px`);
      item.style.setProperty('--scale-active', index === active ? String(scale) : '1');
    });
  }

  return (
    <div
      ref={root}
      className={cn('t-avatar-group', className)}
      onPointerLeave={() => setShifts(null, 'out')}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setShifts(null, 'out');
      }}
    >
      {Children.toArray(children).map((child, index) => (
        <div
          // Children.toArray gives each child a stable key of its own.
          key={(child as { key?: string }).key ?? index}
          className={cn('t-avatar', itemClassName)}
          onPointerEnter={(event: PointerEvent) => {
            if (event.pointerType !== 'touch') setShifts(index, 'in');
          }}
          onFocus={() => setShifts(index, 'in')}
        >
          {child}
        </div>
      ))}
    </div>
  );
}

export { HoverLiftGroup };
