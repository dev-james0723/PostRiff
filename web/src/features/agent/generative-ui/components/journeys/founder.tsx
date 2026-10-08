'use client';
/**
 * J09 — Founder agent (lane E), founder library only (never in the consumer chunk or prompts): receipt-backed metrics,
 * AI cost by dimension, what needs attention and data-source health, from lane D's founder-scope bindings over the
 * founder console's own tools. Read-only: native privileged controls stay on their authenticated console pages.
 *
 * Absent metrics stay "Unavailable" with their reason (e.g. a definition not activated), never zero; every figure shows
 * the receipt it came from; Demo data is labelled as Demo; costs are native micro-units per row and never summed across
 * currencies or periods here.
 */
import { formatInstant, formatMicroMoney, formatNumber } from '../../journeys/format';
import { useJourneyEnvironment } from '../../journeys/runtime';
import { Missing, Pill, QueryFrame } from './shared';
import type { JourneyRendererProps } from './types';

function dims(value: Record<string, unknown> | null | undefined): string {
  if (!value) return '';
  return Object.entries(value)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`)
    .join(' · ');
}

function epochText(value: unknown, zone: string, locale: string): string | null {
  if (typeof value === 'number') return formatInstant(new Date(value < 1e12 ? value * 1000 : value).toISOString(), zone, locale);
  if (typeof value === 'string') return formatInstant(value, zone, locale) ?? value;
  return null;
}

function Receipt({ id, mode }: { id: string | null | undefined; mode: string | null | undefined }) {
  const { copy } = useJourneyEnvironment();
  return (
    <p className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
      {mode === 'demo' ? <Pill tone='muted'>{copy.founder.demo}</Pill> : null}
      {id ? (
        <span>
          {copy.founder.receipt}: <code className='text-[10px]'>{id}</code>
        </span>
      ) : null}
    </p>
  );
}

export function FounderMetricsTable({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='founder_metrics' label={copy.founder.metricsTitle} title={copy.founder.metricsTitle}>
      {(data) => (
        <div className='flex flex-col gap-1.5'>
          <div className='overflow-x-auto'>
            <table className='w-full min-w-[26rem] border-collapse text-sm'>
              <caption className='sr-only'>{copy.founder.metricsTitle}</caption>
              <tbody>
                {data.rows.map((row, i) => {
                  const unit = row.currency ? row.currency : row.unit;
                  const value =
                    typeof row.value === 'number'
                      ? row.unit === 'usd_micro' || row.unit === 'micro'
                        ? formatMicroMoney(row.value, row.currency ?? 'USD', locale)
                        : `${formatNumber(row.value, locale)}${unit && unit !== 'count' ? ` ${unit}` : ''}`
                      : null;
                  return (
                    <tr key={`${row.metricId}:${i}`} className='border-b last:border-0'>
                      <th scope='row' className='py-1.5 pr-2 text-left align-top font-normal'>
                        <span className='font-medium'>{row.metricId ?? <Missing />}</span>
                        {row.dimensions && Object.keys(row.dimensions).length ? <span className='text-muted-foreground block text-xs'>{dims(row.dimensions)}</span> : null}
                      </th>
                      <td className='py-1.5 pr-2 text-right align-top tabular-nums'>
                        {value ?? <span className='text-muted-foreground text-xs italic'>{copy.common.unavailable}</span>}
                        {row.dataState && row.dataState !== 'measured' && row.dataState !== 'available' ? (
                          <span className='text-muted-foreground block text-[10px]'>
                            {copy.founder.dataState[row.dataState] ?? row.dataState}
                            {row.reason ? ` · ${row.reason.replaceAll('_', ' ')}` : ''}
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Receipt id={data.receiptId} mode={data.mode} />
        </div>
      )}
    </QueryFrame>
  );
}

export function FounderCostBreakdown({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='founder_costs' label={copy.founder.costsTitle} title={copy.founder.costsTitle}>
      {(data) => {
        const rows = data.rows ?? data.current?.rows ?? [];
        return (
          <div className='flex flex-col gap-1.5'>
            {data.dimension ? <p className='text-muted-foreground text-xs'>{data.dimension}</p> : null}
            <ul className='flex flex-col gap-1 text-sm'>
              {rows.map((row, i) => {
                const actual = formatMicroMoney(row.actualUsdMicro ?? (row.unit === 'usd_micro' ? row.value : null), row.currency ?? 'USD', locale);
                const estimated = formatMicroMoney(row.estimatedUsdMicro, row.currency ?? 'USD', locale);
                return (
                  <li key={i} className='flex flex-wrap items-baseline justify-between gap-2 border-b pb-1 last:border-0'>
                    <span>{dims(row.dimensions) || <Missing />}</span>
                    <span className='text-right tabular-nums'>
                      {actual ? (
                        <span>
                          {copy.founder.actual}: {actual}
                        </span>
                      ) : (
                        <span className='text-muted-foreground text-xs italic'>
                          {copy.founder.actual}: {copy.common.unavailable}
                        </span>
                      )}
                      {estimated ? (
                        <span className='text-muted-foreground block text-xs'>
                          {copy.founder.estimated}: {estimated}
                        </span>
                      ) : null}
                      {row.costState ? (
                        <span className='text-muted-foreground block text-[10px]'>
                          {copy.founder.costState}: {row.costState}
                        </span>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
            {data.previous ? (
              <p className='text-muted-foreground text-xs'>
                {copy.founder.previous}: {copy.founder.dataState[data.previous.dataState ?? ''] ?? data.previous.dataState ?? copy.common.unknown}
                {data.previous.reason ? ` · ${data.previous.reason.replaceAll('_', ' ')}` : ''}
              </p>
            ) : null}
            <Receipt id={data.receiptId ?? data.current?.receiptId} mode={data.mode} />
          </div>
        );
      }}
    </QueryFrame>
  );
}

export function FounderAttentionList({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='founder_attention' label={copy.founder.attentionTitle} title={copy.founder.attentionTitle}>
      {(data) => (
        <ul className='flex flex-col gap-1.5 text-sm'>
          {data.items.map((item, i) => (
            <li key={item.id ?? i} className='flex flex-wrap items-center gap-2'>
              {item.severity ? (
                <Pill tone={item.severity === 'critical' ? 'attention' : item.severity === 'warning' ? 'waiting' : 'muted'}>{copy.founder.severity[item.severity] ?? item.severity}</Pill>
              ) : null}
              {item.href && item.href.startsWith('/') ? (
                <a className='rafii-focus text-primary underline-offset-4 hover:underline' href={item.href}>
                  {item.title ?? item.id}
                </a>
              ) : (
                <span>{item.title ?? item.id}</span>
              )}
              {typeof item.count === 'number' ? <span className='text-muted-foreground text-xs tabular-nums'>{formatNumber(item.count, locale)}</span> : null}
              {item.since ? (
                <span className='text-muted-foreground text-xs'>
                  {copy.founder.since} {epochText(item.since, timeZone, locale)}
                </span>
              ) : null}
            </li>
          ))}
          {data.mode === 'demo' ? <li><Pill tone='muted'>{copy.founder.demo}</Pill></li> : null}
        </ul>
      )}
    </QueryFrame>
  );
}

export function FounderSourceHealth({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='founder_sources' label={copy.founder.sourcesTitle} title={copy.founder.sourcesTitle}>
      {(data) => (
        <ul className='flex flex-col gap-1 text-sm'>
          {data.sources.map((s, i) => (
            <li key={s.sourceId ?? i} className='flex flex-wrap items-center gap-2'>
              <span>{s.label ?? s.sourceId ?? <Missing />}</span>
              <Pill tone={s.state === 'measured' ? 'good' : s.state === 'stale' ? 'waiting' : 'attention'}>{copy.founder.dataState[s.state ?? ''] ?? s.state ?? copy.common.unknown}</Pill>
              {s.lastGoodAt ? (
                <span className='text-muted-foreground text-xs'>
                  {copy.founder.lastGood}: {epochText(s.lastGoodAt, timeZone, locale)}
                </span>
              ) : null}
              {s.reasonCode ? <span className='text-muted-foreground text-xs'>{s.reasonCode.replaceAll('_', ' ')}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </QueryFrame>
  );
}

export function FounderNote({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const text = typeof props.text === 'string' && props.text.length > 0 && props.text.length <= 600 ? props.text : null;
  if (!text) return null;
  return (
    <aside aria-label={copy.common.rafiiNote} className='border-border/70 flex flex-col gap-0.5 border-l-2 pl-3'>
      <span className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>{copy.common.rafiiNote}</span>
      <p className='text-muted-foreground text-sm text-pretty' dir='auto'>
        {text}
      </p>
    </aside>
  );
}
