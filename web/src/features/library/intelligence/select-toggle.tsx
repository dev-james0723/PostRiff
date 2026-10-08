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
        'rafii-glass absolute z-20 grid size-11 cursor-pointer place-items-center rounded-full transition-opacity focus-within:opacity-100 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-foreground motion-reduce:transition-none',
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
        className='accent-foreground size-5 cursor-pointer'
      />
    </label>
  );
}
