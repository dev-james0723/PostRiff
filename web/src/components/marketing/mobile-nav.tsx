'use client';

import * as React from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { siteConfig } from '@/config/site';

/**
 * Hamburger menu for the marketing header at phone width: an elevated glass sheet with 44px rows
 * (DNA §12, §23.1). The primitive keeps its focus trap and Escape handling.
 */
export function MobileNav() {
  const [open, setOpen] = React.useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<Button variant='quiet' size='icon-control' className='md:hidden' aria-label='Open menu' />}>
        <Icons.menu className='size-5' />
      </SheetTrigger>
      <SheetContent side='right' className='rafii-elevated w-[86vw] max-w-sm rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0'>
        <SheetHeader>
          <SheetTitle>{siteConfig.name}</SheetTitle>
          <SheetDescription className='sr-only'>Site navigation</SheetDescription>
        </SheetHeader>
        <nav className='flex flex-col gap-1 px-2'>
          {siteConfig.mainNav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className='rafii-focus hover:rafii-quiet text-foreground flex min-h-11 items-center rounded-[var(--rafii-radius-control)] px-3 text-base font-medium transition-colors'
            >
              {item.title}
            </Link>
          ))}
        </nav>
        <div className='mt-auto flex flex-col gap-2 p-4'>
          <Link href={siteConfig.links.signIn} onClick={() => setOpen(false)} className={buttonVariants({ variant: 'glass', size: 'control' })}>
            Sign in
          </Link>
          <Link href={siteConfig.links.signUp} onClick={() => setOpen(false)} className={buttonVariants({ variant: 'action', size: 'control' })}>
            Start free trial
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
}
