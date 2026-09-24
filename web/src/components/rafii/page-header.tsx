import type { ReactNode } from 'react';
import { InfoButton } from '@/components/ui/info-button';
import type { InfobarContent } from '@/components/ui/infobar';
import { cn } from '@/lib/utils';

export interface PageHeaderProps {
  /** Short tracked label above the title (WHAT); optional. */
  eyebrow?: ReactNode;
  title: ReactNode;
  /** One serif-italic phrase appended to the title; the rest stays sans (DNA §6.4). */
  accent?: ReactNode;
  description?: ReactNode;
  /** Right-hand slot: the page's one dominant commitment action or quiet utilities. */
  actions?: ReactNode;
  /** Help content published to the info sidebar (existing mechanism). */
  infoContent?: InfobarContent;
  /** `functional` (default) for operational pages; `creative` only on creation surfaces (DNA §21.1). */
  density?: 'functional' | 'creative';
  className?: string;
  titleId?: string;
}

/**
 * The universal page frame's identity block (DNA §9.1): title, optional explanation, one
 * action slot. Compact on every operational page; the creative size belongs to Home.
 */
export function PageHeader({ eyebrow, title, accent, description, actions, infoContent, density = 'functional', className, titleId }: PageHeaderProps) {
  const creative = density === 'creative';
  return (
    <header className={cn('flex flex-col gap-3 md:flex-row md:items-end md:justify-between md:gap-6', className)}>
      <div className='flex min-w-0 flex-col gap-1.5'>
        {eyebrow && (
          <span className='rafii-eyebrow inline-flex items-center gap-2.5'>
            <span aria-hidden className='bg-foreground/70 h-px w-4' />
            {eyebrow}
          </span>
        )}
        <div className='flex items-start gap-2'>
          <h1
            id={titleId}
            className={cn(
              'text-foreground min-w-0 font-medium tracking-[-0.02em] text-balance',
              creative ? 'text-[2.5rem] leading-[1.05] md:text-[3rem] lg:text-[3.1rem]' : 'text-[1.625rem] leading-[1.15] md:text-[1.875rem]'
            )}
          >
            {title}
            {accent && (
              <>
                {' '}
                <em className='rafii-serif text-foreground'>{accent}</em>
              </>
            )}
          </h1>
          {infoContent && (
            <div className='pt-1'>
              <InfoButton content={infoContent} />
            </div>
          )}
        </div>
        {description && <p className={cn('text-muted-foreground max-w-[60ch] text-pretty', creative ? 'text-[15px] leading-relaxed' : 'text-sm leading-relaxed')}>{description}</p>}
      </div>
      {actions && <div className='flex shrink-0 flex-wrap items-center gap-2'>{actions}</div>}
    </header>
  );
}
