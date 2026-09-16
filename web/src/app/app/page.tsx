import type { Metadata } from 'next';
import { Suspense } from 'react';
import { HomeView } from '@/features/agent/home-view';

export const metadata: Metadata = { title: 'Home' };

/** `/app` is the agent chat home (design decision 2); the dashboard moved to /app/overview. */
export default function AppHomePage() {
  return (
    <Suspense fallback={null}>
      <HomeView />
    </Suspense>
  );
}
