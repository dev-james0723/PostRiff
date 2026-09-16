import Link from 'next/link';
import { Icons } from '@/components/icons';
import { CAPABILITY_LEVELS, CapabilityBadge } from '@/components/marketing/capability-badge';
import { Section } from '@/components/marketing/section';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { hostedChannels, localChannels } from '@/config/channels';
import { TRIAL, formatPrice, plans } from '@/config/plans';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

export function ChannelMatrix() {
  return (
    <Section id='channels' eyebrow='Channels' title='Western and Chinese platforms, in one place.' description='Hosted connectors use the official APIs. The desktop companion handles the platforms that have none — through your own login, on your own machine.'>
      <div className='grid gap-6 md:grid-cols-2'>
        <div className='flex flex-col gap-3 rounded-xl border p-5'>
          <p className='flex items-center gap-2 text-sm font-semibold'>
            Hosted <CapabilityBadge level='assisted' label='review pending' />
          </p>
          <div className='flex flex-wrap gap-2'>
            {hostedChannels.map((channel) => (
              <Link key={channel.slug} href={`/channels/${channel.slug}`} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
                {channel.name}
              </Link>
            ))}
          </div>
          <p className='text-muted-foreground text-xs'>Direct publishing switches on per platform once its provider review passes. Until then PostRiff prepares the post and you complete the last step.</p>
        </div>
        <div className='flex flex-col gap-3 rounded-xl border p-5'>
          <p className='flex items-center gap-2 text-sm font-semibold'>
            Desktop companion <CapabilityBadge level='local' />
          </p>
          <div className='flex flex-wrap gap-2'>
            {localChannels.map((channel) => (
              <Link key={channel.slug} href={`/channels/${channel.slug}`} className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'gap-1.5')}>
                {channel.name}
                {channel.nameZh && <span className='text-muted-foreground'>{channel.nameZh}</span>}
              </Link>
            ))}
          </div>
        </div>
      </div>
      <Link href={siteConfig.links.channels} className={cn(buttonVariants({ variant: 'ghost' }), 'mt-4')}>
        All channels and what each can do <Icons.chevronRight className='size-4' />
      </Link>
    </Section>
  );
}

const STEPS = [
  { title: 'Bring a source', body: 'Paste a thought, a paragraph, a transcript or a link. Mark what is your own writing.' },
  { title: 'Get a version per platform', body: 'LinkedIn in English, Instagram in 繁中, 小紅書 with its own rhythm — each written the way you would.' },
  { title: 'Approve the exact post', body: 'Text, media, account and time are frozen into one review. Nothing leaves without your approval.' },
  { title: 'Publish or export', body: 'Direct where a platform allows it, through the companion where it does not, or as an export. Every publication gets a receipt.' }
];

