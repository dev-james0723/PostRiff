'use client';

import { useId, useState, type ComponentPropsWithoutRef } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
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
      <Link href={file.editHref ?? BRAND_HREF} className={buttonVariants({ size: 'sm' })}>
        Set up your voice
      </Link>
    );
  }
  if (!file.editHref) return null;
  return (
    <Link href={file.editHref} className={buttonVariants({ size: 'sm', variant: 'outline' })}>
      Edit in Brand
    </Link>
  );
}

function FileMeta({ file, group, noVoice, nameId, showName }: { file: MemoryFile; group: DraftGroup | null; noVoice: boolean; nameId?: string; showName: boolean }) {
  return (
    <div className='flex flex-wrap items-start justify-between gap-2'>
      <div className='flex min-w-0 flex-col gap-1'>
        <div className='flex flex-wrap items-center gap-2'>
          {showName && (
            <span id={nameId} className='font-mono text-sm font-semibold'>
              {file.name}
            </span>
          )}
          {group && (
            <AnimatedBadge size='sm' status={group === 'given' ? 'info' : 'neutral'} contentKey={group}>
              {DRAFT_GROUP_LABEL[group]}
            </AnimatedBadge>
          )}
          <Badge variant='secondary'>{file.source}</Badge>
        </div>
        {file.purpose && <p className='text-muted-foreground text-xs'>{file.purpose}</p>}
      </div>
      <FileAction file={file} noVoice={noVoice} />
    </div>
  );
}

function BodySkeleton() {
  return (
    <div className='flex flex-col gap-2 p-4'>
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
  const [tab, setTab] = useState('VOICE.md');
  const tabbed = selected === undefined;
  const files = memory.data?.files ?? [];
  const egress = memory.data?.egress;
  const grouped = groupMemoryFiles(files, egress);
  // Only a loaded snapshot can say there is no active voice; until then no call to action is shown.
  const noVoice = snapshot.data ? (snapshot.data.state.speaker?.activeRevision ?? null) === null : false;

  const shell = cn('bg-card ring-foreground/10 flex min-w-0 flex-col overflow-hidden rounded-xl ring-1', className);
  const memoryLink = showMemoryLink ? (
    <Link href={MEMORY_HREF} className='text-muted-foreground hover:text-foreground text-xs underline-offset-4 hover:underline'>
      Change who reads these on Memory
    </Link>
  ) : null;

  let content;
  if (!memory.data) {
    content = memory.isLoading ? (
      <>
        <div className='flex flex-col gap-2 border-b px-4 py-3'>
          <Skeleton className='h-5 w-40' />
          <Skeleton className='h-3 w-56' />
        </div>
        <BodySkeleton />
      </>
    ) : (
      <Unavailable className='p-4' message='Memory files are unavailable right now.' query={memory} />
    );
  } else if (tabbed) {
    const given = grouped.given;
    const current = given.some((f) => f.name === tab) ? tab : (given[0]?.name ?? '');
    content = (
      <>
        <div className='flex flex-col gap-2 border-b px-4 py-3'>
          <h2 id={nameId} className='text-sm font-semibold'>
            What drafts read
          </h2>
          <p className='text-muted-foreground text-xs leading-relaxed'>The files a writing route receives before it drafts, as your workspace renders them right now.</p>
        </div>
        {!grouped.known ? (
          <p className='text-muted-foreground p-4 text-sm'>Which files writing routes receive is unavailable right now.</p>
        ) : given.length === 0 ? (
          <p className='text-muted-foreground p-4 text-sm'>No memory files are given to writing routes.</p>
        ) : (
          <Tabs value={current} onValueChange={setTab} variant='segment' className='flex flex-col'>
            <div className='border-b px-4 py-2'>
              <TabsList className='bg-muted max-w-full flex-wrap'>
                {given.map((file) => (
                  <TabsTrigger key={file.name} value={file.name} className='px-2.5 py-1 font-mono text-xs'>
                    {file.name}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
            {given.map((file) => (
              <TabsContent key={file.name} value={file.name} className='mt-0'>
                <div className='border-b px-4 py-3'>
                  <FileMeta file={file} group='given' noVoice={noVoice} showName={false} />
                </div>
                <div className='max-h-[40vh] overflow-y-auto'>
                  <pre className={BODY_CLASS}>{file.body}</pre>
                </div>
                <p className='text-muted-foreground border-t px-4 py-2.5 text-xs'>{routeLine(file, 'given', egress)}</p>
              </TabsContent>
            ))}
          </Tabs>
        )}
      </>
    );
  } else {
    const file = files.find((f) => f.name === selected) ?? grouped.given[0] ?? files[0];
    const group = file ? draftGroupOf(grouped, file.name) : null;
    content = !file ? (
      <p className='text-muted-foreground p-4 text-sm'>The workspace returned no memory files.</p>
    ) : (
      <>
        <div className='border-b px-4 py-3'>
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
        <p className='text-muted-foreground mt-auto border-t px-4 py-2.5 text-xs'>{routeLine(file, group, egress)}</p>
      </>
    );
  }

  return (
    <section {...rest} aria-labelledby={memory.data && (tabbed || files.length > 0) ? nameId : undefined} aria-label={memory.data ? undefined : 'Memory file'} className={shell}>
      {content}
      {memory.data && memory.isRefetchError && <StaleNotice className='border-t px-4 py-2' query={memory} />}
      {memoryLink && <div className='border-t px-4 py-2.5'>{memoryLink}</div>}
    </section>
  );
}
