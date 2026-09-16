import type { Metadata } from 'next';
import { CalendarView } from '@/features/calendar/calendar-view';

export const metadata: Metadata = { title: 'Calendar' };

export default function Page() {
  return <CalendarView />;
}
