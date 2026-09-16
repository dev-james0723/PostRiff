import type { Metadata } from 'next';
import { Suspense } from 'react';
import { IdeasView } from '@/features/ideas/ideas-view';

export const metadata: Metadata = { title: 'Ideas' };

export default function IdeasPage() {
  return (
    <Suspense fallback={null}>
      <IdeasView />
    </Suspense>
  );
}
