import type { Metadata } from 'next';
import { QueueView } from '@/features/queue/queue-view';

export const metadata: Metadata = { title: 'Queue' };

export default function Page() {
  return <QueueView />;
}
