import type { Metadata } from 'next';
import { AnalyticsView } from '@/features/analytics/analytics-view';

export const metadata: Metadata = { title: 'Analytics' };

export default function Page() {
  return <AnalyticsView />;
}
