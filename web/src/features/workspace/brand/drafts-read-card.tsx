'use client';

import Link from 'next/link';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import type { MemoryEgress, MemoryFile } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { SectionUnavailable, type Refetchable } from './brand-parts';

export const MEMORY_HREF = '/app/workspace/memory';

interface MemoryRead extends Refetchable {
  isLoading: boolean;
  isError: boolean;
  data?: { files: MemoryFile[]; egress?: MemoryEgress };
}

/**
 * A pointer to the Memory page, where the exact Markdown drafts receive is shown. This card names the
 * files and who reads them; it deliberately does not repeat their text.
 */
export function DraftsReadCard({ memory }: { memory: MemoryRead }) {
  const files = Array.isArray(memory.data?.files) ? memory.data.files : [];
  const egress = memory.data?.egress;
  const shared = Array.isArray(egress?.sharedFiles) ? egress.sharedFiles : null;
  // Files given to writing routes, in the server's order; purposes come from the same response.
  const given = shared ? shared.map((name) => ({ name, purpose: files.find((file) => file.name === name)?.purpose ?? null })) : null;

  return (
    <Card data-tour='brand-preview' className='min-w-0'>
      <CardHeader>
        <CardTitle>What drafts read</CardTitle>
        <CardDescription>This page becomes plain Markdown files. The Memory page shows their exact text, as a writing route receives it.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3 text-sm'>
        {memory.isLoading ? (
          <div className='flex flex-col gap-2' aria-busy='true'>
            <Skeleton className='h-4 w-2/3' />
            <Skeleton className='h-4 w-1/2' />
            <Skeleton className='h-4 w-3/5' />
          </div>
        ) : memory.isError || !memory.data ? (
          <SectionUnavailable message='The memory files are unavailable right now.' query={memory} />
        ) : (
          <>
            <div className='flex flex-col gap-1.5'>
              <span className='text-muted-foreground text-xs'>Given to writing routes before every draft</span>
              {given === null ? (
                <p className='text-muted-foreground'>Unavailable</p>
              ) : given.length === 0 ? (
                <p className='text-muted-foreground'>None listed.</p>
              ) : (
                <ul className='flex flex-col gap-1'>
                  {given.map((file) => (
                    <li key={file.name} className='flex min-w-0 flex-wrap items-baseline gap-x-2'>
                      <span className='font-mono text-[13px]'>{file.name}</span>
                      {file.purpose && <span className='text-muted-foreground truncate text-xs'>{file.purpose}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className='flex flex-wrap items-center gap-2 border-t pt-3'>
              <span className='text-muted-foreground text-xs'>Cloud model access</span>
              {egress ? (
                <Badge variant={egress.cloud ? 'secondary' : 'outline'}>{egress.cloud ? 'Shared' : 'Not shared'}</Badge>
              ) : (
                <Badge variant='outline'>Unavailable</Badge>
              )}
              <span className='text-muted-foreground w-full text-xs'>Writing routes on your own machine always read these files. An owner decides on the Memory page whether the cloud model does.</span>
            </div>
          </>
        )}
      </CardContent>
      <CardFooter>
        <Link href={MEMORY_HREF} className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 't-learn')}>
          Open Memory <LearnMoreChevron />
        </Link>
      </CardFooter>
    </Card>
  );
}
