'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { StateMessage, Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useChannels, useConnectionHealth } from '@/lib/api/hooks';
import { healthCopy, fill } from '@/lib/channels/health-copy';
import { splitPlatforms, type HealthPlatform } from '@/lib/channels/health';
import { usePreferences } from '@/lib/preferences';
import { ConnectSheet, type ConnectRequest } from '../connect-sheet';
import { AccountHealthCard, AutonomySummary, StateBadge } from './health-parts';

/**
 * Connection Health Center (P1.4). Every state comes from the server (`connection_health.py`); reconnecting opens the
 * existing Connect sheet, which starts the platform's own OAuth. Shown only where the Channels response says this
 * workspace is admitted (`RAFII_CONNECTION_HEALTH_ENABLED`); elsewhere the page says it isn't available and asks
 * nothing of the health endpoint.
 */
export function ConnectionHealthView() {
  const { locale } = usePreferences();
  const { copy, lang } = healthCopy(locale);
  const channels = useChannels();
  const admitted = channels.data?.connectionHealth?.available === true;
  const health = useConnectionHealth({ enabled: admitted });
  const [request, setRequest] = useState<ConnectRequest | null>(null);
  const providers = channels.data?.providers ?? [];
  const data = health.data;

  const channelsLink = (
    <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
      <Icons.broadcast className='size-4' aria-hidden />
      {copy.openChannels}
    </Link>
  );

  // A 404 means the server no longer admits this workspace: say so, not "error".
  const withdrawn = health.error instanceof ApiError && health.error.status === 404;
  let body: ReactNode;
  if (channels.isLoading || (admitted && health.isLoading)) {
    body = <StateMessage kind='loading' title={copy.loading} />;
  } else if (channels.error || (health.error && !withdrawn)) {
    body = (
      <StateMessage
        kind='error'
        title={copy.error}
        action={
          <Button variant='glass' size='control' onClick={() => void (channels.error ? channels.refetch() : health.refetch())}>
            <Icons.refresh className='size-4' aria-hidden />
            {copy.retry}
          </Button>
        }
      />
    );
  } else if (!admitted || !data) {
    body = <StateMessage kind='unsupported' title={copy.unavailable} action={channelsLink} />;
  } else {
    const { connected, other } = splitPlatforms(data.platforms);
    const onConnect = data.canManage ? (next: ConnectRequest) => setRequest(next) : undefined;
    body = (
      <div className='flex flex-col gap-8'>
        <Surface as='section' material='quiet' radius='card' padding='md' className='flex flex-col gap-2' aria-label={copy.title}>
          <p role='status' className='text-foreground text-base font-medium'>
            {data.attention > 0 ? fill(copy.attentionCount, { count: data.attention }) : copy.attentionNone}
          </p>
          <p className='text-muted-foreground text-sm text-pretty'>{copy.liveNote}</p>
        </Surface>

        <AutonomySummary copy={copy} autonomy={data.autonomy} />

        <section className='flex flex-col gap-5' aria-labelledby='health-accounts'>
          <h2 id='health-accounts' className='text-foreground text-lg font-medium tracking-tight'>
            {copy.accountsHeading}
          </h2>
          {connected.length === 0 ? (
            <StateMessage kind='empty' title={copy.noAccounts} action={channelsLink} />
          ) : (
            connected.map((platform) => <PlatformGroup key={platform.platform} copy={copy} platform={platform} onConnect={onConnect} />)
          )}
        </section>

        {other.length > 0 && (
          <section className='flex flex-col gap-3' aria-labelledby='health-other'>
            <h2 id='health-other' className='text-foreground text-lg font-medium tracking-tight'>
              {copy.otherPlatforms}
            </h2>
            <ul className='grid gap-2 sm:grid-cols-2 xl:grid-cols-3'>
              {other.map((platform) => (
                <li key={platform.platform}>
                  <Surface material='quiet' radius='control' padding='sm' className='flex min-h-14 items-center justify-between gap-3'>
                    <span className='flex min-w-0 items-center gap-2.5'>
                      <ChannelIcon platform={platform.platform} name={platform.platform} size='sm' />
                      <span className='text-foreground truncate text-sm font-medium'>{platform.platform}</span>
                    </span>
                    <span className='flex shrink-0 items-center gap-2'>
                      <StateBadge copy={copy} state={platform.state} />
                      {onConnect && platform.connectable && platform.providerId && (
                        <Button variant='quiet' size='sm' className='h-11 min-w-11' onClick={() => onConnect({ providerId: platform.providerId ?? undefined })}>
                          {copy.connect}
                        </Button>
                      )}
                    </span>
                  </Surface>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    );
  }

  return (
    <div lang={lang} className='contents'>
      <PageContainer pageTitle={copy.title} pageDescription={copy.description} pageHeaderAction={admitted ? channelsLink : undefined}>
        {body}
      </PageContainer>
      {admitted && (
        <ConnectSheet open={request !== null} onOpenChange={(open) => !open && setRequest(null)} providers={providers} request={request} />
      )}
    </div>
  );
}

function PlatformGroup({ copy, platform, onConnect }: { copy: ReturnType<typeof healthCopy>['copy']; platform: HealthPlatform; onConnect?: (request: ConnectRequest) => void }) {
  const headingId = `health-platform-${platform.platform.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  return (
    <section className='flex flex-col gap-3' aria-labelledby={headingId}>
      <div className='flex flex-wrap items-center gap-2.5'>
        <ChannelIcon platform={platform.platform} name={platform.platform} size='sm' />
        <h3 id={headingId} className='text-foreground text-base font-medium'>
          {platform.platform}
        </h3>
        <StateBadge copy={copy} state={platform.state} />
      </div>
      <div className='grid gap-4 xl:grid-cols-2'>
        {platform.accounts.map((account) => (
          <AccountHealthCard key={account.channelId} copy={copy} account={account} onConnect={onConnect} />
        ))}
      </div>
    </section>
  );
}
