import type { Metadata } from 'next';
import { CtaBand } from '@/components/marketing/cta-band';
import { Faq } from '@/components/marketing/landing/sections';
import { PageHero } from '@/components/marketing/page-hero';
import { V2PlanCardView } from '@/components/marketing/plan-card';
import { Section } from '@/components/marketing/section';
import { Surface } from '@/components/rafii';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PublicPricing } from '@/components/marketing/public-pricing';
import { PRICING_CATALOG, v2PlanCards } from '@/config/plans';
import { marketingCopy, v2CompareRows } from '@/config/pricing-copy';

const copy = marketingCopy(PRICING_CATALOG);

export const metadata: Metadata = {
  title: 'Pricing',
  description: copy.pricingMeta.description,
  openGraph: { title: 'Pricing · Rafii', url: '/pricing' }
};

/** Comparison cells wrap so the comparison stays inside its keyboard-accessible scroll region on narrow viewports (DNA §19.3). */
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

/** Pricing v2: Free, Starter, Creator and Studio, outcomes first; credits are explained once in the FAQ below. */
function V2Plans() {
  const cards = v2PlanCards();
  return (
    <>
      <Section className='pt-8 sm:pt-12'>
        <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-4'>
          <PublicPricing>
          {cards.map((card) => (
            <V2PlanCardView key={card.id} card={card} priceSize='large' />
          ))}
          </PublicPricing>
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
      <V2Plans />
      <Faq items={copy.pricingFaq} />
      <CtaBand />
    </>
  );
}
