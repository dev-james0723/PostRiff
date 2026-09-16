'use client';

import { useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { LevelBadge } from '@/components/app/level-badge';
import { ChannelIcon } from '@/components/channel-icon';
import { CapabilityBadge } from '@/components/marketing/capability-badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';
import { localChannels } from '@/config/channels';
import { keys, useChannels } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { ChannelView, OAuthStart, ProviderView } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDate } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';

const CAPS: { key: string; label: string }[] = [
  { key: 'identity', label: 'Identity' },
  { key: 'publish', label: 'Publish' },
  { key: 'schedule', label: 'Schedule' },
  { key: 'analytics', label: 'Analytics' },
  { key: 'comments_read', label: 'Comments' },
  { key: 'reply', label: 'Reply' }
];

const CONNECT_CAPS = ['publish', 'analytics', 'comments_read', 'reply'];

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
      title: 'Disconnecting',
      description: 'Stored tokens are wiped and revoked remotely where the provider supports it. Approved jobs for that account are held.'
    }
  ]
};

function stateTone(state: string) {
  if (state === 'publish_verified' || state === 'read_verified') return 'default';
  if (state === 'disconnected') return 'secondary';
  return 'destructive';
}

function ConnectedCard({ channel, canManage }: { channel: ChannelView; canManage: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);

  async function refresh() {
    await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
    await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
  }

  async function verify() {
    setBusy(true);
    try {
      const result = await api.verifyChannel(workspaceId, channel.id);
      toast.success(`Verification: ${result.state.replace(/_/g, ' ')}${result.detail ? ` — ${result.detail}` : ''}`);
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Verification failed.');
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await api.disconnectChannel(workspaceId, channel.id);
      toast.success('Disconnected. Stored tokens were wiped.');
      await refresh();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not disconnect.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className='flex flex-wrap items-start justify-between gap-2'>
          <div>
            <CardTitle className='flex items-center gap-2'>
              <ChannelIcon platform={channel.platform} name={channel.platform} />
              {channel.platform}
              <Badge variant={stateTone(channel.connectionState)}>{channel.connectionState.replace(/_/g, ' ')}</Badge>
            </CardTitle>
            <CardDescription>
              {channel.account} · {channel.accountType || 'account'}
            </CardDescription>
          </div>
          <div className='flex items-center gap-1.5'>
            <span className='text-muted-foreground text-xs'>publish</span>
            <LevelBadge level={channel.capabilities.publish?.level} size='md' />
          </div>
        </div>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        <div className='overflow-x-auto'>
          <Table>
            <TableBody>
              {CAPS.map((cap) => {
                const value = channel.capabilities[cap.key];
                return (
                  <TableRow key={cap.key}>
                    <TableCell className='w-28 font-medium'>{cap.label}</TableCell>
                    <TableCell className='w-32'>
                      <LevelBadge level={value?.level} />
                    </TableCell>
                    <TableCell className='text-muted-foreground max-w-[28rem] truncate text-xs' title={value?.evidence}>
                      {value?.evidence || '—'}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        <p className='text-muted-foreground text-xs'>
          {channel.expiresAt ? `Access expires ${formatDate(channel.expiresAt)} · ` : ''}
          evidence: {channel.evidenceSource.replace(/_/g, ' ')} · scopes: {channel.scopes.join(', ') || 'none'}
        </p>
        {canManage && (
          <div className='flex flex-wrap gap-2'>
            <Button variant='outline' size='sm' disabled={busy} onClick={() => void verify()}>
              Re-verify
            </Button>
            <DisconnectButton platform={channel.platform} account={channel.account} disabled={busy} onConfirm={disconnect} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DisconnectButton({
  platform,
  account,
  disabled,
  onConfirm
}: {
  platform: string;
  account: string;
  disabled: boolean;
  onConfirm: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant='outline' size='sm' disabled={disabled} className='text-destructive' onClick={() => setOpen(true)}>
        Disconnect
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Disconnect {platform}?</AlertDialogTitle>
            <AlertDialogDescription>
              {account}: stored tokens are wiped and revoked remotely where supported. Approved jobs for this account will be held until you reconnect.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setOpen(false);
                void onConfirm();
              }}
            >
              Disconnect
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function ProviderRow({ provider, canManage }: { provider: ProviderView; canManage: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [capability, setCapability] = useState('publish');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<OAuthStart | null>(null);
  const options = CONNECT_CAPS.filter((key) => provider.capabilities[key] !== false);

  async function start() {
    setBusy(true);
    try {
      setPending(await api.oauthStart(workspaceId, provider.id, capability));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not start the connection.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className='flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between'>
      <div className='min-w-0'>
        <p className='flex items-center gap-2 font-medium'>
          <ChannelIcon platform={provider.platform} name={provider.platform} />
          {provider.platform}
          <CapabilityBadge
            level={provider.productionReviewed ? 'direct' : 'assisted'}
            label={provider.productionReviewed ? 'Direct publishing' : 'Assisted · review pending'}
          />
        </p>
        <p className='text-muted-foreground text-xs'>
          {provider.productionReviewed
            ? 'Production-reviewed app: publishing runs through the official API after your approval.'
            : 'Awaiting provider review: PostRiff prepares each post and you complete the final step.'}
        </p>
      </div>
      {canManage && (
        <div className='flex items-center gap-2'>
          <Select value={capability} onValueChange={(value) => setCapability(String(value))}>
            <SelectTrigger className='w-40' aria-label='Capability to request'>
              <SelectValue>{CAPS.find((c) => c.key === capability)?.label ?? capability}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {options.map((key) => (
                <SelectItem key={key} value={key}>
                  {CAPS.find((c) => c.key === key)?.label ?? key}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button disabled={busy} onClick={() => void start()}>
            Connect
          </Button>
        </div>
      )}
      <Dialog open={Boolean(pending)} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Before you continue to {provider.platform}</DialogTitle>
            <DialogDescription>{pending?.permissionExplanation}</DialogDescription>
          </DialogHeader>
          <p className='text-muted-foreground text-sm'>
            Scopes requested: {pending?.scopes.join(', ') || 'none'}. You will confirm the exact account after{' '}
            {provider.platform} returns you here.
          </p>
          <DialogFooter>
            <Button variant='outline' onClick={() => setPending(null)}>
              Not now
            </Button>
            {pending && (
              <a href={pending.authorizeUrl} className={buttonVariants()}>
                Continue to {provider.platform}
              </a>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function ChannelsView() {
  const { data, isLoading, error } = useChannels();
  const access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission: 'manage_connections' });
  const connected = data?.channels ?? [];
  const providers = data?.providers ?? [];

  return (
    <PageContainer
      pageTitle='Channels'
      pageDescription='Each capability is verified on its own. A connected account is not the same as a publishable one.'
      infoContent={infoContent}
    >
      <div className='flex flex-col gap-8'>
        <section className='flex flex-col gap-4' aria-labelledby='connected-heading'>
          <h3 id='connected-heading' className='text-lg font-semibold'>
            Connected accounts
          </h3>
          {isLoading ? (
            <Skeleton className='h-48 w-full' />
          ) : error ? (
            <p className='text-destructive text-sm'>{error instanceof Error ? error.message : 'Channels could not be loaded.'}</p>
          ) : connected.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <Icons.broadcast />
                </EmptyMedia>
                <EmptyTitle>No accounts connected</EmptyTitle>
                <EmptyDescription>
                  You can draft without connecting anything. Connect an account when you want previews, scheduling, analytics or comments for it.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className='grid gap-4 xl:grid-cols-2'>
              {connected.map((channel) => (
                <ConnectedCard key={channel.id} channel={channel} canManage={canManage} />
              ))}
            </div>
          )}
        </section>

        <section className='flex flex-col gap-4' aria-labelledby='providers-heading'>
          <div>
            <h3 id='providers-heading' className='text-lg font-semibold'>
              Available connections
            </h3>
            <p className='text-muted-foreground text-sm'>
              Hosted connectors use the provider’s official API. Each one clears its own review before it can publish directly.
            </p>
          </div>
          {isLoading ? (
            <Skeleton className='h-24 w-full' />
          ) : providers.length === 0 ? (
            <p className='text-muted-foreground text-sm'>
              No providers are configured on this deployment yet. LinkedIn, Threads and Instagram are the audited launch set; each appears here once its app credentials are in place.
            </p>
          ) : (
            <div className='flex flex-col gap-3'>
              {providers.map((provider) => (
                <ProviderRow key={provider.id} provider={provider} canManage={canManage} />
              ))}
            </div>
          )}
        </section>

        <section className='flex flex-col gap-4' aria-labelledby='local-heading'>
          <div>
            <h3 id='local-heading' className='flex items-center gap-2 text-lg font-semibold'>
              Desktop companion <CapabilityBadge level='local' />
            </h3>
            <p className='text-muted-foreground text-sm'>
              These platforms have no third-party publishing API a small studio can use honestly. The companion signs in on your own machine and publishes through your own session — never from our servers.
            </p>
          </div>
          <div className='flex flex-wrap gap-2'>
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
          </div>
        </section>
      </div>
    </PageContainer>
  );
}
