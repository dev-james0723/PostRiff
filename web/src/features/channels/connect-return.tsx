'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { OAuthComplete } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/** Handles the provider's return (`/channels/connect?provider&state&code`) with the authenticated exchange. */
export function ConnectReturn() {
  const params = useSearchParams();
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
        setResult(value);
        await client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
        await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'The connection could not be completed.'));
  }, [api, client, params, provider, state, workspaceId]);

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
