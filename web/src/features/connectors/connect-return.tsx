'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import PageContainer from '@/components/layout/page-container';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function ProductivityConnectorReturn() {
  const params = useSearchParams();
  const router = useRouter();
  const { api, workspaceId } = useWorkspaceApi();
  const handled = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const provider = params.get('provider') ?? '';
  const state = params.get('state') ?? '';

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    if (!provider || !state) {
      setError('This connection link is incomplete. Start again from Connected apps.');
      return;
    }

    api
      .connectorOauthComplete(
        workspaceId,
        provider,
        state,
        params.get('code') ?? undefined,
        params.get('error') ?? undefined
      )
      .then((value) => {
        if (value.connected) {
          router.replace(
            `/app?connector=${encodeURIComponent(provider)}&connected=1`,
            { scroll: false }
          );
          return;
        }
        setError('Access was not granted. Start again from Connected apps.');
      })
      .catch((err) =>
        setError(
          err instanceof ApiError
            ? err.message
            : 'This connected app could not be confirmed. Try connecting it again.'
        )
      );
  }, [api, params, provider, router, state, workspaceId]);

  const back = (
    <Link href='/app' className={buttonVariants({ variant: 'glass', size: 'control' })}>
      Back to Rafii
    </Link>
  );

  return (
    <PageContainer pageTitle='Finishing connection' width='reading'>
      <div className='flex max-w-xl flex-col gap-4'>
        {!error && <StateMessage kind='loading' title='Confirming your connected app…' />}
        {error && (
          <StateMessage
            kind='error'
            title="Couldn't connect"
            description={error}
            action={back}
          />
        )}
      </div>
    </PageContainer>
  );
}
