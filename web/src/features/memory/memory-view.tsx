'use client';

import { useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useMemory } from '@/lib/api/hooks';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';

const infoContent = {
  title: 'Memory files',
  sections: [
    { title: 'Plain Markdown, yours', description: 'The agent reads these before every draft, and any writing route receives exactly this text. Today they are generated from your voice profile and brand context; the agent cannot change them.' },
    { title: 'Proposals come later', description: 'A later phase lets the agent propose edits as diffs you accept or dismiss. Nothing is learned silently.' },
    { title: 'Same shape as a coding-agent memory folder', description: 'The layout matches Claude Code memory, so exporting and syncing to your own machine is a plain file copy.' }
  ]
};

export function MemoryView() {
  const memory = useMemory();
  const { api, workspaceId } = useWorkspaceApi();
  const files = memory.data?.files ?? [];
  const [selected, setSelected] = useState('VOICE.md');
  const file = files.find((f) => f.name === selected) ?? files[0];

  async function exportPackage() {
    try {
      downloadBlob(await api.exportProfile(workspaceId), 'postriff-personal-voice.zip');
    } catch {
      toast.error('The memory package could not be exported.');
    }
  }

  return (
    <PageContainer
      pageTitle='Memory'
      pageDescription='Plain Markdown files the agent reads before every draft. You own them; the agent can only propose changes.'
      infoContent={infoContent}
      pageHeaderAction={
        <Button variant='outline' onClick={() => void exportPackage()}>
          <Icons.upload className='size-4 rotate-180' /> Export package
        </Button>
      }
    >
      <div className='grid gap-4 md:grid-cols-[18rem_1fr]'>
        <div className='bg-card ring-foreground/10 flex flex-col gap-0.5 rounded-xl p-2 ring-1'>
          <span className='text-muted-foreground px-2 py-1.5 text-xs'>Core files · read every turn</span>
          {memory.isLoading && (
            <div className='flex flex-col gap-2 p-2'>
              <Skeleton className='h-9 w-full' />
              <Skeleton className='h-9 w-full' />
              <Skeleton className='h-9 w-full' />
            </div>
          )}
          {files.map((item) => (
            <button
              key={item.name}
              type='button'
              onClick={() => setSelected(item.name)}
              className={cn('hover:bg-muted flex items-start gap-2.5 rounded-lg px-2.5 py-2 text-left', item.name === file?.name && 'bg-muted')}
            >
              <Icons.page className='mt-0.5 size-4 shrink-0' />
              <span className='flex min-w-0 flex-col'>
                <span className='font-mono text-[13px] font-medium'>{item.name}</span>
                <span className='text-muted-foreground text-xs'>{item.purpose}</span>
              </span>
            </button>
          ))}
          <p className='text-muted-foreground mt-2 border-t px-2 pt-2 text-xs leading-relaxed'>Learned notes and agent proposals arrive in a later phase; until then these files are generated from your profile.</p>
        </div>

        <div className='bg-card ring-foreground/10 flex flex-col overflow-hidden rounded-xl ring-1'>
          <div className='flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='font-mono text-sm font-semibold'>{file?.name ?? '…'}</span>
              {file && <Badge variant='secondary'>{file.source}</Badge>}
              <Badge variant='outline'>Read every draft</Badge>
            </div>
            {file?.editHref && (
              <Link href={file.editHref} className={buttonVariants({ size: 'sm', variant: 'outline' })}>
                Edit in Brand
              </Link>
            )}
          </div>
          {memory.isLoading || !file ? (
            <div className='flex flex-col gap-2 p-4'>
              <Skeleton className='h-4 w-2/3' />
              <Skeleton className='h-4 w-1/2' />
              <Skeleton className='h-4 w-3/4' />
            </div>
          ) : (
            <pre className='overflow-x-auto px-5 py-4 font-sans text-sm leading-relaxed whitespace-pre-wrap'>{file.body}</pre>
          )}
          <div className='text-muted-foreground border-t px-4 py-2.5 text-xs'>Workspace only. Never quoted verbatim in a public post. Included in the export package and given to whichever route writes your drafts.</div>
        </div>
      </div>
    </PageContainer>
  );
}
