import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { LEGAL_LAST_UPDATED, LEGAL_REVIEW_BANNER, LEGAL_REVIEW_STATUS } from '@/config/legal';

export interface LegalSection {
  id: string;
  title: string;
}

interface LegalLayoutProps {
  eyebrow: string;
  title: string;
  intro: ReactNode;
  sections: LegalSection[];
  children: ReactNode;
}

/**
 * Prose container for legal pages: draft banner (until review), sticky
 * table of contents on desktop, dated heading.
 */
export function LegalLayout({ eyebrow, title, intro, sections, children }: LegalLayoutProps) {
  return (
    <div className='mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 sm:py-16'>
      <header className='mb-8 flex max-w-3xl flex-col gap-3'>
        <p className='text-primary text-xs font-semibold tracking-[0.18em] uppercase'>{eyebrow}</p>
        <h1 className='text-3xl font-semibold tracking-tight text-balance sm:text-4xl'>{title}</h1>
        <p className='text-muted-foreground text-sm'>Last updated {LEGAL_LAST_UPDATED}</p>
        <div className='text-muted-foreground text-base text-pretty'>{intro}</div>
        {LEGAL_REVIEW_STATUS === 'draft' && (
          <Alert>
            <Icons.info className='size-4' />
            <AlertTitle>{LEGAL_REVIEW_BANNER}</AlertTitle>
            <AlertDescription>
              This document describes how Rafii actually works today. It has not yet been reviewed by qualified counsel; placeholders in brackets will be completed before general availability.
            </AlertDescription>
          </Alert>
        )}
      </header>
      <div className='grid gap-10 lg:grid-cols-[14rem_1fr]'>
        <nav aria-label='On this page' className='hidden lg:block'>
          <ol className='sticky top-20 flex flex-col gap-1.5 text-sm'>
            {sections.map((section, index) => (
              <li key={section.id}>
                <a href={`#${section.id}`} className='text-muted-foreground hover:text-foreground flex gap-2'>
                  <span className='tabular-nums'>{index + 1}.</span>
                  {section.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <article className='legal-prose max-w-3xl [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:scroll-mt-20 [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-semibold [&_p]:mb-3 [&_p]:text-pretty [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-6 [&_li]:mb-1 [&_table]:mb-4 [&_table]:w-full [&_table]:text-sm [&_th]:border-b [&_th]:py-2 [&_th]:text-left [&_th]:font-semibold [&_td]:border-b [&_td]:py-2 [&_td]:align-top [&_td]:pr-4'>
          {children}
        </article>
      </div>
    </div>
  );
}
