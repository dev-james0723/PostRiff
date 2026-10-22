'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { StatefulButton } from '@/components/motion/button';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { DiscordIdentity, OAuthStart, ProviderView } from '@/lib/api/types';
import { CONNECT_CAPABILITY_OPTIONS } from '@/lib/channels/capabilities';
import { historyImportCopy } from '@/lib/channels/history-import-copy';
import { usePreferences } from '@/lib/preferences';
import { defaultConnectCapability } from '@/lib/channels/onboarding';
import { discordCopy, type DiscordCopy } from '@/lib/channels/discord-copy';
import { DiscordModeChoices, type DiscordPurpose } from './discord-mode-choices';
import { discordDiscoveryState, discordPrivateLinkActions } from '@/lib/channels/discord-personal-account';
import { mastodonReconnectServer } from '@/lib/channels/mastodon-connect';
import { rememberExpectedReconnect } from '@/lib/channels/connect-expect';
import { CONNECT_CAPABILITIES, type ConnectCapability } from '@/lib/channels/state';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useAuth } from '@/lib/auth/session';
import { cn } from '@/lib/utils';
import { CONTROL_48, SHEET_ELEVATED, STATEFUL_ACTION } from './rafii-materials';
import { YouTubePolicyAcceptance } from '@/features/youtube/policy-acceptance';

/** What opened the sheet: a provider tile, the header button, or a card's Reconnect. */
export interface ConnectRequest {
  providerId?: string;
  capability?: ConnectCapability;
  /** Manage this actor-owned identity; never a publishing-channel reconnect. */
  discordIdentityId?: string;
  discordPurpose?: DiscordPurpose;
  /** Reconnect mode: the account this grant has to land on. */
  reconnect?: { channelId: string; account: string };
}

function offeredCapabilities(provider: ProviderView | undefined): ConnectCapability[] {
  if (!provider) return [];
  return CONNECT_CAPABILITIES.filter((key) => provider.capabilities[key] === true);
}

const defaultCapability = defaultConnectCapability;

/** The launch gate and the server cap refuse with stable codes, so the refusal can be shown in the person's language. */
function discordRefusal(error: ApiError, copy: DiscordCopy): string {
  if (error.code === 'discord_access_closed') return copy.accessClosed;
  if (error.code === 'discord_capacity_reached') return copy.capacityReached;
  return error.message;
}

/** A platform that can't be connected says so as icon + words (DNA §4.3); a ready one needs no label. */
function ProviderReadiness({ provider }: { provider: ProviderView }) {
  const blocked = provider.connectReady === false;
  if (!blocked && !provider.executionPaused) return null;
  const label = blocked ? 'Not available yet' : 'Paused';
  const Icon = Icons.warning;
  return (
    <span className='text-muted-foreground inline-flex items-center gap-1 text-xs'>
      <Icon className='size-3.5 shrink-0' aria-hidden />
      {label}
    </span>
  );
}

function ProviderTile({
  provider,
  selected,
  onSelect,
  disabled = false
}: {
  provider: ProviderView;
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type='button'
      data-tour='connect-platform' data-guide-safe
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        'rafii-focus flex min-h-14 items-center gap-3 rounded-[var(--rafii-radius-control)] p-3 text-left transition-colors',
        selected ? 'rafii-glass-selected' : 'rafii-quiet hover:bg-foreground/5'
      )}
    >
      <ChannelIcon platform={provider.platform} name={provider.platform} size='md' />
      <span className='flex min-w-0 flex-col gap-0.5'>
        <span className='text-foreground text-sm font-medium'>{provider.platform}</span>
        <ProviderReadiness provider={provider} />
      </span>
    </button>
  );
}

/**
 * Platform → capability → what the platform will ask → off to the platform, in one surface.
 * The permission explanation and scopes are the API's own words (`oauthStart`), shown only
 * after the request succeeds; nothing about the grant is invented client-side. The sheet
 * stages the choice; Continue commits it (DNA §11.3).
 */
