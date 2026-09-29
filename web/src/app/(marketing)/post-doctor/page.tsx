import type { Metadata } from 'next';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { PublicPostDoctor } from '@/features/growth/public-post-doctor';

export const metadata: Metadata = {
  title: 'Post Doctor',
  description: 'Qualitative advice for your draft, grounded in your writing.'
};

export default function PostDoctorPage() {
  return (
    <>
      <PageHero
        eyebrow='Post Doctor'
        title='Make your next post'
        accent='clearer.'
        description='See what helps, what hurts and what to change across nine writing dimensions.'
      />
      <Section className='pt-8'>
        <PublicPostDoctor />
      </Section>
    </>
  );
}
