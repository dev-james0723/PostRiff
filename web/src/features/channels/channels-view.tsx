'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { AnimatePresence, motion } from 'motion/react';
import PageContainer from '@/components/layout/page-container';
import { Icons, type Icon } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { DigitSwap } from '@/components/motion/digit-swap';
import { InfoTip, SegmentedControl, StateMessage, Surface, type SegmentOption } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { HoverLiftGroup } from '@/components/ui/hover-lift-group';
import { localChannels } from '@/config/channels';
import { useChannels, useSnapshot, useUsage } from '@/lib/api/hooks';
import type { ProviderView } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { capabilityLabel } from '@/lib/channels/capabilities';
import { providerReadinessLabel } from '@/lib/channels/onboarding';
import { publishingSupport } from '@/lib/channels/publishing-support';
import {
  channelCounts,
  CONNECT_CAPABILITIES,
  isConnected,
  listedOnChannels,
  matchesFilter,
  nowSeconds,
  parseChannelFilter,
  sortForAttention,
  type ChannelFilter
} from '@/lib/channels/state';
import { EASE_OUT } from '@/lib/ease';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { toFolderAccounts } from './channel-bloom/helpers';
import { ChannelCard, type ChannelActivity } from './channel-card';
import { ChannelFoldersSection } from './channel-folders-section';
import { ChannelsSummary } from './channels-summary';
import { ConnectSheet, type ConnectRequest } from './connect-sheet';
import { useSiteAgentPageContext } from '@/features/site-agent/use-page-context';

