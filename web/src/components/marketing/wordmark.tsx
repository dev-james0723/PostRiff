import Link from 'next/link';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';

/** Rafii wordmark: a small inverted mark plus the name, in the interface face. Links home. */
export function Wordmark({ className, href = '/' }: { className?: string; href?: string }) {
  return (
    <Link href={href} aria-label={`${siteConfig.name} home`} className={cn('rafii-focus flex items-center gap-2 rounded-md font-semibold tracking-tight', className)}>
      <span aria-hidden className='bg-primary text-primary-foreground flex size-7 items-center justify-center rounded-[var(--rafii-radius-micro)] text-sm font-bold'>
        R
      </span>
      <span className='text-foreground text-base'>{siteConfig.name}</span>
    </Link>
  );
}
