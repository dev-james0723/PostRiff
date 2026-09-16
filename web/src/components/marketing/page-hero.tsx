import * as React from 'react';
import { cn } from '@/lib/utils';

interface PageHeroProps {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}

/**
 * transitions.dev texts reveal (`.t-stagger-line`): eyebrow, title, description and actions rise in one
 * stagger step apart. Plain CSS, so inner pages are readable from first paint without waiting for hydration.
 */
const line = (index: number) => ({ '--stagger-i': index }) as React.CSSProperties;

/** Hero for inner marketing pages (channels, pricing, docs, legal). */
export function PageHero({ eyebrow, title, description, children, className }: PageHeroProps) {
  return (
    <header className={cn('border-b', className)}>
      <div className='mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-14 sm:px-6 sm:py-20'>
        {eyebrow && (
          <p style={line(0)} className='t-stagger-line text-primary text-xs font-semibold tracking-[0.18em] uppercase'>
            {eyebrow}
          </p>
        )}
        <h1 style={line(1)} className='t-stagger-line max-w-3xl text-3xl font-semibold tracking-tight text-balance sm:text-4xl md:text-5xl'>
          {title}
        </h1>
        {description && (
          <p style={line(2)} className='t-stagger-line text-muted-foreground max-w-2xl text-base text-pretty sm:text-lg'>
            {description}
          </p>
        )}
        {children && (
          <div style={line(3)} className='t-stagger-line mt-2 flex flex-wrap items-center gap-3'>
            {children}
          </div>
        )}
      </div>
    </header>
  );
}
