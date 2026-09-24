import Link from 'next/link';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

/** Rafii wordmark: a small mark plus the name. Links home. */
export function Wordmark({ className, href = '/' }: { className?: string; href?: string }) {
  return (
    <Link
      href={href}
      aria-label={`${siteConfig.name} home`}
      className={cn('flex items-center gap-2 font-semibold tracking-tight', className)}
    >
      <span
        aria-hidden
        className='bg-primary text-primary-foreground flex size-7 items-center justify-center rounded-md text-sm font-bold'
      >
        R
      </span>
      <span className='text-base'>{siteConfig.name}</span>
    </Link>
  );
}
