'use client';

import { providerReadinessLabel } from '@/lib/channels/onboarding';

import { publishingSupport } from '@/lib/channels/publishing-support';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Tabs, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { HoverLiftGroup } from '@/components/ui/hover-lift-group';
import { Skeleton } from '@/components/ui/skeleton';
import { localChannels } from '@/config/channels';
import { useChannels, useSnapshot, useUsage } from '@/lib/api/hooks';
import type { ProviderView } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { capabilityLabel } from '@/lib/channels/capabilities';
import {
  channelCounts,
  CONNECT_CAPABILITIES,
  matchesFilter,
  nowSeconds,
  parseChannelFilter,
  sortForAttention,
  type ChannelFilter
} from '@/lib/channels/state';
import { EASE_OUT } from '@/lib/ease';
import { cn } from '@/lib/utils';
import { ChannelCard, type ChannelActivity } from './channel-card';
import { ChannelsSummary } from './channels-summary';
import { ConnectSheet, type ConnectRequest } from './connect-sheet';

const PAGE_DESCRIPTION = 'Each capability is verified on its own. A connected account is not the same as a publishable one.';

const infoContent = {
  title: 'Each capability, verified on its own',
  sections: [
    {
      title: 'A connection is not a permission',
      description:
        'Identity, publishing, scheduling, analytics and comments are separate grants. The card shows the level PostRiff has actually verified for each — never a blended “Ready”.'
    },
    {
      title: 'Direct · Assisted · Unsupported',
      description:
        'Direct: PostRiff acts through the official API after your approval. Assisted: PostRiff prepares the post and you complete the last step (for example while provider review is pending). Unsupported: not offered for this provider yet.'
    },
    {
      title: 'What Re-verify checks',
      description:
        'Re-verify asks the provider, right now, whether the stored token still identifies the same account and still carries the scopes it was granted. It reports what it found; it does not renew anything.'
    },
    {
      title: 'Reconnecting sends you to the provider again',
      description:
        'A reconnect repeats the grant for the same account. Sign in as that account when the provider asks; a different account becomes a new card and the old one still needs reconnecting.'
    },
    {
      title: 'Disconnecting',
      description: 'Stored tokens are wiped and revoked remotely where the provider supports it. Approved jobs for that account are held.'
    }
  ]
};

/** Job states the Queue treats as waiting to publish (`queue-view.tsx`). */
const WAITING_STATES = new Set(['scheduled', 'approved', 'claimed']);

const FILTER_LABELS: Record<ChannelFilter, string> = {
  all: 'All',
  attention: 'Needs attention',
  direct: 'Direct',
  assisted: 'Assisted',
  local: 'Local'
};

function ChannelsSkeleton() {
  return (
    <div className='flex flex-col gap-8' aria-busy>
      <Skeleton className='h-5 w-64' />
      <div className='grid gap-4 xl:grid-cols-2'>
        <Skeleton className='h-56 w-full rounded-xl' />
        <Skeleton className='h-56 w-full rounded-xl' />
      </div>
      <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
        <Skeleton className='h-32 w-full rounded-lg' />
        <Skeleton className='h-32 w-full rounded-lg' />
        <Skeleton className='h-32 w-full rounded-lg' />
      </div>
    </div>
  );
}

