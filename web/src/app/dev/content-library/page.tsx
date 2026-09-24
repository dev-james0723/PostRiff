import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { ContentLibraryInventory } from './inventory';

export const metadata: Metadata = { title: 'Content Library artwork', robots: { index: false } };

/** Visual audit of the 51 + 51 library assets. Development builds only; production answers 404. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <ContentLibraryInventory />;
}
