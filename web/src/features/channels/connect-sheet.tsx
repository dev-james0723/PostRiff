'use client';

import { useEffect, useMemo, useState } from 'react';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { StatefulButton } from '@/components/motion/button';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import type { OAuthStart, ProviderView } from '@/lib/api/types';
import { CONNECT_CAPABILITY_OPTIONS } from '@/lib/channels/capabilities';
import { defaultConnectCapability } from '@/lib/channels/onboarding';
import { rememberExpectedReconnect } from '@/lib/channels/connect-expect';
import { CONNECT_CAPABILITIES, type ConnectCapability } from '@/lib/channels/state';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CONTROL_48, SHEET_ELEVATED, STATEFUL_ACTION } from './rafii-materials';

/** What opened the sheet: a provider tile, the header button, or a card's Reconnect. */
export interface ConnectRequest {
  providerId?: string;
  capability?: ConnectCapability;
  /** Reconnect mode: the account this grant has to land on. */
  reconnect?: { channelId: string; account: string };
}

function offeredCapabilities(provider: ProviderView | undefined): ConnectCapability[] {
  if (!provider) return [];
  return CONNECT_CAPABILITIES.filter((key) => provider.capabilities[key] === true);
}

const defaultCapability = defaultConnectCapability;

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
  onSelect
}: {
  provider: ProviderView;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type='button'
      aria-pressed={selected}
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
  request
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providers: ProviderView[];
  request: ConnectRequest | null;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const isMobile = useIsMobile();
  const [providerId, setProviderId] = useState<string>('');
  const [capability, setCapability] = useState<ConnectCapability>('publish');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<OAuthStart | null>(null);
  const [error, setError] = useState<string | null>(null);

  const provider = useMemo(() => providers.find((p) => p.id === providerId), [providers, providerId]);
  const offered = offeredCapabilities(provider);
  const reconnect = request?.reconnect ?? null;

  // Each opening starts from what opened it: the tile's provider, the card's capability, or the first provider.
  useEffect(() => {
    if (!open) return;
    const initial = providers.find((p) => p.id === request?.providerId) ?? providers[0];
    setProviderId(initial?.id ?? '');
    setCapability(defaultCapability(initial, request?.capability));
    setPending(null);
    setError(null);
    setBusy(false);
  }, [open, providers, request]);

  function choosePlatform(id: string) {
    const next = providers.find((p) => p.id === id);
    setProviderId(id);
    setCapability(defaultCapability(next, capability));
    setError(null);
  }

  async function start() {
    if (!provider) return;
    setBusy(true);
    setError(null);
    try {
      const started = await api.oauthStart(workspaceId, provider.id, capability);
      if (reconnect) {
        rememberExpectedReconnect({ channelId: reconnect.channelId, account: reconnect.account, transactionId: started.transactionId });
      }
      setPending(started);
    } catch (err) {
      // Shown inline above the choices; no toast on top of it.
      setError(err instanceof ApiError ? err.message : 'Try again in a moment.');
    } finally {
      setBusy(false);
    }
  }

  const title = reconnect ? `Reconnect ${reconnect.account}` : 'Connect account';
  // Reconnect keeps its one real gotcha visible: signing in as someone else adds a new account.
  const description = reconnect
    ? `Sign in as ${reconnect.account}${provider ? ` on ${provider.platform}` : ''}. Another account would be added separately.`
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
              <p className='text-sm leading-relaxed'>{pending.permissionExplanation}</p>
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
              <p className='text-muted-foreground text-xs leading-relaxed'>You&apos;ll confirm the account when {pending.platform} sends you back.</p>
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
                      <ProviderTile key={p.id} provider={p} selected={p.id === providerId} onSelect={() => choosePlatform(p.id)} />
                    ))}
                  </div>
                </section>
              )}

              {provider && (
                <div className='text-muted-foreground flex flex-col gap-1.5 text-[13px] leading-relaxed'>
                  {provider.connectReady === false ? <p className='text-foreground'>{provider.platform} isn&apos;t available yet.</p> : <p>{provider.accountRequirement}</p>}
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

              <section className='flex flex-col gap-2' aria-labelledby='connect-capability-heading'>
                <h3 id='connect-capability-heading' className='text-sm font-medium'>
                  What Rafii may do
                </h3>
                {offered.length === 0 ? (
                  <StateMessage kind='unsupported' layout='inline' title={`Nothing to connect on ${provider?.platform ?? 'this platform'} yet.`} />
                ) : (
                  <RadioGroup value={capability} onValueChange={(value) => setCapability(value as ConnectCapability)} aria-labelledby='connect-capability-heading'>
                    {CONNECT_CAPABILITY_OPTIONS.filter((option) => offered.includes(option.key)).map((option) => (
                      <RadioGroupItem
                        key={option.key}
                        value={option.key}
                        label={option.label}
                        description={option.description}
                        className='rafii-quiet rounded-[var(--rafii-radius-control)] p-3 transition-colors data-[state=checked]:rafii-glass-selected'
                      />
                    ))}
                  </RadioGroup>
                )}
                {provider && (provider.executionPaused || !provider.productionReviewed) && (
                  <p className='text-muted-foreground text-xs leading-relaxed'>
                    {provider.executionPaused ? `${provider.platform} is paused.` : 'Publishing awaits platform review. Test accounts can still connect.'}
                  </p>
                )}
              </section>
            </>
          )}
        </div>

        <SheetFooter className='flex-row flex-wrap justify-end gap-2 px-5 pb-[max(1rem,env(safe-area-inset-bottom))]'>
          {pending ? (
            <>
              <Button variant='glass' size='control' onClick={() => setPending(null)}>
                Back
              </Button>
              <a href={pending.authorizeUrl} className={cn(buttonVariants({ variant: 'action', size: 'control' }), 'gap-2')}>
                Continue to {pending.platform}
                <Icons.externalLink className='size-4' aria-hidden />
              </a>
            </>
          ) : (
            <>
              <Button variant='glass' size='control' onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <StatefulButton
                variant='primary'
                className={cn(STATEFUL_ACTION, CONTROL_48)}
                state={busy ? 'loading' : 'idle'}
                loadingText='Preparing…'
                disabled={!provider || provider.connectReady === false || provider.executionPaused || offered.length === 0}
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
