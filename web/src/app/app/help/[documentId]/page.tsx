import type { Metadata } from 'next';
import { HelpArticleView } from '@/features/help/help-view';

export const metadata: Metadata = { title: 'Help article' };

export default async function Page({ params }: { params: Promise<{ documentId: string }> }) {
  const { documentId } = await params;
  return <HelpArticleView documentId={documentId} />;
}