export function ConnectSheet({
  open,
  onOpenChange,
  providers,
  discordIdentities = [],
  request
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providers: ProviderView[];
  discordIdentities?: DiscordIdentity[];
  request: ConnectRequest | null;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const { locale } = usePreferences();
  const dc = discordCopy(locale);
  const { copy: importCopy, lang: importLang } = historyImportCopy(locale);
  const isMobile = useIsMobile();
  const [providerId, setProviderId] = useState<string>('');
  const [capability, setCapability] = useState<ConnectCapability>('publish');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<OAuthStart | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A Bluesky handle or a Mastodon server, when the platform needs one before connecting.
  const [inputValue, setInputValue] = useState('');
  const [checking, setChecking] = useState(false);
  const [discordPurpose, setDiscordPurpose] = useState<DiscordPurpose>('identity');
  const [discordIdentity, setDiscordIdentity] = useState('');
  const [discordGuild, setDiscordGuild] = useState('');
  const [discordGuilds, setDiscordGuilds] = useState<{ id: string; name: string }[]>([]);
  const [discoverGuilds, setDiscoverGuilds] = useState(false);
  const discordRequestGeneration = useRef(0);
  const [notSeenYet, setNotSeenYet] = useState(false);
  const { user } = useAuth();
  const policyContext = `${workspaceId}:${user?.id}:${providerId}:${capability}`;
  const [policyAvailability, setPolicyAvailability] = useState<{ context: string; allowed: boolean }>();
  const policyAllowed = policyAvailability?.context === policyContext && policyAvailability.allowed;
  const onPolicyAvailabilityChange = useCallback((allowed: boolean) => {
    setPolicyAvailability((previous) => previous?.context === policyContext && previous.allowed === allowed
      ? previous : { context: policyContext, allowed });
  }, [policyContext]);
  const client = useQueryClient();

  const provider = useMemo(() => providers.find((p) => p.id === providerId), [providers, providerId]);
  const offered = offeredCapabilities(provider);
  const reconnect = request?.reconnect ?? null;

  // Each opening starts from what opened it: the tile's provider, the card's capability,
  // or the URL deep link. The URL is the final authority for direct-entry flows such as
  // Analytics → Enable analytics; this avoids losing the intended provider/capability
  // during hydration or parent state races. Equivalent React Query provider-array refreshes
  // must not reset an in-progress choice, so depend on the stable provider id signature.
  const providerSignature = providers.map((provider) => provider.id).join('|');
  useEffect(() => {
    discordRequestGeneration.current += 1;
    if (!open) return;
    const search = new URLSearchParams(window.location.search);
    const urlProviderId = search.get('connect') ?? undefined;
    const urlCapabilityValue = search.get('capability');
    const urlCapability = CONNECT_CAPABILITIES.find((value) => value === urlCapabilityValue);
    const requestedProviderId = urlProviderId ?? request?.providerId;
    const requestedCapability = urlCapability ?? request?.capability;
    const initial = providers.find((p) => p.id === requestedProviderId) ?? providers[0];

    setProviderId(initial?.id ?? '');
    setCapability(defaultCapability(initial, requestedCapability));
    setDiscordPurpose(request?.discordPurpose ?? (requestedCapability === 'publish' ? 'installation' : 'identity'));
    const managedIdentity = discordIdentities.find(identity => identity.id === request?.discordIdentityId);
    setDiscordIdentity(managedIdentity?.id ?? ''); setDiscordGuild(''); setDiscordGuilds([]); setDiscoverGuilds(managedIdentity?.discoverGuilds === true);
    setPending(null);
    setError(null);
    setBusy(false);
    setInputValue(initial?.id === 'mastodon' ? mastodonReconnectServer(request?.reconnect?.account) : '');
    setNotSeenYet(false);
    return () => { discordRequestGeneration.current += 1; };
  }, [open, workspaceId, providerSignature, request?.providerId, request?.capability, request?.reconnect?.account, request?.discordIdentityId, request?.discordPurpose]);

  function choosePlatform(id: string) {
    if (busy) return;
    if (id === providerId) return;
    discordRequestGeneration.current += 1;
    setDiscordIdentity(''); setDiscordGuild(''); setDiscordGuilds([]); setDiscoverGuilds(false); setDiscordPurpose('identity');
    const next = providers.find((p) => p.id === id);
    setProviderId(id);
    setCapability(defaultCapability(next, id === 'mastodon' ? undefined : capability));
    setError(null);
    setInputValue('');
  }

  async function start() {
    if (!provider || busy || discordPurpose === 'webhook' && !provider.discordModes?.webhook.enabled) return;
    const generation = ++discordRequestGeneration.current;
    setBusy(true);
    setError(null);
    try {
      const input: Record<string, unknown> = { ...(provider.startInput ? { [provider.startInput.name]: inputValue.trim() } : {}), ...((provider.id === 'discord' || provider.id === 'mastodon') && reconnect ? { connectionId: reconnect.channelId } : {}) };
      if (provider.discordConnectionsV2) {
        Object.assign(input, { discordPurpose, discoverGuilds, identityConnectionId: discordIdentity, guildId: discordGuild });
        if (discordPurpose === 'identity') {
          if (discordIdentity) input.connectionId = discordIdentity; else delete input.connectionId;
        }
      }
      const selectedCapability = provider.discordConnectionsV2 ? discordPurpose === 'identity' ? 'identity' : 'publish' : capability;
      const started = await api.oauthStart(workspaceId, provider.id, selectedCapability, input);
      if (generation !== discordRequestGeneration.current) return;
      if (reconnect) {
        rememberExpectedReconnect({ channelId: reconnect.channelId, account: reconnect.account, transactionId: started.transactionId });
      }
      setPending(started);
    } catch (err) {
      // Ignore a completion belonging to a closed or changed connection context.
      if (generation === discordRequestGeneration.current) setError(err instanceof ApiError ? discordRefusal(err, dc) : 'Try again in a moment.');
    } finally {
      if (generation === discordRequestGeneration.current) setBusy(false);
    }
  }

  /** Bot/device flows keep their confidential claim material server-side; this checks the stored transaction. */
  async function checkCode() {
    if (!pending?.code) return;
    setChecking(true);
    setNotSeenYet(false);
    setError(null);
    try {
      const done = await api.oauthComplete(workspaceId, pending.provider, pending.code);
      if (done.connected) {
        await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
        void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        toast.success(`Connected ${done.account ?? pending.platform}`);
        onOpenChange(false);
      } else if (done.pending) {
        setNotSeenYet(true);
      } else {
        setError(done.reason || 'Start again.');
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Try again in a moment.');
    } finally {
      setChecking(false);
    }
  }

  function prepareDiscordReconnect(identity: DiscordIdentity, requestGuilds = identity.discoverGuilds === true) {
    if (busy) return;
    discordRequestGeneration.current += 1;
    setDiscordPurpose('identity'); setDiscordIdentity(identity.id); setDiscoverGuilds(requestGuilds);
    setDiscordGuild(''); setDiscordGuilds([]); setError(null);
  }

  async function loadDiscordGuilds() {
    const identity = discordIdentities.find(link => link.id === discordIdentity);
    if (busy || discordDiscoveryState(identity) !== 'ready') return;
    const generation = ++discordRequestGeneration.current;
    setBusy(true); setError(null);
    try {
      const value = await api.discordGuilds(workspaceId, discordIdentity);
      if (generation !== discordRequestGeneration.current) return;
      if (value.identityConnectionId !== discordIdentity) {
        setError('Discord returned a different identity. Reload this connection.');
        return;
      }
      setDiscordGuilds(value.guilds); setDiscordGuild('');
    } catch (err) {
      if (generation === discordRequestGeneration.current) setError(err instanceof ApiError ? err.message : 'Could not load Discord servers.');
    } finally { if (generation === discordRequestGeneration.current) setBusy(false); }
  }
  async function disconnectIdentity(id: string) {
    setBusy(true); setError(null);
    try {
      const value = await api.disconnectDiscordIdentity(workspaceId, id);
      setDiscordIdentity(''); setDiscordGuild(''); setDiscordGuilds([]);
      await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
      await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
      toast.success('Discord identity disconnected', { description: value.note });
    } catch (err) { setError(err instanceof ApiError ? err.message : 'Could not disconnect the identity.'); }
    finally { setBusy(false); }
  }
  async function updatePrivateLink(identityId: string, remove: boolean) {
    if (busy) return;
    const generation = ++discordRequestGeneration.current;
    setBusy(true); setError(null);
    try {
      await api.discordInteractionLink(workspaceId, identityId, remove);
      if (generation === discordRequestGeneration.current) {
        toast.success(dc.privateLinked);
        void client.invalidateQueries({queryKey: keys.channels(workspaceId)});
        void client.invalidateQueries({queryKey: keys.snapshot(workspaceId)});
      }
    } catch (err) {
      if (generation === discordRequestGeneration.current) setError(err instanceof ApiError ? err.message : dc.requestFailed);
    } finally { if (generation === discordRequestGeneration.current) setBusy(false); }
  }
  const selectedDiscordIdentity = discordIdentities.find(link => link.id === discordIdentity);
  const discoveryState = discordDiscoveryState(selectedDiscordIdentity);
  const discordNeedsSelection = provider?.discordConnectionsV2 && discordPurpose === 'installation' && (!discordIdentity || !discordGuild || !discordIdentities.some(x => x.id === discordIdentity && x.status === 'linked'));
  const needsInput = Boolean(provider?.startInput) && inputValue.trim().length === 0;
  const title = reconnect ? `Reconnect ${reconnect.account}` : 'Connect account';
  // Mastodon binds the return to this connection; other providers may add a different account.
  const description = reconnect
    ? providerId === 'mastodon'
      ? `Sign in as ${reconnect.account} on Mastodon. A different account cannot replace this connection.`
      : `Sign in as ${reconnect.account}${provider ? ` on ${provider.platform}` : ''}. Another account would be added separately.`
    : 'Choose a platform and what Rafii may do.';

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={isMobile ? 'bottom' : 'right'} className={cn(SHEET_ELEVATED, 'data-[side=bottom]:max-h-[92dvh] data-[side=right]:sm:max-w-md')}>
        <SheetHeader className='gap-1.5 px-5 pt-5 pr-14 pb-4'>
          <SheetTitle className='text-xl font-medium tracking-tight text-balance'>{title}</SheetTitle>
          <SheetDescription className={cn('leading-relaxed', !reconnect && 'sr-only')}>{description}</SheetDescription>
        </SheetHeader>

        <div className='flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5'>
          {error && <StateMessage kind='error' layout='inline' title="Couldn't start connecting" description={error} className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3' />}

          {pending ? (
            <div className='flex flex-col gap-4'>
              <div className='flex items-center gap-2 text-sm font-medium'>
                <ChannelIcon platform={pending.platform} name={pending.platform} />
                {pending.platform} · {CONNECT_CAPABILITY_OPTIONS.find((c) => c.key === pending.capability)?.label ?? pending.capability}
              </div>
              {pending.capability === 'analytics' && ['threads', 'instagram'].includes(pending.provider) ? (
                <div className='flex flex-col gap-2 text-sm leading-relaxed' lang={importLang}>
                  <p>{importCopy.analyticsAccess}</p><p>{importCopy.metadata}</p><p>{importCopy.purge}</p>
                </div>
              ) : <p className='text-sm leading-relaxed'>{pending.permissionExplanation}</p>}
              {/* Permissions stay explicit: they are what the person is about to grant. */}
              <div className='flex flex-col gap-1.5'>
                <span className='text-muted-foreground text-xs'>Permissions requested</span>
                {pending.scopes.length > 0 ? (
                  <ul className='flex flex-wrap gap-1.5' aria-label='Permissions requested'>
                    {pending.scopes.map((scope) => (
                      <li key={scope} className='rafii-quiet rounded-md px-2 py-1 font-mono text-xs'>
                        {scope}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className='text-muted-foreground text-xs'>None</span>
                )}
              </div>
              {(pending.connectKind === 'bot_code' || pending.connectKind === 'device_code') && pending.code ? (
                <div className='flex flex-col gap-3'>
                  <ol className='flex list-decimal flex-col gap-1.5 pl-5 text-sm leading-relaxed'>
                    {(pending.instructions ?? []).map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                  {pending.connectKind === 'bot_code' ? (
                    <div className='flex items-center gap-2'>
                      <code className='rafii-field min-w-0 flex-1 rounded-md px-2 py-1.5 font-mono text-sm break-all' aria-label='Code to post in your channel'>
                        {pending.code}
                      </code>
                      <Button
                        variant='glass'
                        size='control'
                        onClick={() => void navigator.clipboard.writeText(pending.code ?? '').then(() => toast.success('Code copied'))}
                      >
                        <Icons.copy className='size-4' aria-hidden />
                        Copy
                      </Button>
                    </div>
                  ) : pending.userCode ? (
                    <div className='flex flex-col gap-1.5'>
                      <span className='text-muted-foreground text-xs'>Provider confirmation code</span>
                      <code className='rafii-field w-fit rounded-md px-2 py-1.5 font-mono text-sm' aria-label='Provider confirmation code'>
                        {pending.userCode}
                      </code>
                    </div>
                  ) : null}
                  {notSeenYet && (
                    <StateMessage
                      kind='partial'
                      layout='inline'
                      title={pending.connectKind === 'device_code' ? `${pending.platform} is still waiting for your approval.` : `${pending.botUsername ?? 'Rafii’s bot'} hasn’t seen the code yet.`}
                      description={pending.connectKind === 'device_code' ? 'Finish the provider-controlled QR confirmation, or cancel there. Rafii cannot approve it for you.' : 'Check that the bot is an admin that can post, then post the code again.'}
                      className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3'
                    />
                  )}
                </div>
              ) : (
                <p className='text-muted-foreground text-xs leading-relaxed'>You&apos;ll confirm the account when {pending.platform} sends you back.</p>
              )}
            </div>
          ) : providers.length === 0 ? (
            <StateMessage
              kind='partial'
              layout='inline'
              title='No platforms available yet.'
            />
          ) : (
            <>
              {!reconnect && (
                <section className='flex flex-col gap-2' aria-labelledby='connect-platform-heading'>
                  <h3 id='connect-platform-heading' className='text-sm font-medium'>
                    Platform
                  </h3>
                  <div className='grid gap-2 sm:grid-cols-2'>
                    {providers.map((p) => (
                      <ProviderTile key={p.id} provider={p} selected={p.id === providerId} disabled={busy} onSelect={() => choosePlatform(p.id)} />
                    ))}
                  </div>
                </section>
              )}

              {provider && (
                <div className='text-muted-foreground flex flex-col gap-1.5 text-[13px] leading-relaxed'>
                  {provider.connectReady === false ? (
                    <p className='text-foreground'>{provider.id === 'discord' && provider.discordAccess?.status === 'closed' ? dc.accessClosed : `${provider.platform} isn't available yet.`}</p>
                  ) : <p>{provider.accountRequirement}</p>}
                  {/* Setup detail for whoever runs the workspace: available on request, never the headline. */}
                  {Boolean(provider.setupIssues?.length || (provider.callbackUri && provider.connectReady === false)) && (
                    <details className='text-xs'>
                      <summary className='rafii-focus w-fit cursor-pointer rounded-sm'>Details</summary>
                      <div className='flex flex-col gap-1.5 pt-1.5'>
                        {provider.setupIssues?.map((issue) => (
                          <p key={issue} className='flex items-start gap-1.5'>
                            <Icons.warning className='mt-0.5 size-3.5 shrink-0' aria-hidden />
                            {issue}
                          </p>
                        ))}
                        {provider.callbackUri && provider.connectReady === false && (
                          <p className='break-all'>
                            Callback: <code className='rafii-field rounded-md px-1.5 py-0.5 font-mono'>{provider.callbackUri}</code>
                          </p>
                        )}
                      </div>
                    </details>
                  )}
                  {provider.id === 'linkedin' && !provider.historyAvailableForApp && <p>LinkedIn doesn&apos;t share past posts yet. Add your own text in Learn my voice.</p>}
                </div>
              )}

              {provider?.startInput && provider.connectReady !== false && (
                <div className='flex flex-col gap-1.5'>
                  <Label htmlFor='connect-start-input' className='text-sm font-medium'>
                    {provider.startInput.label}
                  </Label>
                  <Input
                    id='connect-start-input'
                    value={inputValue}
                    onChange={(event) => setInputValue(event.target.value)}
                    placeholder={providerId === 'mastodon' ? 'your-server.example or @name@your-server.example' : provider.startInput.placeholder ?? undefined}
                    aria-describedby={providerId === 'mastodon' ? 'mastodon-server-help' : undefined}
                    inputMode={providerId === 'mastodon' ? 'url' : 'text'}
                    disabled={busy}
                    autoComplete='off'
                    autoCapitalize='none'
                    spellCheck={false}
                    maxLength={253}
                  />
                  {providerId === 'mastodon' && (
                    <p id='mastodon-server-help' className='text-muted-foreground text-xs leading-relaxed'>Your Mastodon server hosts your account. Enter its domain, HTTPS URL or @name@server. You will approve access on that server. Each connected account keeps its own permissions.</p>
                  )}
                </div>
              )}

              {providerId === 'youtube' && (
                <YouTubePolicyAcceptance key={policyContext}
                  force={capability !== 'identity' && capability !== 'posts_read'}
                  onAvailabilityChange={onPolicyAvailabilityChange} />
              )}
              {provider?.discordConnectionsV2 && (
                <section className='flex flex-col gap-3' aria-label='Discord connection steps'>
                  <p className='text-sm'>{dc.identityStep}</p>
                  <p className='text-muted-foreground text-xs'>{dc.botStep}</p>
                  <DiscordModeChoices purpose={discordPurpose} busy={busy} modes={provider.discordModes} copy={dc} onChange={purpose => {
                    if (busy) return;
                    discordRequestGeneration.current += 1; setDiscordPurpose(purpose); setDiscordGuild(''); setDiscordGuilds([]); setError(null);
                    if (purpose === 'webhook' && !discordIdentities.some(x => x.id === discordIdentity && x.status === 'linked' && x.discoverGuilds === true)) setDiscordIdentity('');
                  }} />
                  {discordIdentities.map(link => (
                    <div key={link.id} className='rafii-quiet flex flex-wrap items-center gap-2 rounded-md p-2 text-sm'>
                      <span className='min-w-0 break-words'>{link.account} · {link.userId} · {link.status === 'linked' ? dc.statusLinked : link.status === 'disconnected' ? dc.statusDisconnected : link.status === 'reconnect_required' ? dc.statusReconnect : dc.statusUnknown}</span>
                      {link.privateDraftsLinked !== undefined && <span className='text-muted-foreground text-xs'>{link.privateDraftsLinked ? dc.privateStoredLinked : dc.privateStoredUnlinked}</span>}
                      <Button size='sm' className='min-h-11' variant='glass' disabled={busy} onClick={() => prepareDiscordReconnect(link)}>{dc.reconnectIdentity}</Button>
                      {discordPrivateLinkActions(link, provider.discordModes?.userInstall.enabled === true).bind &&
                        <Button size='sm' className='min-h-11' variant='glass' disabled={busy} onClick={() => void updatePrivateLink(link.id, false)}>{dc.linkPrivate}</Button>}
                      {discordPrivateLinkActions(link, provider.discordModes?.userInstall.enabled === true).remove &&
                        <Button size='sm' className='min-h-11' variant='glass' disabled={busy} onClick={() => void updatePrivateLink(link.id, true)}>{dc.unlinkPrivate}</Button>}
                      {link.status !== 'disconnected' && <Button size='sm' className='min-h-11' variant='glass' disabled={busy} onClick={() => void disconnectIdentity(link.id)}>{dc.disconnectIdentity}</Button>}
                    </div>
                  ))}
                  {discordPurpose === 'identity' ? (
                    <label className='flex items-start gap-2 text-sm'>
                      <input type='checkbox' aria-label={dc.discoverGuilds}
                        checked={discoverGuilds} disabled={busy} onChange={e => setDiscoverGuilds(e.target.checked)} />
                      {dc.discoverGuilds}
                    </label>
                  ) : discordPurpose === 'installation' ? (
                    <>
                      <label className='flex flex-col gap-1 text-sm'>{dc.identityLabel}
                        <select aria-label={dc.identityLabel} value={discordIdentity} disabled={busy} onChange={e => { discordRequestGeneration.current += 1; setDiscordIdentity(e.target.value); setDiscordGuild(''); setDiscordGuilds([]); setError(null); }} className='rafii-quiet rounded-md p-2'>
                          <option value=''>{dc.chooseIdentity}</option>
                          {discordIdentities.filter(x => x.status === 'linked').map(x => <option key={x.id} value={x.id}>{x.account} · {x.userId}</option>)}
                        </select>
                      </label>
                      {discoveryState === 'scope_required' && <div className='rafii-quiet flex flex-col gap-2 rounded-md p-3 text-sm'>
                        <p>{dc.scopeNeeded}</p>
                        <Button variant='glass' disabled={busy} onClick={() => { if (selectedDiscordIdentity) prepareDiscordReconnect(selectedDiscordIdentity, true); }}>{dc.scopeUpgrade}</Button>
                        <p className='text-muted-foreground text-xs'>{dc.scopeReview}</p>
                      </div>}
                      {discoveryState === 'reconnect_required' && <p className='text-muted-foreground text-sm'>{dc.reconnectBeforeServer}</p>}
                      <Button variant='glass' disabled={discoveryState !== 'ready' || busy} onClick={() => void loadDiscordGuilds()}>{dc.loadServers}</Button>
                      <label className='flex flex-col gap-1 text-sm'>{dc.serverLabel}
                        <select aria-label={dc.serverLabel} value={discordGuild} disabled={busy} onChange={e => setDiscordGuild(e.target.value)} className='rafii-quiet rounded-md p-2'>
                          <option value=''>{dc.chooseServer}</option>
                          {discordGuilds.map(x => <option key={x.id} value={x.id}>{x.name} · {x.id}</option>)}
                        </select>
                      </label>
                      <p className='text-muted-foreground text-xs'>{dc.separateChannel}</p>
                    </>
                  ) : discordPurpose === 'webhook' ? (
                    <label className='flex flex-col gap-1 text-sm'>{dc.webhookIdentityLabel}
                      <select aria-label={dc.webhookIdentityLabel} value={discordIdentity} disabled={busy}
                        onChange={e => { discordRequestGeneration.current += 1; setDiscordIdentity(e.target.value); setError(null); }}
                        className='rafii-quiet rounded-md p-2'>
                        <option value=''>{dc.webhookIdentityNone}</option>
                        {discordIdentities.filter(x => x.status === 'linked' && x.discoverGuilds === true).map(x =>
                          <option key={x.id} value={x.id}>{x.account} · {x.userId}</option>)}
                      </select>
                    </label>
                  ) : null}
                  <p className='text-muted-foreground text-xs'>{dc.reconnectNotice}</p>
                  <p className='text-muted-foreground text-xs'>{dc.disconnectNotice}</p>
                </section>
              )}
              {!provider?.discordConnectionsV2 && (
              <section className='flex flex-col gap-2' aria-labelledby='connect-capability-heading' data-tour='connect-capability'>
                <h3 id='connect-capability-heading' className='text-sm font-medium'>
                  What Rafii may do
                </h3>
                {offered.length === 0 ? (
                  <StateMessage kind='unsupported' layout='inline' title={`Nothing to connect on ${provider?.platform ?? 'this platform'} yet.`} />
                ) : (
                  <RadioGroup value={capability} onValueChange={(value) => {
                    discordRequestGeneration.current += 1;
                    setBusy(false);
                    setError(null);
                    setCapability(value as ConnectCapability);
                  }} aria-labelledby='connect-capability-heading'>
                    {CONNECT_CAPABILITY_OPTIONS.filter((option) => offered.includes(option.key)).map((option) => (
                      <RadioGroupItem
                        key={option.key}
                        value={option.key}
                        aria-label={option.label}
                        label={option.label}
                        description={option.key === 'analytics' && provider && ['threads', 'instagram'].includes(provider.id) ? importCopy.analyticsAccess : option.description}
                        className='rafii-quiet rounded-[var(--rafii-radius-control)] p-3 transition-colors data-[state=checked]:rafii-glass-selected'
                      />
                    ))}
                  </RadioGroup>
                )}
                {provider && (provider.executionPaused || !provider.productionReviewed) && (
                  <p className='text-muted-foreground text-xs leading-relaxed'>
                    {provider.executionPaused ? `${provider.platform} is paused.` : providerId === 'mastodon' ? 'Connecting your account does not enable publishing. Publishing is available only when Rafii reports it ready.' : 'Publishing awaits platform review. Test accounts can still connect.'}
                  </p>
                )}
              </section>
              )}
            </>
          )}
        </div>

        <SheetFooter className='flex-row flex-wrap justify-end gap-2 px-5 pb-[max(1rem,env(safe-area-inset-bottom))]'>
          {pending ? (
            <>
              <Button variant='glass' size='control' onClick={() => setPending(null)}>
                Back
              </Button>
              {pending.connectKind === 'bot_code' || pending.connectKind === 'device_code' ? (
                <>
                  {pending.connectKind === 'device_code' && pending.authorizeUrl && (
                    <a href={pending.authorizeUrl} target='_blank' rel='noreferrer' className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'gap-2')}>
                      Open {pending.platform}
                      <Icons.externalLink className='size-4' aria-hidden />
                    </a>
                  )}
                  <StatefulButton
                    variant='primary'
                    className={cn(STATEFUL_ACTION, CONTROL_48)}
                    state={checking ? 'loading' : 'idle'}
                    loadingText='Checking…'
                    onClick={() => void checkCode()}
                  >
                    Check connection
                  </StatefulButton>
                </>
              ) : pending.authorizeUrl ? (
                <a href={pending.authorizeUrl} data-tour='connect-authorize' className={cn(buttonVariants({ variant: 'action', size: 'control' }), 'gap-2')}>
                  Continue to {pending.platform}
                  <Icons.externalLink className='size-4' aria-hidden />
                </a>
              ) : null}
            </>
          ) : (
            <>
              <Button variant='glass' size='control' onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <StatefulButton
                data-tour='connect-continue'
                variant='primary'
                className={cn(STATEFUL_ACTION, CONTROL_48)}
                state={busy ? 'loading' : 'idle'}
                loadingText='Preparing…'
                disabled={!provider || provider.connectReady === false || provider.executionPaused || offered.length === 0 || needsInput || discordNeedsSelection || discordPurpose === 'webhook' && !provider.discordModes?.webhook.enabled || providerId === 'youtube' && !policyAllowed}
                onClick={() => void start()}
              >
                Continue
              </StatefulButton>
            </>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
