import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';
import { MobileNav } from './mobile-nav';
import { Wordmark } from './wordmark';

/**
 * Public header on the same translucent panel as the app's `Header` (DNA §8.2): wordmark, the
 * main navigation as quiet text controls, the theme toggle, and the two entry paths (Sign in,
 * Start free trial) whose hrefs are the product's real auth routes.
 */
export function SiteHeader() {
  return (
    <header className='rafii-panel sticky top-0 z-40'>
      <div className='mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6 md:h-[3.75rem]'>
        <div className='flex min-w-0 items-center gap-6 lg:gap-8'>
          <Wordmark />
          <nav aria-label='Main' className='hidden items-center gap-1 md:flex'>
            {siteConfig.mainNav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className='rafii-focus text-muted-foreground hover:text-foreground hover:rafii-quiet inline-flex min-h-10 items-center rounded-[var(--rafii-radius-control)] px-3 text-sm font-medium transition-colors'
              >
                {item.title}
              </Link>
            ))}
          </nav>
        </div>
        <div className='flex items-center gap-2'>
          <ThemeModeToggle />
          <Link href={siteConfig.links.signIn} className={cn(buttonVariants({ variant: 'quiet', size: 'lg' }), 'hidden min-h-10 px-3.5 md:inline-flex')}>
            Sign in
          </Link>
          <Link href={siteConfig.links.signUp} className={cn(buttonVariants({ variant: 'action', size: 'lg' }), 'hidden min-h-10 px-4 md:inline-flex')}>
            Start free trial
          </Link>
          <MobileNav />
        </div>
      </div>
    </header>
  );
}
