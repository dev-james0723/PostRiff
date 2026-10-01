import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { FOUNDER_SECTIONS, isRoutedSectionId } from '@/config/founder-nav';
import { FounderSectionPage } from '@/features/founder/shell/section-page';

type Params = Promise<{ section: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { section } = await params;
  return isRoutedSectionId(section) ? { title: FOUNDER_SECTIONS[section].title } : {};
}

/** `/founder/<section>` for the eight domain pages; anything else is a 404, never a guessed page. */
export default async function FounderSectionRoute({ params }: { params: Params }) {
  const { section } = await params;
  if (!isRoutedSectionId(section)) notFound();
  return <FounderSectionPage section={section} />;
}
