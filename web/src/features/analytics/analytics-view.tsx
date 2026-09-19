'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StatCard } from '@/components/app/stat-card';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Tooltip } from '@/components/motion/tooltip';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTableSkeleton } from '@/components/ui/table/data-table-skeleton';
import { ApiError } from '@/lib/api/client';
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
  title: 'Native numbers, side by side',
  sections: [
    {
      title: 'Each provider keeps its own definitions',
      description:
        'A “view” on Threads is not a “view” on Instagram. Metrics are shown with their native names and never added across platforms.'
    },
    {
      title: 'Unavailable is not zero',
      description:
        'When a provider has not reported a metric, PostRiff shows “Unavailable”. A real zero is shown as 0.'
    },
    {
      title: 'Rates carry their denominator',
      description:
        'Every rate shows numerator and denominator; fewer than three posts is an insufficient sample.'
    },
    {
      title: 'When PostRiff reads',
      description:
        'A reading happens when PostRiff’s worker asks the provider for a post’s insights after the provider verifies the publication. There is no fixed schedule yet, so no “next read” time is shown; each row carries the time of its own reading.'
    },
    {
      title: 'Why some accounts have no numbers',
      description:
        'Analytics is a separate permission from publishing, granted per account. Some providers do not offer insights to this app at all — LinkedIn’s official API is one — and those accounts stay Unsupported rather than “coming soon”.',
      links: [{ title: 'Channels', url: '/app/channels' }]
    }
  ]
};

const REFRESH_NOTE =
  'Refresh arrives with scheduled readings. Nothing on this page is live; each row carries the time of its own reading.';

function errorMessage(error: unknown, what: string) {
  if (error instanceof ApiError) return `${what} could not be read (HTTP ${error.status}).`;
  return `${what} could not be read.`;
}

