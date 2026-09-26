import type { Metadata } from 'next';
import { Suspense } from 'react';
import PageContainer from '@/components/layout/page-container';
import { ProductivityConnectorReturn } from '@/features/connectors/connect-return';

export const metadata: Metadata = { title: 'Finishing connection' };

export default function ProductivityConnectorConnectPage() {
  return (
    <Suspense fallback={<PageContainer pageTitle='Finishing connection' width='reading' isLoading>{null}</PageContainer>}>
      <ProductivityConnectorReturn />
    </Suspense>
  );
}
