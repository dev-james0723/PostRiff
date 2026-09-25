import type { Metadata } from 'next';
import { Suspense } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ConnectReturn } from '@/features/channels/connect-return';

export const metadata: Metadata = { title: 'Finishing connection' };

export default function ConnectReturnPage() {
  return (
    <Suspense fallback={<PageContainer pageTitle='Finishing connection' width='reading' isLoading />}>
      <ConnectReturn />
    </Suspense>
  );
}
