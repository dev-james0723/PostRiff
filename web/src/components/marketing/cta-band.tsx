import Link from 'next/link';
import { Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { PRICING_CATALOG } from '@/config/plans';
import { marketingCopy } from '@/config/pricing-copy';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

/** The public entry promise stays Free during launch and rollback. */
const CTA = marketingCopy(PRICING_CATALOG).ctaBand;

interface CtaLink {
  label: string;
  href: string;
}

interface CtaBandProps {
  title?: string;
  description?: string;
  primary?: CtaLink;
  secondary?: CtaLink;
  note?: string;
  className?: string;
}

/** Closing call to action: one glass work surface with the dominant entry action and a quiet secondary (DNA §9.2). */
export function CtaBand({
  title = 'Write once. Approve each version. Publish where your readers are.',
  description = CTA.description,
  primary = { label: CTA.primaryLabel, href: siteConfig.links.signUp },
  secondary = { label: 'See all channels', href: siteConfig.links.channels },
  note = CTA.note,
  className
}: CtaBandProps) {
  return (
    <section className={cn('py-14 sm:py-20', className)}>
      <div className='mx-auto w-full max-w-6xl px-4 sm:px-6'>
        <Surface material='glass' radius='composer' padding='none' className='flex flex-col gap-6 p-6 sm:p-10 md:flex-row md:items-center md:justify-between'>
          <div className='flex max-w-2xl flex-col gap-2'>
            <h2 className='text-foreground text-2xl leading-[1.15] font-medium tracking-[-0.02em] text-balance sm:text-[2rem]'>{title}</h2>
            {description && <p className='text-muted-foreground text-base leading-relaxed text-pretty'>{description}</p>}
          </div>
          <div className='flex flex-col gap-3 md:items-end'>
            <div className='flex flex-wrap gap-3'>
              <Link href={primary.href} className={buttonVariants({ variant: 'action', size: 'control' })}>
                {primary.label}
              </Link>
              {secondary && (
                <Link href={secondary.href} className={buttonVariants({ variant: 'glass', size: 'control' })}>
                  {secondary.label}
                </Link>
              )}
            </div>
            {note && <p className='text-muted-foreground text-xs'>{note}</p>}
          </div>
        </Surface>
      </div>
    </section>
  );
}
