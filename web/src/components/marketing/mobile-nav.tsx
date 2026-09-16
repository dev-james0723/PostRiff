'use client';

import * as React from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger
} from '@/components/ui/sheet';
import { siteConfig } from '@/config/site';

/** Hamburger menu for the marketing header at phone width. */
export function MobileNav() {
  const [open, setOpen] = React.useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        render={<Button variant='ghost' size='icon' className='md:hidden' aria-label='Open menu' />}
      >
        <Icons.menu />
      </SheetTrigger>
      <SheetContent side='right' className='w-[86vw] max-w-sm'>
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
              className='hover:bg-muted rounded-lg px-3 py-2.5 text-base font-medium'
            >
              {item.title}
            </Link>
          ))}
        </nav>
        <div className='mt-auto flex flex-col gap-2 p-4'>
          <Link
            href={siteConfig.links.signIn}
            onClick={() => setOpen(false)}
            className={buttonVariants({ variant: 'outline', size: 'lg' })}
          >
            Sign in
          </Link>
          <Link
            href={siteConfig.links.signUp}
            onClick={() => setOpen(false)}
            className={buttonVariants({ size: 'lg' })}
          >
            Start free trial
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
}
