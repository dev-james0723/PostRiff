'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useAnalytics, useChannels, useSnapshot } from '@/lib/api/hooks';
import { formatDateTime, relativeTime } from '@/lib/time';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import {
  ALL_CONNECTIONS,
  STATE_LABEL,
  analyticsFamilies,
  STATE_STATUS,
  buildCoverage,
  capabilitySummary,
  coverageState,
  indexJobs,
  jobForPost,
  latestObservedAt,
  unreadVerifiedCount,
  type AnalyticsPostRow,
  type ConnectionCoverage
} from './coverage';
import { CoverageStrip } from './coverage-strip';
import { AnalyticsEmptyState, chooseEmptyKind } from './empty-states';
import { PostSheet } from './post-sheet';
import { PostsTable, type PostRowData } from './posts-table';
import { RulesCollapsible } from './rules-collapsible';

const infoContent = {
  title: 'Analytics',
  sections: [
    {
      title: 'Each platform’s own numbers',
      description: 'A “view” on Threads isn’t a “view” on Instagram. Metrics keep their native names and are never added across platforms.'
    },
    { title: 'Unavailable isn’t zero', description: 'A metric the platform hasn’t reported shows “Unavailable”. A real zero shows 0.' },
    { title: 'Rates', description: 'Every rate shows both of its numbers. Fewer than three posts is too few to compare.' },
    { title: 'When numbers update', description: 'Numbers aren’t collected automatically yet. A row shows numbers only after a reading, with the time it was read.' },
    {
      title: 'Accounts without numbers',
      description: 'Analytics is a separate permission, granted per account. Some platforms, like LinkedIn, don’t share analytics with Rafii.',
      links: [{ title: 'Channels', url: '/app/channels' }]
    }
  ]
};

function RetryState({ title, error, onRetry }: { title: string; error: unknown; onRetry: () => void }) {
  return (
    <StateMessage
      kind='error'
      title={`Couldn't load ${title}`}
      description={error instanceof Error && error.message ? error.message : undefined}
      action={
        <Button variant='glass' size='default' onClick={onRetry}>
          <Icons.refresh /> Try again
        </Button>
      }
    />
  );
}

function Dot() {
  return (
    <span aria-hidden className='text-muted-foreground/60'>
      ·
    </span>
  );
}

/** A query that has either answered or failed; either way the page stops waiting on it. */
function settled(query: { data?: unknown; error: unknown }) {
  return query.data !== undefined || query.error != null;
}

