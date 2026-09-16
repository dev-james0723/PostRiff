import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';
import { MobileNav } from './mobile-nav';
import { Wordmark } from './wordmark';

export function SiteHeader() {
  return (
    <header className='bg-background/80 supports-backdrop-filter:bg-background/60 sticky top-0 z-40 border-b backdrop-blur'>
      <div className='mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6'>
        <div className='flex items-center gap-8'>
          <Wordmark />
          <nav aria-label='Main' className='hidden items-center gap-1 md:flex'>
            {siteConfig.mainNav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className='text-muted-foreground hover:text-foreground rounded-md px-3 py-1.5 text-sm font-medium transition-colors'
              >
                {item.title}
              </Link>
            ))}
          </nav>
        </div>
        <div className='flex items-center gap-2'>
          <ThemeModeToggle />
          <Link
            href={siteConfig.links.signIn}
            className={cn(buttonVariants({ variant: 'ghost' }), 'hidden md:inline-flex')}
          >
            Sign in
          </Link>
          <Link
            href={siteConfig.links.signUp}
            className={cn(buttonVariants(), 'hidden md:inline-flex')}
          >
            Start free trial
          </Link>
          <MobileNav />
        </div>
      </div>
    </header>
  );
}
