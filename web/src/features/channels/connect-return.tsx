'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { OAuthComplete } from '@/lib/api/types';
import { takeExpectedReconnect } from '@/lib/channels/connect-expect';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/** Handles the provider's return (`/channels/connect?provider&state&code`) with the authenticated exchange. */
export function ConnectReturn() {
  const params = useSearchParams();
  const router = useRouter();
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const handled = useRef(false);
  const [result, setResult] = useState<OAuthComplete | null>(null);
  const [error, setError] = useState<string | null>(null);

  const provider = params.get('provider') ?? '';
  const state = params.get('state') ?? '';

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    if (!provider || !state) {
      setError('This return link is incomplete. Start the connection again from Channels.');
      return;
    }
    api
      .oauthComplete(workspaceId, provider, state, params.get('code') ?? undefined, params.get('error') ?? undefined)
      .then(async (value) => {
        // A reconnect parked the account it was meant for; read it once whatever the outcome.
        const expected = takeExpectedReconnect();
        // The API returns `connectionId` (oauth.py: complete); the TS type does not list it yet.
        const connectionId = (value as { connectionId?: string }).connectionId;
        await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
        void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
        await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        if (value.connected && connectionId) {
          if (value.missingScopes?.length) {
            toast.warning(`Missing scopes: ${value.missingScopes.join(', ')} — publishing stays Assisted.`);
          }
          if (expected && expected.channelId !== connectionId) {
            toast.warning(`You connected a different account; ${expected.account} still needs reconnecting.`);
          }
          // Straight back to Channels: the page scrolls to the new card and plays its check once.
          router.replace(`/app/channels?connected=${encodeURIComponent(connectionId)}`);
          return;
        }
        setResult(value);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'The connection could not be completed.'));
  }, [api, client, params, provider, router, state, workspaceId]);

  return (
    <PageContainer pageTitle='Finishing connection' pageDescription='Confirming the account the provider returned.'>
      <div className='flex max-w-xl flex-col gap-4'>
        {!result && !error && <Skeleton className='h-24 w-full' />}
        {error && (
          <Alert variant='destructive'>
            <Icons.alertCircle className='size-4' />
            <AlertTitle>Not connected</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {result && (
          <Alert variant={result.connected ? 'default' : 'destructive'}>
            {result.connected ? <Icons.circleCheck className='size-4' /> : <Icons.alertCircle className='size-4' />}
            <AlertTitle>{result.connected ? `Connected ${result.account ?? ''}` : 'Connection was not granted'}</AlertTitle>
            <AlertDescription>
              {result.connected
                ? `Confirm this is the right account on the Channels page.${
                    result.missingScopes?.length
                      ? ` Missing scopes: ${result.missingScopes.join(', ')} — publishing stays Assisted.`
                      : ''
                  }`
                : result.reason || 'Nothing was stored.'}
            </AlertDescription>
          </Alert>
        )}
        <Link href='/app/channels' className={buttonVariants({ variant: 'outline' })}>
          Back to Channels
        </Link>
      </div>
    </PageContainer>
  );
}
