'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { StateMessage } from '@/components/rafii';

export function ConnectorConnectForwarder() {
  const router = useRouter();
  const params = useSearchParams();

  useEffect(() => {
    router.replace(`/app/connectors/connect?${params.toString()}`);
  }, [router, params]);

  return (
    <main className='flex min-h-dvh items-center justify-center px-4'>
      <StateMessage kind='loading' title='Returning to your workspace…' className='w-full max-w-md' />
    </main>
  );
}
