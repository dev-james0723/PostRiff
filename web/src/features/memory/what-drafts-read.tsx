'use client';

import { useId, useState, type ComponentPropsWithoutRef } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { SegmentedControl, StateMessage, Surface } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useMemory, useSnapshot } from '@/lib/api/hooks';
import type { MemoryEgress, MemoryFile } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { cn } from '@/lib/utils';
import { DRAFT_GROUP_LABEL, draftGroupOf, groupMemoryFiles, type DraftGroup } from './memory-files';
import { StaleNotice, Unavailable } from './memory-states';

const BRAND_HREF = '/app/workspace/brand';
const MEMORY_HREF = '/app/workspace/memory';
const BODY_CLASS = 'max-w-prose overflow-x-auto px-5 py-4 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap';

type WhatDraftsReadProps = {
  /**
   * The file to show, picked by a list the page owns (the Memory page's file tree). Leave it out and the panel
   * offers the files given to writing routes as its own tabs, for a page without a file list (Brand).
   */
  selected?: string | null;
  /** Links to the Memory page, where an owner decides who else reads these files. */
  showMemoryLink?: boolean;
  className?: string;
} & Omit<ComponentPropsWithoutRef<'section'>, 'children' | 'className'>;

/** What a writing route does with this file, from the API's own lists. Never a claim the API did not make. */
function routeLine(file: MemoryFile, group: DraftGroup | null, egress: MemoryEgress | undefined) {
  if (group === null) return 'Which files writing routes receive is unavailable right now.';
  if (group === 'reference') return 'For you to read. Writing routes don’t receive this file.';
  const parts = [
    egress?.cloud
      ? 'Routes on your own machine receive this file when they draft, and so does the cloud model, because an owner allowed it.'
      : 'Routes on your own machine receive this file when they draft. The cloud model doesn’t until an owner allows it.'
  ];
  if (file.name === 'VOICE.md') parts.push('When a draft names its channels, its copy lists only the learned preferences that apply to them.');
  const withheld = egress?.withheldBoundaries ?? 0;
  if (file.name === 'BOUNDARIES.md' && egress?.cloud && withheld > 0) {
    parts.push(`The cloud model’s copy leaves out ${withheld} private or local-only boundar${withheld === 1 ? 'y' : 'ies'}.`);
  }
  return parts.join(' ');
}

function FileAction({ file, noVoice }: { file: MemoryFile; noVoice: boolean }) {
  if (file.name === 'VOICE.md' && noVoice) {
    return (
      <Link href={file.editHref ?? BRAND_HREF} className={buttonVariants({ variant: 'action', size: 'default' })}>
        Set up your voice
      </Link>
    );
  }
  if (!file.editHref) return null;
  return (
    <Link href={file.editHref} className={buttonVariants({ variant: 'glass', size: 'default' })}>
      Edit in Brand
    </Link>
  );
}

function FileMeta({ file, group, noVoice, nameId, showName }: { file: MemoryFile; group: DraftGroup | null; noVoice: boolean; nameId?: string; showName: boolean }) {
  return (
    <div className='flex flex-wrap items-start justify-between gap-2'>
      <div className='flex min-w-0 flex-col gap-1.5'>
        <div className='flex flex-wrap items-center gap-2'>
          {showName && (
            <span id={nameId} className='text-foreground font-mono text-sm font-semibold'>
              {file.name}
            </span>
          )}
          {group && <StatusChip icon={group === 'given' ? 'send' : 'eye'}>{DRAFT_GROUP_LABEL[group]}</StatusChip>}
          <StatusChip icon={null}>{file.source}</StatusChip>
        </div>
        {file.purpose && <p className='text-muted-foreground text-xs'>{file.purpose}</p>}
      </div>
      <FileAction file={file} noVoice={noVoice} />
    </div>
  );
}

function BodySkeleton() {
  return (
    <div className='flex flex-col gap-2 p-5' role='status' aria-label='Loading the file'>
      <Skeleton className='h-4 w-2/3' />
      <Skeleton className='h-4 w-1/2' />
      <Skeleton className='h-4 w-3/4' />
    </div>
  );
}

/**
 * The memory files exactly as the API renders them, with what a writing route does with each one: the files
 * in `egress.sharedFiles` are given to routes, the rest are for people to read. One component for every page
 * that shows "what drafts read" (Memory owns it; Brand embeds it without `selected`).
 */
