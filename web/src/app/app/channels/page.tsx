import type { Metadata } from 'next';
import { ChannelsView } from '@/features/channels/channels-view';

export const metadata: Metadata = { title: 'Channels' };

export default function ChannelsPage() {
  return <ChannelsView />;
}
