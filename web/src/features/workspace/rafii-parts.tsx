'use client';

import type { ComponentPropsWithoutRef, ElementType, ReactNode } from 'react';
import { Icons } from '@/components/icons';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { NumberTicker } from '@/components/motion/number-ticker';
import { Surface, type SurfaceMaterial } from '@/components/rafii';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

/**
 * Local compositions shared by the Workspace, Memory, Overview and Analytics routes while
 * `components/rafii` has no section panel, stat tile, status chip or form-field recipe
 * (reported as a shared-component gap). Everything here is built from the shared materials
 * (`Surface`, the `rafii-*` utilities) and forks nothing.
 */

/* ---------- section panel (DNA §9.1, §21.15): heading, explanation, one action slot, the work ---------- */

export type PanelProps = {
  title?: ReactNode;
  titleId?: string;
  eyebrow?: ReactNode;
  description?: ReactNode;
  /** Quiet utilities or the panel's one dominant action, on the heading row. */
  actions?: ReactNode;
  material?: SurfaceMaterial;
  headingLevel?: 'h2' | 'h3';
  footer?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
} & Omit<ComponentPropsWithoutRef<'section'>, 'title' | 'className' | 'children'>;

export function Panel({ title, titleId, eyebrow, description, actions, material = 'quiet', headingLevel = 'h2', footer, children, className, bodyClassName, ...rest }: PanelProps) {
  const Heading = headingLevel as ElementType;
  const hasHeader = Boolean(title || description || actions || eyebrow);
  const hasBody = children !== undefined && children !== null && children !== false;
  return (
    <Surface as='section' material={material} padding='none' aria-labelledby={title && titleId ? titleId : undefined} className={cn('flex flex-col gap-4 p-5 md:p-6', className)} {...rest}>
      {hasHeader && (
        <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4'>
          <div className='flex min-w-0 flex-col gap-1'>
            {eyebrow && <span className='rafii-eyebrow'>{eyebrow}</span>}
            {title && (
              <Heading id={titleId} className='text-foreground text-base font-medium tracking-tight'>
                {title}
              </Heading>
            )}
            {description && <p className='text-muted-foreground max-w-prose text-sm leading-relaxed text-pretty'>{description}</p>}
          </div>
          {actions && <div className='flex shrink-0 flex-wrap items-center gap-2'>{actions}</div>}
        </div>
      )}
      {hasBody && <div className={cn('flex min-w-0 flex-col gap-4', bodyClassName)}>{children}</div>}
      {footer && <div className='text-muted-foreground text-xs leading-relaxed'>{footer}</div>}
    </Surface>
  );
}

/** A page-level section heading (a group of panels or a table), not itself on a surface. */
export function SectionHeading({ id, title, description, actions, level = 'h2', className }: { id?: string; title: ReactNode; description?: ReactNode; actions?: ReactNode; level?: 'h2' | 'h3'; className?: string }) {
  const Heading = level as ElementType;
  return (
    <div className={cn('flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between sm:gap-4', className)}>
      <div className='flex min-w-0 flex-col gap-1'>
        <Heading id={id} className='text-foreground text-lg font-medium tracking-tight'>
          {title}
        </Heading>
        {description && <p className='text-muted-foreground max-w-prose text-sm leading-relaxed text-pretty'>{description}</p>}
      </div>
      {actions && <div className='flex shrink-0 flex-wrap items-center gap-2'>{actions}</div>}
    </div>
  );
}

/* ---------- stat tile (DNA §21.13): label, tabular value, a hint with its denominator, a quiet footer ---------- */

export function StatTile({ label, value, hint, footer, badge, loading, className }: { label: ReactNode; value: ReactNode; hint?: ReactNode; footer?: ReactNode; badge?: ReactNode; loading?: boolean; className?: string }) {
  return (
    <div className={cn('rafii-quiet flex min-w-0 flex-col gap-1.5 rounded-[var(--rafii-radius-card)] p-4 md:p-5', className)}>
      <div className='flex items-start justify-between gap-2'>
        <span className='text-muted-foreground text-xs font-medium'>{label}</span>
        {badge}
      </div>
      <span className='text-foreground text-2xl font-semibold tracking-[-0.02em] tabular-nums'>{loading ? <Skeleton className='h-8 w-20' /> : typeof value === 'number' ? <NumberTicker value={value} locale /> : value}</span>
      {hint && <span className='text-foreground text-sm'>{hint}</span>}
      {footer && <span className='text-muted-foreground text-xs leading-relaxed'>{footer}</span>}
    </div>
  );
}

