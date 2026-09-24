import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { TRIAL, formatPrice, type Plan } from '@/config/plans';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

/**
 * One plan on a glass work surface (DNA §21.18): tagline, name, price, highlights and one
 * dominant action. Prices and limits come from `config/plans`; nothing here is invented.
 */
export function PlanCard({ plan, priceSize = 'inline', className }: { plan: Plan; priceSize?: 'inline' | 'large'; className?: string }) {
  return (
    <Surface material='glass' radius='card' padding='lg' className={cn('flex flex-1 flex-col gap-5', className)}>
      <div className='flex flex-col gap-1.5'>
        <p className='text-muted-foreground text-sm'>{plan.tagline}</p>
        {priceSize === 'large' ? (
          <>
            <h3 className='text-foreground text-2xl font-medium tracking-[-0.01em]'>{plan.name}</h3>
            <p className='text-foreground text-[2rem] leading-none font-medium tracking-[-0.02em] tabular-nums'>
              {formatPrice(plan)} <span className='text-muted-foreground text-base font-normal tracking-normal'>/ {plan.interval}</span>
            </p>
          </>
        ) : (
          <h3 className='text-foreground flex flex-wrap items-baseline gap-x-2 text-2xl font-medium tracking-[-0.01em]'>
            {plan.name}
            <span className='text-muted-foreground text-base font-normal tabular-nums'>
              {formatPrice(plan)} / {plan.interval}
            </span>
          </h3>
        )}
      </div>
      <ul className='flex flex-1 flex-col gap-2 text-sm'>
        {plan.highlights.map((item) => (
          <li key={item} className='text-foreground flex items-start gap-2'>
            <Icons.check className='mt-0.5 size-4 shrink-0' aria-hidden />
            {item}
          </li>
        ))}
      </ul>
      <div className='flex flex-col items-start gap-2'>
        <Link href={`${siteConfig.links.signUp}?plan=${plan.id}`} className={buttonVariants({ variant: 'action', size: 'control' })}>
          Start {TRIAL.days}-day trial
        </Link>
        {plan.status === 'proposed' && <p className='text-muted-foreground text-xs'>Introductory pricing — subject to change before general availability.</p>}
      </div>
    </Surface>
  );
}
