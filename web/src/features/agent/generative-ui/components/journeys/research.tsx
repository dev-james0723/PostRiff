'use client';
/**
 * J07 — Research and content intelligence (lane E): whether web research may run (off is explicit, with the in-app
 * guide), the pages this answer's approved research returned, saved web sources, and a side-by-side comparison.
 *
 * Page text is quoted data from the public web, never instructions: it is shown as quoted text under an explicit label,
 * never styled as Rafii's own words. A missing publication date stays "no date"; the fetch time is labelled as such.
 * External links come only from server-checked https addresses and open in a new tab without referrer. Saving pages as
 * sources is the original drafting command (consent re-checked; nothing is fetched again).
 */
import type { ReactNode } from 'react';
import { z } from 'zod';
import { cn } from '@/lib/utils';
import { formatInstant } from '../../journeys/format';
import { useBound, useJourneyEnvironment, useSelectionRecorder } from '../../journeys/runtime';
import type { ResearchPage } from '../../journeys/views';
import { GuardedAction, Missing, Pill, QueryFrame, SelectToggle, toggleInOrder } from './shared';
import type { JourneyRendererProps } from './types';

export const MAX_SELECTED_PAGES = 6;
const SAFE_HTTPS = /^https:\/\/[A-Za-z0-9.-]{1,253}(?::\d{1,5})?(?:\/[^\s<>"'`]*)?$/;
const titleProps = z.object({ title: z.string().max(120).optional().nullable() });
const briefProps = titleProps.extend({ actionId: z.literal('research_save_sources').optional().nullable() });

/** Page indexes as the selection $variable holds them ("0".."11"), in picked order. */
function indexes(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  const out: number[] = [];
  for (const v of value) {
    const n = typeof v === 'number' ? v : typeof v === 'string' && /^\d{1,2}$/.test(v) ? Number(v) : NaN;
    if (Number.isInteger(n) && n >= 0 && n <= 11 && !out.includes(n)) out.push(n);
  }
  return out;
}

function fetchedText(value: unknown, zone: string, locale: string): string | null {
  if (typeof value === 'number') return formatInstant(new Date(value < 1e12 ? value * 1000 : value).toISOString(), zone, locale);
  if (typeof value === 'string') return formatInstant(value, zone, locale) ?? value;
  return null;
}

export function ExternalLink({ href, children }: { href: string | null | undefined; children: ReactNode }) {
  if (!href || !SAFE_HTTPS.test(href)) return <>{children}</>;
  return (
    <a className='rafii-focus text-primary underline-offset-4 hover:underline' href={href} target='_blank' rel='noopener noreferrer nofollow'>
      {children}
    </a>
  );
}

export function ResearchStatus({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='research_state' label={copy.research.statusTitle} title={copy.research.statusTitle}>
      {(data) => (
        <div className='flex flex-col gap-1 text-sm' role='status'>
          <p>
            <Pill tone={data.allowed ? 'good' : 'muted'}>{data.allowed ? copy.research.on : copy.research.off}</Pill>
          </p>
          {!data.allowed && data.reason ? <p className='text-muted-foreground text-xs'>{copy.research.reason[data.reason] ?? data.reason}</p> : null}
          {!data.allowed && data.guide?.href && data.guide.canOpen !== false ? (
            <a className='rafii-focus text-primary text-xs underline-offset-4 hover:underline' href={data.guide.href}>
              {data.guide.title ?? copy.research.openGuide}
            </a>
          ) : null}
        </div>
      )}
    </QueryFrame>
  );
}

function PageCard({ page, selected, onToggle, canPick }: { page: ResearchPage; selected?: boolean; onToggle?: () => void; canPick?: boolean }) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <article className={cn('flex flex-col gap-1 rounded-md border p-2', selected && 'ring-primary ring-2')} aria-label={page.title ?? page.host ?? `#${page.index + 1}`}>
      <div className='flex items-start gap-2'>
        {onToggle ? <SelectToggle selected={Boolean(selected)} label={page.title ?? page.host ?? `#${page.index + 1}`} disabled={!canPick && !selected} onToggle={onToggle} /> : null}
        <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
          <span className='text-sm font-medium break-words' dir='auto'>
            <span className='text-muted-foreground tabular-nums'>[{page.index + 1}] </span>
            <ExternalLink href={page.url}>{page.title ?? page.host ?? <Missing />}</ExternalLink>
          </span>
          <span className='text-muted-foreground text-xs'>
            {[
              page.host,
              page.published ? page.publishedLabel : copy.common.noDate,
              page.fetchedAt ? `${copy.research.fetched} ${fetchedText(page.fetchedAt, timeZone, locale)}` : null,
              page.urlUnsafe ? copy.research.unsafeUrl : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </div>
      </div>
      {page.facts.length > 0 ? (
        <blockquote className='border-border text-muted-foreground border-l-2 pl-2 text-xs' dir='auto'>
          <ul className='flex flex-col gap-0.5'>
            {page.facts.map((fact) => (
              <li key={fact}>“{fact}”</li>
            ))}
          </ul>
        </blockquote>
      ) : null}
    </article>
  );
}

export function ResearchBrief({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = briefProps.safeParse(props);
  const actionId = literal.success ? literal.data.actionId ?? undefined : undefined;
  const selection = useBound<string[]>(`${statementId ?? 'research'}Selected`, props.selected);
  const picked = indexes(selection.value);
  const record = useSelectionRecorder(statementId ?? 'research');
  return (
    <QueryFrame value={props.data} binding='research_results' label={copy.research.briefTitle} title={(literal.success ? literal.data.title : null) ?? copy.research.briefTitle}>
      {(data) => {
        const toggle = (page: ResearchPage) => {
          const next = toggleInOrder(picked.map(String), String(page.index), MAX_SELECTED_PAGES);
          selection.set(next);
          const byIndex = new Map(data.pages.map((p) => [String(p.index), p]));
          record(
            next.map((i) => ({ type: 'web_page', id: i, title: byIndex.get(i)?.title ?? byIndex.get(i)?.host ?? undefined })),
            data.pages.map((p) => ({ type: 'web_page', id: String(p.index) })),
          );
        };
        return (
          <div className='flex flex-col gap-2'>
            <p className='text-muted-foreground text-xs'>{data.note ?? copy.research.quoted}</p>
            <div className='flex flex-col gap-1.5'>
              {data.pages.map((page) => (
                <PageCard key={page.index} page={page} selected={picked.includes(page.index)} canPick={picked.length < MAX_SELECTED_PAGES} onToggle={() => toggle(page)} />
              ))}
            </div>
            {actionId ? (
              <GuardedAction
                actionId={actionId}
                controlId={statementId}
                ready={picked.length > 0 && picked.every((i) => data.pages.some((p) => p.index === i && p.url))}
                notReadyHint={copy.research.pickPages}
                inputs={picked.length ? { indexes: picked } : null}
              />
            ) : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

export function ComparisonMatrix({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const selection = useBound<string[]>(`${statementId ?? 'matrix'}Selected`, props.selected);
  const picked = indexes(selection.value);
  return (
    <QueryFrame value={props.data} binding='research_results' label={copy.research.matrixTitle} title={copy.research.matrixTitle}>
      {(data) => {
        const pages = picked.length >= 2 ? picked.map((i) => data.pages.find((p) => p.index === i)).filter((p): p is ResearchPage => Boolean(p)) : data.pages.slice(0, 4);
        if (pages.length < 2) return <p className='text-muted-foreground text-sm'>{copy.research.pickToCompare}</p>;
        return (
          <div className='overflow-x-auto'>
            <table className='w-full min-w-[32rem] border-collapse text-xs'>
              <caption className='sr-only'>{copy.research.matrixTitle}</caption>
              <thead>
                <tr className='border-b text-left'>
                  <th scope='col' className='text-muted-foreground py-1 pr-2 font-medium' />
                  {pages.map((p) => (
                    <th key={p.index} scope='col' className='py-1 pr-2 align-top font-medium'>
                      [{p.index + 1}] <ExternalLink href={p.url}>{p.title ?? p.host ?? ''}</ExternalLink>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className='border-b'>
                  <th scope='row' className='text-muted-foreground py-1 pr-2 text-left font-normal'>
                    {copy.research.host}
                  </th>
                  {pages.map((p) => (
                    <td key={p.index} className='py-1 pr-2'>
                      {p.host ?? <Missing />}
                    </td>
                  ))}
                </tr>
                <tr className='border-b'>
                  <th scope='row' className='text-muted-foreground py-1 pr-2 text-left font-normal'>
                    {copy.analytics.published}
                  </th>
                  {pages.map((p) => (
                    <td key={p.index} className='py-1 pr-2'>
                      {p.published ? p.publishedLabel : copy.common.noDate}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th scope='row' className='text-muted-foreground py-1 pr-2 text-left align-top font-normal'>
                    {copy.research.facts}
                  </th>
                  {pages.map((p) => (
                    <td key={p.index} className='py-1 pr-2 align-top' dir='auto'>
                      {p.facts.length ? (
                        <ul className='flex flex-col gap-0.5'>
                          {p.facts.slice(0, 6).map((f) => (
                            <li key={f}>“{f}”</li>
                          ))}
                        </ul>
                      ) : (
                        <Missing word='none' />
                      )}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
            <p className='text-muted-foreground mt-1 text-xs'>{copy.research.quoted}</p>
          </div>
        );
      }}
    </QueryFrame>
  );
}

export function SavedSources({ props }: JourneyRendererProps) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='research_sources' label={copy.research.savedTitle} title={copy.research.savedTitle}>
      {(data) => (
        <ul className='flex flex-col gap-1 text-sm'>
          {data.sources.map((s) => (
            <li key={s.ref} className='flex flex-col gap-0.5 rounded-md border p-2'>
              <span className='font-medium break-words' dir='auto'>
                <ExternalLink href={s.url}>{s.title ?? s.host ?? <Missing />}</ExternalLink>
              </span>
              <span className='text-muted-foreground text-xs'>
                {[s.host, s.publishedLabel === 'no date' ? copy.common.noDate : s.publishedLabel, s.fetchedAt ? `${copy.research.fetched} ${fetchedText(s.fetchedAt, timeZone, locale)}` : null]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
              <span className='flex flex-wrap gap-1 text-xs'>
                <span>{copy.research.factsApproved(s.approvedFacts, s.facts)}</span>
                {s.retracted ? <Pill tone='attention'>{copy.research.retracted}</Pill> : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </QueryFrame>
  );
}
