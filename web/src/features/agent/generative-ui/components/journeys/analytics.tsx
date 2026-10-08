'use client';
/**
 * J06 — Analytics and content performance (lane E), from lane D's analytics bindings over the existing metric
 * definitions: per-post readings, a metric over time per account, like-for-like comparisons and the honest coverage.
 *
 * Every number shown was computed on the server. Unknown is never zero: a missing reading prints its availability
 * ("Unavailable", "Not read yet"), a bucket without readings is a gap in the chart and a dash in the table, accounts are
 * never summed across platforms, and a comparison below the minimum sample says so and never claims a cause.
 */
import { useState } from 'react';
import { z } from 'zod';
import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts';
import { ChartContainer, type ChartConfig } from '@/components/ui/chart';
import { formatCalendarDate, formatInstant, formatNumber } from '../../journeys/format';
import { useJourneyEnvironment } from '../../journeys/runtime';
import { ANALYTICS_METRICS } from '../../journeys/views';
import { Missing, Pill, QueryFrame } from './shared';
import type { JourneyRendererProps } from './types';

const tableProps = z.object({ metrics: z.array(z.enum(ANALYTICS_METRICS)).min(1).max(6).optional().nullable(), title: z.string().max(120).optional().nullable() });
const chartProps = z.object({ kind: z.enum(['line', 'bar']).optional().nullable(), title: z.string().max(120).optional().nullable() });

/** An exact server rational ("15/2") or a number, as a number; null stays null. */
export function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string') return null;
  const match = /^(-?\d+)(?:\/(\d+))?$/.exec(value.trim());
  if (!match) return null;
  const n = Number(match[1]);
  const d = match[2] ? Number(match[2]) : 1;
  return d === 0 ? null : n / d;
}

