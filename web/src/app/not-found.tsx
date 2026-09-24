import type { Metadata } from 'next';
import Link from 'next/link';
import { SiteFooter } from '@/components/marketing/site-footer';
import { SiteHeader } from '@/components/marketing/site-header';
import { Magnetic } from '@/components/motion/magnetic';
import { NotFoundStage } from '@/components/motion/not-found/shared';
import { buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

export const metadata: Metadata = {
  title: 'Page not found',
  description: 'The page you are looking for does not exist or has moved.'
};

const CODE = '404';

/**
 * beUI's Magnetic 404 digits over the Rafii page frame. The digits are decorative and the <h1>
 * keeps the page's real heading; the two actions follow the action ladder (DNA §9.2, §20.4).
 */
export default function NotFound() {
  return (
    <div className='relative isolate flex min-h-svh flex-col'>
      <div aria-hidden className='rafii-ambient' />
      <SiteHeader />
      <main className='flex flex-1 items-center'>
        <NotFoundStage className='mx-auto max-w-6xl py-20 sm:px-6'>
          <div aria-hidden className='text-foreground flex items-center justify-center leading-none font-medium tracking-[-0.04em] select-none [font-size:clamp(5rem,18vw,12rem)]'>
            {Array.from(CODE).map((digit, index) => (
              <Magnetic key={index} strength={0.6} className={cn(index > 0 && '-ml-2')}>
                <span className='inline-block px-1 tabular-nums'>{digit}</span>
              </Magnetic>
            ))}
          </div>
          <div className='flex flex-col items-center gap-2'>
            <h1 className='text-foreground text-[1.625rem] leading-[1.15] font-medium tracking-[-0.02em] text-balance md:text-[1.875rem]'>This page does not exist</h1>
            <p className='text-muted-foreground max-w-sm text-sm leading-relaxed text-pretty'>
              The link may be out of date, or the page may have moved. Try the channel list or head
              back to the start.
            </p>
          </div>
          <div className='flex flex-wrap items-center justify-center gap-3'>
            <Link href='/' className={buttonVariants({ variant: 'action', size: 'control' })}>
              Back to home
            </Link>
            <Link href={siteConfig.links.channels} className={buttonVariants({ variant: 'glass', size: 'control' })}>
              Browse channels
            </Link>
          </div>
        </NotFoundStage>
      </main>
      <SiteFooter />
    </div>
  );
}
