import { notFound } from 'next/navigation';
import { NotificationSystemPreview } from './preview';

export const metadata = { title: 'Notification system visual fixture', robots: { index: false } };

/** Existing dev-route convention: visual states are unavailable in production. */
export default async function Page({ searchParams }: { searchParams: Promise<{ count?: string; state?: string; partial?: string }> }) {
  if (process.env.NODE_ENV === 'production') notFound();
  const options = await searchParams;
  return <NotificationSystemPreview count={options.count} state={options.state} partial={options.partial === '1'} />;
}
