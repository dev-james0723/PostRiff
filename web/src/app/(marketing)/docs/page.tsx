import type { Metadata } from 'next';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { DOCS } from '@/content/docs';

export const metadata: Metadata = {
  title: 'Docs',
  description: 'How Rafii works: getting started, channels and capabilities, approvals, usage and billing, privacy and data.',
  openGraph: { title: 'Docs · Rafii', url: '/docs' }
};

export default function DocsPage() {
  return (
    <>
      <PageHero eyebrow='Docs' title='Short guides to how Rafii works.' description='Written for people who want to know exactly what happens when they press a button.' />
      <Section>
        <ul className='grid gap-3 sm:grid-cols-2'>
          {DOCS.map((doc) => (
            <li key={doc.slug}>
              <Link href={`/docs/${doc.slug}`} className='bg-card hover:border-primary/60 flex h-full flex-col gap-1 rounded-xl border p-5 transition-colors'>
                <span className='flex items-center justify-between font-semibold'>
                  {doc.title}
                  <Icons.chevronRight className='text-muted-foreground size-4' />
                </span>
                <span className='text-muted-foreground text-sm'>{doc.summary}</span>
              </Link>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