export function WhatDraftsRead({ selected, showMemoryLink = false, className, ...rest }: WhatDraftsReadProps) {
  const memory = useMemory();
  const snapshot = useSnapshot();
  const reduce = useReducedMotion();
  const nameId = useId();
  const panelBase = useId();
  const [tab, setTab] = useState('VOICE.md');
  const tabbed = selected === undefined;
  const files = memory.data?.files ?? [];
  const egress = memory.data?.egress;
  const grouped = groupMemoryFiles(files, egress);
  // Only a loaded snapshot can say there is no active voice; until then no call to action is shown.
  const noVoice = snapshot.data ? (snapshot.data.state.speaker?.activeRevision ?? null) === null : false;

  const memoryLink = showMemoryLink ? (
    <Link href={MEMORY_HREF} className='rafii-focus text-muted-foreground hover:text-foreground rounded-md text-xs underline-offset-4 hover:underline'>
      Change who reads these on Memory
    </Link>
  ) : null;

  let content;
  if (!memory.data) {
    content = memory.isLoading ? (
      <>
        <div className='flex flex-col gap-2 px-5 pt-5'>
          <Skeleton className='h-5 w-40' />
          <Skeleton className='h-3 w-56' />
        </div>
        <BodySkeleton />
      </>
    ) : (
      <Unavailable className='p-5' message='Memory files are unavailable right now.' query={memory} />
    );
  } else if (tabbed) {
    const given = grouped.given;
    const current = given.some((f) => f.name === tab) ? tab : (given[0]?.name ?? '');
    const panelIds = given.map((file) => `${panelBase}-${file.name.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
    const currentFile = given.find((file) => file.name === current);
    const currentIndex = given.findIndex((file) => file.name === current);
    content = (
      <>
        <div className='flex flex-col gap-1 px-5 pt-5'>
          <h2 id={nameId} className='text-foreground text-base font-medium tracking-tight'>
            What drafts read
          </h2>
          <p className='text-muted-foreground text-sm leading-relaxed'>The files a writing route receives before it drafts, as your workspace renders them right now.</p>
        </div>
        {!grouped.known ? (
          <StateMessage kind='partial' layout='inline' className='px-5 pb-5' title='Which files writing routes receive is unavailable right now.' />
        ) : given.length === 0 ? (
          <StateMessage kind='empty' layout='inline' className='px-5 pb-5' title='No memory files are given to writing routes.' />
        ) : (
          <div className='flex flex-col'>
            <div className='relative scrollbar-hide overflow-x-auto px-5 pt-4 pb-2'>
              <SegmentedControl
                options={given.map((file) => ({ value: file.name, label: <span className='font-mono text-xs'>{file.name}</span> }))}
                value={current}
                onChange={setTab}
                pattern='tabs'
                label='Memory files given to writing routes'
                size='sm'
                widths='content'
                panelIds={panelIds}
                className='min-w-max'
              />
            </div>
            {currentFile && (
              <div role='tabpanel' id={panelIds[currentIndex]} tabIndex={0} className='rafii-focus flex flex-col rounded-b-[var(--rafii-radius-card)]'>
                <div className='px-5 py-3'>
                  <FileMeta file={currentFile} group='given' noVoice={noVoice} showName={false} />
                </div>
                <div className='max-h-[40vh] overflow-y-auto'>
                  <pre className={BODY_CLASS}>{currentFile.body}</pre>
                </div>
                <p className='text-muted-foreground px-5 py-3 text-xs leading-relaxed'>{routeLine(currentFile, 'given', egress)}</p>
              </div>
            )}
          </div>
        )}
      </>
    );
  } else {
    const file = files.find((f) => f.name === selected) ?? grouped.given[0] ?? files[0];
    const group = file ? draftGroupOf(grouped, file.name) : null;
    content = !file ? (
      <StateMessage kind='empty' layout='inline' className='p-5' title='The workspace returned no memory files.' />
    ) : (
      <>
        <div className='px-5 pt-5 pb-3'>
          <FileMeta file={file} group={group} noVoice={noVoice} nameId={nameId} showName />
        </div>
        <AnimatePresence mode='wait' initial={false}>
          <motion.pre
            key={file.name}
            initial={{ opacity: 0, y: reduce ? 0 : 4 }}
            animate={{ opacity: 1, y: 0, transition: reduce ? { duration: 0 } : { duration: 0.18, ease: EASE_OUT } }}
            exit={{ opacity: 0, y: reduce ? 0 : -4, transition: reduce ? { duration: 0 } : { duration: 0.12, ease: EASE_OUT } }}
            className={BODY_CLASS}
          >
            {file.body}
          </motion.pre>
        </AnimatePresence>
        <p className='text-muted-foreground mt-auto px-5 py-3 text-xs leading-relaxed'>{routeLine(file, group, egress)}</p>
      </>
    );
  }

  return (
    <Surface
      as='section'
      material='quiet'
      padding='none'
      {...rest}
      aria-labelledby={memory.data && (tabbed || files.length > 0) ? nameId : undefined}
      aria-label={memory.data ? undefined : 'Memory file'}
      className={cn('flex min-w-0 flex-col overflow-hidden', className)}
    >
      {content}
      {memory.data && memory.isRefetchError && <StaleNotice className='px-5 py-2' query={memory} />}
      {memoryLink && <div className='px-5 pt-1 pb-4'>{memoryLink}</div>}
    </Surface>
  );
}
