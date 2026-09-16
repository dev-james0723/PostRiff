import type { Metadata } from 'next';
import { OverviewView } from '@/features/overview/overview-view';

export const metadata: Metadata = { title: 'Overview' };

export default function AppOverviewPage() {
  return <OverviewView />;
}
