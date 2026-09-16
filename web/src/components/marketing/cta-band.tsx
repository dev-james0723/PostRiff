import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

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

/** Closing call-to-action strip used at the bottom of marketing pages. */
export function CtaBand({
  title = 'Write once. Approve each version. Publish where your readers are.',
  description = 'Start a 14-day trial with two connected accounts and ten writing batches. Export everything, any time.',
  primary = { label: 'Start free trial', href: siteConfig.links.signUp },
  secondary = { label: 'See all channels', href: siteConfig.links.channels },
  note = 'No credit card required during the trial.',
  className
}: CtaBandProps) {
  return (
    <section className={cn('py-14 sm:py-20', className)}>
      <div className='mx-auto w-full max-w-6xl px-4 sm:px-6'>
        <div className='bg-card flex flex-col gap-6 rounded-2xl border p-6 sm:p-10 md:flex-row md:items-center md:justify-between'>
          <div className='flex max-w-2xl flex-col gap-2'>
            <h2 className='text-2xl font-semibold tracking-tight text-balance sm:text-3xl'>
              {title}
            </h2>
            {description && (
              <p className='text-muted-foreground text-base text-pretty'>{description}</p>
            )}
          </div>
          <div className='flex flex-col gap-3 md:items-end'>
            <div className='flex flex-wrap gap-3'>
              <Link href={primary.href} className={buttonVariants({ size: 'lg' })}>
                {primary.label}
              </Link>
              {secondary && (
                <Link
                  href={secondary.href}
                  className={buttonVariants({ size: 'lg', variant: 'outline' })}
                >
                  {secondary.label}
                </Link>
              )}
            </div>
            {note && <p className='text-muted-foreground text-xs'>{note}</p>}
          </div>
        </div>
      </div>
    </section>
  );
}
