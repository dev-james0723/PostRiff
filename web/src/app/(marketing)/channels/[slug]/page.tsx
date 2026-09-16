import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CapabilityBadge, type CapabilityLevel } from '@/components/marketing/capability-badge';
import { CtaBand } from '@/components/marketing/cta-band';
import { Faq } from '@/components/marketing/landing/sections';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { channelBySlug, channels, type ChannelCapabilityKey } from '@/config/channels';
import { siteConfig } from '@/config/site';

const CAP_LABELS: Record<ChannelCapabilityKey, string> = {
  identity: 'Identity',
  publish: 'Publish',
  schedule: 'Schedule',
  analytics: 'Analytics',
  comments_read: 'Read comments',
  reply: 'Reply'
};

export function generateStaticParams() {
  return channels.map((channel) => ({ slug: channel.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const channel = channelBySlug(slug);
  if (!channel) return {};
  const name = channel.nameZh ? `${channel.name} (${channel.nameZh})` : channel.name;
  return {
    title: `${name} publishing`,
    description: `${channel.description} How PostRiff connects to ${channel.name}, what it can do today, and what is still pending.`,
    openGraph: { title: `${name} · PostRiff`, url: `/channels/${channel.slug}` }
  };
}

function levelKey(level: string): CapabilityLevel {
  return level === 'Direct' ? 'direct' : level === 'Assisted' ? 'assisted' : 'unsupported';
}

export default async function ChannelPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const channel = channelBySlug(slug);
  if (!channel) notFound();

  const faq =
    channel.group === 'hosted'
      ? [
          { q: `Can PostRiff publish to ${channel.name} directly today?`, a: `Not yet. ${channel.reviewStatus ?? 'Provider review is pending'}. Until it passes, PostRiff prepares the post and you complete the final step; the badge on your channel card says exactly that.` },
          { q: 'What permissions does PostRiff ask for?', a: 'Only the scopes for the capability you enable — publishing, analytics, comments or replies — and the connection card lists the ones actually granted.' },
          { q: 'How do I disconnect?', a: 'From Channels → Disconnect. The stored token is wiped and revoked with the provider where supported.' }
        ]
      : [
          { q: `Why is ${channel.name} not a hosted connector?`, a: `${channel.name} does not offer a third-party publishing API a small studio can use honestly, or its API is restricted or paid. The desktop companion publishes through your own login on your own machine instead — never from our servers.` },
          { q: 'When is the companion available?', a: 'It is in development alongside the hosted connectors. We do not promise dates; the changelog shows what has shipped.' },
          { q: 'Is my login shared with PostRiff?', a: 'No. The companion keeps your session on your machine. Drafts and approvals still come from your PostRiff workspace.' }
        ];

  return (
    <>
      <PageHero
        eyebrow={channel.group === 'hosted' ? 'Hosted connector' : 'Desktop companion'}
        title={
          <>
            {channel.name}
            {channel.nameZh && <span className='text-muted-foreground ml-3 text-2xl font-normal'>{channel.nameZh}</span>}
          </>
        }
        description={channel.description}
      >
        <CapabilityBadge level={channel.capability} size='md' label={channel.reviewStatus ? `${channel.capability === 'assisted' ? 'Assisted' : 'Local'} · ${channel.reviewStatus}` : undefined} />
        {channel.formats.map((format) => (
          <Badge key={format} variant='outline'>
            {format}
          </Badge>
        ))}
      </PageHero>

      <Section eyebrow='Capabilities' title={`What PostRiff can do on ${channel.name} today`}>
        <div className='max-w-2xl overflow-x-auto rounded-xl border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Capability</TableHead>
                <TableHead>Level</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(Object.keys(CAP_LABELS) as ChannelCapabilityKey[]).map((key) => {
                const level = channel.capabilities[key];
                return (
                  <TableRow key={key}>
                    <TableCell className='font-medium'>{CAP_LABELS[key]}</TableCell>
                    <TableCell>{channel.group === 'local' ? <CapabilityBadge level='local' /> : <CapabilityBadge level={levelKey(level ?? 'Unsupported')} />}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {channel.notes && channel.notes.length > 0 && (
          <ul className='text-muted-foreground mt-4 flex max-w-2xl list-disc flex-col gap-1 pl-5 text-sm'>
            {channel.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </Section>

      <Section eyebrow='Connecting' title='How connection works'>
        <div className='max-w-2xl text-sm text-pretty'>
          {channel.group === 'hosted' ? (
            <ol className='flex list-decimal flex-col gap-2 pl-5'>
              <li>In Channels, choose the capability you want and press Connect. PostRiff shows the exact scopes before you leave.</li>
              <li>{channel.name} asks you to authorise PostRiff. Your password never touches PostRiff.</li>
              <li>Back in PostRiff, confirm the account. The card shows each capability’s verified level.</li>
            </ol>
          ) : (
            <ol className='flex list-decimal flex-col gap-2 pl-5'>
              <li>Install the PostRiff desktop companion on your own computer (coming with the companion release).</li>
              <li>Sign in to {channel.name} inside the companion. The session stays on your machine.</li>
              <li>Approve a post in your PostRiff workspace; the companion publishes it through your session and reports the receipt back.</li>
            </ol>
          )}
        </div>
        <div className='mt-4 flex flex-wrap gap-2'>
          <Link href={siteConfig.links.signUp} className={buttonVariants()}>
            Start free trial
          </Link>
          <Link href={siteConfig.links.channels} className={buttonVariants({ variant: 'outline' })}>
            All channels
          </Link>
        </div>
      </Section>

      <Faq items={faq} />
      <CtaBand />
    </>
  );
}
