'use client';

import { useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { Icons, type Icon } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { StatefulButton } from '@/components/motion/button';
import { StateMessage, Surface, type StateKind } from '@/components/rafii';
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { SuccessCheck } from '@/components/ui/success-check';
import { useFlash } from '@/hooks/use-flash';
import { keys } from '@/lib/api/hooks';
import { useChangeError } from '@/lib/auth/use-sign-in-again';
import { ApiError } from '@/lib/api/client';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import {
  ATTENTION_STATES,
  attentionSentence,
  channelBadge,
  disconnectedByCustomer,
  expiringSoon,
  needsAttention,
  nowSeconds,
  reconnectCapability,
  VERIFIED_STATES,
  type ChannelBadge
} from '@/lib/channels/state';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CapabilityChips } from './capability-chips';
import { ChannelHistorySheet } from './channel-history-sheet';
import type { ConnectRequest } from './connect-sheet';
import { DestinationPicker } from './destination-picker';
import { CONTROL_44, DIALOG_ELEVATED, DIALOG_FOOTER_PLAIN, STATEFUL_GLASS } from './rafii-materials';

/** Jobs for this account, counted from the workspace snapshot by the page. */
export interface ChannelActivity {
  scheduled: number;
  held: number;
  published: number;
}

export interface ChannelCardProps {
  channel: ChannelView;
  /** The mounted provider for this platform; undefined when this platform can no longer be connected. */
  provider?: ProviderView;
  canManage: boolean;
  activity?: ChannelActivity | null;
  /** Plays the success check once: the card the provider just returned. */
  highlight?: boolean;
  /** The first card carries the tour anchors. */
  tour?: boolean;
  onReconnect: (request: ConnectRequest) => void;
}

/**
 * Connected, expiring, expired or revoked, missing permission, identity-only, disconnected and
 * unknown each get their own mark (DNA §20.2, §21.6); the words come from `channelBadge`.
 */
function connectionIcon(channel: ChannelView, expiring: boolean): Icon {
  if (VERIFIED_STATES.has(channel.connectionState)) return expiring ? Icons.clock : Icons.check;
  if (disconnectedByCustomer(channel)) return Icons.circleDashed;
  switch (channel.connectionState) {
    case 'token_expired':
    case 'reauthorization_required':
      return Icons.warning;
    case 'scope_missing':
      return Icons.lock;
    case 'identity_known':
      return Icons.user;
    default:
      return Icons.circleDashed;
  }
}

/** Monochrome connection state: icon + text on a quiet capsule (DNA §4.3). */
function ConnectionStatus({ channel, badge, expiring }: { channel: ChannelView; badge: ChannelBadge; expiring: boolean }) {
  const Icon = connectionIcon(channel, expiring);
  return (
    <span className='rafii-quiet text-foreground inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap'>
      <Icon className='size-3.5' aria-hidden />
      {badge.label}
    </span>
  );
}

