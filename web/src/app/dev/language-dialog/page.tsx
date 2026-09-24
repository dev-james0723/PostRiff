import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { LanguageDialogPlayground } from './playground';

export const metadata: Metadata = { title: 'Language dialog · dev', robots: { index: false } };

/** Evidence page for the Rafii v9 output-language dialog. Development builds only; production answers 404. */
export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <LanguageDialogPlayground />;
}
