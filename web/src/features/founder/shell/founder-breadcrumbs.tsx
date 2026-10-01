'use client';

import { Fragment } from 'react';
import { usePathname } from 'next/navigation';
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb';
import { Icons } from '@/components/icons';
import { founderBreadcrumbs } from '@/config/founder-nav';

/** `Founder › Section` from the address; record ids never appear here (they live in the drawer's query string). */
export function FounderBreadcrumbs() {
  const items = founderBreadcrumbs(usePathname() ?? '/founder');
  return (
    <Breadcrumb className='min-w-0'>
      <BreadcrumbList className='min-w-0 flex-nowrap md:max-lg:gap-1'>
        {items.map((item, index) => (
          <Fragment key={item.link}>
            {index < items.length - 1 ? (
              <>
                <BreadcrumbItem className='hidden min-w-6 md:block'>
                  <BreadcrumbLink href={item.link} className='block truncate' title={item.title}>
                    {item.title}
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator className='hidden shrink-0 md:block'>
                  <Icons.slash />
                </BreadcrumbSeparator>
              </>
            ) : (
              <BreadcrumbItem className='min-w-6'>
                <BreadcrumbPage className='block truncate' title={item.title}>
                  {item.title}
                </BreadcrumbPage>
              </BreadcrumbItem>
            )}
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}
