import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { ChannelBloomDevPage } from './dev-page';

export const metadata: Metadata = { title: 'Channel Bloom', robots: { index: false } };

/** Review page for the Channel Bloom dialog against the real workspace snapshot. Development builds only; production answers 404. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <ChannelBloomDevPage />;
}
