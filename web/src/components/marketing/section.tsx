import * as React from 'react';
import { cn } from '@/lib/utils';

interface SectionProps extends Omit<React.ComponentProps<'section'>, 'title'> {
  eyebrow?: string;
  title?: React.ReactNode;
  /** One serif-italic phrase appended to the title; the rest stays sans (DNA §6.4). */
  accent?: React.ReactNode;
  description?: React.ReactNode;
  align?: 'left' | 'center';
  /** Extra classes for the inner max-w-6xl container. */
  containerClassName?: string;
}

/**
 * Marketing section (DNA §21.19): the app PageHeader's eyebrow → title → explanation frame with
 * more editorial room; max-w-6xl container and a 16px side gutter on phones.
 */
export function Section({ eyebrow, title, accent, description, align = 'left', className, containerClassName, children, ...props }: SectionProps) {
  const hasHeader = eyebrow || title || description;
  return (
    <section className={cn('py-14 sm:py-20', className)} {...props}>
      <div className={cn('mx-auto w-full max-w-6xl px-4 sm:px-6', containerClassName)}>
        {hasHeader && (
          <div className={cn('mb-8 flex max-w-2xl flex-col gap-3 sm:mb-12', align === 'center' && 'mx-auto items-center text-center')}>
            {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
            {title && (
              <h2 className='text-foreground text-[1.75rem] leading-[1.15] font-medium tracking-[-0.02em] text-balance sm:text-[2rem] md:text-[2.25rem]'>
                {title}
                {accent && (
                  <>
                    {' '}
                    <em className='rafii-serif'>{accent}</em>
                  </>
                )}
              </h2>
            )}
            {description && <p className='text-muted-foreground text-base leading-relaxed text-pretty sm:text-lg'>{description}</p>}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

/** Section eyebrow: the app header's tracked label with its short rule (readable 11px, DNA §6.3). */
export function Eyebrow({ className, children, ...props }: React.ComponentProps<'p'>) {
  return (
    <p className={cn('rafii-eyebrow inline-flex items-center gap-2.5', className)} {...props}>
      <span aria-hidden className='bg-foreground/70 h-px w-4' />
      {children}
    </p>
  );
}

/** Bare container without the section padding, for custom layouts. */
export function Container({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('mx-auto w-full max-w-6xl px-4 sm:px-6', className)} {...props} />;
}
