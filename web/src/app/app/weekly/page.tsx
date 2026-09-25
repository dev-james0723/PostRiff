import type { Metadata } from 'next';
import { Suspense } from 'react';
import { WeeklyView } from '@/features/coworker/weekly/weekly-view';

export const metadata: Metadata = { title: 'Weekly review' };

/** `?tab=`, `?week=` and `?recipe=` live in the URL (deep links from notifications), so the reader sits under Suspense. */
export default function WeeklyPage() {
  return (
    <Suspense fallback={null}>
      <WeeklyView />
    </Suspense>
  );
}
