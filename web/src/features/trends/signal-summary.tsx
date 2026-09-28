import type { Coverage, Trend } from '@/lib/coworker/trend-types';
import {
  creatorConfidence,
  creatorMomentum,
  platformLabel,
  sourceOverview,
  sourceStatus
} from './creator-language';

export function SignalSummary({ trend }: { trend: Trend }) {
  const momentum = creatorMomentum(trend),
    confidence = creatorConfidence(trend);
  return (
    <div className='trend-signal-grid'>
      <section aria-label='Momentum'>
        <h3>Momentum</h3>
        <p className='trend-signal-value'>
          <span aria-hidden='true'>{momentum.symbol}</span> {momentum.label}
        </p>
        <p className='trend-signal-detail'>{momentum.detail}</p>
      </section>
      <section aria-label='Confidence'>
        <h3>Confidence</h3>
        <p className='trend-signal-value'>{confidence.label}</p>
        <p className='trend-signal-detail'>{confidence.detail}</p>
      </section>
    </div>
  );
}
export function SourcesSummary({ coverage }: { coverage: Coverage }) {
  return (
    <div className='trend-sources-summary'>
      <ul aria-label='Sources' className='trend-platforms'>
        {coverage.sources.map((source) => (
          <li key={source.platform}>
            <span aria-hidden='true'>{source.availability === 'available' ? '✓' : '—'}</span>{' '}
            {platformLabel(source.platform)}
            {source.availability !== 'available' &&
              ` · ${sourceStatus(source.availability).toLowerCase()}`}
            <span className='sr-only'>
              {source.availability === 'available' ? ' available' : ''}
            </span>
          </li>
        ))}
      </ul>
      <p className='trend-source-note'>{sourceOverview(coverage)}</p>
    </div>
  );
}
