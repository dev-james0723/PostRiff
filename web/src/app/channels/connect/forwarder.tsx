'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

export function ConnectForwarder() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    router.replace(`/app/channels/connect?${params.toString()}`);
  }, [router, params]);
  return <p className='text-muted-foreground p-6 text-sm'>Returning to your workspace…</p>;
}
