'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ActionSwapIcon } from '@/components/motion/action-swap';
import { FileTree, FileTreeFile, FileTreeFolder } from '@/components/motion/file-tree';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useFlash } from '@/hooks/use-flash';
import { ApiError } from '@/lib/api/client';
import { useMemory } from '@/lib/api/hooks';
import type { MemoryFile } from '@/lib/api/types';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { AccessCard } from './access-card';
import { LearningPanel } from './learning-panel';
import { DRAFT_GROUP_LABEL, groupMemoryFiles } from './memory-files';
import { Unavailable } from './memory-states';
import { WhatDraftsRead } from './what-drafts-read';

const infoContent = {
  title: 'Memory files',
  sections: [
    {
      title: 'Plain Markdown, yours',
      description:
        'The files marked “Given to writing routes” are what a writing route receives before it drafts. Routes on your own machine always receive them; the cloud model reads them only if an owner allows it, and never a boundary marked private or local-only. The other files are here for you to read. Everything is rendered from your voice profile, brand context and the preferences an owner accepted; the agent cannot change the files itself.'
    },
    {
      title: 'Proposals, never silent changes',
      description:
        'When you tell the agent how to write, or your edits show a pattern, it proposes a preference that an owner remembers, rewords or dismisses. A suggestion nobody decides expires. Accepted preferences appear in VOICE.md under “Learned from how you edit” and shape future drafts only.'
    },
    {
      title: 'Readable, not hidden',
      description: 'One topic per file, in plain text, rendered again from your workspace each time this page loads. What you read here is what the files say now.'
    }
  ]
};

function fileNode(file: MemoryFile) {
  return <FileTreeFile key={file.name} value={file.name} name={file.name} className='font-mono text-[13px]' />;
}

/** The file list, grouped by what a writing route receives. The groups come from the API, never from a fixed list. */
function MemoryFileList({ selected, onSelect }: { selected: string; onSelect: (name: string) => void }) {
  const memory = useMemory();
  const files = memory.data?.files ?? [];
  const grouped = groupMemoryFiles(files, memory.data?.egress);
  const current = files.some((f) => f.name === selected) ? selected : (grouped.given[0]?.name ?? files[0]?.name ?? null);

  return (
    <div className='bg-card ring-foreground/10 flex min-w-0 flex-col gap-0.5 rounded-xl p-2 ring-1' data-tour='memory-files'>
      <span className='text-muted-foreground px-2 py-1.5 text-xs'>Memory files</span>
      {memory.data ? (
        files.length > 0 ? (
          <FileTree
            ariaLabel='Memory files'
            value={current}
            // Group rows only expand and collapse; the viewer follows files.
            onValueChange={(value) => {
              if (files.some((f) => f.name === value)) onSelect(value);
            }}
            defaultExpandedIds={['group:given', 'group:reference', 'group:all']}
          >
            {grouped.known ? (
              <>
                {grouped.given.length > 0 && (
                  <FileTreeFolder value='group:given' name={DRAFT_GROUP_LABEL.given}>
                    {grouped.given.map(fileNode)}
                  </FileTreeFolder>
                )}
                {grouped.reference.length > 0 && (
                  <FileTreeFolder value='group:reference' name={DRAFT_GROUP_LABEL.reference}>
                    {grouped.reference.map(fileNode)}
                  </FileTreeFolder>
                )}
              </>
            ) : (
              <FileTreeFolder value='group:all' name='memory/'>
                {files.map(fileNode)}
              </FileTreeFolder>
            )}
          </FileTree>
        ) : (
          <p className='text-muted-foreground px-2 py-1.5 text-sm'>The workspace returned no memory files.</p>
        )
      ) : memory.isLoading ? (
        <div className='flex flex-col gap-2 p-2'>
          <Skeleton className='h-9 w-full' />
          <Skeleton className='h-9 w-full' />
          <Skeleton className='h-9 w-full' />
        </div>
      ) : (
        <Unavailable className='px-2 py-1.5' message='Memory files are unavailable right now.' query={memory} />
      )}
      {memory.data && !grouped.known && <p className='text-muted-foreground px-2 py-1.5 text-xs'>Which files writing routes receive is unavailable right now.</p>}
      <p className='text-muted-foreground mt-2 border-t px-2 pt-2 text-xs leading-relaxed'>Preferences an owner accepts appear in VOICE.md under “Learned from how you edit”. Each file names its source beside it.</p>
    </div>
  );
}

export function MemoryView() {
  const { api, workspaceId } = useWorkspaceApi();
  const [selected, setSelected] = useState('VOICE.md');
  const [exporting, setExporting] = useState(false);
  const [exported, flashExported] = useFlash<'done'>(1800);

  async function exportPackage() {
    setExporting(true);
    try {
      downloadBlob(await api.exportProfile(workspaceId), 'postriff-personal-voice.zip');
      flashExported('done');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The voice package could not be exported.');
    } finally {
      setExporting(false);
    }
  }

  return (
    <PageContainer
      pageTitle='Memory'
      pageDescription='Plain Markdown files behind every draft. You own them; the agent can only propose changes.'
      infoContent={infoContent}
      pageHeaderAction={
        <Button variant='outline' data-tour='memory-export' disabled={exporting} onClick={() => void exportPackage()}>
          <ActionSwapIcon value={exporting ? 'busy' : exported ?? 'idle'} className='size-4'>
            {exporting ? <Icons.spinner className='size-4 motion-safe:animate-spin' /> : exported ? <Icons.check className='size-4' /> : <Icons.download className='size-4' />}
          </ActionSwapIcon>
          Export voice package
        </Button>
      }
    >
      <div className='flex min-w-0 flex-col gap-4'>
        <AccessCard />
        <div className='grid min-w-0 gap-4 md:grid-cols-[18rem_minmax(0,1fr)]'>
          <MemoryFileList selected={selected} onSelect={setSelected} />
          <WhatDraftsRead selected={selected} data-tour='memory-viewer' />
        </div>
        <div className='flex min-w-0 flex-col gap-3' data-tour='memory-learning'>
          <LearningPanel />
        </div>
      </div>
    </PageContainer>
  );
}
