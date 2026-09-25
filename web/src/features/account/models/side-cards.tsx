'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import type { LearningSummary, MemoryEgress, ModelOption, ResearchEgress } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { SettingsSection } from '../settings-section';
import { costCopy, distinctCostClasses } from './catalog';

const linkClass = cn('t-learn', buttonVariants({ variant: 'quiet', size: 'sm' }), 'text-foreground -ml-2.5 min-h-9');

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
    <SettingsSection id='models-billing' title='Costs' data-tour='models-billing'>
      <div className='flex flex-col gap-3 text-sm'>
        {classes.map((costClass) => {
          const copy = costCopy(costClass || undefined);
          return (
            <div key={costClass || 'unreported'} className='flex flex-col items-start gap-1'>
              <Badge variant='secondary'>{copy.badge}</Badge>
              <span className='text-muted-foreground leading-relaxed'>{copy.line}</span>
            </div>
          );
        })}
      </div>
      <div className='flex flex-col items-start gap-1'>
        <PageLink href='/app/account/billing'>Usage &amp; plan</PageLink>
        {!owner && <span className='text-muted-foreground text-xs'>Only the owner sees billing.</span>}
      </div>
    </SettingsSection>
  );
}

function ConsentRow({ title, state, children }: { title: string; state: string; children: ReactNode }) {
  return (
    <div className='flex flex-col gap-1'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-foreground text-sm font-medium'>{title}</span>
        <Badge variant='secondary'>{state}</Badge>
      </div>
      <p className='text-muted-foreground text-xs leading-relaxed'>{children}</p>
    </div>
  );
}

/** Describes the extractor configured on the API server and its current consent gate. */
function LearningRow({ learning }: { learning: LearningSummary; egress: MemoryEgress | undefined }) {
  if (learning.enabled === false) {
    return (
      <ConsentRow title='Learning from your edits' state='Off'>
        Your edits aren’t read.
      </ConsentRow>
    );
  }
  const extractor = learning.extractor;
  if (extractor?.kind === 'rules') return <ConsentRow title='Learning from your edits' state='Rules only'>Simple rules read your edits. No AI model does.</ConsentRow>;
  if (extractor?.kind === 'local' && extractor.egress === 'local') return <ConsentRow title='Learning from your edits' state='Local model'>A local model ({extractor.model ?? 'name not reported'}) may read your edits. Nothing goes to the cloud.</ConsentRow>;
  if (extractor?.kind === 'cloud' || extractor?.egress === 'cloud' || extractor?.kind === 'local') return <ConsentRow title='Learning from your edits' state={extractor.allowed ? 'Cloud model allowed' : 'Rules only'}>{extractor.allowed ? `A cloud model (${extractor.model ?? 'name not reported'}) may read redacted edits.` : 'No cloud model reads your edits until an owner turns on cloud learning and memory sharing.'}</ConsentRow>;
  return <ConsentRow title='Learning from your edits' state='Not reported'>Simple rules read your edits. AI model use wasn’t reported.</ConsentRow>;
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
        <StateMessage
          kind='error'
          layout='inline'
          title='Couldn’t load these settings'
          action={
            error ? (
              <Button variant='glass' size='sm' className='min-h-9' onClick={onRetry}>
                <Icons.refresh className='size-3.5' /> Retry
              </Button>
            ) : undefined
          }
        />
      );
    }
    const withheld = egress?.withheldBoundaries ?? 0;
    return (
      <div className='flex flex-col gap-3'>
        {egress && (
          <ConsentRow title='Memory files for the managed model' state={egress.cloud ? 'Shared' : 'Not shared'}>
            {egress.cloud ? `Reads ${egress.sharedFiles.length} memory file${egress.sharedFiles.length === 1 ? '' : 's'}.` : 'Writes without your memory files.'}{' '}
            {withheld > 0 ? `${withheld} private boundar${withheld === 1 ? 'y is' : 'ies are'} never sent. ` : ''}
            CLI writers always read them.
          </ConsentRow>
        )}
        {research && (
          <ConsentRow
            title='Web research'
            state={research.enabled === false ? 'Off' : research.hosted ? (research.web ? 'On' : 'Off') : 'On'}
          >
            {research.enabled === false
              ? 'Drafts use only what you supply.'
              : research.hosted
                ? research.web
                  ? 'Looks up missing facts, with any writer.'
                  : 'Drafts use only what you supply.'
                : 'Always on when running on your own computer.'}
            {research.enabled !== false && research.processors.length > 0 ? ` Sent to: ${research.processors.join('; ')}.` : ''}
          </ConsentRow>
        )}
        {learning && <LearningRow learning={learning} egress={egress} />}
      </div>
    );
  };

  return (
    <SettingsSection id='models-consent' title='What may leave this workspace' description='The owner sets these in Memory.' data-tour='models-consent'>
      {body()}
      <div className='flex flex-wrap gap-x-3'>
        <PageLink href='/app/workspace/memory'>Memory</PageLink>
        <PageLink href='/app/account/privacy'>Privacy &amp; data</PageLink>
      </div>
    </SettingsSection>
  );
}
