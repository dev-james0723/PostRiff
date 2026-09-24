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
      <PageHero eyebrow='Docs' title='Short guides to' accent='how Rafii works.' description='Written for people who want to know exactly what happens when they press a button.' />
      <Section className='pt-8 sm:pt-12'>
        <ul className='grid gap-3 sm:grid-cols-2'>
          {DOCS.map((doc) => (
            <li key={doc.slug} className='flex'>
              <Link
                href={`/docs/${doc.slug}`}
                className='rafii-quiet hover:rafii-glass rafii-focus flex flex-1 flex-col gap-1.5 rounded-[var(--rafii-radius-card)] p-5 transition-[background,box-shadow] duration-200'
              >
                <span className='text-foreground flex items-center justify-between gap-3 font-medium'>
                  {doc.title}
                  <Icons.chevronRight className='text-muted-foreground size-4 shrink-0' aria-hidden />
                </span>
                <span className='text-muted-foreground text-sm leading-relaxed'>{doc.summary}</span>
              </Link>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
