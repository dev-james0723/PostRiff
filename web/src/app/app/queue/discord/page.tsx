import { Suspense } from 'react';
import type { Metadata } from 'next';
import { DiscordReviewEntry } from '@/features/channels/discord-review-entry';
export const metadata: Metadata = { title: 'Private Discord review' };
export default function Page() {
  return <Suspense><DiscordReviewEntry /></Suspense>;
}
