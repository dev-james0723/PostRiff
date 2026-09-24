import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { ModelDialogPlayground } from './playground';

export const metadata: Metadata = { title: 'Model dialog · dev', robots: { index: false } };

/** Evidence page for the Rafii v9 model and reasoning dialog over the real catalog. Development builds only; production answers 404. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <ModelDialogPlayground />;
}
