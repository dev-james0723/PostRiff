import * as React from 'react';
import { PageHeader } from '@/components/rafii';
import { cn } from '@/lib/utils';

interface PageHeroProps {
  eyebrow?: string;
  title: React.ReactNode;
  /** One serif-italic phrase appended to the title (DNA §6.4). */
  accent?: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

/**
 * Identity block for inner marketing pages (channels, pricing, docs, contact, status): the app's
 * own `PageHeader` at its creative size, on the canvas with no rule beneath it (DNA §9.1, §21.19).
 * Static from first paint — public pages carry no forced entrance animation.
 */
export function PageHero({ eyebrow, title, accent, description, children, className }: PageHeroProps) {
  return (
    <div className={cn('mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 pt-12 sm:px-6 sm:pt-16', className)}>
      <PageHeader
        density='creative'
        eyebrow={eyebrow}
        title={title}
        accent={accent}
        description={description ? <span className='block text-base leading-relaxed sm:text-lg'>{description}</span> : undefined}
      />
      {children && <div className='flex flex-wrap items-center gap-3'>{children}</div>}
    </div>
  );
}
