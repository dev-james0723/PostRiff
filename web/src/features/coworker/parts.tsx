'use client';

import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { errorMessage, isFeatureDisabled } from '@/lib/coworker/api';
import { cn } from '@/lib/utils';
import type { Tone } from './present';

/**
 * Small pieces shared by the coworker screens. Status is always icon + words (never colour alone); the one
 * attention tone is the existing monochrome StatusChip treatment.
 */

export function ToneChip({ tone, icon, children, className }: { tone: Tone; icon?: string; children: ReactNode; className?: string }) {
  const name = (icon && icon in Icons ? icon : tone === 'attention' ? 'warning' : tone === 'success' ? 'check' : 'circle') as keyof typeof Icons;
  return (
    <StatusChip icon={name} tone={tone === 'attention' ? 'attention' : 'neutral'} className={className}>
      {children}
    </StatusChip>
  );
}

/** Where a preference comes from: said by a person, noticed by Rafii, or seen in results. Words, not colour. */
export function OriginBadge({ origin }: { origin: 'explicit' | 'inferred' | 'performance' }) {
  const meta = {
    explicit: { icon: 'userPen', label: 'You said this' },
    inferred: { icon: 'sparkles', label: 'Rafii noticed this' },
    performance: { icon: 'trendingUp', label: 'Pattern in results' }
  }[origin] as { icon: keyof typeof Icons; label: string };
  return (
    <StatusChip icon={meta.icon} data-origin={origin}>
      {meta.label}
    </StatusChip>
  );
}

export function ScopeChips({ scope }: { scope: { platform?: string; language?: string; contentTypeId?: string; audience?: string } | undefined }) {
  const parts = [scope?.platform, scope?.language, scope?.contentTypeId?.replace(/_/g, ' '), scope?.audience].filter(Boolean) as string[];
  if (parts.length === 0) {
    return <span className='rafii-quiet text-muted-foreground inline-flex h-6 items-center rounded-full px-2 text-xs'>Everywhere</span>;
  }
  return (
    <span className='flex flex-wrap gap-1' aria-label={`Applies to ${parts.join(', ')}`}>
      {parts.map((part) => (
        <span key={part} className='rafii-quiet text-foreground inline-flex h-6 items-center rounded-full px-2 text-xs'>
          {part}
        </span>
      ))}
    </span>
  );
}

/** A query's failure: hidden when the feature is off (`hideWhenOff`), otherwise a retryable message. */
export function QueryProblem({ error, onRetry, what, hideWhenOff = false }: { error: unknown; onRetry?: () => void; what: string; hideWhenOff?: boolean }) {
  if (isFeatureDisabled(error)) {
    if (hideWhenOff) return null;
    return <StateMessage kind='unsupported' title={`${what} is not turned on for this workspace yet.`} description='Nothing is missing from your account; this feature isn’t turned on yet.' />;
  }
  return (
    <StateMessage
      kind='error'
      title={`${what} is unavailable right now.`}
      description={errorMessage(error)}
      action={
        onRetry ? (
          <Button variant='glass' size='control' onClick={onRetry}>
            <Icons.refresh className='size-4' aria-hidden /> Retry
          </Button>
        ) : undefined
      }
    />
  );
}

/** The "Why Rafii suggested this" explainer: the three kinds of signal and what each one may change. */
export function WhyRafiiExplainer({ className }: { className?: string }) {
  return (
    <details className={cn('rafii-quiet group rounded-[var(--rafii-radius-control)] px-4 py-3', className)}>
      <summary className='rafii-focus text-foreground flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-sm text-sm font-medium [&::-webkit-details-marker]:hidden'>
        Why Rafii suggested this
        <Icons.chevronDown aria-hidden className='text-muted-foreground size-4 transition-transform group-open:rotate-180 motion-reduce:transition-none' />
      </summary>
      <dl className='text-muted-foreground mt-2 grid gap-3 pb-1 text-sm leading-relaxed'>
        <div>
          <dt className='text-foreground font-medium'>You said this</dt>
          <dd>A note someone in this workspace wrote. It always wins over anything Rafii noticed and never expires.</dd>
        </div>
        <div>
          <dt className='text-foreground font-medium'>Rafii noticed this</dt>
          <dd>A pattern in your edits and approvals. It carries a confidence, the evidence behind it and an expiry, and it fades unless new evidence supports it.</dd>
        </div>
        <div>
          <dt className='text-foreground font-medium'>Pattern in results</dt>
          <dd>How comparable posts on one account performed. It may point to something worth testing; it is not proof and it never changes your voice on its own.</dd>
        </div>
      </dl>
    </details>
  );
}

export function formatDate(epochSeconds: number | null | undefined): string | null {
  if (!epochSeconds || !Number.isFinite(epochSeconds)) return null;
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(epochSeconds * 1000));
}
