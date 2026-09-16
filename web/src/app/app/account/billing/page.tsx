import type { Metadata } from 'next';
import { Suspense } from 'react';
import { BillingView } from '@/features/billing/billing-view';

export const metadata: Metadata = { title: 'Usage & plan' };

export default function BillingPage() {
  return (
    <Suspense fallback={null}>
      <BillingView />
    </Suspense>
  );
}
