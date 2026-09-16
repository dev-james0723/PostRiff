import type { Metadata } from 'next';
import Link from 'next/link';
import { SiteFooter } from '@/components/marketing/site-footer';
import { SiteHeader } from '@/components/marketing/site-header';
import { buttonVariants } from '@/components/ui/button';
import { siteConfig } from '@/config/site';

export const metadata: Metadata = {
  title: 'Page not found',
  description: 'The page you are looking for does not exist or has moved.'
};

export default function NotFound() {
  return (
    <div className='flex min-h-svh flex-col'>
      <SiteHeader />
      <main className='flex flex-1 items-center'>
        <div className='mx-auto flex w-full max-w-6xl flex-col items-start gap-4 px-4 py-20 sm:px-6'>
          <p className='text-primary text-xs font-semibold tracking-[0.18em] uppercase'>404</p>
          <h1 className='text-3xl font-semibold tracking-tight text-balance sm:text-4xl'>
            This page does not exist
          </h1>
          <p className='text-muted-foreground max-w-md text-pretty'>
            The link may be out of date, or the page may have moved. Try the channel list or head
            back to the start.
          </p>
          <div className='mt-2 flex flex-wrap gap-3'>
            <Link href='/' className={buttonVariants({ size: 'lg' })}>
              Back to home
            </Link>
            <Link
              href={siteConfig.links.channels}
              className={buttonVariants({ size: 'lg', variant: 'outline' })}
            >
              Browse channels
            </Link>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
