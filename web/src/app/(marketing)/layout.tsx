import { SiteFooter } from '@/components/marketing/site-footer';
import { SiteHeader } from '@/components/marketing/site-header';

/**
 * Public site frame. The same ambient canvas as the signed-in shell sits behind the header, so
 * landing → app reads as one product (DNA §21.19); the skip link targets this page's main content.
 */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className='relative isolate flex min-h-svh flex-col'>
      <div aria-hidden className='rafii-ambient' />
      <a
        href='#main-content'
        className='bg-background ring-ring sr-only rounded-md px-3 py-2 text-sm font-medium shadow focus:not-sr-only focus:absolute focus:top-2 focus:start-2 focus:z-50 focus:ring-2'
      >
        Skip to content
      </a>
      <SiteHeader />
      <main id='main-content' tabIndex={-1} className='flex-1 outline-none'>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