/* ---------- monochrome status (DNA §4.3): icon + text; amber only where a real state distinction needs it ---------- */

export type StatusTone = 'neutral' | 'attention';

const STATUS_ICON: Record<AnimatedBadgeStatus, keyof typeof Icons> = {
  neutral: 'circle',
  info: 'info',
  success: 'check',
  warning: 'warning',
  danger: 'close',
  loading: 'spinner'
};

export function StatusChip({ icon, status, tone, className, children, ...rest }: { icon?: keyof typeof Icons | null; status?: AnimatedBadgeStatus; tone?: StatusTone } & ComponentPropsWithoutRef<'span'>) {
  const name = icon === undefined ? (status ? STATUS_ICON[status] : null) : icon;
  const Icon = name ? Icons[name] : null;
  const attention = tone === 'attention' || (tone === undefined && (status === 'warning' || status === 'danger'));
  return (
    <span className={cn('rafii-quiet text-foreground inline-flex h-7 max-w-full items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap', className)} {...rest}>
      {Icon && <Icon aria-hidden className={cn('size-3.5 shrink-0', status === 'loading' && 'animate-spin motion-reduce:animate-none', attention ? 'text-foreground' : 'text-muted-foreground')} />}
      <span className='truncate'>{children}</span>
    </span>
  );
}

/* ---------- form fields (DNA §11.1–§11.2): borderless fill, 48px, 16px text on phones, one chevron ---------- */

/** Extra classes for the shadcn `Input`: removes its stroke, keeps its focus ring, adds the Rafii fill. */
export const FIELD_CLASS = 'rafii-field h-12 rounded-[var(--rafii-radius-control)] border-0 px-3.5 text-base shadow-none focus-visible:border-transparent md:text-sm dark:bg-[var(--rafii-surface-field)]';

/** Extra classes for the shadcn `Textarea`. */
export const TEXTAREA_CLASS = 'rafii-field min-h-24 rounded-[var(--rafii-radius-control)] border-0 px-3.5 py-3 text-base shadow-none focus-visible:border-transparent md:text-sm dark:bg-[var(--rafii-surface-field)]';

/** Extra classes for the base-ui `SelectTrigger` (small straightforward lists stay native-like). */
export const SELECT_TRIGGER_CLASS = 'rafii-field h-12 w-full rounded-[var(--rafii-radius-control)] border-0 pr-3 pl-3.5 text-base shadow-none focus-visible:border-transparent data-[size=default]:h-12 md:text-sm dark:bg-[var(--rafii-surface-field)] dark:hover:bg-[var(--rafii-surface-field)]';

export const NATIVE_SELECT_CLASS = 'rafii-field h-12 w-full appearance-none rounded-[var(--rafii-radius-control)] pr-10 pl-3.5 text-base outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm';

/** A labelled native select with the Rafii field material and its own chevron (DNA §11.2). */
export function SelectField({ label, hideLabel = false, className, selectClassName, children, ...rest }: { label: ReactNode; hideLabel?: boolean; className?: string; selectClassName?: string; children: ReactNode } & Omit<ComponentPropsWithoutRef<'select'>, 'className' | 'children'>) {
  return (
    <label className={cn('flex min-w-0 flex-col gap-2 text-sm', className)}>
      <span className={hideLabel ? 'sr-only' : 'text-foreground font-medium'}>{label}</span>
      <span className='relative block'>
        <select className={cn(NATIVE_SELECT_CLASS, selectClassName)} {...rest}>
          {children}
        </select>
        <Icons.chevronDown aria-hidden className='text-muted-foreground pointer-events-none absolute top-1/2 right-3.5 size-4 -translate-y-1/2' />
      </span>
    </label>
  );
}

/** A quiet band inside a panel for a sub-setting or a nested group (spacing and fill, no divider). */
export function Band({ as, className, ...props }: { as?: 'div' | 'li' | 'section' } & ComponentPropsWithoutRef<'div'>) {
  const Component = (as ?? 'div') as ElementType;
  return <Component className={cn('rafii-quiet flex min-w-0 flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4', className)} {...props} />;
}
