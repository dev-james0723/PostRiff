import type { Metadata } from 'next';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { CHANGELOG } from '@/content/changelog';

export const metadata: Metadata = {
  title: 'Changelog',
  description: 'What has shipped in PostRiff, by date.',
  openGraph: { title: 'Changelog · PostRiff', url: '/changelog' }
};

export default function ChangelogPage() {
  return (
    <>
      <PageHero eyebrow='Changelog' title='What has shipped.' description='Only released changes appear here — no roadmap promises.' />
      <Section>
        <ol className='flex max-w-3xl flex-col gap-8'>
          {CHANGELOG.map((entry) => (
            <li key={entry.date} className='grid gap-2 sm:grid-cols-[8rem_1fr]'>
              <time dateTime={entry.date} className='text-muted-foreground text-sm'>
                {entry.date}
              </time>
              <div>
                <h2 className='font-semibold'>{entry.title}</h2>
                <ul className='text-muted-foreground mt-2 flex list-disc flex-col gap-1 pl-5 text-sm'>
                  {entry.items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      </Section>
    </>
  );
}
