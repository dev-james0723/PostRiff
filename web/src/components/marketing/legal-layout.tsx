import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { PageHeader } from '@/components/rafii';
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
 * Reading frame for legal pages: the app's PageHeader as identity, the draft banner (until review)
 * on the quiet material, a quiet sticky table of contents on desktop, and the article at a 16px
 * reading measure. Section ids and the legal text itself are untouched.
 */
export function LegalLayout({ eyebrow, title, intro, sections, children }: LegalLayoutProps) {
  return (
    <div className='mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 sm:py-16'>
      <header className='mb-10 flex max-w-3xl flex-col gap-4'>
        <PageHeader density='creative' eyebrow={eyebrow} title={title} description={<span className='block text-base leading-relaxed sm:text-lg'>{intro}</span>} />
        <p className='text-muted-foreground text-sm'>Last updated {LEGAL_LAST_UPDATED}</p>
        {LEGAL_REVIEW_STATUS === 'draft' && (
          <Alert className='rafii-quiet rounded-[var(--rafii-radius-card)] px-4 py-3'>
            <Icons.info className='size-4' />
            <AlertTitle>{LEGAL_REVIEW_BANNER}</AlertTitle>
            <AlertDescription>
              This document describes how Rafii actually works today. It has not yet been reviewed by qualified counsel; placeholders in brackets will be completed before general availability.
            </AlertDescription>
          </Alert>
        )}
      </header>
      <div className='grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[14rem_minmax(0,1fr)]'>
        <nav aria-label='On this page' className='hidden lg:block'>
          <ol className='rafii-quiet sticky top-20 flex flex-col gap-0.5 rounded-[var(--rafii-radius-card)] p-2 text-sm'>
            {sections.map((section, index) => (
              <li key={section.id}>
                <a href={`#${section.id}`} className='rafii-focus text-muted-foreground hover:text-foreground hover:bg-foreground/5 flex min-h-8 items-center gap-2 rounded-[var(--rafii-radius-micro)] px-2 transition-colors'>
                  <span className='tabular-nums'>{index + 1}.</span>
                  {section.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <article className='legal-prose min-w-0 [overflow-wrap:anywhere] text-foreground max-w-3xl text-base leading-relaxed [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:scroll-mt-24 [&_h2]:text-xl [&_h2]:font-medium [&_h2]:tracking-[-0.01em] [&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-medium [&_p]:mb-3 [&_p]:text-pretty [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-6 [&_li]:mb-1 [&_table]:mb-4 [&_table]:w-full [&_table]:text-sm [&_th]:border-b [&_th]:py-2 [&_th]:text-left [&_th]:font-medium [&_td]:border-b [&_td]:py-2 [&_td]:align-top [&_td]:pr-4'>
          {children}
        </article>
      </div>
    </div>
  );
}
