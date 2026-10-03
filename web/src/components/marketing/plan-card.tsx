'use client';

import Link from 'next/link';
import { usePublicPricing } from './public-pricing';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { formatPrice, v2CardAction, v2PlanCards, type Plan, type V2PlanCard } from '@/config/plans';
import { cardPrice } from '@/config/pricing-copy';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

/* Legacy data has no new-sale renderer, including during public rollback. */
export function PlanCard({ plan }: { plan: Plan; priceSize?: 'inline' | 'large'; className?: string }) {
  if (plan.id !== 'studio' && plan.id !== 'assist') throw new Error('Unsupported legacy public plan');
  return null;
}

/**
 * A Pricing v2 plan (Free or a proposed paid plan) in the same glass recipe.
 * Free starts signup; Creator stays unavailable until explicit catalog qualification.
 * A navigation link never authorizes a purchase.
 */
export function V2PlanCardView({ card, priceSize = 'inline', className }: { card: V2PlanCard; priceSize?: 'inline' | 'large'; className?: string }) {
  const catalog = usePublicPricing();
  if (catalog) card = v2PlanCards(catalog).find(plan => plan.id === card.id) ?? { ...card, checkout: 'not_yet_available', checkoutAvailable: false };
  const action = v2CardAction(card, siteConfig.links.signUp);
  const price = cardPrice(card);
  const headingId = `plan-${card.id}`;
  return (
    <Surface material='glass' radius='card' padding='lg' className={cn('flex flex-1 flex-col gap-5', className)} role='group' aria-labelledby={headingId}>
      <div className='flex flex-col gap-1.5'>
        <p className='text-muted-foreground text-sm'>{card.tagline}</p>
        {priceSize === 'large' ? (
          <>
            <h3 id={headingId} className='text-foreground text-2xl font-medium tracking-[-0.01em]'>
              {card.name}
            </h3>
            <p className='text-foreground text-[2rem] leading-none font-medium tracking-[-0.02em] tabular-nums'>
              {formatPrice(card)}
              {card.interval && <span className='text-muted-foreground text-base font-normal tracking-normal'> / {card.interval}</span>}
            </p>
          </>
        ) : (
          <h3 id={headingId} className='text-foreground flex flex-wrap items-baseline gap-x-2 text-2xl font-medium tracking-[-0.01em]'>
            {card.name}
            <span className='text-muted-foreground text-base font-normal tabular-nums'>{price}</span>
          </h3>
        )}
      </div>
      <ul className='flex flex-1 flex-col gap-2 text-sm'>
        {card.highlights.map((item) => (
          <li key={item} className='text-foreground flex items-start gap-2'>
            <Icons.check className='mt-0.5 size-4 shrink-0' aria-hidden />
            {item}
          </li>
        ))}
      </ul>
      <div className='flex flex-col items-start gap-2'>
        {action.href ? (
          <Link href={action.href} className={buttonVariants({ variant: card.plan === 'free' ? 'glass' : 'action', size: 'control' })}>
            {action.label}
          </Link>
        ) : (
          <button type='button' disabled className={buttonVariants({ variant: 'glass', size: 'control' })}>
            {action.label}
          </button>
        )}
        {action.note && <p className='text-muted-foreground text-xs text-pretty'>{action.note}</p>}
      </div>
    </Surface>
  );
}
