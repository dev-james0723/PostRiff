import type { Metadata } from 'next';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { ContentDNA } from '@/features/growth/public-post-doctor';

export const metadata: Metadata = {
  title: 'Content DNA',
  robots: { index: false, follow: false },
  referrer: 'no-referrer'
};

export default async function ContentDNAPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <>
      <PageHero
        eyebrow='Content DNA'
        title='A few things that make'
        accent='this writing theirs.'
        description='Writing labels selected and shared by the creator.'
      />
      <Section className='pt-8'>
        <ContentDNA token={token} />
      </Section>
    </>
  );
}
