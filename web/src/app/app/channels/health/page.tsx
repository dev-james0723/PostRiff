import type { Metadata } from 'next';
import { ConnectionHealthView } from '@/features/channels/health/connection-health-view';

export const metadata: Metadata = { title: 'Connection health' };

export default function ConnectionHealthPage() {
  return <ConnectionHealthView />;
}