export function AnalyticsView() {
  const analytics = useAnalytics();
  const channels = useChannels();
  const snapshot = useSnapshot();
  const canManage = checkAccess(useWorkspaceAccess(), { permission: 'manage_connections' });
  const [tab, setTab] = useState<string>(ALL_CONNECTIONS);
  const [selected, setSelected] = useState<PostRowData | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const now = Date.now() / 1000;

  const data = analytics.data;
  const families = useMemo(() => analyticsFamilies(data), [data]);
  const jobs = useMemo(() => snapshot.data?.state.phase2?.jobs ?? [], [snapshot.data]);
  const coverage = useMemo(
    () =>
      buildCoverage({
        channels: channels.data?.channels ?? [],
        providers: channels.data?.providers ?? [],
        jobs,
        posts: data?.posts ?? []
      }),
    [channels.data, jobs, data?.posts]
  );
  // Posts can show once the summary is here and the account and job lists have answered or failed.
  const postsReady = Boolean(data) && settled(channels) && settled(snapshot);
  // The state chip and the empty states need every list: they are about what is missing.
  const complete = Boolean(data && channels.data && snapshot.data);
  const state = coverageState(coverage);

  // `?connection=<id>` from a draft's details or the Channels page preselects a tab, once, when the accounts are known.
  const preselected = useRef(false);
  useEffect(() => {
    if (preselected.current || !channels.data) return;
    preselected.current = true;
    const id = new URLSearchParams(window.location.search).get('connection');
    if (id && coverage.connections.some((c) => c.id === id)) setTab(id);
  }, [channels.data, coverage.connections]);

  const current = tab === ALL_CONNECTIONS ? null : (coverage.connections.find((c) => c.id === tab) ?? null);
  useEffect(() => {
    if (tab !== ALL_CONNECTIONS && channels.data && !current) setTab(ALL_CONNECTIONS);
  }, [tab, channels.data, current]);

  const allPosts = useMemo(() => [...coverage.connections.flatMap((c) => c.posts), ...coverage.unmatchedPosts], [coverage]);
  const visiblePosts: AnalyticsPostRow[] = current ? current.posts : allPosts;
  const connectionsInView = current ? [current] : coverage.connections;
  const unreadInView = unreadVerifiedCount(connectionsInView);
  const directCount = coverage.connections.filter((c) => c.direct).length;
  const latestOverall = latestObservedAt(allPosts);

  const rows = useMemo<PostRowData[]>(() => {
    const index = indexJobs(jobs);
    const connectionOf = new Map<AnalyticsPostRow, ConnectionCoverage>();
    for (const connection of coverage.connections) for (const post of connection.posts) connectionOf.set(post, connection);
    return visiblePosts.map((post) => ({
      post,
      job: jobForPost(post, index),
      connection: connectionOf.get(post) ?? null
    }));
  }, [visiblePosts, jobs, coverage.connections]);

  const open = useCallback((row: PostRowData) => {
    setSelected(row);
    setSheetOpen(true);
  }, []);

  const emptyKind = complete ? chooseEmptyKind(coverage) : null;

  const headerAction = (
    <div className='flex flex-wrap items-center gap-2'>
      {complete ? (
        <StatusChip data-tour='analytics-freshness' status={STATE_STATUS[state]}>
          {STATE_LABEL[state]}
        </StatusChip>
      ) : analytics.error || channels.error || snapshot.error ? null : (
        <Skeleton className='h-7 w-32 rounded-full' />
      )}
      {data && (
        <span className='text-muted-foreground hidden text-xs whitespace-nowrap sm:inline' title={latestOverall ? formatDateTime(latestOverall) : undefined}>
          {latestOverall ? `Last read ${relativeTime(latestOverall, now)}` : 'Not read yet'}
        </span>
      )}
    </div>
  );

  return (
    <PageContainer pageTitle='Analytics' infoContent={infoContent} pageHeaderAction={headerAction}>
      <div className='flex min-w-0 flex-col gap-6'>
        {channels.error ? (
          <RetryState title='accounts' error={channels.error} onRetry={() => channels.refetch()} />
        ) : coverage.connections.length > 0 || channels.isLoading ? (
          <CoverageStrip coverage={coverage} value={tab} onValueChange={setTab} loading={channels.isLoading} canManage={canManage} showNotes={emptyKind !== 'no-analytics-capability'} />
        ) : null}

        {analytics.error && <RetryState title='analytics' error={analytics.error} onRetry={() => analytics.refetch()} />}
        {snapshot.error && <RetryState title='published posts' error={snapshot.error} onRetry={() => snapshot.refetch()} />}

        {/* One line of numbers instead of three tiles; the latest reading time sits in the header. */}
        {postsReady ? (
          <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm' aria-label='Reading summary'>
            <span>
              <span className='text-foreground font-medium tabular-nums'>{visiblePosts.length}</span> {visiblePosts.length === 1 ? 'post' : 'posts'} read
            </span>
            {snapshot.data && unreadInView > 0 && (
              <>
                <Dot />
                <span>
                  <span className='text-foreground font-medium tabular-nums'>{unreadInView}</span> waiting for a first read
                </span>
              </>
            )}
            {channels.data && (
              <>
                <Dot />
                <span>
                  <span className='text-foreground font-medium tabular-nums'>{directCount}</span> of {coverage.connections.length} accounts reporting
                </span>
              </>
            )}
          </p>
        ) : analytics.error ? null : (
          <Skeleton className='h-5 w-64 rounded-md' aria-hidden />
        )}

        {analytics.error ? null : !postsReady ? (
          <StateMessage kind='loading' title='Loading readings…' />
        ) : emptyKind ? (
          <AnalyticsEmptyState kind={emptyKind} coverage={coverage} canManage={canManage} />
        ) : rows.length === 0 ? (
          <StateMessage
            kind='empty'
            title={current ? `No numbers for ${current.account} yet` : 'No numbers yet'}
            description={
              !current
                ? undefined
                : !current.direct
                  ? capabilitySummary(current)
                  : current.verifiedJobs.length > 0
                    ? `${current.verifiedJobs.length} ${current.verifiedJobs.length === 1 ? 'post' : 'posts'} waiting for a first read.`
                    : 'No published posts on this account yet.'
            }
          />
        ) : (
          <section className='flex min-w-0 flex-col gap-2' aria-label='Posts with readings'>
            <PostsTable rows={rows} families={families} onOpen={open} metricSort={current !== null} />
            {!current && coverage.unmatchedPosts.length > 0 && (
              <p className='text-muted-foreground text-xs'>
                {coverage.unmatchedPosts.length === 1 ? '1 post isn’t linked to an account and shows' : `${coverage.unmatchedPosts.length} posts aren’t linked to an account and show`} under All only.
              </p>
            )}
          </section>
        )}

        {data && <RulesCollapsible rules={data.rules} />}
      </div>
      <PostSheet row={selected} families={families} open={sheetOpen} onOpenChange={setSheetOpen} />
    </PageContainer>
  );
}
