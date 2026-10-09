'use client';

import { cn } from '@/lib/utils';

/**
 * The selection checkbox on a card or row (UI spec §3, §5). A native checkbox in a 44 px target: Space toggles it,
 * it appears on keyboard focus and on hover, and on every item once selection mode is on (Select, or anything
 * selected). Selecting is never a drag or a long press.
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
        'bg-background/90 ring-foreground/10 absolute z-20 grid size-8 cursor-pointer place-items-center rounded-[10px] shadow-xs ring-1 transition-opacity duration-150 has-[:focus-visible]:opacity-100 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-foreground motion-reduce:transition-none after:absolute after:-inset-1.5 after:content-[""]',
        // Touch screens show checkboxes only in selection mode (Select, or once anything is selected); until then a
        // tap on the corner opens the item instead of hitting an invisible box. Mouse: on hover. Keyboard: on focus.
        checked || visible
          ? 'opacity-100'
          : 'opacity-0 pointer-coarse:pointer-events-none pointer-fine:group-hover/asset:opacity-100 group-has-[:focus-visible]/asset:opacity-100',
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
        // Above the label's enlarged hit area: a press on the box itself lands on the checkbox, around it on the label.
        className='accent-foreground relative z-10 size-4 cursor-pointer'
      />
    </label>
  );
}
