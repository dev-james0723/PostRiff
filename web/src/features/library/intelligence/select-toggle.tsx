'use client';

import { cn } from '@/lib/utils';

/**
 * The selection checkbox on a card or row (UI spec §3, §5). A native checkbox in a 44 px target: Space toggles it,
 * it appears on keyboard focus as well as hover, it is always visible on touch screens and once anything is selected.
 * Selecting is never a drag or a long press.
 */
export function SelectToggle({
  title,
  checked,
  visible,
  onChange,
  className
}: {
  title: string;
  checked: boolean;
  /** Selection mode is active (something is selected): show every checkbox. */
  visible: boolean;
  onChange: (checked: boolean, extend: boolean) => void;
  className?: string;
}) {
  return (
    <label
      data-select-toggle=''
      className={cn(
        'bg-background/90 ring-foreground/10 absolute z-20 grid size-8 cursor-pointer place-items-center rounded-[10px] shadow-xs ring-1 transition-opacity duration-150 focus-within:opacity-100 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-foreground motion-reduce:transition-none pointer-coarse:size-11 pointer-coarse:rounded-full',
        checked || visible ? 'opacity-100' : 'opacity-0 group-hover/asset:opacity-100 group-focus-within/asset:opacity-100 pointer-coarse:opacity-100',
        className
      )}
    >
      <input
        type='checkbox'
        aria-label={`Select ${title}`}
        checked={checked}
        onChange={(event) => onChange(event.currentTarget.checked, false)}
        onClick={(event) => {
          // Shift extends the selection from the last item chosen (keyboard and mouse alike).
          if (event.shiftKey) {
            event.preventDefault();
            onChange(!checked, true);
          }
        }}
        className='accent-foreground size-4 cursor-pointer pointer-coarse:size-5'
      />
    </label>
  );
}
