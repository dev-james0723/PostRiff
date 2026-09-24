import type { Metadata } from 'next';
import Link from 'next/link';
import { CtaBand } from '@/components/marketing/cta-band';
import { Faq } from '@/components/marketing/landing/sections';
import { PageHero } from '@/components/marketing/page-hero';
import { PlanCard } from '@/components/marketing/plan-card';
import { Section } from '@/components/marketing/section';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { TRIAL, plans } from '@/config/plans';
import { siteConfig } from '@/config/site';

export const metadata: Metadata = {
  title: 'Pricing',
  description: 'Simple monthly plans. 14-day trial, no card. Allowances stop at the limit — never a surprise charge.',
  openGraph: { title: 'Pricing · Rafii', url: '/pricing' }
};

const ROWS: { label: string; value: (plan: (typeof plans)[number]) => string }[] = [
  { label: 'Connected accounts', value: (p) => String(p.limits.connectedAccounts) },
  { label: 'AI writing batches / month', value: (p) => (p.limits.writingBatches === 'none' ? 'Not included' : String(p.limits.writingBatches)) },
  { label: 'Media credits / month', value: (p) => String(p.limits.mediaCredits) },
  { label: 'Storage', value: (p) => `${p.limits.storageMb / 1000} GB` },
  { label: 'Members', value: (p) => String(p.limits.members) },
  { label: 'Overage behaviour', value: () => 'Stops — never charged silently' },
  { label: 'Export everything', value: () => 'Always' },
  { label: 'Account deletion', value: () => 'Self-service' }
];

const PRICING_FAQ = [
  { q: 'When am I billed?', a: 'Monthly, in advance, from the day you subscribe. The trial never converts automatically; you choose a plan yourself.' },
  { q: 'Can I cancel any time?', a: 'Yes, from the billing portal. Paid features run to the end of the period; drafts stay readable and exportable afterwards.' },
  { q: 'What does “introductory pricing” mean?', a: 'These are the prices for early customers. If they change before general availability, existing subscribers keep their price for at least a year.' },
  { q: 'Refunds?', a: 'See the Terms of Service. Nothing is charged during the trial, so you can evaluate Rafii fully before paying.' },
  { q: 'Taxes?', a: 'Shown at checkout where applicable, based on your billing address.' }
];

/** Comparison cells wrap so the three columns fit a 320px viewport without page scroll (DNA §19.3). */
const CELL = 'px-4 py-3 align-top whitespace-normal';

export default function PricingPage() {
  const anyProposed = plans.some((p) => p.status === 'proposed');
  return (
    <>
      <PageHero eyebrow='Pricing' title='Simple pricing.' accent='No surprises.' description={`Start with a ${TRIAL.days}-day trial — ${TRIAL.connectedAccounts} connected accounts, ${TRIAL.writingBatches} writing batches, no card. Pick a plan when you are ready.`} />
      <Section className='pt-8 sm:pt-12'>
        <div className='grid gap-4 md:grid-cols-3'>
          {plans.map((plan) => (
            <PlanCard key={plan.id} plan={plan} priceSize='large' />
          ))}
          <Surface material='quiet' radius='card' padding='lg' className='flex flex-col gap-5'>
            <div className='flex flex-col gap-1.5'>
              <p className='text-muted-foreground text-sm'>Before you pay</p>
              <h3 className='text-foreground text-2xl font-medium tracking-[-0.01em]'>Trial</h3>
              <p className='text-foreground text-[2rem] leading-none font-medium tracking-[-0.02em] tabular-nums'>
                $0 <span className='text-muted-foreground text-base font-normal tracking-normal'>/ {TRIAL.days} days</span>
              </p>
            </div>
            <ul className='text-foreground flex flex-1 flex-col gap-2 text-sm'>
              <li>{TRIAL.connectedAccounts} connected accounts</li>
              <li>{TRIAL.writingBatches} AI writing batches</li>
              <li>{TRIAL.mediaCredits} media credit</li>
              <li>{TRIAL.storageMb} MB storage</li>
              <li>No card. No automatic conversion.</li>
            </ul>
            <div>
              <Link href={siteConfig.links.signUp} className={buttonVariants({ variant: 'glass', size: 'control' })}>
                Start free
              </Link>
            </div>
          </Surface>
        </div>
        {anyProposed && (
          <p className='text-muted-foreground mt-4 text-xs'>
            Prices are shown in USD. Introductory pricing applies to early customers; see the FAQ below.
          </p>
        )}
      </Section>

      <Section eyebrow='Compare' title='What each plan includes'>
        <Surface material='quiet' radius='card' padding='none' className='overflow-hidden'>
          <Table>
            <TableHeader>
              <TableRow className='hover:bg-transparent'>
                <TableHead className={`${CELL} md:w-56`}>Feature</TableHead>
                {plans.map((plan) => (
                  <TableHead key={plan.id} className={CELL}>
                    {plan.name}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {ROWS.map((row) => (
                <TableRow key={row.label} className='hover:bg-transparent'>
                  <TableCell className={`${CELL} text-foreground font-medium`}>{row.label}</TableCell>
                  {plans.map((plan) => (
                    <TableCell key={plan.id} className={CELL}>
                      {row.value(plan)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Surface>
      </Section>

      <Faq items={PRICING_FAQ} />
      <CtaBand />
    </>
  );
}
