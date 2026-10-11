import type { Metadata } from 'next';
import { YouTubeCreatorView } from '@/features/youtube/creator-view';
export const metadata: Metadata = { title: 'YouTube creator' };
export default function Page() {
  return <YouTubeCreatorView />;
}
