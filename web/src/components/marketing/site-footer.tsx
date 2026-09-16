import Link from 'next/link';
import { ThemeModeToggle } from '@/components/themes/theme-mode-toggle';
import { siteConfig } from '@/config/site';
import { Wordmark } from './wordmark';

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className='border-t'>
      <div className='mx-auto w-full max-w-6xl px-4 py-12 sm:px-6'>
        <div className='grid gap-10 md:grid-cols-[1.4fr_repeat(4,1fr)]'>
          <div className='flex flex-col gap-3'>
            <Wordmark />
            <p className='text-muted-foreground max-w-xs text-sm text-pretty'>
              One idea, every platform, in your voice. You approve before anything publishes.
            </p>
          </div>
          {siteConfig.footerNav.map((column) => (
            <div key={column.title} className='flex flex-col gap-3'>
              <h3 className='text-sm font-semibold'>{column.title}</h3>
              <ul className='flex flex-col gap-2'>
                {column.items.map((item) => (
                  <li key={item.href + item.title}>
                    <Link
                      href={item.href}
                      className='text-muted-foreground hover:text-foreground text-sm transition-colors'
                    >
                      {item.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className='mt-10 flex flex-col-reverse items-start justify-between gap-4 border-t pt-6 sm:flex-row sm:items-center'>
          <p className='text-muted-foreground text-xs'>
            © {year} {siteConfig.name}. All rights reserved.
          </p>
          <ThemeModeToggle />
        </div>
      </div>
    </footer>
  );
}
