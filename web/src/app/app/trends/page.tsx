import type { Metadata } from 'next';
import { TrendsView } from '@/features/trends/trends-view';
export const metadata: Metadata = { title: 'Trend Radar' };
export default function TrendsPage() {
  return <TrendsView />;
}
