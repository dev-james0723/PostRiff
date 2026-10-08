'use client';

import type { AssetUsage } from '@/lib/api/library-intelligence-types';
import { metricName, metricValue, usageLabel } from '@/lib/library/proactive';
import { formatDateTime, relativeTime } from '@/lib/time';

/**
 * Where an item was actually used (PRD R15): drafts, posts, channels and times, and the metrics those posts recorded
 * with each reading's own time. A missing value reads "unknown". The server's note says what this is: correlation.
 */
export function UsagePanel({ usage }: { usage: AssetUsage }) {
  const { uses, summary } = usage;
  return (
    <div className='flex flex-col gap-3'>
      <p className='text-sm'>
        {summary.uses} {summary.uses === 1 ? 'use' : 'uses'} · {summary.drafts} {summary.drafts === 1 ? 'draft' : 'drafts'} · {summary.posts} {summary.posts === 1 ? 'post' : 'posts'}
        {summary.channels.length ? ` · ${summary.channels.join(', ')}` : ''}
      </p>
      {uses.length ? (
        <ul className='flex flex-col gap-2' aria-label='Uses of this item'>
          {uses.map((entry, index) => (
            <li key={`${entry.source}-${entry.jobId ?? entry.reviewId ?? entry.draftId ?? entry.key ?? index}-${index}`} className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
              <span className='flex flex-wrap items-baseline justify-between gap-2'>
                <span>
                  {usageLabel(entry)}
                  {entry.channel ? <span className='text-muted-foreground'> · {entry.channel}</span> : null}
                  {entry.account ? <span className='text-muted-foreground'> · {entry.account}</span> : null}
                  {entry.state ? <span className='text-muted-foreground'> · {entry.state.replaceAll('_', ' ')}</span> : null}
                </span>
                <span className='text-muted-foreground text-xs' title={typeof entry.at === 'number' ? formatDateTime(entry.at) : undefined}>
                  {typeof entry.at === 'number' ? relativeTime(entry.at) : 'Time not recorded'}
                </span>
              </span>
              {entry.metricsStatus === 'not_applicable' ? null : entry.metrics && Object.keys(entry.metrics).length ? (
                <dl className='text-muted-foreground grid grid-cols-[auto_auto_1fr] gap-x-3 text-xs'>
                  {Object.entries(entry.metrics).map(([name, reading]) => (
                    <div key={name} className='contents'>
                      <dt>{metricName(name)}</dt>
                      <dd className='text-foreground tabular-nums'>{metricValue(reading)}</dd>
                      <dd>{typeof reading?.observedAt === 'number' ? `as of ${formatDateTime(reading.observedAt)}` : 'reading time unknown'}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <span className='text-muted-foreground text-xs'>Metrics: unknown</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className='text-muted-foreground text-sm'>Not used yet</p>
      )}
      {usage.truncated ? <p className='text-muted-foreground text-xs'>Only the most recent uses are listed.</p> : null}
      {usage.warnings.map((warning) => (
        <p key={warning} className='text-muted-foreground text-xs'>
          {warning}
        </p>
      ))}
      <p className='text-muted-foreground text-xs'>{usage.note}</p>
    </div>
  );
}
