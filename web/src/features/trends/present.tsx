'use client';
import { useExpired } from './hooks';
import { Disclosure } from './disclosure';
import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import type {
  Coverage,
  TrendEnvelope,
  TrendEvidence,
  TrendMetric
} from '@/lib/coworker/trend-types';
export const words = (s: string) => s.replaceAll('_', ' ');
export const date = (s: string | null) =>
  s
    ? new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : 'Unknown';
export const fieldClass = 'rafii-field rafii-focus min-h-11 w-full rounded-xl px-3 py-2 text-base';
export function SafeLink({ url, children }: { url: string | null; children: ReactNode }) {
  if (!url || !/^https?:\/\//i.test(url)) return <span>{children}</span>;
  return (
    <a
      className='rafii-focus rounded-sm underline underline-offset-4'
      href={url}
      target='_blank'
      rel='noopener noreferrer'
    >
      {children}
      <span className='sr-only'> (opens in a new tab)</span>
    </a>
  );
}
export function TrendError({ error, retry }: { error: unknown; retry?: () => void }) {
  const status = error instanceof ApiError ? error.status : 0;
  const title =
    status === 410
      ? 'Evidence revoked or no longer available'
      : status === 403
        ? 'This workspace cannot access these trends'
        : status === 401
          ? 'Sign in again to view trends'
          : status === 429
            ? 'Trend requests are paused'
            : status === 503
              ? 'Sources are unavailable'
              : status === 409
                ? 'This revision changed. Reload before continuing.'
                : 'Trends could not load';
  return (
    <StateMessage
      kind={status === 410 ? 'stale' : 'error'}
      title={title}
      description={
        status === 410
          ? 'Previously shown claims have been removed.'
          : status === 429
            ? 'Please check back later. Your request is paused.'
            : 'Try opening this view again when you’re ready.'
      }
      action={
        retry && ![401, 403, 410].includes(status) ? (
          <Button variant='glass' onClick={retry}>
            Try again
          </Button>
        ) : undefined
      }
    />
  );
}
export function QueryContent<T>({
  query,
  children
}: {
  query: UseQueryResult<TrendEnvelope<T>, Error>;
  children: (data: T) => ReactNode;
}) {
  if (query.isError) return <TrendError error={query.error} retry={() => void query.refetch()} />;
  if (!query.data) return <StateMessage kind='loading' title='Loading evidence…' />;
  if (query.data.execution_state === 'unavailable')
    return (
      <>
        <StateMessage
          kind='offline'
          title='Evidence is unavailable'
          description='There isn’t enough accessible evidence to show this view right now.'
        />
        {query.data.limitations.length > 0 && (
          <Disclosure title='Why this view is unavailable'>
            <ul>
              {query.data.limitations.map((limit, i) => (
                <li key={i}>{limit}</li>
              ))}
            </ul>
          </Disclosure>
        )}
      </>
    );
  return (
    <>
      {query.data.execution_state === 'collecting' && (
        <StateMessage
          kind='loading'
          title='Collecting evidence'
          description='A clearer picture is still forming. Explore what’s available so far.'
        />
      )}
      {query.data.execution_state === 'partial' && (
        <>
          <StateMessage
            kind='partial'
            title='Some coverage is missing'
            description='Some sources are missing, so this view covers only what’s available.'
          />
          {query.data.limitations.length > 0 && (
            <Disclosure title='Why this view is incomplete'>
              <ul>
                {query.data.limitations.map((limit, i) => (
                  <li key={i}>{limit}</li>
                ))}
              </ul>
            </Disclosure>
          )}
        </>
      )}
      {children(query.data.data)}
    </>
  );
}
export function CoverageDetails({
  coverage,
  limitations = []
}: {
  coverage: Coverage;
  limitations?: string[];
}) {
  return (
    <div className='trend-coverage space-y-3 text-sm'>
      <p>
        <strong>Coverage:</strong> {words(coverage.availability)} · {words(coverage.representation)}{' '}
        · {words(coverage.completeness)}
      </p>
      <p>
        <strong>Scope:</strong> {coverage.scope}
      </p>
      <p>
        <strong>Breadth:</strong> {coverage.breadth} within this scope; platform-wide prevalence is
        not established.
      </p>
      <p>Latest successful read: {date(coverage.latest_successful_read)}</p>
      <p>Freshness deadline: {date(coverage.freshness_deadline)}</p>
      <p className='text-xs'>
        Scope reference: {coverage.scope_ref} · Coverage epoch: {coverage.coverage_epoch}
      </p>
      {coverage.sources.length > 0 && (
        <ul aria-label='Source health' className='list-inside list-disc'>
          {coverage.sources.map((s) => (
            <li key={s.platform}>
              {s.platform}: {words(s.availability)}
              {s.reason && ` — ${s.reason}`}
            </li>
          ))}
        </ul>
      )}
      {limitations.length > 0 && (
        <ul aria-label='Limitations' className='list-inside list-disc'>
          {limitations.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
export function Metric({
  name,
  metric,
  advanced = false
}: {
  name: string;
  metric: TrendMetric;
  advanced?: boolean;
}) {
  return (
    <div className='trend-metric min-w-0 space-y-2 break-words'>
      <dt className='text-muted-foreground text-sm font-medium'>{words(name)}</dt>
      <dd>
        <p className='trend-metric-value'>
          {metric.value === null
            ? `Unknown — ${metric.null_reason}`
            : `${metric.value.toLocaleString()} ${metric.unit}`}
        </p>
        <p className='text-sm'>
          Window: {date(metric.window.start)} – {date(metric.window.end)} (end excluded)
        </p>
        <p className='text-sm'>Denominator: {metric.denominator ?? 'Not established'}</p>
        {advanced && (
          <p className='text-sm'>
            Definition: {metric.definition_id} / {metric.definition_version}; baseline:{' '}
            {metric.baseline_ref ?? 'None'}
          </p>
        )}
      </dd>
    </div>
  );
}
export function EvidenceList({ evidence }: { evidence: TrendEvidence[] }) {
  const allowed = evidence.filter(
    (e) => e.display_state === 'displayable' && Date.parse(e.expires_at) > Date.now()
  );
  // Re-render at the earliest evidence deadline even while the drawer remains open.
  const nextExpiry = allowed.reduce<string | null>(
    (next, e) =>
      e.display_state === 'displayable' && (!next || e.expires_at < next) ? e.expires_at : next,
    null
  );
  useExpired(nextExpiry);
  return allowed.length ? (
    <ul className='space-y-4' aria-label='Representative conversations'>
      {allowed.map(
        (e) =>
          e.display_state === 'displayable' && (
            <li key={e.id} className='trend-evidence-row'>
              <p className='text-muted-foreground text-xs'>
                {e.platform} · {date(e.observed_at)}
              </p>
              {e.excerpt && (
                <blockquote
                  lang={e.language}
                  dir='auto'
                  className='my-3 whitespace-pre-wrap text-base leading-relaxed'
                >
                  {e.excerpt}
                </blockquote>
              )}
              <SafeLink url={e.url}>Original conversation</SafeLink>
            </li>
          )
      )}
    </ul>
  ) : (
    <p className='text-sm'>
      No display-permitted conversations are available. Aggregate-only or restricted sources do not
      include representative post text.
    </p>
  );
}

/** A notice is rendered only when the service explicitly labels this payload as demonstration data. */
export function DemoNotice({ limitations }: { limitations: string[] }) {
  const notice = limitations.find((value) => value.startsWith('Demo data:'));
  return notice ? (
    <p className='trend-demo-notice' role='note'>
      <strong>Demo data</strong>
      <span>An example to explore; this isn’t live social activity.</span>
    </p>
  ) : null;
}
