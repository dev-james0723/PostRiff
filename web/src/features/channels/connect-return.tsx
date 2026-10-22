'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { keys, useMe } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { OAuthComplete } from '@/lib/api/types';
import { takeExpectedReconnect } from '@/lib/channels/connect-expect';
import { missingScopePublishingMessage } from '@/lib/channels/discord-personal-account';
import { usePreferences } from '@/lib/preferences';
import { discordCopy } from '@/lib/channels/discord-copy';
import { discordRefusal } from '@/lib/channels/discord-refusal';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/**
 * Handles the platform's return (`/channels/connect?provider&state&code`) with the authenticated exchange.
 * Only the Rafii-owned surfaces are styled here; the exchange, its query handling and redirects are untouched.
 */
/** One-use Discord OAuth must not exchange again if Next re-mounts this view.
 * Only public account metadata is retained by these bounded in-memory promises.
 * The cache is per browser JS runtime and scoped to the exact signed-in actor,
 * workspace, provider and OAuth callback response; it is never persisted.
 */
const discordOAuthExchanges = new Map<string, Promise<OAuthComplete>>();
function discordSingleFlight(key: string, start: () => Promise<OAuthComplete>): Promise<OAuthComplete> {
  const previous = discordOAuthExchanges.get(key);
  if (previous) return previous;
  const request = start();
  discordOAuthExchanges.set(key, request);
  if (discordOAuthExchanges.size > 32) {
    const oldest = discordOAuthExchanges.keys().next().value;
    if (oldest) discordOAuthExchanges.delete(oldest);
  }
  return request;
}

export function ConnectReturn() {
  const params = useSearchParams();
  const dc = discordCopy(usePreferences().locale);
  const me = useMe();
  const router = useRouter();
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const handled = useRef(false);
  const mounted = useRef(false);
  const { user, status: authStatus } = useAuth();
  const activeDiscordContext = useRef('');
  const startedDiscordContext = useRef('');
  const [result, setResult] = useState<OAuthComplete | null>(null);
  const [error, setError] = useState<string | null>(null);

  const provider = params.get('provider') ?? '';
  const callbackCopy = provider === 'discord' ? dc : discordCopy('en');
  const state = params.get('state') ?? '';
  const discordContext = JSON.stringify([workspaceId, user?.id ?? '', provider, state]);
  activeDiscordContext.current = discordContext;

  // Layout hydration can remount this view while the one-use exchange is shared.
  // Only the currently mounted view may consume reconnect state or notify.
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    // Do not consume a single-use OAuth code before authentication is ready.
    if (provider === 'discord' && (authStatus === 'loading' || !workspaceId)) return;
    if (provider === 'discord' && authStatus !== 'signed-in') {
      setError(callbackCopy.callbackSignIn);
      return;
    }
    // Preferences re-key the page when this existing profile query resolves.
    if (provider === 'discord' && me.isPending) return;
    if (handled.current) {
      if (provider === 'discord' && startedDiscordContext.current !== discordContext) setError(dc.callbackContextChanged);
      return;
    }
    handled.current = true;
    startedDiscordContext.current = discordContext;
    const staleDiscord = () => provider === 'discord' && (!mounted.current || activeDiscordContext.current !== discordContext);
    if (!provider || !state) {
      setError(callbackCopy.callbackIncomplete);
      return;
    }
    // The server independently verifies `iss` and the exact OAuth transaction.
    const start = () => api.oauthComplete(workspaceId, provider, state, params.get('code') ?? undefined,
      params.get('error') ?? undefined, params.get('iss') ?? undefined);
    const exchange = provider === 'discord'
      ? discordSingleFlight(JSON.stringify([discordContext, params.get('code'), params.get('error'), params.get('iss')]), start)
      : start();
    void exchange.then(async (value) => {
        if (staleDiscord()) return;
        const expectedBeforeRefresh = provider === 'discord' ? null : takeExpectedReconnect();
        // The API returns `connectionId` (oauth.py: complete); the TS type does not list it yet.
        const connectionId = (value as { connectionId?: string }).connectionId;
        await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
        void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
        await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        if (staleDiscord()) return;
        // Consume only after refresh: an old view may have unmounted while awaiting it.
        const expected = provider === 'discord' ? takeExpectedReconnect() : expectedBeforeRefresh;
        if (value.connected && connectionId) {
          if (value.discordPurpose === 'identity') toast.success(dc.callbackIdentity, { description: dc.identityNotice });
          if (value.discordPurpose === 'webhook') toast.success(dc.callbackWebhook);
          if (value.missingScopes?.length) {
            toast.warning(callbackCopy.callbackPermissionsTitle, { description: provider === 'discord' ? `${dc.callbackMissingPermissions} ${value.missingScopes.join(', ')}. ${dc.publishUnavailable}` : `Missing: ${value.missingScopes.join(', ')}. ${missingScopePublishingMessage(provider)}` });
          }
          if (expected && (provider === 'discord' || expected.transactionId === state) && expected.channelId !== connectionId) {
            toast.warning(callbackCopy.callbackDifferentAccount.replace('{account}', () => expected.account));
          }
          // Straight back to Channels: the page scrolls to the new card and plays its check once.
          router.replace(`/app/channels?connected=${encodeURIComponent(connectionId)}`);
          return;
        }
        setResult(value);
      })
      .catch((err) => { if (!staleDiscord()) setError(err instanceof ApiError ? (provider === 'discord' ? discordRefusal(err, dc) : err.message) : callbackCopy.callbackRetry); });
  }, [api, client, params, provider, router, state, workspaceId, dc, callbackCopy, discordContext, authStatus, me.isPending]);

  const back = (
    <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
      {callbackCopy.callbackBack}
    </Link>
  );

  return (
    <PageContainer pageTitle={callbackCopy.callbackTitle} width='reading'>
      <div className='flex max-w-xl flex-col gap-4'>
        {!result && !error && <StateMessage kind='loading' title={callbackCopy.callbackConfirming} />}
        {error && <StateMessage kind='error' title={callbackCopy.callbackFailed} description={error} action={back} />}
        {result &&
          (result.connected ? (
            <StateMessage
              kind='success'
              title={callbackCopy.callbackConnected.replace('{account}', () => result.account ?? '').trim()}
              description={result.missingScopes?.length ? `${callbackCopy.callbackMissingPermissions} ${result.missingScopes.join(', ')}. ${provider === 'discord' ? dc.publishUnavailable : missingScopePublishingMessage(provider)}` : undefined}
              action={back}
            />
          ) : (
            <StateMessage kind='error' title={callbackCopy.callbackDenied} description={result.reason || undefined} action={back} />
          ))}
      </div>
    </PageContainer>
  );
}
