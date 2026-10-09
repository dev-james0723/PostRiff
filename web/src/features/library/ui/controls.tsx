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

/**
 * Shared by buttons and links styled as buttons, so a `<Link>` matches its neighbours exactly. `Control` and
 * `IconControl` also pass the material as `variant`: `Button` otherwise applies its own default (filled) material.
 */
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
    <Button {...props} variant={MATERIAL[tone]} disabled={disabled || loading} aria-busy={loading || undefined} data-active={active || undefined} className={controlClass({ tone, size, active, className })}>
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
  const classes = controlClass({ tone, size, iconOnly: true, active, className });
  if (!tooltip) {
    return (
      <Button {...props} variant={MATERIAL[tone]} aria-label={label} data-active={active || undefined} className={classes}>
        {children}
      </Button>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger render={<Button {...props} variant={MATERIAL[tone]} aria-label={label} data-active={active || undefined} className={classes} />}>{children}</TooltipTrigger>
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
  const current = options.find((option) => option.value === value)?.label ?? '';
  return (
    // The chip is as wide as the current choice (a bare <select> takes its longest option's width); the native select
    // lies invisibly on top, so keyboard, screen readers and the system picker on touch behave exactly as before.
    <span
      data-active={active || undefined}
      className={cn(
        'relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[var(--rafii-radius-control)] px-2.5 text-[13px] font-medium whitespace-nowrap pointer-coarse:h-11',
        'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] transition-colors duration-150',
        'has-[:focus-visible]:ring-ring/50 has-[:focus-visible]:ring-3',
        active && 'bg-foreground/[0.07] text-foreground',
        className
      )}
    >
      {icon ? <span aria-hidden className='[&_svg]:size-4'>{icon}</span> : null}
      <span aria-hidden>{current}</span>
      <Icons.chevronDown aria-hidden className='size-3.5 opacity-70' />
      <select
        id={id}
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value as V)}
        data-active={active || undefined}
        className='absolute inset-0 size-full cursor-pointer appearance-none opacity-0 outline-none'
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </span>
  );
}

/** A thin vertical rule between toolbar groups. */
export function ToolbarDivider({ className }: { className?: string }) {
  return <span aria-hidden className={cn('bg-foreground/10 mx-1 h-5 w-px shrink-0', className)} />;
}

/*
 * Existing Library panels keep their `variant`/`size` vocabulary but render on this scale: the old 48 px `control` and
 * hand-set 44 px heights become the 36/32 px (44 px on touch) controls. Inside a dialog the filled `action` stays the
 * dialog's one primary; inline on the page it becomes secondary, so the page keeps a single filled Add.
 */
type LegacyProps = Omit<ComponentProps<typeof Button>, 'className'> & { className?: string };

const LEGACY_TONE: Record<string, Exclude<ControlTone, 'primary'> | 'action'> = {
  action: 'action',
  default: 'action',
  glass: 'secondary',
  outline: 'secondary',
  secondary: 'secondary',
  quiet: 'ghost',
  ghost: 'ghost',
  destructive: 'danger'
};

function legacyClass({ variant, size, className, primaryInside }: { variant: string; size: string; className?: string; primaryInside: boolean }) {
  const mapped = LEGACY_TONE[variant] ?? 'secondary';
  const tone: ControlTone = mapped === 'action' ? (primaryInside ? 'primary' : 'secondary') : mapped;
  const iconOnly = size.startsWith('icon');
  const small = ['sm', 'xs', 'icon-sm', 'icon-xs'].includes(size);
  const cleaned = className?.replace(/(^|\s)(min-)?h-1[12](?=\s|$)/g, ' ').trim();
  return { tone, classes: controlClass({ tone, size: small ? 'sm' : 'md', iconOnly, className: cleaned }) };
}

/** For buttons inline on the Library page and in the inspector. */
export function PanelButton({ variant = 'default', size = 'default', className, ...props }: LegacyProps) {
  if (variant === 'link') return <Button {...props} variant='link' size={size} className={className} />;
  const { tone, classes } = legacyClass({ variant: variant ?? 'default', size: size ?? 'default', className, primaryInside: false });
  return <Button {...props} variant={MATERIAL[tone]} className={classes} />;
}

/** For buttons inside a Library dialog, where the filled action is that dialog's one primary. */
export function DialogButton({ variant = 'default', size = 'default', className, ...props }: LegacyProps) {
  if (variant === 'link') return <Button {...props} variant='link' size={size} className={className} />;
  const { tone, classes } = legacyClass({ variant: variant ?? 'default', size: size ?? 'default', className, primaryInside: true });
  return <Button {...props} variant={MATERIAL[tone]} className={classes} />;
}
