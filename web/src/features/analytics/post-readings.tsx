'use client';

import { Icons } from '@/components/icons';
import { formatDateTime } from '@/lib/time';

export interface PostReading {
  observedAt: number;
}

/**
 * Slot for a post's reading history. The summary endpoint carries one reading per post today,
 * so this renders the honest sentence for fewer than two observations. When the API returns a
 * history (`GET /analytics/posts?connectionId=`), the ≥2 branch is where the per-metric sparkline
 * goes (ChartContainer + Recharts line, 250ms, off under reduced motion) — never a line through one point.
 */
export function PostReadings({ readings }: { readings: PostReading[] }) {
  if (readings.length === 0) {
    return <p className='text-muted-foreground text-sm'>No reading yet.</p>;
  }
  if (readings.length < 2) {
    return (
      <p className='text-muted-foreground flex items-center gap-2 text-sm'>
        <Icons.hourglass className='size-4 shrink-0' aria-hidden />
        One reading so far — no trend yet.
      </p>
    );
  }
  return (
    <ol className='text-muted-foreground flex flex-col gap-1 text-sm'>
      {readings.map((reading) => (
        <li key={reading.observedAt}>{formatDateTime(reading.observedAt)}</li>
      ))}
    </ol>
  );
}
