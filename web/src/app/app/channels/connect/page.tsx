import type { Metadata } from 'next';
import { Suspense } from 'react';
import { ConnectReturn } from '@/features/channels/connect-return';

export const metadata: Metadata = { title: 'Finishing connection' };

export default function ConnectReturnPage() {
  return (
    <Suspense fallback={null}>
      <ConnectReturn />
    </Suspense>
  );
}