export function MetricTable({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  const literal = tableProps.safeParse(props);
  const wanted = literal.success && literal.data.metrics ? literal.data.metrics : null;
  return (
    <QueryFrame value={props.data} binding='analytics_posts' label={copy.analytics.tableTitle} title={(literal.success ? literal.data.title : null) ?? copy.analytics.tableTitle}>
      {(data) => {
        const present = new Set(data.posts.flatMap((p) => Object.keys(p.metrics)));
        const metrics = (wanted ?? ANALYTICS_METRICS.filter((m) => present.has(m))).slice(0, 6);
        return (
          <div className='flex flex-col gap-1.5'>
            <p className='text-muted-foreground text-xs'>
              {formatInstant(data.startUtc, data.timeZone, locale, null, { dateOnly: true, withZone: false })} – {formatInstant(data.endUtc, data.timeZone, locale, null, { dateOnly: true })}
              {typeof data.postsWithReadings === 'number' && typeof data.verifiedPostsInWindow === 'number'
                ? ` · ${copy.analytics.readingsOf(data.postsWithReadings, data.verifiedPostsInWindow)}`
                : ''}
            </p>
            <div className='overflow-x-auto'>
              <table className='w-full min-w-[28rem] border-collapse text-sm'>
                <caption className='sr-only'>{copy.analytics.tableTitle}</caption>
                <thead>
                  <tr className='text-muted-foreground border-b text-left text-xs'>
                    <th scope='col' className='py-1.5 pr-2 font-medium'>
                      {copy.analytics.post}
                    </th>
                    <th scope='col' className='py-1.5 pr-2 font-medium'>
                      {copy.analytics.published}
                    </th>
                    {metrics.map((m) => (
                      <th key={m} scope='col' className='py-1.5 pr-2 text-right font-medium'>
                        {copy.analytics.metric[m] ?? m}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.posts.map((post) => (
                    <tr key={post.ref} className='border-b last:border-0'>
                      <th scope='row' className='py-1.5 pr-2 text-left font-normal'>
                        {post.platform ?? post.provider ?? <Missing />}
                      </th>
                      <td className='text-muted-foreground py-1.5 pr-2 text-xs'>{formatInstant(post.publishedAt, timeZone, locale, post.publishedLocal) ?? <Missing word='noDate' />}</td>
                      {metrics.map((m) => {
                        const r = post.metrics[m];
                        const shown = r && r.availability === 'available' ? formatNumber(r.value, locale) : null;
                        return (
                          <td key={m} className='py-1.5 pr-2 text-right tabular-nums'>
                            {shown ?? <span className='text-muted-foreground text-xs italic'>{r ? copy.analytics.availability[r.availability] ?? r.availability : copy.analytics.availability.not_read}</span>}
                            {r && r.availability === 'available' && r.readOffset ? <span className='text-muted-foreground block text-[10px]'>{`${copy.analytics.readAfter} ${r.readOffset}`}</span> : null}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.undated ? <p className='text-muted-foreground text-xs'>{copy.analytics.undated(data.undated)}</p> : null}
            {data.definitionVersion ? (
              <p className='text-muted-foreground text-xs'>
                {copy.common.rule}: {data.definitionVersion}
              </p>
            ) : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

export function MetricChart({ props, statementId }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  const literal = chartProps.safeParse(props);
  const kind = literal.success && literal.data.kind ? literal.data.kind : 'line';
  const [showTable, setShowTable] = useState(false);
  return (
    <QueryFrame value={props.data} binding='analytics_series' label={copy.analytics.chartTitle} title={(literal.success ? literal.data.title : null) ?? copy.analytics.chartTitle}>
      {(data) => {
        const keys = data.series.map((s, i) => ({ key: `s${i}`, label: [s.platform ?? s.provider, s.connectionId ? `· ${s.connectionId.slice(0, 8)}` : ''].filter(Boolean).join(' ') || `#${i + 1}` }));
        const buckets = data.series[0]?.points.map((p) => p.bucket) ?? [];
        const rows = buckets.map((bucket, b) => {
          const row: Record<string, string | number | null> = { bucket: formatCalendarDate(bucket, locale) ?? bucket };
          data.series.forEach((s, i) => {
            const point = s.points[b];
            row[`s${i}`] = point && point.measured > 0 ? toNumber(point.total) : null;
          });
          return row;
        });
        const config: ChartConfig = Object.fromEntries(keys.map((k, i) => [k.key, { label: k.label, color: `var(--chart-${(i % 5) + 1})` }]));
        const metricLabel = copy.analytics.metric[data.metric] ?? data.metric;
        const tableId = `${statementId ?? 'chart'}-table`;
        return (
          <figure className='flex flex-col gap-2'>
            <figcaption className='text-muted-foreground text-xs'>
              {metricLabel} · {copy.analytics.bucket}: {data.bucket} · {copy.common.timeZone}: {data.timeZone}
            </figcaption>
            <div aria-hidden>
              <ChartContainer config={config} className='aspect-auto h-48 w-full'>
                {kind === 'bar' ? (
                  <BarChart data={rows}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey='bucket' tickLine={false} axisLine={false} />
                    <YAxis tickLine={false} axisLine={false} width={40} />
                    {keys.map((k) => (
                      <Bar key={k.key} dataKey={k.key} fill={`var(--color-${k.key})`} isAnimationActive={false} />
                    ))}
                  </BarChart>
                ) : (
                  <LineChart data={rows}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey='bucket' tickLine={false} axisLine={false} />
                    <YAxis tickLine={false} axisLine={false} width={40} />
                    {keys.map((k) => (
                      <Line key={k.key} dataKey={k.key} stroke={`var(--color-${k.key})`} connectNulls={false} dot isAnimationActive={false} />
                    ))}
                  </LineChart>
                )}
              </ChartContainer>
            </div>
            <button
              type='button'
              className='rafii-focus text-primary self-start text-xs underline-offset-4 hover:underline'
              aria-expanded={showTable}
              aria-controls={tableId}
              onClick={() => setShowTable((v) => !v)}
            >
              {showTable ? copy.analytics.hideTable : copy.analytics.showTable}
            </button>
            {/* The table is the chart's accessible alternative: always in the DOM for screen readers, shown on request. */}
            <div id={tableId} className={showTable ? 'overflow-x-auto' : 'sr-only'}>
              <table className='w-full border-collapse text-xs'>
                <caption className='sr-only'>{`${metricLabel} · ${data.bucket}`}</caption>
                <thead>
                  <tr className='text-muted-foreground border-b text-left'>
                    <th scope='col' className='py-1 pr-2 font-medium'>
                      {copy.analytics.bucket}
                    </th>
                    {keys.map((k) => (
                      <th key={k.key} scope='col' className='py-1 pr-2 text-right font-medium'>
                        {k.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {buckets.map((bucket, b) => (
                    <tr key={bucket} className='border-b last:border-0'>
                      <th scope='row' className='py-1 pr-2 text-left font-normal'>
                        {formatCalendarDate(bucket, locale) ?? bucket}
                      </th>
                      {data.series.map((s, i) => {
                        const p = s.points[b];
                        const value = p && p.measured > 0 ? formatNumber(toNumber(p.total), locale) : null;
                        return (
                          <td key={i} className='py-1 pr-2 text-right tabular-nums'>
                            {value ?? <span className='text-muted-foreground italic'>{copy.common.notMeasured}</span>}
                            {p ? <span className='text-muted-foreground block text-[10px]'>{copy.analytics.measuredOf(p.measured, p.posts)}</span> : null}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className='text-muted-foreground text-xs'>
              {copy.common.rule}: {data.rule}
              {data.definitionVersion ? ` · ${data.definitionVersion}` : ''}
            </p>
          </figure>
        );
      }}
    </QueryFrame>
  );
}

export function ComparisonSummary({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='analytics_compare' label={copy.analytics.compareTitle} title={copy.analytics.compareTitle}>
      {(data) => (
        <div className='flex flex-col gap-1.5'>
          <ul className='flex flex-col gap-1.5'>
            {data.comparisons.map((row, i) => (
              <li key={i} className='flex flex-col gap-0.5 rounded-md border p-2 text-sm'>
                <span className='flex flex-wrap items-center gap-2'>
                  <Pill tone={row.interpretation === 'observation_only' ? 'neutral' : 'muted'}>{copy.analytics.interpretation[row.interpretation] ?? row.interpretation}</Pill>
                  <span className='text-muted-foreground text-xs'>
                    {[row.cohort.provider, row.cohort.language, row.cohort.window].filter((v) => typeof v === 'string' && v).join(' · ')}
                  </span>
                </span>
                <span className='text-xs'>
                  {copy.analytics.sampleSize}: {typeof row.sampleSize === 'number' ? row.sampleSize : copy.common.unknown}
                  {typeof row.measured === 'number' ? ` · ${copy.analytics.measured}: ${row.measured}` : ''}
                  {typeof row.missing === 'number' ? ` · ${copy.analytics.missing}: ${row.missing}` : ''}
                  {row.interpretation === 'observation_only' && row.mean ? ` · ${copy.analytics.mean}: ${formatNumber(toNumber(row.mean), locale) ?? copy.common.unknown}` : ''}
                </span>
                {row.interpretation === 'insufficient_sample' && typeof row.minimum === 'number' ? <span className='text-muted-foreground text-xs'>{copy.analytics.minimum(row.minimum)}</span> : null}
                {row.reason ? <span className='text-muted-foreground text-xs'>{row.reason}</span> : null}
              </li>
            ))}
          </ul>
          <p className='text-muted-foreground text-xs'>
            {copy.analytics.notCausal}
            {data.rules?.like_for_like ? ` ${copy.common.rule}: ${data.rules.like_for_like}` : ''}
          </p>
        </div>
      )}
    </QueryFrame>
  );
}

export function CoverageNote({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='analytics_coverage' label={copy.analytics.coverageTitle} title={copy.analytics.coverageTitle}>
      {(data) => (
        <div className='flex flex-col gap-1.5'>
          <p className='text-sm' role='status'>
            <Pill tone={data.state === 'ready' ? 'good' : data.state === 'unavailable' ? 'attention' : 'waiting'}>{copy.analytics.coverageState[data.state]}</Pill>
          </p>
          <ul className='flex flex-col gap-1 text-sm'>
            {data.connections.map((c) => (
              <li key={c.connectionId} className='flex flex-wrap items-center gap-2'>
                <span>{[c.platform, c.account].filter(Boolean).join(' · ')}</span>
                <Pill tone={c.direct ? 'good' : 'muted'}>{c.direct ? copy.analytics.direct : copy.analytics.notDirect}</Pill>
                {c.direct ? <span className='text-muted-foreground text-xs'>{copy.analytics.readOf(c.readPosts, c.verifiedPosts)}</span> : null}
                {c.lastObservedAt ? (
                  <span className='text-muted-foreground text-xs'>
                    {copy.analytics.lastReading}: {formatInstant(c.lastObservedAt, timeZone, locale)}
                  </span>
                ) : null}
                {!c.direct && c.enableHref ? (
                  <a className='rafii-focus text-primary text-xs underline-offset-4 hover:underline' href={c.enableHref}>
                    {copy.analytics.enable}
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
          <p className='text-muted-foreground text-xs'>
            {copy.common.rule}: {data.rule}
          </p>
        </div>
      )}
    </QueryFrame>
  );
}

export function PostFeedback({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='post_feedback' label={copy.analytics.feedbackTitle} title={copy.analytics.feedbackTitle}>
      {(data) => (
        <div className='flex flex-col gap-1.5 text-sm'>
          <ul className='flex flex-col gap-1'>
            {data.readings.map((r, i) => {
              const horizon = typeof r.horizon === 'string' ? r.horizon : `#${i + 1}`;
              const status = typeof r.status === 'string' ? r.status : 'unknown';
              const multiple = toNumber(r.multiple);
              return (
                <li key={horizon} className='flex flex-wrap items-center gap-2'>
                  <span className='tabular-nums'>{horizon}</span>
                  <Pill tone={status === 'observed' ? 'neutral' : 'muted'}>{status.replaceAll('_', ' ')}</Pill>
                  {status === 'observed' && multiple !== null ? <span className='text-xs'>× {multiple.toFixed(2)}</span> : null}
                </li>
              );
            })}
          </ul>
          <p className='text-muted-foreground text-xs'>{copy.analytics.notCausal}</p>
        </div>
      )}
    </QueryFrame>
  );
}
