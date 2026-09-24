'use client';

import type { ReactNode } from 'react';
import { NumberTicker } from '@/components/motion/number-ticker';
import { Surface, type SurfaceMaterial } from '@/components/rafii';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

/**
 * One settings group (Design DNA §21.15): a heading with helper text and an optional action slot
 * over a quiet reading surface. `material='none'` leaves the children on the canvas for groups
 * that are lists of their own surfaces (workspaces, accounts), so glass never nests in glass
 * (§5.5). A stand-in for a shared `components/rafii` section until one exists.
 */
export function SettingsSection({
  id,
  title,
  description,
  action,
  material = 'quiet',
  padding = 'md',
  className,
  bodyClassName,
  children,
  ...rest
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  material?: SurfaceMaterial | 'none';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
  'data-tour'?: string;
  'aria-label'?: string;
}) {
  const headingId = `${id}-heading`;
  return (
    <section aria-labelledby={headingId} className={cn('flex min-w-0 flex-col gap-3', className)} {...rest}>
      <div className='flex flex-wrap items-end justify-between gap-x-4 gap-y-1 px-1'>
        <div className='flex min-w-0 flex-col gap-1'>
          <h2 id={headingId} className='text-foreground text-lg font-medium tracking-tight'>
            {title}
          </h2>
          {/* Plain text stays a paragraph; anything else (a loading skeleton) needs a block container. */}
          {description && (typeof description === 'string' ? <p className='text-muted-foreground max-w-[64ch] text-sm leading-relaxed text-pretty'>{description}</p> : <div className='text-muted-foreground max-w-[64ch] text-sm leading-relaxed text-pretty'>{description}</div>)}
        </div>
        {action && <div className='flex shrink-0 flex-wrap items-center gap-2'>{action}</div>}
      </div>
      {material === 'none' ? (
        <div className={cn('flex min-w-0 flex-col gap-3', bodyClassName)}>{children}</div>
      ) : (
        <Surface material={material} radius='card' padding={padding} className={cn('flex flex-col gap-4', bodyClassName)}>
          {children}
        </Surface>
      )}
    </section>
  );
}

/** A sub-group inside one settings surface: icon, title, helper text and its own action (§7.1 spacing does the separating). */
export function SettingsGroup({
  icon,
  title,
  description,
  action,
  titleId,
  children,
  className
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  titleId?: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex min-w-0 flex-col gap-3', className)}>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='flex min-w-0 flex-col gap-1'>
          <div className='flex items-center gap-2'>
            {icon && (
              <span aria-hidden className='text-muted-foreground flex size-5 shrink-0 items-center justify-center'>
                {icon}
              </span>
            )}
            <span id={titleId} className='text-foreground text-sm font-medium'>
              {title}
            </span>
          </div>
          {description && (typeof description === 'string' ? <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{description}</p> : <div className='text-muted-foreground text-sm leading-relaxed text-pretty'>{description}</div>)}
        </div>
        {action && <div className='flex shrink-0 flex-wrap items-center gap-2'>{action}</div>}
      </div>
      {children}
    </div>
  );
}

/**
 * A quiet stat tile (§20.1 honest counts): label, the real value or an explicit Unavailable, and a
 * hint. Numbers roll once inside the motion budget; strings render as they are.
 */
export function StatTile({
  label,
  value,
  hint,
  footer,
  loading,
  className
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  footer?: ReactNode;
  loading?: boolean;
  className?: string;
}) {
  return (
    <Surface material='quiet' radius='card' padding='none' className={cn('flex min-w-0 flex-col gap-1 p-4', className)}>
      <span className='text-muted-foreground text-xs font-medium'>{label}</span>
      <span className='text-foreground text-2xl font-semibold tracking-tight tabular-nums'>
        {loading ? (
          <Skeleton className='h-8 w-20' />
        ) : typeof value === 'number' ? (
          <NumberTicker value={value} locale startOnView={false} duration={0.26} stagger={value >= 1000 ? 0 : 0.04} />
        ) : (
          <span className={cn(typeof value === 'string' && value === 'Unavailable' && 'text-muted-foreground text-base font-medium')}>{value}</span>
        )}
      </span>
      {hint && <span className='text-foreground text-xs'>{hint}</span>}
      {footer && <span className='text-muted-foreground text-xs leading-relaxed'>{footer}</span>}
    </Surface>
  );
}
