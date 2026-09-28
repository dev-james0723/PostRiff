import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { CalendarCardPlayground } from './playground';

export const metadata: Metadata = { title: 'Calendar card · dev', robots: { index: false } };

/** Visual and accessibility fixture for the read-only calendar answer card. Development builds only. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <CalendarCardPlayground />;
}