function RetryAlert({
  title,
  error,
  onRetry
}: {
  title: string;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <Alert variant='destructive'>
      <Icons.alertCircle />
      <AlertTitle>{errorMessage(error, title)}</AlertTitle>
      <AlertDescription>
        {error instanceof Error && error.message ? error.message : 'Try again in a moment.'}
      </AlertDescription>
      <AlertAction>
        <Button variant='outline' size='xs' onClick={onRetry}>
          Retry
        </Button>
      </AlertAction>
    </Alert>
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
  // The state badge and the empty states need every list: they are about what is missing.
  const complete = Boolean(data && channels.data && snapshot.data);
  const state = coverageState(coverage);

  // `?connection=<id>` from the Pipeline or Channels pages preselects a tab, once, when the accounts are known.
  const preselected = useRef(false);
  useEffect(() => {
    if (preselected.current || !channels.data) return;
    preselected.current = true;
    const id = new URLSearchParams(window.location.search).get('connection');
    if (id && coverage.connections.some((c) => c.id === id)) setTab(id);
  }, [channels.data, coverage.connections]);

  const current =
    tab === ALL_CONNECTIONS ? null : (coverage.connections.find((c) => c.id === tab) ?? null);
  useEffect(() => {
    if (tab !== ALL_CONNECTIONS && channels.data && !current) setTab(ALL_CONNECTIONS);
  }, [tab, channels.data, current]);

  const allPosts = useMemo(
    () => [...coverage.connections.flatMap((c) => c.posts), ...coverage.unmatchedPosts],
    [coverage]
  );
  const visiblePosts: AnalyticsPostRow[] = current ? current.posts : allPosts;
  const connectionsInView = current ? [current] : coverage.connections;
  const verifiedInView = connectionsInView.reduce((n, c) => n + c.verifiedJobs.length, 0);
  const unreadInView = unreadVerifiedCount(connectionsInView);
  const directCount = coverage.connections.filter((c) => c.direct).length;
  const latest = latestObservedAt(visiblePosts);
  const latestOverall = latestObservedAt(allPosts);

  const rows = useMemo<PostRowData[]>(() => {
    const index = indexJobs(jobs);
    const connectionOf = new Map<AnalyticsPostRow, ConnectionCoverage>();
    for (const connection of coverage.connections)
      for (const post of connection.posts) connectionOf.set(post, connection);
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
    <div className='flex flex-col items-end gap-1.5 sm:flex-row sm:items-center sm:gap-2'>
      {complete ? (
        <AnimatedBadge data-tour='analytics-freshness' status={STATE_STATUS[state]} size='sm'>
          {STATE_LABEL[state]}
        </AnimatedBadge>
      ) : analytics.error || channels.error || snapshot.error ? null : (
        <Skeleton className='h-6 w-32' />
      )}
      {data && (
        <span
          className='text-muted-foreground hidden text-xs whitespace-nowrap sm:inline'
          title={latestOverall ? formatDateTime(latestOverall) : undefined}
        >
          {latestOverall ? `Last read ${relativeTime(latestOverall, now)}` : 'No reading yet'}
        </span>
      )}
      <Tooltip content={REFRESH_NOTE} side='bottom'>
        <Button
          variant='outline'
          size='sm'
          disabled
          aria-label='Refresh (arrives with scheduled readings)'
        >
          <Icons.refresh />
          Refresh
        </Button>
      </Tooltip>
    </div>
  );

  return (
    <PageContainer
      pageTitle='Analytics'
      pageDescription='Post performance from providers that report it, with their own definitions.'
      infoContent={infoContent}
      pageHeaderAction={headerAction}
    >
      <div className='flex min-w-0 flex-col gap-6'>
        {channels.error ? (
          <RetryAlert title='Accounts' error={channels.error} onRetry={() => channels.refetch()} />
        ) : coverage.connections.length > 0 || channels.isLoading ? (
          <CoverageStrip
            coverage={coverage}
            value={tab}
            onValueChange={setTab}
            loading={channels.isLoading}
            canManage={canManage}
            showNotes={emptyKind !== 'no-analytics-capability'}
          />
        ) : null}

        {analytics.error && (
          <RetryAlert
            title='Analytics'
            error={analytics.error}
            onRetry={() => analytics.refetch()}
          />
        )}
        {snapshot.error && (
          <RetryAlert
            title='Published posts'
            error={snapshot.error}
            onRetry={() => snapshot.refetch()}
          />
        )}

        <section className='flex flex-col gap-2'>
          <div className='grid gap-4 sm:grid-cols-3'>
            <StatCard
              label='Posts read'
              value={postsReady ? visiblePosts.length : '—'}
              loading={!postsReady && !analytics.error}
              hint={postsReady && snapshot.data ? `of ${verifiedInView} verified` : undefined}
              footer={analytics.error ? 'Unavailable' : 'Posts with at least one reading'}
            />
            <StatCard
              label='Latest read'
              value={data ? (latest ? relativeTime(latest, now) : '—') : '—'}
              loading={analytics.isLoading}
              hint={latest ? formatDateTime(latest) : data ? 'No reading yet' : undefined}
              footer={analytics.error ? 'Unavailable' : 'Each row carries its own reading time'}
            />
            <StatCard
              label='Accounts reporting'
              value={channels.data ? directCount : '—'}
              loading={channels.isLoading}
              hint={channels.data ? `of ${coverage.connections.length} connected` : undefined}
              footer={channels.error ? 'Unavailable' : 'Direct analytics only'}
            />
          </div>
          <p className='text-muted-foreground text-xs'>
            There is no “next reading” time: PostRiff does not schedule readings yet. {REFRESH_NOTE}
          </p>
        </section>

        {analytics.error ? null : !postsReady ? (
          <DataTableSkeleton
            columnCount={6}
            rowCount={3}
            withViewOptions={false}
            withPagination={false}
            filterCount={0}
          />
        ) : emptyKind ? (
          <AnalyticsEmptyState kind={emptyKind} coverage={coverage} canManage={canManage} />
        ) : rows.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <Icons.trendingUp />
              </EmptyMedia>
              <EmptyTitle>
                {current ? `No readings for ${current.account} yet` : 'No readings to show'}
              </EmptyTitle>
              <EmptyDescription>
                {!current
                  ? 'The summary has no posts with a reading.'
                  : !current.direct
                    ? capabilitySummary(current)
                    : current.verifiedJobs.length > 0
                      ? `${current.verifiedJobs.length} verified ${current.verifiedJobs.length === 1 ? 'post is' : 'posts are'} waiting for a first reading.`
                      : 'Nothing published through PostRiff on this account has been verified yet.'}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <section className='flex min-w-0 flex-col gap-2'>
            <PostsTable
              rows={rows}
              families={families}
              onOpen={open}
              metricSort={current !== null}
            />
            {unreadInView > 0 && (
              <p className='text-muted-foreground text-xs'>
                {unreadInView === 1
                  ? 'One verified post has'
                  : `${unreadInView} verified posts have`}{' '}
                no reading yet and {unreadInView === 1 ? 'is' : 'are'} not listed.
              </p>
            )}
            {!current && coverage.unmatchedPosts.length > 0 && (
              <p className='text-muted-foreground text-xs'>
                {coverage.unmatchedPosts.length === 1
                  ? 'One post'
                  : `${coverage.unmatchedPosts.length} posts`}{' '}
                could not be matched to a connected account, so{' '}
                {coverage.unmatchedPosts.length === 1 ? 'it appears' : 'they appear'} under All
                only.
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
