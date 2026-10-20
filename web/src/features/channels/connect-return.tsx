'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { OAuthComplete } from '@/lib/api/types';
import { takeExpectedReconnect } from '@/lib/channels/connect-expect';
import { missingScopePublishingMessage } from '@/lib/channels/discord-personal-account';
import { usePreferences } from '@/lib/preferences';
import { discordCopy } from '@/lib/channels/discord-copy';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/**
 * Handles the platform's return (`/channels/connect?provider&state&code`) with the authenticated exchange.
 * Only the Rafii-owned surfaces are styled here; the exchange, its query handling and redirects are untouched.
 */
export function ConnectReturn() {
  const params = useSearchParams();
  const dc = discordCopy(usePreferences().locale);
  const router = useRouter();
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const handled = useRef(false);
  const { user } = useAuth();
  const activeDiscordContext = useRef('');
  const startedDiscordContext = useRef('');
  const [result, setResult] = useState<OAuthComplete | null>(null);
  const [error, setError] = useState<string | null>(null);

  const provider = params.get('provider') ?? '';
  const state = params.get('state') ?? '';
  const discordContext = JSON.stringify([workspaceId, user?.id ?? '', provider, state]);
  activeDiscordContext.current = discordContext;

  useEffect(() => {
    if (handled.current) {
      if (provider === 'discord' && startedDiscordContext.current !== discordContext) setError(dc.callbackContextChanged);
      return;
    }
    handled.current = true;
    startedDiscordContext.current = discordContext;
    const staleDiscord = () => provider === 'discord' && activeDiscordContext.current !== discordContext;
    if (!provider || !state) {
      setError('This link is incomplete. Start again from Channels.');
      return;
    }
    api
      // `iss` names the authorization server that answered (including Discord); the API checks it against the one it started with.
      .oauthComplete(workspaceId, provider, state, params.get('code') ?? undefined, params.get('error') ?? undefined, params.get('iss') ?? undefined)
      .then(async (value) => {
        if (staleDiscord()) return;
        // A reconnect parked the account it was meant for; read it once whatever the outcome.
        const expected = takeExpectedReconnect();
        // The API returns `connectionId` (oauth.py: complete); the TS type does not list it yet.
        const connectionId = (value as { connectionId?: string }).connectionId;
        await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
        void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
        await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        if (staleDiscord()) return;
        if (value.connected && connectionId) {
          if (value.discordPurpose === 'identity') toast.success(dc.callbackIdentity, { description: dc.identityNotice });
          if (value.discordPurpose === 'webhook') toast.success(dc.callbackWebhook);
          if (value.missingScopes?.length) {
            toast.warning('Some permissions weren’t granted', { description: `Missing: ${value.missingScopes.join(', ')}. ${provider === 'discord' ? dc.publishUnavailable : missingScopePublishingMessage(provider)}` });
          }
          if (expected && expected.channelId !== connectionId) {
            toast.warning(`Different account connected. ${expected.account} still needs reconnecting.`);
          }
          // Straight back to Channels: the page scrolls to the new card and plays its check once.
          router.replace(`/app/channels?connected=${encodeURIComponent(connectionId)}`);
          return;
        }
        setResult(value);
      })
      .catch((err) => { if (!staleDiscord()) setError(err instanceof ApiError ? err.message : 'Start again from Channels.'); });
  }, [api, client, params, provider, router, state, workspaceId, dc, discordContext]);

  const back = (
    <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
      Back to Channels
    </Link>
  );

  return (
    <PageContainer pageTitle='Finishing connection' width='reading'>
      <div className='flex max-w-xl flex-col gap-4'>
        {!result && !error && <StateMessage kind='loading' title='Confirming your account…' />}
        {error && <StateMessage kind='error' title="Couldn't connect" description={error} action={back} />}
        {result &&
          (result.connected ? (
            <StateMessage
              kind='success'
              title={`Connected ${result.account ?? ''}`.trim()}
              description={result.missingScopes?.length ? `Missing permissions: ${result.missingScopes.join(', ')}. ${provider === 'discord' ? dc.publishUnavailable : missingScopePublishingMessage(provider)}` : undefined}
              action={back}
            />
          ) : (
            <StateMessage kind='error' title='Access not granted' description={result.reason || undefined} action={back} />
          ))}
      </div>
    </PageContainer>
  );
}
