import type { Metadata } from 'next';
import { OverviewView } from '@/features/founder/overview';

export const metadata: Metadata = { title: 'Overview' };

export default function FounderOverviewPage() {
  return <OverviewView />;
}
