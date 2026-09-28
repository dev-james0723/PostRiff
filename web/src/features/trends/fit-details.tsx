'use client';
import type { Trend } from '@/lib/coworker/trend-types';
import { Disclosure } from './disclosure';
import { words } from './present';
export function FitDetails({
  fit,
  title = 'Fit, timing and risk'
}: {
  fit: NonNullable<Trend['workspace_fit']>;
  title?: string;
}) {
  return (
    <Disclosure title={title}>
      <p className='text-muted-foreground text-sm'>{fit.reason}</p>
      <dl className='trend-fit-grid'>
        {(
          [
            'trend_relevance',
            'brand',
            'audience',
            'timing',
            'originality',
            'risk',
            'confidence'
          ] as const
        ).map((key) => (
          <div key={key}>
            <dt>
              <span>{words(key)}</span>
              <span className='trend-assessment'>{words(fit[key].assessment)}</span>
            </dt>
            <dd>
              {fit[key].reason}
              <p className='mt-1 text-xs'>
                Evidence: {fit[key].evidence_refs.join(', ') || 'Unknown'}
              </p>
            </dd>
          </div>
        ))}
      </dl>
    </Disclosure>
  );
}
