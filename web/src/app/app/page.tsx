import type { Metadata } from 'next';
import { Suspense } from 'react';
import { HomeView } from '@/features/agent/home-view';
import { HomeBackdrop } from './home-backdrop';

export const metadata: Metadata = { title: 'Home' };

/**
 * `/app` is the agent chat home (design decision 2); the dashboard moved to /app/overview.
 * Behind the chat sits an ambient particle field that answers the pointer (`HomeBackdrop`):
 * ornament only, quiet while the person writes, and not drawn under reduced motion.
 */
export default function AppHomePage() {
  return (
    <div className='relative isolate flex min-w-0 flex-1 flex-col'>
      <HomeBackdrop />
      <Suspense fallback={null}>
        <HomeView />
      </Suspense>
    </div>
  );
}
