'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ActionSwapIcon } from '@/components/motion/action-swap';
import { FileTree, FileTreeFile, FileTreeFolder } from '@/components/motion/file-tree';
import { StateMessage, Surface } from '@/components/rafii';
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
import { DRAFT_GROUP_LABEL, groupMemoryFiles, memoryFileLabel } from './memory-files';
import { Unavailable } from './memory-states';
import { WhatDraftsRead } from './what-drafts-read';
import { useSiteAgentPageContext } from '@/features/site-agent/use-page-context';

const infoContent = {
  title: 'Memory files',
  sections: [
    {
      title: 'Plain Markdown, yours',
      description:
        'Files marked “Sent to writers” are what a draft is written from. Local writers always get them; the cloud model only if an owner allows it, and never private boundaries. The agent can’t edit these files.'
    },
    {
      title: 'Proposals, never silent changes',
      description: 'The agent proposes preferences from what you say and how you edit. An owner accepts, rewords or dismisses each one; unanswered ones expire.'
    }
  ]
};

function fileNode(file: MemoryFile) {
  return <FileTreeFile key={file.name} value={file.name} name={memoryFileLabel(file.name)} className='text-[13px]' />;
}

/** The file list, grouped by what a writing route receives. The groups come from the API, never from a fixed list. */
function MemoryFileList({ selected, onSelect }: { selected: string; onSelect: (name: string) => void }) {
  const memory = useMemory();
  const files = memory.data?.files ?? [];
  const grouped = groupMemoryFiles(files, memory.data?.egress);
  const current = files.some((f) => f.name === selected) ? selected : (grouped.given[0]?.name ?? files[0]?.name ?? null);

  return (
    <Surface material='quiet' padding='none' className='flex flex-col gap-0.5 p-2' data-tour='memory-files'>
      <span className='rafii-eyebrow px-2 py-2'>Memory files</span>
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
          <StateMessage kind='empty' layout='inline' className='px-2' title='No memory files yet' />
        )
      ) : memory.isLoading ? (
        <div className='flex flex-col gap-2 p-2' role='status' aria-label='Loading memory files'>
          <Skeleton className='h-9 w-full rounded-[var(--rafii-radius-control)]' />
          <Skeleton className='h-9 w-full rounded-[var(--rafii-radius-control)]' />
          <Skeleton className='h-9 w-full rounded-[var(--rafii-radius-control)]' />
        </div>
      ) : (
        <Unavailable className='px-2 py-1.5' message='Couldn’t load memory files.' query={memory} />
      )}
      {memory.data && !grouped.known && <p className='text-muted-foreground px-2 py-1.5 text-xs'>Couldn’t check which files writers receive.</p>}
    </Surface>
  );
}

export function MemoryView() {
  const { api, workspaceId } = useWorkspaceApi();
  const [selected, setSelected] = useState('VOICE.md');
  useSiteAgentPageContext({ visibleState: { file: selected } });
  const [exporting, setExporting] = useState(false);
  const [exported, flashExported] = useFlash<'done'>(1800);

  async function exportPackage() {
    setExporting(true);
    try {
      downloadBlob(await api.exportProfile(workspaceId), 'postriff-personal-voice.zip');
      flashExported('done');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t export the voice package.');
    } finally {
      setExporting(false);
    }
  }

  return (
    <PageContainer
      pageTitle='Memory'
      infoContent={infoContent}
      pageHeaderAction={
        <Button variant='glass' size='control' data-tour='memory-export' disabled={exporting} onClick={() => void exportPackage()}>
          <ActionSwapIcon value={exporting ? 'busy' : (exported ?? 'idle')} className='size-4'>
            {exporting ? <Icons.spinner className='size-4 motion-safe:animate-spin' /> : exported ? <Icons.check className='size-4' /> : <Icons.download className='size-4' />}
          </ActionSwapIcon>
          Export voice package
        </Button>
      }
    >
      <div className='flex min-w-0 flex-col gap-4 md:gap-5'>
        <AccessCard />
        <div className='grid min-w-0 gap-4 md:grid-cols-[18rem_minmax(0,1fr)] md:gap-5'>
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
