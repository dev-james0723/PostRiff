import type { Metadata } from 'next';
import { ProviderReadinessView } from '@/features/workspace/provider-readiness-view';

export const metadata: Metadata = { title: 'Provider readiness' };

export default function Page() {
  return <ProviderReadinessView />;
}