function ProviderTile({
  provider,
  alreadyConnected,
  canManage,
  onConnect
}: {
  provider: ProviderView;
  alreadyConnected: boolean;
  canManage: boolean;
  onConnect: () => void;
}) {
  const offered = CONNECT_CAPABILITIES.filter((key) => provider.capabilities[key] === true);
  return (
    <div className='flex h-full flex-col gap-3 rounded-lg border p-4'>
      <div className='flex items-start justify-between gap-2'>
        <div className='flex min-w-0 items-center gap-2'>
          <ChannelIcon platform={provider.platform} name={provider.platform} size='md' />
          <span className='truncate font-medium'>{provider.platform}</span>
        </div>
        <CapabilityBadge
          level={!provider.executionPaused && provider.productionReviewed ? 'direct' : 'assisted'}
          label={providerReadinessLabel(provider)}
        />
      </div>
      <p className='text-muted-foreground text-xs'>
        {provider.configured === false ? 'This provider is not ready for OAuth. Correct the presence-only configuration issues below; credentials never belong in the browser.' : provider.executionPaused ? 'This connector is temporarily paused. Existing drafts and receipts remain available.' : provider.productionReviewed
          ? 'Direct candidate: confirm this account’s permissions and supported format before scheduling. App configuration is not proof of a verified publication.'
          : 'Platform review has not been confirmed. Eligible developer/test accounts may connect; public-user access, history and publishing remain separately checked.'}
      </p>
      <p className='text-muted-foreground text-xs'>{provider.accountRequirement}</p>
      {provider.setupIssues?.map((issue) => <p key={issue} role='status' className='text-destructive break-words text-xs'>{issue}</p>)}
      {provider.callbackUri && provider.connectReady === false && <p className='text-muted-foreground break-all text-xs'>Callback: <code>{provider.callbackUri}</code></p>}
      <p className='text-muted-foreground text-xs'>{publishingSupport(provider.platform)}</p>
      {offered.length > 0 && (
        <ul className='flex flex-wrap gap-1' aria-label='Capabilities you can request'>
          {offered.map((key) => (
            <li key={key} className='bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-[11px]'>
              {capabilityLabel(key)}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <div className='mt-auto'>
          <Button variant={alreadyConnected ? 'outline' : 'default'} size='sm' disabled={provider.connectReady === false || provider.executionPaused} onClick={onConnect}>
            <Icons.add className='size-3.5' />
            {alreadyConnected ? 'Connect another account' : 'Connect'}
          </Button>
        </div>
      )}
    </div>
  );
}

function CompanionDirectory() {
  return (
    // transitions.dev avatar group hover: the hovered chip lifts and its neighbours follow.
    <HoverLiftGroup className='flex flex-wrap gap-2'>
      {localChannels.map((channel) => (
        <Link
          key={channel.slug}
          href={`/channels/${channel.slug}`}
          className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'gap-1.5')}
        >
          <ChannelIcon slug={channel.slug} name={channel.name} size='xs' />
          {channel.name}
          {channel.nameZh && <span className='text-muted-foreground'>{channel.nameZh}</span>}
        </Link>
      ))}
    </HoverLiftGroup>
  );
}

const COMPANION_SENTENCE =
  'These platforms have no third-party publishing API a small studio can use honestly. The companion will sign in on your own machine and publish through your own session — never from our servers. It is not available yet; this page will say so until it is.';

function ChannelsPage() {
  const channelsQuery = useChannels();
  const usage = useUsage();
  const snapshot = useSnapshot();
  const access = useWorkspaceAccess();
  const reduce = useReducedMotion();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const canManage = checkAccess(access, { permission: 'manage_connections' });

  const { data, isLoading, isFetching, error, refetch } = channelsQuery;
  const channels = useMemo(() => data?.channels ?? [], [data]);
  const providers = useMemo(() => data?.providers ?? [], [data]);
  const filter = parseChannelFilter(params.get('filter'));
  const connectedParam = params.get('connected');

  const [connectRequest, setConnectRequest] = useState<ConnectRequest | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [companionOpen, setCompanionOpen] = useState<boolean | null>(null);

  // Per-account job counts from the snapshot. `channelId` is on the API manifest but not yet in the TS type.
  const activityByChannel = useMemo(() => {
    const map: Record<string, ChannelActivity> = {};
    for (const job of snapshot.data?.state.phase2?.jobs ?? []) {
      const channelId = (job.manifest as { channelId?: string }).channelId;
      if (!channelId) continue;
      const entry = (map[channelId] ??= { scheduled: 0, held: 0, published: 0 });
      if (WAITING_STATES.has(job.state)) entry.scheduled += 1;
      else if (job.state === 'held') entry.held += 1;
      else if (job.state === 'published') entry.published += 1;
    }
    return map;
  }, [snapshot.data]);
  const heldByChannel = useMemo(
    () => Object.fromEntries(Object.entries(activityByChannel).map(([id, activity]) => [id, activity.held])),
    [activityByChannel]
  );

  const now = nowSeconds();
  const counts = channelCounts(channels, now, heldByChannel);
  const sorted = useMemo(() => sortForAttention(channels, now, heldByChannel), [channels, now, heldByChannel]);
  const visible = sorted.filter((channel) => matchesFilter(channel, filter, now, heldByChannel[channel.id] ?? 0));
  const connectedPlatforms = useMemo(() => new Set(channels.map((channel) => channel.platform)), [channels]);

  const replaceParams = useCallback(
    (mutate: (next: URLSearchParams) => void) => {
      const next = new URLSearchParams(params.toString());
      mutate(next);
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [params, pathname, router]
  );

  const setFilter = useCallback(
    (value: string) => {
      const next = parseChannelFilter(value);
      replaceParams((search) => {
        if (next === 'all') search.delete('filter');
        else search.set('filter', next);
      });
    },
    [replaceParams]
  );

  // The provider's return lands here with `?connected=<id>`: scroll to that card, play the check once, clear the param.
  useEffect(() => {
    if (!connectedParam || !data) return;
    const exists = channels.some((channel) => channel.id === connectedParam);
    if (!exists && isFetching) return; // the list is still catching up with the exchange
    if (exists) {
      setHighlightId(connectedParam);
      window.requestAnimationFrame(() => {
        document.getElementById(`channel-${connectedParam}`)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
      });
    }
    replaceParams((search) => search.delete('connected'));
  }, [channels, connectedParam, data, isFetching, reduce, replaceParams]);

  const openConnect = useCallback(
    (request: ConnectRequest) => {
      if (!canManage) return;
      setConnectRequest(request);
      setConnectOpen(true);
    },
    [canManage]
  );

  // Deep link from other pages (Analytics "Enable analytics"): `?connect=<provider>&capability=<cap>`
  // opens the sheet preselected, once the provider list is known, then clears both params.
  const connectParam = params.get('connect');
  const capabilityParam = params.get('capability');
  useEffect(() => {
    if (!connectParam || !data) return;
    if (canManage && providers.some((provider) => provider.id === connectParam)) {
      const capability = CONNECT_CAPABILITIES.find((value) => value === capabilityParam);
      openConnect({ providerId: connectParam, capability });
    }
    replaceParams((search) => {
      search.delete('connect');
      search.delete('capability');
    });
  }, [canManage, capabilityParam, connectParam, data, openConnect, providers, replaceParams]);

  const companionExpanded = companionOpen ?? (data ? counts.connected === 0 : false);
  const errorMessage = error instanceof Error ? error.message : 'Channels could not be loaded.';

  const headerAction = canManage ? (
    <Button data-tour='channels-connect' onClick={() => openConnect({})} aria-label='Connect an account'>
      <Icons.add className='size-4' />
      <span className='sr-only sm:not-sr-only'>Connect</span>
    </Button>
  ) : (
    <p className='text-muted-foreground text-xs'>Ask an owner or admin to connect accounts</p>
  );

  return (
    <PageContainer pageTitle='Channels' pageDescription={PAGE_DESCRIPTION} infoContent={infoContent} pageHeaderAction={headerAction}>
      {isLoading ? (
        <ChannelsSkeleton />
      ) : (
        <div className='flex flex-col gap-8'>
          {error ? (
            <Alert variant='destructive'>
              <Icons.alertCircle className='size-4' />
              <AlertTitle>Channels could not be loaded</AlertTitle>
              <AlertDescription>{errorMessage}</AlertDescription>
              <AlertAction>
                <Button size='sm' variant='outline' onClick={() => void refetch()}>
                  Retry
                </Button>
              </AlertAction>
            </Alert>
          ) : (
            <>
              <ChannelsSummary
                counts={counts}
                providersCount={providers.filter((provider) => provider.connectReady !== false).length}
                usage={usage.data}
                data-tour='channels-summary'
              />

              <section className='flex flex-col gap-4' aria-labelledby='connected-heading'>
                <div className='flex flex-wrap items-center justify-between gap-3'>
                  <h3 id='connected-heading' className='text-lg font-semibold'>
                    Connected accounts
                  </h3>
                  <Tabs value={filter} onValueChange={setFilter} variant='pill' className='min-w-0 max-w-full'>
                    <TabsList aria-label='Filter accounts' data-tour='channels-filter' className='max-w-full overflow-x-auto'>
                      {(Object.keys(FILTER_LABELS) as ChannelFilter[]).map((key) => (
                        <TabsTrigger key={key} value={key} className='gap-1.5'>
                          {FILTER_LABELS[key]}
                          <DigitSwap
                            value={key === 'local' ? localChannels.length : counts[key === 'all' ? 'all' : key]}
                            className='opacity-70'
                          />
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </Tabs>
                </div>

                {filter === 'local' ? (
                  <div className='flex flex-col gap-3'>
                    <p className='text-muted-foreground text-sm'>{COMPANION_SENTENCE}</p>
                    <CompanionDirectory />
                  </div>
                ) : channels.length === 0 ? (
                  <Empty data-tour='channels-empty'>
                    <EmptyHeader>
                      <EmptyMedia variant='icon'>
                        <Icons.broadcast />
                      </EmptyMedia>
                      <EmptyTitle>No accounts connected</EmptyTitle>
                      <EmptyDescription>
                        You can draft and export without connecting anything. Connect an account when you want previews, scheduling, analytics or comments for it — each capability is verified on its own.
                      </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                      {canManage ? (
                        <Button onClick={() => openConnect({})}>
                          <Icons.add className='size-4' />
                          Connect an account
                        </Button>
                      ) : (
                        <p className='text-muted-foreground text-xs'>Ask an owner or admin to connect accounts</p>
                      )}
                    </EmptyContent>
                  </Empty>
                ) : visible.length === 0 ? (
                  <Empty>
                    <EmptyHeader>
                      <EmptyMedia variant='icon'>{filter === 'attention' ? <Icons.circleCheck /> : <Icons.broadcast />}</EmptyMedia>
                      <EmptyTitle>{filter === 'attention' ? 'Nothing needs attention' : `No ${FILTER_LABELS[filter].toLowerCase()} accounts`}</EmptyTitle>
                      <EmptyDescription>
                        {filter === 'attention'
                          ? 'Tokens are checked when a post is claimed and when you re-verify.'
                          : 'No connected account publishes at this level right now.'}
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                ) : (
                  <div className='grid gap-4 xl:grid-cols-2'>
                    <AnimatePresence initial={false} mode='popLayout'>
                      {visible.map((channel, index) => (
                        <motion.div
                          key={channel.id}
                          layout={!reduce}
                          initial={reduce ? { opacity: 1 } : { opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6 }}
                          transition={{ duration: reduce ? 0 : 0.18, ease: EASE_OUT, delay: reduce ? 0 : Math.min(index, 3) * 0.04 }}
                        >
                          <ChannelCard
                            channel={channel}
                            provider={providers.find((provider) => provider.platform === channel.platform)}
                            canManage={canManage}
                            activity={activityByChannel[channel.id] ?? null}
                            highlight={highlightId === channel.id}
                            tour={index === 0}
                            onReconnect={openConnect}
                          />
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                )}
              </section>
            </>
          )}

          <section className='flex flex-col gap-4' aria-labelledby='providers-heading'>
            <div>
              <h3 id='providers-heading' className='text-lg font-semibold'>
                Connect
              </h3>
              <p className='text-muted-foreground text-sm'>
                Hosted connectors use the provider’s official API. Each one clears its own review before it can publish directly.
              </p>
            </div>
            {error ? (
              <p className='text-muted-foreground text-sm'>Available connections could not be loaded.</p>
            ) : providers.length === 0 ? (
              <p className='text-muted-foreground text-sm'>
                Channel setup information is unavailable. Refresh this page or check the channel API; app sign-in configuration is separate from connecting social accounts.
              </p>
            ) : (
              <div className='grid gap-3 sm:grid-cols-2 xl:grid-cols-3'>
                {providers.map((provider) => (
                  <ProviderTile
                    key={provider.id}
                    provider={provider}
                    alreadyConnected={connectedPlatforms.has(provider.platform)}
                    canManage={canManage}
                    onConnect={() => openConnect({ providerId: provider.id })}
                  />
                ))}
              </div>
            )}
          </section>

          {filter !== 'local' && (
            <section className='flex flex-col gap-3' aria-labelledby='local-heading'>
              <Collapsible open={companionExpanded} onOpenChange={setCompanionOpen}>
                <CollapsibleTrigger
                  data-tour='companion-section'
                  className='flex w-full items-center justify-between gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
                >
                  <span className='flex flex-wrap items-center gap-2'>
                    <h3 id='local-heading' className='text-lg font-semibold'>
                      Desktop companion
                    </h3>
                    <CapabilityBadge level='local' label='Local · not available yet' />
                  </span>
                  <Icons.chevronDown className={cn('text-muted-foreground size-4 shrink-0 transition-transform', companionExpanded && 'rotate-180')} />
                </CollapsibleTrigger>
                <CollapsibleContent className='flex flex-col gap-4 pt-3'>
                  <p className='text-muted-foreground text-sm'>{COMPANION_SENTENCE}</p>
                  <CompanionDirectory />
                </CollapsibleContent>
              </Collapsible>
            </section>
          )}
        </div>
      )}

      <ConnectSheet open={connectOpen} onOpenChange={setConnectOpen} providers={providers} request={connectRequest} />
    </PageContainer>
  );
}

/** `useSearchParams` needs a Suspense boundary above it when the route is prerendered. */
export function ChannelsView() {
  return (
    <Suspense
      fallback={
        <PageContainer pageTitle='Channels' pageDescription={PAGE_DESCRIPTION} infoContent={infoContent}>
          <ChannelsSkeleton />
        </PageContainer>
      }
    >
      <ChannelsPage />
    </Suspense>
  );
}
