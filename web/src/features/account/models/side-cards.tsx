'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import type { LearningSummary, MemoryEgress, ModelOption, ResearchEgress } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { costCopy, distinctCostClasses } from './catalog';

const linkClass = cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), '-ml-2.5');

function PageLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className={linkClass}>
      {children} <LearnMoreChevron />
    </Link>
  );
}

/** How each writer someone can pick here is paid for, generated from the cost classes of available options. */
export function BillingCard({ options, owner }: { options: ModelOption[]; owner: boolean }) {
  const classes = distinctCostClasses(options);
  if (classes.length === 0) return null;

  return (
    <Card data-tour='models-billing'>
      <CardHeader>
        <CardTitle className='text-base'>How each writer is paid for</CardTitle>
        <CardDescription>Only the kinds of writer available to pick here.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3 text-sm'>
        {classes.map((costClass) => {
          const copy = costCopy(costClass || undefined);
          return (
            <div key={costClass || 'unreported'} className='flex flex-col items-start gap-1'>
              <Badge variant='outline'>{copy.badge}</Badge>
              <span className='text-muted-foreground'>{copy.line}</span>
            </div>
          );
        })}
      </CardContent>
      <CardFooter className='flex flex-col items-start gap-1'>
        <PageLink href='/app/account/billing'>Usage &amp; plan</PageLink>
        {!owner && <span className='text-muted-foreground text-xs'>Costs and billing controls are visible to the workspace owner.</span>}
      </CardFooter>
    </Card>
  );
}

function ConsentRow({ title, state, children }: { title: string; state: string; children: ReactNode }) {
  return (
    <div className='flex flex-col gap-1'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-medium'>{title}</span>
        <Badge variant='outline'>{state}</Badge>
      </div>
      <p className='text-muted-foreground text-xs'>{children}</p>
    </div>
  );
}

/** Describes the extractor configured on the API server and its current consent gate. */
function LearningRow({ learning }: { learning: LearningSummary; egress: MemoryEgress | undefined }) {
  if (learning.enabled === false) {
    return (
      <ConsentRow title='Learning from your edits' state='Off'>
        Learning is switched off, so PostRiff does not read your edits to propose preferences.
      </ConsentRow>
    );
  }
  const extractor = learning.extractor;
  if (extractor?.kind === 'rules') return <ConsentRow title='Learning from your edits' state='Counting rules'>Counting rules read your edits. No model extractor is configured.</ConsentRow>;
  if (extractor?.kind === 'local') return <ConsentRow title='Learning from your edits' state='Local model'>Counting rules and the configured local model ({extractor.model ?? 'model name unavailable'}) may read edit pairs. The cloud switch does not govern this local route.</ConsentRow>;
  if (extractor?.kind === 'cloud') return <ConsentRow title='Learning from your edits' state={extractor.allowed ? 'Cloud model allowed' : 'Counting rules only'}>Counting rules read your edits. {extractor.allowed ? `The configured cloud model (${extractor.model ?? 'model name unavailable'}) may read redacted edit pairs.` : 'The configured cloud model cannot read edit pairs until both cloud extraction and memory sharing are enabled.'}</ConsentRow>;
  return <ConsentRow title='Learning from your edits' state='Extractor unavailable'>Counting rules read your edits. This server did not report whether a model extractor is configured.</ConsentRow>;
}

export interface ConsentCardProps {
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  egress: MemoryEgress | undefined;
  research: ResearchEgress | undefined;
  learning: LearningSummary | undefined;
}

/** What may leave the workspace while drafting, read from the Memory endpoint. Owners change it on Memory. */
export function ConsentCard({ loading, error, onRetry, egress, research, learning }: ConsentCardProps) {
  const body = () => {
    if (loading) {
      return (
        <div className='flex flex-col gap-3'>
          <Skeleton className='h-10 w-full' />
          <Skeleton className='h-10 w-full' />
        </div>
      );
    }
    if (error || (!egress && !research)) {
      return (
        <div className='flex flex-col items-start gap-2'>
          <p className='text-sm'>Unavailable</p>
          <p className='text-muted-foreground text-xs'>These settings could not be loaded. Nothing here means they are off.</p>
          {error && (
            <Button variant='outline' size='sm' onClick={onRetry}>
              <Icons.refresh className='size-3.5' /> Retry
            </Button>
          )}
        </div>
      );
    }
    const withheld = egress?.withheldBoundaries ?? 0;
    return (
      <div className='flex flex-col gap-3'>
        {egress && (
          <ConsentRow title='Memory files for the managed model' state={egress.cloud ? 'Shared' : 'Not shared'}>
            {egress.cloud
              ? `The managed model reads ${egress.sharedFiles.length} memory file${egress.sharedFiles.length === 1 ? '' : 's'}.`
              : 'The managed model writes without your memory files.'}{' '}
            {withheld > 0 ? `${withheld} private or local-only boundar${withheld === 1 ? 'y is' : 'ies are'} never sent. ` : ''}
            Local CLI writers always read them.
          </ConsentRow>
        )}
        {research && (
          <ConsentRow
            title='Web research'
            state={research.enabled === false ? 'Off for this deployment' : research.hosted ? (research.web ? 'On' : 'Off') : 'On'}
          >
            {research.enabled === false
              ? 'Drafts use only what you supply.'
              : research.hosted
                ? research.web
                  ? 'When a draft needs facts you have not supplied, PostRiff looks them up, whichever writer you pick.'
                  : 'Drafts use only what you supply, whichever writer you pick.'
                : 'Always on when PostRiff runs on your own machine, whichever writer you pick.'}
            {research.enabled !== false && research.processors.length > 0 ? ` Sent to: ${research.processors.join('; ')}.` : ''}
          </ConsentRow>
        )}
        {learning && <LearningRow learning={learning} egress={egress} />}
      </div>
    );
  };

  return (
    <Card data-tour='models-consent'>
      <CardHeader>
        <CardTitle className='text-base'>What may leave this workspace</CardTitle>
        <CardDescription>An owner decides these on the Memory page.</CardDescription>
      </CardHeader>
      <CardContent>{body()}</CardContent>
      <CardFooter className='flex flex-wrap gap-x-3'>
        <PageLink href='/app/workspace/memory'>Memory</PageLink>
        <PageLink href='/app/account/privacy'>Privacy &amp; data</PageLink>
      </CardFooter>
    </Card>
  );
}
