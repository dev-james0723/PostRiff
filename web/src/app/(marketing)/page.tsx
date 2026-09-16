import type { Metadata } from 'next';
import { Section } from '@/components/marketing/section';
import { siteConfig } from '@/config/site';

export const metadata: Metadata = {
  title: {
    absolute: `${siteConfig.name} · One idea, every platform, in your voice`
  },
  description: siteConfig.description,
  openGraph: {
    title: `${siteConfig.name} · One idea, every platform, in your voice`,
    description: siteConfig.description,
    url: '/'
  }
};

// Placeholder: the landing page content is written separately.
export default function HomePage() {
  return (
    <Section>
      <h1 className='text-4xl font-semibold tracking-tight'>{siteConfig.name}</h1>
    </Section>
  );
}