const infoContent = {
  title: 'Channels',
  sections: [
    {
      title: 'Each permission is separate',
      description: 'Publishing, analytics and comments are granted one by one. Each account shows what it can do.'
    },
    {
      title: 'Direct · Assisted · Local',
      description: 'Direct: Rafii does it after your approval. Assisted: Rafii prepares it and you finish the last step. Local: runs on your own computer.'
    },
    {
      title: 'Re-verify',
      description: 'Checks the account still signs in and still has its permissions. It doesn’t renew access.'
    },
    {
      title: 'Reconnect',
      description: 'Sign in as the same account. A different account is added as a new one.'
    },
    {
      title: 'Disconnect',
      description: 'Removes Rafii’s access. Approved posts for that account are held.'
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

/** The same identity block on the Suspense fallback and the page (DNA §9.1). */
const PAGE_FRAME = { pageTitle: 'Channels', infoContent };

/** Loading keeps the page geometry and says what is being loaded (DNA §20.1). */
function ChannelsSkeleton() {
  return (
    <div className='flex flex-col gap-8' aria-busy>
      <StateMessage kind='loading' title='Loading channels…' />
      <div className='grid gap-4 xl:grid-cols-2' aria-hidden>
        <div className='rafii-quiet h-56 rounded-[var(--rafii-radius-card)]' />
        <div className='rafii-quiet h-56 rounded-[var(--rafii-radius-card)]' />
      </div>
    </div>
  );
}

/** A provider's setup state as icon + words (DNA §4.3): ready, connectable while review is pending, or blocked. */
function ProviderReadiness({ provider }: { provider: ProviderView }) {
  const blocked =
    provider.configured === false ||
    provider.connectReady === false ||
    provider.executionPaused === true ||
    provider.configurationState === 'partial_configuration' ||
    provider.configurationState === 'invalid_configuration';
  const IconMark: Icon = blocked ? Icons.warning : provider.productionReviewed ? Icons.check : Icons.clock;
  return (
    <span className='text-muted-foreground inline-flex shrink-0 items-center gap-1.5 text-xs'>
      <IconMark className='size-3.5 shrink-0' aria-hidden />
      {providerReadinessLabel(provider)}
    </span>
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
  const blocked = provider.connectReady === false || provider.executionPaused === true;
  return (
    <Surface material='quiet' radius='card' padding='md' className='flex h-full flex-col gap-3'>
      <div className='flex items-start justify-between gap-3'>
        <div className='flex min-w-0 items-center gap-2.5'>
          <ChannelIcon platform={provider.platform} name={provider.platform} size='md' />
          <span className='text-foreground truncate font-medium'>{provider.platform}</span>
          <InfoTip label={`What ${provider.platform} can publish`} description={publishingSupport(provider.platform)} className='-my-3 -ml-2' />
        </div>
        <ProviderReadiness provider={provider} />
      </div>
      <p className='text-muted-foreground text-[13px] leading-relaxed'>{provider.accountRequirement}</p>
      {/* Setup detail is for whoever runs the workspace: available, never the headline. */}
      {Boolean(provider.setupIssues?.length || (provider.callbackUri && provider.connectReady === false)) && (
        <Collapsible>
          <CollapsibleTrigger
            aria-label={`${provider.platform} setup details`}
            className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-6 items-center gap-0.5 rounded-sm text-xs underline-offset-2 hover:underline'
          >
            Details
            <Icons.chevronDown className='size-3' aria-hidden />
          </CollapsibleTrigger>
          <CollapsibleContent className='flex flex-col gap-1.5 pt-1.5'>
            {provider.setupIssues?.map((issue) => (
              <p key={issue} className='text-muted-foreground flex min-w-0 items-start gap-1.5 text-xs [overflow-wrap:anywhere]'>
                <Icons.warning className='mt-0.5 size-3.5 shrink-0' aria-hidden />
                {issue}
              </p>
            ))}
            {provider.callbackUri && provider.connectReady === false && (
              <p className='text-muted-foreground text-xs break-all'>
                Callback: <code className='rafii-field rounded-md px-1.5 py-0.5 font-mono'>{provider.callbackUri}</code>
              </p>
            )}
            <p className='text-muted-foreground text-xs'>Credentials go in the server settings, never in the browser.</p>
          </CollapsibleContent>
        </Collapsible>
      )}
      {offered.length > 0 && (
        <ul className='text-muted-foreground flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs' aria-label='Capabilities you can request'>
          {offered.map((key, index) => (
            <li key={key} className='inline-flex items-center gap-1.5'>
              {index > 0 && <span aria-hidden>·</span>}
              {capabilityLabel(key)}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <div className='mt-auto pt-1'>
          <Button variant='glass' size='control' disabled={blocked} onClick={onConnect}>
            <Icons.add className='size-4' />
            {alreadyConnected ? 'Connect another account' : 'Connect'}
          </Button>
        </div>
      )}
    </Surface>
  );
}

function CompanionDirectory() {
  return (
    // transitions.dev avatar group hover: the hovered chip lifts and its neighbours follow.
    <HoverLiftGroup className='flex flex-wrap gap-2'>
      {localChannels.map((channel) => (
        <Link key={channel.slug} href={`/channels/${channel.slug}`} className={cn(buttonVariants({ variant: 'glass' }), 'h-11 gap-2 px-3.5 text-sm')}>
          <ChannelIcon slug={channel.slug} name={channel.name} size='xs' />
          {channel.name}
          {channel.nameZh && <span className='text-muted-foreground'>{channel.nameZh}</span>}
        </Link>
      ))}
    </HoverLiftGroup>
  );
}

const COMPANION_SENTENCE = 'For platforms without a public API. It will publish from your computer, with your own sign-in — never from our servers. Not available yet.';

function ChannelsPage() {
  const channelsQuery = useChannels();
  const usage = useUsage();
  const snapshot = useSnapshot();
  const access = useWorkspaceAccess();
  const { reduced } = useMotionPreference();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const canManage = checkAccess(access, { permission: 'manage_connections' });

  const { data, isLoading, isFetching, error, refetch } = channelsQuery;
  const providers = useMemo(() => data?.providers ?? [], [data]);
  const filter = parseChannelFilter(params.get('filter'));
  useSiteAgentPageContext({ visibleState: { filter } });
  const connectedParam = params.get('connected');

  const [connectRequest, setConnectRequest] = useState<ConnectRequest | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [companionOpen, setCompanionOpen] = useState<boolean | null>(null);
  // Saved folders narrow the account list below (a view, never a mutation); empty means every account.
  const [folderView, setFolderView] = useState<string[]>([]);

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
  const channels = useMemo(
    () => (data?.channels ?? []).filter((channel) => listedOnChannels(channel, heldByChannel[channel.id] ?? 0)),
    [data, heldByChannel]
  );

  const now = nowSeconds();
  const counts = channelCounts(channels, now, heldByChannel);
  const sorted = useMemo(() => sortForAttention(channels, now, heldByChannel), [channels, now, heldByChannel]);
  const visible = sorted.filter((channel) => matchesFilter(channel, filter, now, heldByChannel[channel.id] ?? 0) && (folderView.length === 0 || folderView.includes(channel.id)));
  const folderAccounts = useMemo(() => toFolderAccounts(snapshot.data?.state.phase2?.channels), [snapshot.data]);
  const connectedPlatforms = useMemo(() => new Set(channels.filter((channel) => isConnected(channel)).map((channel) => channel.platform)), [channels]);

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
        document.getElementById(`channel-${connectedParam}`)?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
      });
    }
    replaceParams((search) => search.delete('connected'));
  }, [channels, connectedParam, data, isFetching, reduced, replaceParams]);

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
  const errorMessage = error instanceof Error ? error.message : undefined;

  // WHAT: the account views, each with its real count (DNA §22.4).
  const filterOptions: SegmentOption<ChannelFilter>[] = (Object.keys(FILTER_LABELS) as ChannelFilter[]).map((key) => ({
    value: key,
    label: (
      <>
        {FILTER_LABELS[key]}
        <DigitSwap value={key === 'local' ? localChannels.length : counts[key === 'all' ? 'all' : key]} className='text-muted-foreground text-xs' />
      </>
    )
  }));

  // COMMIT: Connect channel is the page's one primary action (DNA §21.6); it stays visible with its label on phones.
  // With no accounts yet, the empty state below carries that action, so the header does not repeat it.
  const emptyOwnsAction = !isLoading && !error && channels.length === 0 && filter !== 'local';
  const headerAction = emptyOwnsAction ? undefined : canManage ? (
    <Button data-tour='channels-connect' variant='action' size='control' onClick={() => openConnect({})}>
      <Icons.add className='size-4' />
      Connect account
    </Button>
  ) : (
    <p className='text-muted-foreground text-sm'>Only owners and admins can connect accounts</p>
  );

  return (
    <PageContainer {...PAGE_FRAME} pageHeaderAction={headerAction}>
      {isLoading ? (
        <ChannelsSkeleton />
      ) : (
        <div className='flex flex-col gap-8'>
          {error ? (
            <StateMessage
              kind='error'
              title="Couldn't load channels"
              description={errorMessage}
              action={
                <Button variant='glass' size='control' onClick={() => void refetch()}>
                  <Icons.refresh className='size-4' />
                  Try again
                </Button>
              }
            />
          ) : (
            <>
              <ChannelsSummary
                counts={counts}
                providersCount={providers.filter((provider) => provider.connectReady !== false).length}
                usage={usage.data}
                data-tour='channels-summary'
              />

              {/* rafii-v9: folders — Saved folders (Phase2State.channelFolders) through Stream A's Channel Bloom package. Hidden until there is an account to group. */}
              {channels.length > 0 && <ChannelFoldersSection accounts={folderAccounts} view={folderView} onViewChange={setFolderView} />}

              <section className='flex flex-col gap-4' aria-labelledby='connected-heading'>
                <div className='flex flex-col gap-3 md:flex-row md:items-center md:justify-between'>
                  <h2 id='connected-heading' className='text-foreground text-lg font-medium tracking-tight'>
                    Accounts
                  </h2>
                  <div data-tour='channels-filter' className='relative -mx-1 max-w-full overflow-x-auto px-1 py-0.5 md:mx-0 md:px-0'>
                    <SegmentedControl options={filterOptions} value={filter} onChange={setFilter} label='Filter accounts' widths='content' />
                  </div>
                </div>

                {filter === 'local' ? (
                  <div className='flex flex-col gap-3'>
                    <p className='text-muted-foreground max-w-[70ch] text-sm leading-relaxed'>{COMPANION_SENTENCE}</p>
                    <CompanionDirectory />
                  </div>
                ) : channels.length === 0 ? (
                  <div data-tour='channels-empty'>
                    <StateMessage
                      kind='empty'
                      title='No accounts connected'
                      media={
                        <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
                          <Icons.broadcast className='size-5' />
                        </span>
                      }
                      action={
                        canManage ? (
                          <Button data-tour='channels-connect' variant='action' size='control' onClick={() => openConnect({})}>
                            <Icons.add className='size-4' />
                            Connect account
                          </Button>
                        ) : (
                          <span className='text-muted-foreground text-sm'>Only owners and admins can connect accounts</span>
                        )
                      }
                    />
                  </div>
                ) : visible.length === 0 ? (
                  <StateMessage
                    kind={filter === 'attention' && folderView.length === 0 ? 'success' : 'empty'}
                    title={
                      folderView.length > 0
                        ? 'No accounts match this view'
                        : filter === 'attention'
                          ? 'Nothing needs attention'
                          : `No ${FILTER_LABELS[filter].toLowerCase()} accounts`
                    }
                    action={
                      <Button
                        variant='quiet'
                        size='sm'
                        className='h-9'
                        onClick={() => {
                          setFilter('all');
                          setFolderView([]);
                        }}
                      >
                        Show all
                      </Button>
                    }
                  />
                ) : (
                  <div className='grid gap-4 xl:grid-cols-2'>
                    <AnimatePresence initial={false} mode='popLayout'>
                      {visible.map((channel, index) => (
                        <motion.div
                          key={channel.id}
                          layout={!reduced}
                          initial={reduced ? { opacity: 1 } : { opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={reduced ? { opacity: 0 } : { opacity: 0, y: -6 }}
                          transition={{ duration: reduced ? 0 : 0.18, ease: EASE_OUT }}
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
            <div className='flex flex-col gap-1'>
              <h2 id='providers-heading' className='text-foreground text-lg font-medium tracking-tight'>
                Connect
              </h2>
            </div>
            {error ? (
              <StateMessage kind='partial' layout='inline' title="Couldn't load platforms." />
            ) : providers.length === 0 ? (
              <StateMessage
                kind='partial'
                layout='inline'
                title='No platforms available yet.'
              />
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
                  className='rafii-focus flex min-h-11 w-full items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] text-left'
                >
                  <span className='flex flex-wrap items-center gap-x-3 gap-y-1'>
                    <h2 id='local-heading' className='text-foreground text-lg font-medium tracking-tight'>
                      Desktop companion
                    </h2>
                    <span className='text-muted-foreground inline-flex items-center gap-1.5 text-xs'>
                      <Icons.slash className='size-3.5' aria-hidden />
                      Not available yet
                    </span>
                  </span>
                  <Icons.chevronDown className={cn('text-muted-foreground size-4 shrink-0 transition-transform', companionExpanded && 'rotate-180')} />
                </CollapsibleTrigger>
                <CollapsibleContent className='flex flex-col gap-4 pt-3'>
                  <p className='text-muted-foreground max-w-[70ch] text-sm leading-relaxed'>{COMPANION_SENTENCE}</p>
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
        <PageContainer {...PAGE_FRAME}>
          <ChannelsSkeleton />
        </PageContainer>
      }
    >
      <ChannelsPage />
    </Suspense>
  );
}
