'use client';

import React from 'react';
import { PageHeader } from '@/components/rafii/page-header';
import { StateMessage } from '@/components/rafii/state-message';
import { useInfobar, type InfobarContent } from '@/components/ui/infobar';
import { cn } from '@/lib/utils';

/**
 * Publishes a page's help content to the right-hand info sidebar. Pages with a title do this through
 * the heading's info button; a page without a header (Home) would otherwise never publish, and the
 * sidebar would show its generic fallback.
 */
function PublishInfo({ content }: { content: InfobarContent }) {
  const { setContent } = useInfobar();
  const ref = React.useRef(content);
  ref.current = content;
  React.useEffect(() => {
    setContent(ref.current);
  }, [setContent]);
  return null;
}

function PageSkeleton() {
  return (
    <div role='status' aria-label='Loading page' className='flex flex-1 flex-col gap-4'>
      <div className='bg-muted h-8 w-48 animate-pulse rounded-lg motion-reduce:animate-none' />
      <div className='rafii-quiet mt-2 h-40 w-full rounded-[var(--rafii-radius-card)]' />
      <div className='rafii-quiet h-40 w-full rounded-[var(--rafii-radius-card)]' />
    </div>
  );
}

export default function PageContainer({
  children,
  isLoading = false,
  access = true,
  accessFallback,
  pageTitle,
  pageDescription,
  pageEyebrow,
  pageAccent,
  infoContent,
  pageHeaderAction,
  density = 'functional',
  width = 'full',
  className
}: {
  children?: React.ReactNode;
  isLoading?: boolean;
  access?: boolean;
  accessFallback?: React.ReactNode;
  pageTitle?: string;
  pageDescription?: string;
  /** Short tracked label above the title. */
  pageEyebrow?: string;
  /** Serif-italic phrase appended to the title (one short phrase, DNA §6.4). */
  pageAccent?: string;
  infoContent?: InfobarContent;
  pageHeaderAction?: React.ReactNode;
  density?: 'functional' | 'creative';
  /** `reading` narrows long forms and settings to a comfortable measure; `full` keeps dense tools wide. */
  width?: 'full' | 'reading';
  className?: string;
}) {
  if (!access) {
    return (
      <div className='flex flex-1 items-center justify-center p-4 md:px-6'>
        {accessFallback ?? <StateMessage kind='permission' title='No access' description='Ask a workspace owner or admin for access.' className='w-full max-w-md' />}
      </div>
    );
  }

  const content = isLoading ? <PageSkeleton /> : children;
  const hasHeader = pageTitle || pageHeaderAction;

  return (
    <div className={cn('flex min-w-0 flex-1 flex-col gap-5 px-4 pt-3 pb-6 md:px-8 md:pt-5 lg:px-10', width === 'reading' && 'mx-auto w-full max-w-4xl', className)}>
      {!hasHeader && infoContent && <PublishInfo content={infoContent} />}
      {hasHeader && <PageHeader eyebrow={pageEyebrow} title={pageTitle ?? ''} accent={pageAccent} description={pageDescription} infoContent={infoContent} actions={pageHeaderAction} density={density} />}
      {content}
    </div>
  );
}
