'use client';

import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { readinessCopy, type FeatureReadiness } from '@/lib/feature-readiness';

type ReasonCopy = Record<string, { title?: string; detail?: string }>;

// One honest, actionable state for a page or tab that cannot fully work yet.
// Copy comes from the server state plus the feature's own reason copy; the
// only controls rendered are the ones the server says can lead somewhere.
export function FeatureReadinessNotice({
  readiness,
  reasons,
  onRetry,
  className,
  children
}: {
  readiness: FeatureReadiness;
  reasons?: ReasonCopy;
  onRetry?: () => void;
  className?: string;
  children?: React.ReactNode;
}) {
  const copy = readinessCopy(readiness, reasons);
  const step = readiness.nextStep;
  const updated = readiness.lastSuccessfulReadAt ? new Date(readiness.lastSuccessfulReadAt) : null;
  return (
    <section
      className={['feature-readiness', className].filter(Boolean).join(' ')}
      data-readiness-state={readiness.state}
      data-readiness-reasons={readiness.reasonCodes.join(' ')}
      role={copy.live === 'assertive' ? 'alert' : 'status'}
      aria-live={copy.live}
    >
      <h2 className='feature-readiness-title'>{copy.title}</h2>
      {copy.detail ? <p className='feature-readiness-detail'>{copy.detail}</p> : null}
      {updated && !Number.isNaN(updated.getTime()) ? (
        <p className='feature-readiness-updated'>
          Last successful update <time dateTime={readiness.lastSuccessfulReadAt ?? undefined}>{updated.toLocaleString()}</time>
        </p>
      ) : null}
      {step?.kind === 'retry' && onRetry ? (
        <Button variant='outline' onClick={onRetry}>
          {copy.action}
        </Button>
      ) : step && step.href && step.kind !== 'contact_owner' && step.kind !== 'wait' ? (
        <Link className='feature-readiness-action' href={step.href}>
          {copy.action}
        </Link>
      ) : step?.kind === 'contact_owner' ? (
        <p className='feature-readiness-owner'>Only the workspace owner can take this step. Ask them to open this page.</p>
      ) : null}
      {children}
    </section>
  );
}
