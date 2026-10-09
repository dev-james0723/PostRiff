'use client';

import type { ComponentProps, ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

/**
 * The Library's one control scale (redesign §4), built on the shared `Button` materials without changing them:
 * primary = the filled action (one per surface), secondary = quiet glass, ghost = text utility, danger = destructive.
 * `md` is 36 px and `sm` 32 px with a mouse; both become 44 px touch targets on coarse pointers.
 */
export type ControlTone = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ControlSize = 'md' | 'sm';

const MATERIAL: Record<ControlTone, 'action' | 'glass' | 'quiet' | 'destructive'> = {
  primary: 'action',
  secondary: 'glass',
  ghost: 'quiet',
  danger: 'destructive'
};

const SIZE: Record<ControlSize, string> = {
  md: 'h-9 gap-1.5 px-3 text-sm pointer-coarse:h-11 pointer-coarse:px-3.5',
  sm: 'h-8 gap-1.5 px-2.5 text-[13px] pointer-coarse:h-11 pointer-coarse:px-3'
};

const SQUARE: Record<ControlSize, string> = {
  md: 'size-9 px-0 pointer-coarse:size-11',
  sm: 'size-8 px-0 pointer-coarse:size-11'
};

/** Shared by buttons and links styled as buttons, so a `<Link>` matches its neighbours exactly. */
export function controlClass({
  tone = 'secondary',
  size = 'md',
  iconOnly = false,
  active = false,
  className
}: {
  tone?: ControlTone;
  size?: ControlSize;
  iconOnly?: boolean;
  /** A ghost control whose setting is not the default (a filter in use, an open panel). */
  active?: boolean;
  className?: string;
}) {
  return cn(
    buttonVariants({ variant: MATERIAL[tone] }),
    "rounded-[var(--rafii-radius-control)] font-medium [&_svg:not([class*='size-'])]:size-4",
    iconOnly ? SQUARE[size] : SIZE[size],
    tone === 'ghost' && 'hover:bg-foreground/[0.05] active:bg-foreground/[0.08]',
    tone === 'ghost' && active && 'bg-foreground/[0.07] text-foreground',
    tone === 'danger' && 'focus-visible:ring-destructive/30',
    className
  );
}

/** Library controls take a plain class string (base-ui also allows a state function, which these never need). */
type ButtonProps = Omit<ComponentProps<typeof Button>, 'size' | 'variant' | 'className'> & { className?: string };

export function Control({
  tone = 'secondary',
  size = 'md',
  active = false,
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...props
}: ButtonProps & { tone?: ControlTone; size?: ControlSize; active?: boolean; loading?: boolean; icon?: ReactNode }) {
  return (
    <Button {...props} disabled={disabled || loading} aria-busy={loading || undefined} data-active={active || undefined} className={controlClass({ tone, size, active, className })}>
      {loading ? <Icons.spinner aria-hidden className='animate-spin motion-reduce:animate-none' /> : icon}
      {children}
    </Button>
  );
}

/** Icon-only: always named, with the same words as a tooltip for pointer users. */
export function IconControl({
  label,
  tone = 'ghost',
  size = 'md',
  active = false,
  tooltip = true,
  side = 'top',
  className,
  children,
  ...props
}: Omit<ButtonProps, 'aria-label'> & {
  label: string;
  tone?: ControlTone;
  size?: ControlSize;
  active?: boolean;
  /** Off where the control is already a menu or dialog trigger (one popup per trigger). */
  tooltip?: boolean;
  side?: 'top' | 'bottom' | 'left' | 'right';
}) {
  const className_ = controlClass({ tone, size, iconOnly: true, active, className });
  if (!tooltip) {
    return (
      <Button {...props} aria-label={label} data-active={active || undefined} className={className_}>
        {children}
      </Button>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger render={<Button {...props} aria-label={label} data-active={active || undefined} className={className_} />}>{children}</TooltipTrigger>
      <TooltipContent side={side}>{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * A compact toolbar filter: a native select (keyboard, screen readers and the system picker on touch for free) dressed
 * as a ghost control. The option text names the state ("All types", "Photos"), so no visible prefix is needed; the
 * accessible name still says what it filters.
 */
export function ToolbarSelect<V extends string>({
  id,
  label,
  value,
  defaultValue,
  options,
  onChange,
  className,
  icon
}: {
  id: string;
  label: string;
  value: V;
  /** The "no filter" value: anything else shows as active. */
  defaultValue?: V;
  options: { value: V; label: string }[];
  onChange: (value: V) => void;
  className?: string;
  icon?: ReactNode;
}) {
  const active = defaultValue !== undefined && value !== defaultValue;
  return (
    <span className={cn('relative inline-flex shrink-0', className)}>
      {icon ? <span className='text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 [&_svg]:size-4'>{icon}</span> : null}
      <select
        id={id}
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value as V)}
        data-active={active || undefined}
        className={cn(
          'rafii-focus h-9 cursor-pointer appearance-none rounded-[var(--rafii-radius-control)] bg-transparent pr-8 text-[13px] font-medium outline-none pointer-coarse:h-11',
          'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] transition-colors duration-150',
          icon ? 'pl-8' : 'pl-3',
          active && 'bg-foreground/[0.07] text-foreground'
        )}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Icons.chevronDown aria-hidden className='text-muted-foreground pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2' />
    </span>
  );
}

/** A thin vertical rule between toolbar groups. */
export function ToolbarDivider({ className }: { className?: string }) {
  return <span aria-hidden className={cn('bg-foreground/10 mx-1 h-5 w-px shrink-0', className)} />;
}
