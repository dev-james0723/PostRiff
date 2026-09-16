import * as React from 'react';
import { cn } from '@/lib/utils';

interface SectionProps extends Omit<React.ComponentProps<'section'>, 'title'> {
  eyebrow?: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  align?: 'left' | 'center';
  /** Extra classes for the inner max-w-6xl container. */
  containerClassName?: string;
}

/**
 * Marketing section: max-w-6xl container, 16px side gutter on phones,
 * optional eyebrow / title / description header.
 */
export function Section({
  eyebrow,
  title,
  description,
  align = 'left',
  className,
  containerClassName,
  children,
  ...props
}: SectionProps) {
  const hasHeader = eyebrow || title || description;
  return (
    <section className={cn('py-14 sm:py-20', className)} {...props}>
      <div className={cn('mx-auto w-full max-w-6xl px-4 sm:px-6', containerClassName)}>
        {hasHeader && (
          <div
            className={cn(
              'mb-8 flex max-w-2xl flex-col gap-3 sm:mb-12',
              align === 'center' && 'mx-auto items-center text-center'
            )}
          >
            {eyebrow && (
              <p className='text-primary text-xs font-semibold tracking-[0.18em] uppercase'>
                {eyebrow}
              </p>
            )}
            {title && (
              <h2 className='text-2xl font-semibold tracking-tight text-balance sm:text-3xl md:text-4xl'>
                {title}
              </h2>
            )}
            {description && (
              <p className='text-muted-foreground text-base text-pretty sm:text-lg'>
                {description}
              </p>
            )}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}

/** Bare container without the section padding, for custom layouts. */
export function Container({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('mx-auto w-full max-w-6xl px-4 sm:px-6', className)} {...props} />;
}
