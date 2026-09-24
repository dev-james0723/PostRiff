import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { buttonVariants } from '@/components/ui/button';
import { DOCS, docBySlug } from '@/content/docs';

export function generateStaticParams() {
  return DOCS.map((doc) => ({ slug: doc.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const doc = docBySlug(slug);
  return doc ? { title: doc.title, description: doc.summary, openGraph: { title: `${doc.title} · Rafii Docs`, url: `/docs/${doc.slug}` } } : {};
}

export default async function DocPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = docBySlug(slug);
  if (!doc) notFound();
  return (
    <>
      <PageHero eyebrow='Docs' title={doc.title} description={doc.summary} />
      <Section>
        <article className='flex max-w-3xl flex-col gap-8'>
          {doc.sections.map((section) => (
            <section key={section.heading}>
              <h2 className='mb-2 text-xl font-semibold'>{section.heading}</h2>
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph} className='text-muted-foreground mb-3 text-pretty'>
                  {paragraph}
                </p>
              ))}
              {section.bullets && (
                <ul className='text-muted-foreground list-disc pl-5'>
                  {section.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}
          <Link href='/docs' className={buttonVariants({ variant: 'outline' })}>
            All docs
          </Link>
        </article>
      </Section>
    </>
  );
}
