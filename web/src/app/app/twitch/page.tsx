import type { Metadata } from 'next';
import { TwitchWorkspaceView } from '@/features/twitch/twitch-view';

export const metadata: Metadata = { title: 'Twitch workspace' };

export default function Page() {
  return <TwitchWorkspaceView />;
}
