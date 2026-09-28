'use client';
import { useEffect, useId, useRef } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Surface, StateMessage } from '@/components/rafii';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { TrendOpportunity } from '@/lib/coworker/trend-types';
import { useExpired, useTrendContext } from './hooks';
import { OpportunityCard } from './opportunity-card';
import { exposurePage, useOpportunityExposure, type ExposurePage } from './opportunity-exposure';
import { QueryContent } from './present';
import './trends.css';

type Pool = 'home' | 'weekly';

/** Qualification, cooldown and ordering belong to the server's exact signed page. */
export function WorkspaceOpportunityPreview({ pool }: { pool: Pool }) {
  const context = useTrendContext();
  if (!context.enabled || context.flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED !== true) return null;
  return <OpportunityPool key={`${context.w}:${pool}`} pool={pool} />;
}

function OpportunityPool({ pool }: { pool: Pool }) {
  const { api, w } = useTrendContext();
  const snapshot = useSnapshot();
  const deliveredIds = useRef(new Set<string>());
  const heading = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focused = useRef<HTMLElement | null>(null);
  const query = useQuery({
    queryKey: ['trends', w, 'opportunities', 'pool', pool],
    queryFn: ({ signal }) => api.opportunityPool(w, pool, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: 'always'
    // Refresh on entry, focus and existing accept/dismiss invalidations. Polling would
    // discard an open form merely because its own visible exposure started cooldown.
  });
  useEffect(() => {
    for (const op of query.data?.data ?? []) deliveredIds.current.add(op.id);
    // A successful decision removes a pool card. Keep keyboard focus in this section.
    if (
      focused.current &&
      !focused.current.isConnected &&
      document.activeElement === document.body
    ) {
      headingRef.current?.focus({ preventScroll: true });
      focused.current = null;
    }
  }, [query.data]);
  const savedSources = snapshot.isError
    ? []
    : (snapshot.data?.state.sources ?? []).filter((source) => {
        const origin = source.origin;
        if (!source.active || origin?.kind !== 'trend_opportunity' || !('trendLineage' in origin))
          return false;
        const lineage = origin.trendLineage;
        return (
          lineage !== null &&
          typeof lineage === 'object' &&
          'opportunity_id' in lineage &&
          typeof lineage.opportunity_id === 'string' &&
          deliveredIds.current.has(lineage.opportunity_id)
        );
      });
  const page = exposurePage(query.data?.exposure_token, query.data?.data ?? []);
  return (
    <Surface
      as='section'
      material='quiet'
      padding='md'
      className='trend-radar min-w-0 space-y-4'
      aria-labelledby={heading}
      data-trend-pool={pool}
      onFocusCapture={(event) => {
        focused.current = event.target as HTMLElement;
      }}
      onBlurCapture={(event) => {
        if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node))
          focused.current = null;
      }}
    >
      <header className='flex flex-wrap items-center justify-between gap-2'>
        <h2
          id={heading}
          ref={headingRef}
          tabIndex={-1}
          className='rafii-focus text-base font-semibold'
        >
          {pool === 'home' ? 'Conversations to explore' : 'Ideas for this week'}
        </h2>
        <Link
          href='/app/trends'
          className='rafii-focus inline-flex min-h-11 items-center rounded-sm text-sm underline underline-offset-4'
        >
          Open Trend Radar
        </Link>
      </header>
      {pool === 'weekly' && (
        <p className='text-muted-foreground text-sm'>
          Explore an angle alongside your plan. Your planned posts stay in place.
        </p>
      )}
      {pool === 'weekly' &&
        savedSources.map((source) => (
          <p key={source.id} role='status' className='text-sm'>
            Saved to Ideas.{' '}
            <Link
              className='rafii-focus inline-flex min-h-11 items-center rounded-sm underline underline-offset-4'
              href={`/app/ideas?source=${encodeURIComponent(source.id)}`}
            >
              Review source and create original post
            </Link>
          </p>
        ))}
      <QueryContent query={query}>
        {(items) =>
          items.length === 0 ? (
            <StateMessage
              kind='empty'
              layout='inline'
              title={
                pool === 'home'
                  ? 'No fresh conversations to suggest right now.'
                  : 'No fresh opportunities for this week.'
              }
              description='New suggestions appear when current evidence supports them.'
            />
          ) : (
            <ul className='grid min-w-0 gap-4' aria-labelledby={heading}>
              {items.map((op) => (
                <li
                  key={`${op.id}:${op.revision}`}
                  className='min-w-0'
                  data-pool-opportunity={op.id}
                >
                  {pool === 'home' ? (
                    <HomeOpportunity opportunity={op} page={page} />
                  ) : (
                    <OpportunityCard opportunity={op} exposurePage={page} />
                  )}
                </li>
              ))}
            </ul>
          )
        }
      </QueryContent>
    </Surface>
  );
}

function HomeOpportunity({
  opportunity: op,
  page
}: {
  opportunity: TrendOpportunity;
  page: ExposurePage;
}) {
  const { api, w, enabled, flags } = useTrendContext();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const expired = useExpired(op.expires_at);
  const current =
    !expired && op.verification_state === 'verified' && ['candidate', 'ready'].includes(op.state);
  const exposure = useOpportunityExposure(
    api,
    w,
    op,
    page,
    current && enabled && canEdit && flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED === true
  );
  if (!current)
    return (
      <StateMessage
        kind='stale'
        layout='inline'
        title='This conversation needs a fresh evidence check.'
      />
    );
  return (
    <article data-trend-opportunity className='min-w-0 space-y-2 text-sm'>
      <h3 ref={exposure.anchorRef} className='text-base font-medium' dir='auto'>
        {op.title}
      </h3>
      <p dir='auto'>{op.contribution}</p>
      <p className='text-muted-foreground' dir='auto'>
        Keep in mind: {op.uncertainty}
      </p>
    </article>
  );
}
