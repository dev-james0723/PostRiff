'use client';

import { forwardRef, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { SuccessCheck } from '@/components/ui/success-check';
import { useFlash } from '@/hooks/use-flash';
import { keys } from '@/lib/api/hooks';
import { useChangeError } from '@/lib/auth/use-sign-in-again';
import { ApiError } from '@/lib/api/client';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import {
  attentionSentence,
  channelBadge,
  expiringSoon,
  needsAttention,
  nowSeconds,
  reconnectCapability,
  VERIFIED_STATES
} from '@/lib/channels/state';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CapabilityChips } from './capability-chips';
import { ChannelHistorySheet } from './channel-history-sheet';
import type { ConnectRequest } from './connect-sheet';

/** Jobs for this account, counted from the workspace snapshot by the page. */
export interface ChannelActivity {
  scheduled: number;
  held: number;
  published: number;
}

export interface ChannelCardProps {
  channel: ChannelView;
  /** The mounted provider for this platform; undefined when the deployment no longer offers it. */
  provider?: ProviderView;
  canManage: boolean;
  activity?: ChannelActivity | null;
  /** Plays the success check once: the card the provider just returned. */
  highlight?: boolean;
  /** The first card carries the tour anchors. */
  tour?: boolean;
  onReconnect: (request: ConnectRequest) => void;
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

function ScopesList({ scopes }: { scopes: string[] }) {
  const [open, setOpen] = useState(false);
  if (scopes.length === 0) return <span>no scopes</span>;
  return (
    <Collapsible open={open} onOpenChange={setOpen} className='inline'>
      <CollapsibleTrigger className='inline-flex items-center gap-0.5 underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring/50 rounded-sm outline-none'>
        {scopes.length} {scopes.length === 1 ? 'scope' : 'scopes'}
        <Icons.chevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className='mt-1.5 flex flex-wrap gap-1'>
          {scopes.map((scope) => (
            <li key={scope} className='bg-muted rounded px-1.5 py-0.5 font-mono text-[11px]'>
              {scope}
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * One account on one platform: who it is, the level PostRiff verified for each capability, when
 * access ends and what to do about it. Every value on the card is the API's; nothing is derived
 * into a blended "ready".
 */
export const ChannelCard = forwardRef<HTMLDivElement, ChannelCardProps>(function ChannelCard(
  { channel, provider, canManage, activity, highlight = false, tour = false, onReconnect },
  ref
) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [verifyOutcome, flashVerifyOutcome] = useFlash<{ state: 'success' | 'error'; label: string }>();

  const held = activity?.held ?? 0;
  const badge = channelBadge(channel);
  const attention = needsAttention(channel, undefined, held);
  const expiring = expiringSoon(channel);
  const expired = typeof channel.expiresAt === 'number' && channel.expiresAt <= nowSeconds();
  const sentence = attentionSentence(channel, undefined, held);
  const identityVerifiedAt = channel.capabilities.identity?.verifiedAt ?? null;
  const activityTotal = activity ? activity.scheduled + activity.held + activity.published : 0;

  async function refresh() {
    await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
    await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    await client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
  }

  async function verify() {
    setBusy(true);
    setVerifying(true);
    try {
      const result = await api.verifyChannel(workspaceId, channel.id);
      toast.success(`Verification: ${result.state.replace(/_/g, ' ')}${result.detail ? ` — ${result.detail}` : ''}`);
      await refresh();
      // The request can succeed while the check fails (an expired token): only a verified state earns "Verified".
      flashVerifyOutcome(VERIFIED_STATES.has(result.state) ? { state: 'success', label: 'Verified' } : { state: 'error', label: 'Not verified' });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Verification failed.');
      flashVerifyOutcome({ state: 'error', label: 'Try again' });
    } finally {
      setBusy(false);
      setVerifying(false);
    }
  }

  const reportChangeError = useChangeError();

  async function disconnect() {
    setBusy(true);
    try {
      await api.disconnectChannel(workspaceId, channel.id);
      toast.success('Disconnected. Stored tokens were wiped.');
      await refresh();
    } catch (err) {
      reportChangeError(err, 'Could not disconnect.');
    } finally {
      setBusy(false);
    }
  }

  function reconnect() {
    if (!provider) return;
    onReconnect({
      providerId: provider.id,
      capability: reconnectCapability(channel),
      reconnect: { channelId: channel.id, account: channel.account }
    });
  }

  return (
    <Card
      ref={ref}
      id={`channel-${channel.id}`}
      data-tour={tour ? 'channel-card' : undefined}
      data-attention={attention ? 'true' : undefined}
      className={cn(
        'h-full scroll-mt-24',
        attention && 'shadow-[inset_3px_0_0_0_var(--color-amber-500)] dark:shadow-[inset_3px_0_0_0_var(--color-amber-400)]'
      )}
    >
      <CardHeader>
        <div className='flex flex-wrap items-start justify-between gap-2'>
          <div className='min-w-0'>
            <CardTitle className='flex items-center gap-2'>
              <ChannelIcon platform={channel.platform} name={channel.platform} />
              <span className='truncate'>{channel.platform}</span>
              {highlight && <SuccessCheck className='size-5 text-emerald-600 dark:text-emerald-400' />}
            </CardTitle>
            <CardDescription className='truncate'>
              {channel.account} · {channel.accountType || 'account'}
            </CardDescription>
          </div>
          <AnimatedBadge size='sm' status={badge.status} contentKey={`${channel.connectionState}:${expiring ? 'expiring' : 'steady'}`}>
            {badge.label}
          </AnimatedBadge>
        </div>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        {attention && sentence && (
          <Alert className='border-amber-500/40 bg-amber-500/5 text-amber-900 dark:text-amber-100'>
            <Icons.warning className='size-4 text-amber-600 dark:text-amber-400' />
            <AlertTitle>Needs attention</AlertTitle>
            <AlertDescription className='text-amber-900/90 dark:text-amber-100/90'>
              <div className='flex flex-col items-start gap-2'>
                <span>{sentence}</span>
                {canManage && provider && (
                  <Button size='sm' onClick={reconnect}>
                    <Icons.refresh className='size-3.5' />
                    Reconnect
                  </Button>
                )}
                {canManage && !provider && (
                  <span className='text-xs'>This provider is not configured on this deployment, so it cannot be reconnected here.</span>
                )}
              </div>
            </AlertDescription>
          </Alert>
        )}

        <CapabilityChips capabilities={channel.capabilities} data-tour={tour ? 'capability-chips' : undefined} />

        {/* A div, not a p: the scopes list expands a block inside this row. */}
        <div className='text-muted-foreground flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs'>
          {channel.expiresAt ? (
            <span className={cn((expiring || expired) && 'text-amber-700 dark:text-amber-300')}>
              {expired
                ? `Access expired ${relativeTime(channel.expiresAt)} (${formatDate(channel.expiresAt)})`
                : `Access until ${formatDate(channel.expiresAt)} · ${relativeTime(channel.expiresAt)}`}
            </span>
          ) : (
            <span>No expiry reported</span>
          )}
          <span aria-hidden>·</span>
          <span>{identityVerifiedAt ? `Verified ${relativeTime(identityVerifiedAt)}` : 'Not verified yet'}</span>
          <span aria-hidden>·</span>
          <span>Evidence: {channel.evidenceSource.replace(/_/g, ' ')}</span>
          <span aria-hidden>·</span>
          <ScopesList scopes={channel.scopes} />
        </div>

        {activityTotal > 0 && activity && (
          <Link
            href={`/app/queue?channel=${encodeURIComponent(channel.id)}`}
            className='text-muted-foreground hover:text-foreground w-fit text-xs underline-offset-2 hover:underline'
          >
            {activity.scheduled} scheduled · {activity.held} held · {activity.published} published
          </Link>
        )}

        <div className='flex flex-wrap gap-2' data-tour={tour ? 'channel-actions' : undefined}>
          {canManage && (
            <StatefulButton
              variant='outline'
              size='sm'
              state={verifying ? 'loading' : (verifyOutcome?.state ?? 'idle')}
              loadingText='Verifying…'
              successText={verifyOutcome?.label ?? 'Verified'}
              errorText={verifyOutcome?.label ?? 'Try again'}
              disabled={busy}
              onClick={() => void verify()}
            >
              Re-verify
            </StatefulButton>
          )}
          {/* History is read-only, so every member may open it; manage actions stay behind manage_connections. */}
          <Button variant='outline' size='sm' onClick={() => setHistoryOpen(true)}>
            <Icons.history className='size-3.5' />
            History
          </Button>
          {canManage && <DisconnectButton platform={channel.platform} account={channel.account} disabled={busy} onConfirm={disconnect} />}
        </div>
      </CardContent>
      <ChannelHistorySheet channel={channel} open={historyOpen} onOpenChange={setHistoryOpen} />
    </Card>
  );
});
