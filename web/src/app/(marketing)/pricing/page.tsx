import type { Metadata } from 'next';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { CtaBand } from '@/components/marketing/cta-band';
import { Faq } from '@/components/marketing/landing/sections';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { TRIAL, formatPrice, plans } from '@/config/plans';
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

export default function PricingPage() {
  const anyProposed = plans.some((p) => p.status === 'proposed');
  return (
    <>
      <PageHero eyebrow='Pricing' title='Simple pricing. No surprises.' description={`Start with a ${TRIAL.days}-day trial — ${TRIAL.connectedAccounts} connected accounts, ${TRIAL.writingBatches} writing batches, no card. Pick a plan when you are ready.`} />
      <Section>
        <div className='grid gap-4 md:grid-cols-3'>
          {plans.map((plan) => (
            <Card key={plan.id} className='flex flex-col'>
              <CardHeader>
                <CardDescription>{plan.tagline}</CardDescription>
                <CardTitle className='text-2xl'>{plan.name}</CardTitle>
                <p className='text-3xl font-semibold tabular-nums'>
                  {formatPrice(plan)} <span className='text-muted-foreground text-base font-normal'>/ {plan.interval}</span>
                </p>
              </CardHeader>
              <CardContent className='flex-1'>
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
          <Card className='bg-muted/40'>
            <CardHeader>
              <CardDescription>Before you pay</CardDescription>
              <CardTitle className='text-2xl'>Trial</CardTitle>
              <p className='text-3xl font-semibold'>
                $0 <span className='text-muted-foreground text-base font-normal'>/ {TRIAL.days} days</span>
              </p>
            </CardHeader>
            <CardContent>
              <ul className='flex flex-col gap-1.5 text-sm'>
                <li>{TRIAL.connectedAccounts} connected accounts</li>
                <li>{TRIAL.writingBatches} AI writing batches</li>
                <li>{TRIAL.mediaCredits} media credit</li>
                <li>{TRIAL.storageMb} MB storage</li>
                <li>No card. No automatic conversion.</li>
              </ul>
            </CardContent>
            <CardFooter>
              <Link href={siteConfig.links.signUp} className={buttonVariants({ variant: 'outline' })}>
                Start free
              </Link>
            </CardFooter>
          </Card>
        </div>
        {anyProposed && (
          <p className='text-muted-foreground mt-4 text-xs'>
            Prices are shown in USD. Introductory pricing applies to early customers; see the FAQ below.
          </p>
        )}
      </Section>

      <Section eyebrow='Compare' title='What each plan includes'>
        <div className='overflow-x-auto rounded-xl border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className='w-56'>Feature</TableHead>
                {plans.map((plan) => (
                  <TableHead key={plan.id}>{plan.name}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {ROWS.map((row) => (
                <TableRow key={row.label}>
                  <TableCell className='font-medium'>{row.label}</TableCell>
                  {plans.map((plan) => (
                    <TableCell key={plan.id}>{row.value(plan)}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Section>

      <Faq items={PRICING_FAQ} />
      <CtaBand />
    </>
  );
}
