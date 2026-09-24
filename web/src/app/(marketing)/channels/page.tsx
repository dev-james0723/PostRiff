import type { Metadata } from 'next';
import { CAPABILITY_LEVELS, CapabilityBadge } from '@/components/marketing/capability-badge';
import { CtaBand } from '@/components/marketing/cta-band';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { Surface } from '@/components/rafii';
import { channels } from '@/config/channels';
import { ChannelDirectory } from './channel-directory';

export const metadata: Metadata = {
  title: 'Channels',
  description: `${channels.length} platforms — hosted connectors through official APIs, and a desktop companion for the platforms that have none, including 小紅書, B站, 知乎 and 抖音.`,
  openGraph: { title: 'Channels · Rafii', url: '/channels' }
};

export default function ChannelsPage() {
  return (
    <>
      <PageHero eyebrow='Channels' title={`${channels.length} platforms, each labelled with`} accent='what Rafii can really do.' description='Hosted connectors use the official APIs and clear their own provider reviews. Companion channels are listed as pending until a released companion and account workflow have been verified.' />
      <Section className='pt-8 sm:pt-12'>
        <ChannelDirectory channels={channels} />
      </Section>
      <Section eyebrow='Levels' title='What the badges mean'>
        <div className='grid gap-4 sm:grid-cols-2 md:grid-cols-4'>
          {(['direct', 'assisted', 'local', 'unsupported'] as const).map((level) => (
            <Surface key={level} material='quiet' radius='card' padding='md' className='flex flex-col gap-3'>
              <CapabilityBadge level={level} size='md' />
              <p className='text-muted-foreground text-sm leading-relaxed'>{CAPABILITY_LEVELS[level].description}</p>
            </Surface>
          ))}
        </div>
      </Section>
      <CtaBand secondary={{ label: 'See pricing', href: '/pricing' }} />
    </>
  );
}