/** Which state grammar the attention band uses: a permission gap, a lapsed grant, or a warning ahead of time. */
function attentionKind(channel: ChannelView, expiring: boolean): StateKind {
  if (channel.connectionState === 'scope_missing') return 'permission';
  if (ATTENTION_STATES.has(channel.connectionState)) return 'error';
  return expiring ? 'stale' : 'partial';
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
      <Button variant='quiet' disabled={disabled} className={cn(CONTROL_44, 'text-destructive hover:text-destructive')} onClick={() => setOpen(true)}>
        Disconnect
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent className={DIALOG_ELEVATED}>
          <AlertDialogHeader>
            <AlertDialogTitle className='text-xl font-medium tracking-tight'>Disconnect {platform}?</AlertDialogTitle>
            <AlertDialogDescription>
              Rafii loses access to {account}. Writing samples imported from it are deleted, and Writing DNA built from them must be rebuilt. Manual samples stay. Approved posts are held until you reconnect.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className={DIALOG_FOOTER_PLAIN}>
            <AlertDialogCancel variant='glass' size='control'>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              variant='action'
              size='control'
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
  if (scopes.length === 0) return <span>No permissions</span>;
  return (
    <Collapsible open={open} onOpenChange={setOpen} className='inline'>
      <CollapsibleTrigger className='rafii-focus inline-flex min-h-6 items-center gap-0.5 rounded-sm underline-offset-2 hover:underline'>
        {scopes.length} {scopes.length === 1 ? 'permission' : 'permissions'}
        <Icons.chevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className='mt-1.5 flex flex-wrap gap-1'>
          {scopes.map((scope) => (
            <li key={scope} className='rafii-field rounded-md px-1.5 py-0.5 font-mono text-xs'>
              {scope}
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * One account on one platform (DNA §21.6): who it is first — account name, then platform and
 * account type — the connection state, the level PostRiff verified for each capability, when
 * access ends and what to do about it. Every value on the card is the API's; nothing is derived
 * into a blended "ready". Glass marks it as the page's work surface; Reconnect and Manage stay
 * secondary because Connect channel is the page's one primary action.
 */
export function ChannelCard({ channel, provider, canManage, activity, highlight = false, tour = false, onReconnect }: ChannelCardProps) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [verifyOutcome, flashVerifyOutcome] = useFlash<{ state: 'success' | 'error'; label: string }>();

  const held = activity?.held ?? 0;
  // Listed only while posts for it are on hold (`listedOnChannels`): the card offers Reconnect and History, nothing else.
  const disconnected = disconnectedByCustomer(channel);
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
      await refresh();
      // The request can succeed while the check fails (an expired token): only a verified state earns "Verified".
      // Success shows on the button and the badge; a failed check keeps its detail in the toast.
      const verified = VERIFIED_STATES.has(result.state);
      if (!verified) toast.error(`${channel.platform} not verified`, { description: result.detail || result.state.replace(/_/g, ' ') });
      flashVerifyOutcome(verified ? { state: 'success', label: 'Verified' } : { state: 'error', label: 'Not verified' });
    } catch (err) {
      toast.error(`Couldn't verify ${channel.platform}`, { description: err instanceof ApiError ? err.message : undefined });
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
      // The card leaves the list (`listedOnChannels`), so the toast is the confirmation.
      toast.success(`${channel.platform} disconnected`, { description: channel.account });
      await refresh();
    } catch (err) {
      // 404: already disconnected (another tab, or a list that had not caught up). Show the list as it is.
      if (err instanceof ApiError && err.status === 404) await refresh();
      else reportChangeError(err, "Couldn't disconnect.");
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
    <Surface
      material='glass'
      radius='card'
      padding='md'
      id={`channel-${channel.id}`}
      data-tour={tour ? 'channel-card' : undefined}
      data-attention={attention ? 'true' : undefined}
      className='flex h-full scroll-mt-24 flex-col gap-4'
    >
      <header className='flex flex-wrap items-start justify-between gap-3'>
        <div className='flex min-w-0 items-center gap-3'>
          <ChannelIcon platform={channel.platform} name={channel.platform} size='md' />
          <div className='min-w-0'>
            <p className='text-foreground truncate text-base font-medium'>{channel.account}</p>
            <p className='text-muted-foreground truncate text-sm'>
              {channel.platform} · {channel.accountType || 'account'}
            </p>
          </div>
          {highlight && <SuccessCheck className='text-foreground size-5 shrink-0' />}
        </div>
        <ConnectionStatus channel={channel} badge={badge} expiring={expiring} />
      </header>

      {attention && sentence && (
        <StateMessage
          kind={attentionKind(channel, expiring)}
          layout='inline'
          title={sentence}
          action={
            canManage && provider ? (
              <Button variant='glass' size='control' onClick={reconnect}>
                <Icons.refresh className='size-4' />
                Reconnect
              </Button>
            ) : canManage && !provider ? (
              <span className='text-muted-foreground text-xs'>Reconnect isn&apos;t available for {channel.platform} yet.</span>
            ) : undefined
          }
          className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3'
        />
      )}

      {!disconnected && <CapabilityChips capabilities={channel.capabilities} data-tour={tour ? 'capability-chips' : undefined} />}
      {!disconnected && channel.socialReadiness && (
        <ul className='text-muted-foreground flex flex-col gap-1 text-[13px] leading-relaxed' aria-label='Permissions for this account'>
          <li>
            {channel.socialReadiness.publishing === 'PUBLISHING_AVAILABLE'
              ? 'Can publish posts you approve.'
              : channel.socialReadiness.publishing === 'PUBLISHING_AWAITING_PROVIDER_REVIEW'
                ? 'Publishing awaits platform review.'
                : 'Can’t publish from this account.'}
          </li>
          <li>
            {channel.socialReadiness.history === 'HISTORICAL_IMPORT_AVAILABLE' ? (
              'Can import past posts.'
            ) : (
              <>
                {channel.socialReadiness.connection === 'CONNECTED' && channel.platform === 'LinkedIn'
                  ? 'LinkedIn hasn’t granted permission to import past posts.'
                  : 'Can’t import past posts right now.'}{' '}
                <Link href='/app/workspace/brand#manual-writing-samples' className='rafii-focus text-foreground rounded-sm underline underline-offset-2'>
                  Add samples manually
                </Link>
              </>
            )}
          </li>
        </ul>
      )}

      {/* A div, not a p: the scopes list expands a block inside this row. */}
      {!disconnected && (
        <div className='text-muted-foreground flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs'>
          {channel.expiresAt ? (
            <>
              <span className={cn((expiring || expired) && 'text-foreground font-medium')} title={formatDate(channel.expiresAt)}>
                {expired ? `Expired ${relativeTime(channel.expiresAt)}` : `Expires ${relativeTime(channel.expiresAt)}`}
              </span>
              <span aria-hidden>·</span>
            </>
          ) : null}
          {/* Secondary on phones: verification time and its evidence stay in the History sheet and the title. */}
          <span className='hidden md:inline' title={`Evidence: ${channel.evidenceSource.replace(/_/g, ' ')}`}>
            {identityVerifiedAt ? `Verified ${relativeTime(identityVerifiedAt)}` : 'Not verified yet'}
          </span>
          <span aria-hidden className='hidden md:inline'>
            ·
          </span>
          <ScopesList scopes={channel.scopes} />
        </div>
      )}

      {activityTotal > 0 && activity && (
        <Link
          href={`/app/queue?channel=${encodeURIComponent(channel.id)}`}
          className='rafii-focus text-muted-foreground hover:text-foreground w-fit rounded-sm text-xs underline-offset-2 hover:underline'
        >
          {[
            activity.scheduled > 0 && `${activity.scheduled} scheduled`,
            activity.held > 0 && `${activity.held} on hold`,
            activity.published > 0 && `${activity.published} published`
          ]
            .filter(Boolean)
            .join(' · ')}
        </Link>
      )}

      <div className='mt-auto flex flex-wrap gap-2 pt-1' data-tour={tour ? 'channel-actions' : undefined}>
        {canManage && !disconnected && (
          <StatefulButton
            variant='outline'
            className={cn(STATEFUL_GLASS, CONTROL_44)}
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
        <Button variant='quiet' className={CONTROL_44} onClick={() => setHistoryOpen(true)}>
          <Icons.history className='size-4' />
          History
        </Button>
        {canManage && !disconnected && provider?.hasDestinations && <DestinationPicker channelId={channel.id} platform={channel.platform} disabled={busy} />}
        {canManage && !disconnected && <DisconnectButton platform={channel.platform} account={channel.account} disabled={busy} onConfirm={disconnect} />}
      </div>
      <ChannelHistorySheet channel={channel} open={historyOpen} onOpenChange={setHistoryOpen} />
    </Surface>
  );
}
