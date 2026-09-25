'use client';

import * as React from 'react';
import { Icons } from '@/components/icons';
import Link from 'next/link';
import { StateMessage } from '@/components/rafii';
import {
  Infobar,
  InfobarContent,
  InfobarGroup,
  InfobarGroupContent,
  InfobarHeader,
  InfobarRail,
  InfobarTrigger,
  useInfobar,
  type InfobarContent as InfobarData
} from '@/components/ui/infobar';
import { cn } from '@/lib/utils';

// Default/fallback data when no content is set
// Shown only on a page that publishes no help of its own. It points at the real help surfaces.
const defaultData: InfobarData = {
  title: 'Help',
  sections: [
    {
      title: 'Take the tour',
      description: 'Open the ? menu in the header for the tour and tips for this page.'
    },
    {
      title: 'Jump anywhere',
      description: 'Press ⌘K (Ctrl+K) and type any page or action.'
    }
  ]
};

/**
 * The contextual help panel (DNA §8.2): a quiet reading surface on the shell's translucent
 * panel, borderless, with spacing and eyebrows doing the grouping. Content still arrives
 * through `useInfobar`; the trigger, rail and keyboard shortcut are the shared Infobar's.
 */
export function InfoSidebar({ className, ...props }: React.ComponentProps<typeof Infobar>) {
  const { content } = useInfobar();
  const data = content || defaultData;

  return (
    <Infobar className={cn('rounded-tl-[var(--rafii-radius-card)] border-0', className)} {...props}>
      <InfobarHeader className='sticky top-0 z-10 flex flex-row items-start justify-between gap-3 px-5 pt-5 pb-3'>
        <div className='flex min-w-0 flex-1 flex-col gap-1'>
          <h2 className='text-foreground text-lg font-medium tracking-tight wrap-break-word'>{data.title}</h2>
        </div>
        <div className='shrink-0'>
          <InfobarTrigger className='rafii-focus hover:rafii-quiet size-9 rounded-full' />
        </div>
      </InfobarHeader>
      <InfobarContent>
        <InfobarGroup className='p-0'>
          <InfobarGroupContent>
            <div className='flex flex-col gap-6 px-5 pt-1 pb-6'>
              {data.sections && data.sections.length > 0 ? (
                data.sections.map((section) => (
                  <div key={section.title} className='flex flex-col gap-2'>
                    {section.title && <h3 className='text-foreground text-sm font-medium'>{section.title}</h3>}
                    {section.description && <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>{section.description}</p>}
                    {section.links && section.links.length > 0 && (
                      <div className='flex flex-col gap-2 pt-1'>
                        <h4 className='rafii-eyebrow'>Learn more</h4>
                        <ul className='flex flex-col gap-1'>
                          {section.links.map((link) => (
                            <li key={link.title}>
                              <Link
                                href={link.url}
                                className='rafii-focus text-foreground -mx-1 inline-flex min-h-9 items-center gap-1.5 rounded-md px-1 text-sm underline underline-offset-4'
                                target='_blank'
                                rel='noopener noreferrer'
                              >
                                <span>{link.title}</span>
                                <Icons.chevronRight className='size-3.5' aria-hidden />
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <StateMessage kind='empty' layout='inline' title='No help for this page yet' />
              )}
            </div>
          </InfobarGroupContent>
        </InfobarGroup>
      </InfobarContent>
      <InfobarRail />
    </Infobar>
  );
}
