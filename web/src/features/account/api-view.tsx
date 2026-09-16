'use client';

import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { hostedChannels, localChannels } from '@/config/channels';
import { siteConfig } from '@/config/site';
import { useChannels } from '@/lib/api/hooks';

export function ApiView() {
  const channels = useChannels();
  const connected = channels.data?.channels ?? [];
  return (
    <PageContainer
      pageTitle='API & integrations'
      pageDescription='What is connected today, and how developer access works.'
    >
      <div className='grid gap-4 lg:grid-cols-2'>
        <Card>
          <CardHeader>
            <CardTitle>Connected providers</CardTitle>
            <CardDescription>OAuth grants you have made to PostRiff. Manage them on the Channels page.</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-2 text-sm'>
            {connected.length === 0 ? (
              <p className='text-muted-foreground'>No providers connected yet.</p>
            ) : (
              connected.map((channel) => (
                <div key={channel.id} className='flex items-center justify-between gap-3 rounded-lg border p-3'>
                  <span className='flex items-center gap-2'>
                    <ChannelIcon platform={channel.platform} name={channel.platform} size='xs' />
                    {channel.platform} · <span className='text-muted-foreground'>{channel.account}</span>
                  </span>
                  <Badge variant='outline'>{channel.scopes.length} scope{channel.scopes.length === 1 ? '' : 's'}</Badge>
                </div>
              ))
            )}
          </CardContent>
          <CardFooter>
            <Link href='/app/channels' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
              Open Channels
            </Link>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Developer access</CardTitle>
            <CardDescription>Honest status: the hosted API is session-authenticated today.</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-3 text-sm'>
            <p>
              Every request the app makes goes to <code className='bg-muted rounded px-1'>/api/*</code> with your session token. There is no separate API key yet, and no rate plan for automated clients.
            </p>
            <p className='text-muted-foreground'>
              A public API, an MCP server and an n8n node are on the roadmap. If you would build on them, tell us what you need — early access is arranged case by case.
            </p>
          </CardContent>
          <CardFooter>
            <Link href={`${siteConfig.links.contact}?topic=api`} className={buttonVariants({ size: 'sm' })}>
              Request early access
            </Link>
          </CardFooter>
        </Card>

        <Card className='lg:col-span-2'>
          <CardHeader>
            <CardTitle>Integration surface</CardTitle>
            <CardDescription>Where PostRiff can publish, and how.</CardDescription>
          </CardHeader>
          <CardContent className='grid gap-4 md:grid-cols-2'>
            <div>
              <p className='mb-2 flex items-center gap-2 text-sm font-medium'>
                Hosted connectors <CapabilityBadge level='assisted' label='review pending' />
              </p>
              <ul className='text-muted-foreground flex flex-col gap-1 text-sm'>
                {hostedChannels.map((channel) => (
                  <li key={channel.slug} className='flex items-center gap-2'>
                    <ChannelIcon slug={channel.slug} name={channel.name} size='xs' />
                    {channel.name} — {channel.reviewStatus}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className='mb-2 flex items-center gap-2 text-sm font-medium'>
                Desktop companion <CapabilityBadge level='local' />
              </p>
              <p className='text-muted-foreground text-sm'>
                {localChannels.length} platforms publish through the companion on your own machine, including {localChannels.filter((c) => c.region === 'cn').length} Chinese platforms.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
