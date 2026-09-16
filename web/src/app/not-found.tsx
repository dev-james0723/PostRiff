import type { Metadata } from 'next';
import { SiteFooter } from '@/components/marketing/site-footer';
import { SiteHeader } from '@/components/marketing/site-header';
import { Magnetic } from '@/components/motion/magnetic';
import { NotFoundActions, NotFoundStage } from '@/components/motion/not-found/shared';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

export const metadata: Metadata = {
  title: 'Page not found',
  description: 'The page you are looking for does not exist or has moved.'
};

const CODE = '404';

/**
 * beUI's Magnetic 404, assembled from its exported parts. The stock `NotFoundMagnetic` makes the code the <h1> and the
 * title a <p>; here the digits are decorative and the <h1> keeps the page's real heading.
 */
export default function NotFound() {
  return (
    <div className='flex min-h-svh flex-col'>
      <SiteHeader />
      <main className='flex flex-1 items-center'>
        <NotFoundStage className='mx-auto max-w-6xl py-20 sm:px-6'>
          <div aria-hidden className='text-foreground flex items-center justify-center leading-none font-bold tracking-tighter select-none [font-size:clamp(5rem,18vw,12rem)]'>
            {Array.from(CODE).map((digit, index) => (
              <Magnetic key={index} strength={0.6} className={cn(index > 0 && '-ml-2')}>
                <span className='inline-block px-1 tabular-nums'>{digit}</span>
              </Magnetic>
            ))}
          </div>
          <div className='flex flex-col items-center gap-2'>
            <h1 className='text-foreground text-lg font-semibold text-balance'>This page does not exist</h1>
            <p className='text-muted-foreground max-w-sm text-sm text-pretty'>
              The link may be out of date, or the page may have moved. Try the channel list or head
              back to the start.
            </p>
          </div>
          <NotFoundActions homeHref='/' homeLabel='Back to home' browseHref={siteConfig.links.channels} browseLabel='Browse channels' />
        </NotFoundStage>
      </main>
      <SiteFooter />
    </div>
  );
}
