import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { PreviewDeckSheet } from '@/components/application/post-preview/preview-deck-sheet';

export const metadata: Metadata = { title: 'Preview deck', robots: { index: false } };

/** Review sheet for the phone preview deck, dock and expanded dialog. Development builds only; production answers 404. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <PreviewDeckSheet />;
}
