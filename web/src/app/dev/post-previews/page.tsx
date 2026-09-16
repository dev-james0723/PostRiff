import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { PostPreviewGallery } from '@/components/application/post-preview/gallery';

export const metadata: Metadata = { title: 'Post preview templates', robots: { index: false } };

/** Review sheet for the phone templates. Development builds only; production answers 404. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <PostPreviewGallery />;
}
