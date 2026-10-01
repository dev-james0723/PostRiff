import type { Metadata } from 'next';
import Link from 'next/link';
import { CtaBand } from '@/components/marketing/cta-band';
import { Faq } from '@/components/marketing/landing/sections';
import { PageHero } from '@/components/marketing/page-hero';
import { PlanCard, V2PlanCardView } from '@/components/marketing/plan-card';
import { Section } from '@/components/marketing/section';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PRICING_CATALOG, plans, v2PlanCards } from '@/config/plans';
import { LEGACY_TRIAL_CARD, legacyCompareRows, marketingCopy, v2CompareRows } from '@/config/pricing-copy';
import { siteConfig } from '@/config/site';

const copy = marketingCopy(PRICING_CATALOG);

export const metadata: Metadata = {
  title: 'Pricing',
  description: copy.pricingMeta.description,
  openGraph: { title: 'Pricing · Rafii', url: '/pricing' }
};

/** Comparison cells wrap so the three columns fit a 320px viewport without page scroll (DNA §19.3). */
const CELL = 'px-4 py-3 align-top whitespace-normal';

function CompareTable({ columns, rows }: { columns: string[]; rows: { label: string; values: string[] }[] }) {
  return (
    <Surface material='quiet' radius='card' padding='none' className='overflow-hidden'>
      <Table>
        <TableHeader>
          <TableRow className='hover:bg-transparent'>
            <TableHead className={`${CELL} md:w-56`}>Feature</TableHead>
            {columns.map((name) => (
              <TableHead key={name} className={CELL}>
                {name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label} className='hover:bg-transparent'>
              <TableCell className={`${CELL} text-foreground font-medium`}>{row.label}</TableCell>
              {row.values.map((value, index) => (
                <TableCell key={columns[index]} className={CELL}>
                  {value}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Surface>
  );
}

/** Today's catalog: two plans and the trial. Unchanged until NEXT_PUBLIC_PRICING_CATALOG=v2. */
function LegacyPlans() {
  return (
    <>
      <Section className='pt-8 sm:pt-12'>
        <div className='grid gap-4 md:grid-cols-3'>
          {plans.map((plan) => (
            <PlanCard key={plan.id} plan={plan} priceSize='large' />
          ))}
          <Surface material='quiet' radius='card' padding='lg' className='flex flex-col gap-5'>
            <div className='flex flex-col gap-1.5'>
              <p className='text-muted-foreground text-sm'>{LEGACY_TRIAL_CARD.eyebrow}</p>
              <h3 className='text-foreground text-2xl font-medium tracking-[-0.01em]'>{LEGACY_TRIAL_CARD.title}</h3>
              <p className='text-foreground text-[2rem] leading-none font-medium tracking-[-0.02em] tabular-nums'>
                $0 <span className='text-muted-foreground text-base font-normal tracking-normal'>{LEGACY_TRIAL_CARD.priceSuffix}</span>
              </p>
            </div>
            <ul className='text-foreground flex flex-1 flex-col gap-2 text-sm'>
              {LEGACY_TRIAL_CARD.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <div>
              <Link href={siteConfig.links.signUp} className={buttonVariants({ variant: 'glass', size: 'control' })}>
                {LEGACY_TRIAL_CARD.action}
              </Link>
            </div>
          </Surface>
        </div>
        {copy.pricingFootnote && <p className='text-muted-foreground mt-4 text-xs'>{copy.pricingFootnote}</p>}
      </Section>

      <Section eyebrow='Compare' title='What each plan includes'>
        <CompareTable columns={plans.map((plan) => plan.name)} rows={legacyCompareRows()} />
      </Section>
    </>
  );
}

/** Pricing v2: Free and Creator only, outcomes first; credits are explained once in the FAQ below. */
function V2Plans() {
  const cards = v2PlanCards();
  return (
    <>
      <Section className='pt-8 sm:pt-12'>
        <div className='grid gap-4 md:grid-cols-2'>
          {cards.map((card) => (
            <V2PlanCardView key={card.id} card={card} priceSize='large' />
          ))}
        </div>
        {copy.pricingFootnote && <p className='text-muted-foreground mt-4 text-xs text-pretty'>{copy.pricingFootnote}</p>}
      </Section>

      <Section eyebrow='Compare' title='What each plan includes'>
        <CompareTable columns={cards.map((card) => card.name)} rows={v2CompareRows()} />
      </Section>
    </>
  );
}

export default function PricingPage() {
  const hero = copy.pricingHero;
  return (
    <>
      <PageHero eyebrow={hero.eyebrow} title={hero.title} accent={hero.accent} description={hero.description} />
      {copy.catalog === 'v2' ? <V2Plans /> : <LegacyPlans />}
      <Faq items={copy.pricingFaq} />
      <CtaBand />
    </>
  );
}