export function HowItWorks() {
  return (
    <Section id='how-it-works' eyebrow='How it works' title='Four steps. You hold the last one.'>
      <ol className='grid gap-4 md:grid-cols-2 lg:grid-cols-4'>
        {STEPS.map((step, index) => (
          <li key={step.title} className='bg-card flex flex-col gap-2 rounded-xl border p-5'>
            <span className='text-primary text-xs font-semibold tracking-[0.18em]'>0{index + 1}</span>
            <h3 className='font-semibold'>{step.title}</h3>
            <p className='text-muted-foreground text-sm text-pretty'>{step.body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}

export function Honesty() {
  const levels = ['direct', 'assisted', 'local'] as const;
  return (
    <Section id='honesty' eyebrow='We do not pretend' title='Every channel shows what it can really do.' description='Most tools show a green “Connected”. PostRiff shows each capability — identity, publish, schedule, analytics, comments, reply — with the level it has actually verified.'>
      <div className='grid gap-4 md:grid-cols-3'>
        {levels.map((level) => (
          <div key={level} className='bg-card flex flex-col gap-3 rounded-xl border p-5'>
            <CapabilityBadge level={level} size='md' />
            <p className='text-sm text-pretty'>{CAPABILITY_LEVELS[level].description}</p>
          </div>
        ))}
      </div>
      <p className='text-muted-foreground mt-4 text-sm'>
        Unsupported stays grey. Unavailable metrics say “Unavailable”, never 0. If a platform review is pending, the badge says so.
      </p>
    </Section>
  );
}

export function DesignPartners() {
  return (
    <Section id='early-access' eyebrow='Early access' title='Design partner programme' description='PostRiff is new. Instead of borrowed logos, here is what early partners get and how to apply.'>
      <div className='grid gap-4 md:grid-cols-[1fr_auto] md:items-center'>
        <ul className='grid gap-2 text-sm sm:grid-cols-3'>
          <li className='rounded-lg border p-4'>A weekly call with the founder while we tune drafts to your voice.</li>
          <li className='rounded-lg border p-4'>Priority on the platforms you need next, including Chinese ones.</li>
          <li className='rounded-lg border p-4'>Locked introductory pricing for the first year.</li>
        </ul>
        <Link href={`${siteConfig.links.contact}?topic=design-partner`} className={buttonVariants({ size: 'lg' })}>
          Apply as a design partner
        </Link>
      </div>
    </Section>
  );
}

export function PricingSummary() {
  return (
    <Section id='pricing' eyebrow='Pricing' title='Two plans. No surprises.' description={`${TRIAL.days}-day trial with ${TRIAL.connectedAccounts} connected accounts and ${TRIAL.writingBatches} writing batches. No card, no automatic conversion.`}>
      <div className='grid gap-4 md:grid-cols-2'>
        {plans.map((plan) => (
          <Card key={plan.id}>
            <CardHeader>
              <CardDescription>{plan.tagline}</CardDescription>
              <CardTitle className='flex items-baseline gap-2 text-2xl'>
                {plan.name}
                <span className='text-muted-foreground text-base font-normal'>
                  {formatPrice(plan)} / {plan.interval}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className='flex flex-col gap-1.5 text-sm'>
                {plan.highlights.map((item) => (
                  <li key={item} className='flex items-start gap-2'>
                    <Icons.check className='text-primary mt-0.5 size-4 shrink-0' aria-hidden />
                    {item}
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter className='flex flex-col items-start gap-2'>
              <Link href={`${siteConfig.links.signUp}?plan=${plan.id}`} className={buttonVariants()}>
                Start {TRIAL.days}-day trial
              </Link>
              {plan.status === 'proposed' && <p className='text-muted-foreground text-xs'>Introductory pricing — subject to change before general availability.</p>}
            </CardFooter>
          </Card>
        ))}
      </div>
      <Link href={siteConfig.links.pricing} className={cn(buttonVariants({ variant: 'ghost' }), 'mt-4')}>
        Compare plans in detail <Icons.chevronRight className='size-4' />
      </Link>
    </Section>
  );
}

export const FAQ_ITEMS = [
  { q: 'Do you ever post without my approval?', a: 'No. A review freezes the exact text, media, account and time; only approving that review creates a publication. There is no auto-post, auto-reply or bulk mode.' },
  { q: 'Which channels are direct today?', a: 'None yet. LinkedIn, Threads and Instagram are hosted connectors awaiting provider review; until each passes, publishing is Assisted (PostRiff prepares the post, you complete the last step). Chinese and other platforms run through the desktop companion on your own machine.' },
  { q: 'What happens while a platform review is pending?', a: 'The channel card says “Assisted · review pending”. You can still draft, schedule and export; direct publishing switches on for that platform when the review passes.' },
  { q: 'Can I export everything?', a: 'Yes — drafts, sources, approvals and receipts as a zip with a SHA-256 receipt, at any time, on any plan, including after cancellation.' },
  { q: 'How does the trial work?', a: `${TRIAL.days} days, ${TRIAL.connectedAccounts} connected accounts, ${TRIAL.writingBatches} writing batches, no card. It never converts into a paid plan by itself.` },
  { q: 'Do you train AI on my content?', a: 'No. Drafts come only from sources you select and approve, and our provider contracts will prohibit training. See the Privacy Policy.' }
];

export function Faq({ items = FAQ_ITEMS }: { items?: { q: string; a: string }[] }) {
  return (
    <Section id='faq' eyebrow='FAQ' title='Straight answers.'>
      <Accordion className='max-w-3xl'>
        {items.map((item, index) => (
          <AccordionItem key={item.q} value={`faq-${index}`}>
            <AccordionTrigger>{item.q}</AccordionTrigger>
            <AccordionContent>
              <p className='text-muted-foreground text-sm text-pretty'>{item.a}</p>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </Section>
  );
}
