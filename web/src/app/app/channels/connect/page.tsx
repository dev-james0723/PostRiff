import type { Metadata } from 'next';
import { Suspense } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ConnectReturn } from '@/features/channels/connect-return';

export const metadata: Metadata = { title: 'Finishing connection' };

export default function ConnectReturnPage() {
  return (
    <Suspense fallback={<PageContainer pageEyebrow='Connections' pageTitle='Finishing connection' pageDescription='Confirming the account the provider returned.' width='reading' isLoading>{null}</PageContainer>}>
      <ConnectReturn />
    </Suspense>
  );
}
