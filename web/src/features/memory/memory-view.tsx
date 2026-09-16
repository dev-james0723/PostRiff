'use client';

import { useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { FileTree, FileTreeFile, FileTreeFolder } from '@/components/motion/file-tree';
import { Switch } from '@/components/motion/switch';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { useAct, useInvalidate, useMembers, useMemory, useSnapshot } from '@/lib/api/hooks';
import { downloadBlob } from '@/lib/download';
import { EASE_OUT } from '@/lib/ease';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { LearningPanel } from './learning-panel';

const infoContent = {
  title: 'Memory files',
  sections: [
    { title: 'Plain Markdown, yours', description: 'The agent reads these before every draft. Writing routes on your own machine receive exactly this text; the cloud model reads it only if you allow it, and never a boundary marked private or local-only. The files are generated from your voice profile, brand context and the preferences you accepted; the agent cannot change them itself.' },
    { title: 'Proposals, never silent changes', description: 'When you tell the agent how to write, or your edits show a pattern, it proposes a preference you remember, reword or dismiss. Accepted preferences appear in VOICE.md under “Learned from how you edit” and shape future drafts only.' },
    { title: 'Same shape as a coding-agent memory folder', description: 'The layout matches Claude Code memory, so exporting and syncing to your own machine is a plain file copy.' }
  ]
};

/** When an owner decision last changed and, for owners, whether they made it (a workspace can have several owners). */
function useDecidedLine(decidedAt: number | null, decidedBy: string | null, isOwner: boolean) {
  const members = useMembers();
  if (!decidedAt) return null;
  const when = new Date(decidedAt * 1000).toLocaleDateString();
  if (!isOwner || !members.data) return `Last changed ${when}.`;
  const byYou = members.data.members.some((m) => m.you && m.userId === decidedBy);
  return byYou ? `Changed by you on ${when}.` : `Changed by another owner on ${when}.`;
}

function AccessStrip({ title, on, badge, description, note, switchLabel, ariaLabel, disabled, onChange }: {
  title: string;
  on: boolean;
  badge: string;
  description: string;
  note: string;
  switchLabel?: string;
  ariaLabel: string;
  disabled: boolean;
  onChange?: (value: boolean) => void;
}) {
  return (
    <div className='bg-card ring-foreground/10 flex flex-col gap-3 rounded-xl p-4 ring-1 sm:flex-row sm:items-start sm:justify-between'>
      <div className='flex min-w-0 flex-col gap-1'>
        <div className='flex flex-wrap items-center gap-2'>
          <span className='text-sm font-semibold'>{title}</span>
          <Badge variant={on ? 'secondary' : 'outline'}>{badge}</Badge>
        </div>
        <p className='text-muted-foreground max-w-prose text-xs leading-relaxed'>{description}</p>
        <p className='text-muted-foreground text-xs'>{note}</p>
      </div>
      {onChange && <Switch checked={on} disabled={disabled} onCheckedChange={onChange} ariaLabel={ariaLabel} label={switchLabel} />}
    </div>
  );
}

function CloudSharing() {
  const memory = useMemory();
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const egress = memory.data?.egress;
  const isOwner = snapshot.data?.membership?.role === 'owner';
  const decidedLine = useDecidedLine(egress?.decidedAt ?? null, egress?.decidedBy ?? null, isOwner);
  if (!egress) return null;
  const withheld = egress.withheldBoundaries;

  function decide(cloud: boolean) {
    act.mutate(
      { revision: snapshot.data?.revision ?? 0, action: 'memory_egress', payload: { cloud, confirmed: true } },
      {
        onSuccess: () => {
          invalidate('memory');
          toast.success(cloud ? 'The cloud model can now read your voice, identity and shareable boundaries.' : 'The cloud model no longer reads your memory files.');
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The sharing choice could not be saved.')
      }
    );
  }

  return (
    <AccessStrip
      title='Cloud model access'
      on={egress.cloud}
      badge={egress.cloud ? 'Shared' : 'Not shared'}
      description={
        (egress.cloud
          ? 'PostRiff’s cloud model reads VOICE.md, IDENTITY.md and the boundaries marked public or workspace, so its drafts follow your voice and rules.'
          : 'Drafts written by PostRiff’s cloud model don’t see your voice, identity or boundaries until you allow it. Writing routes on your own machine always read them.') +
        (withheld > 0 ? ` ${withheld} boundar${withheld === 1 ? 'y is' : 'ies are'} private or local-only and never leave, either way.` : '')
      }
      note={isOwner ? decidedLine ?? 'Nothing is shared until you turn this on.' : ['Only an owner can change this.', decidedLine].filter(Boolean).join(' ')}
      switchLabel='Allow'
      ariaLabel='Let the cloud model read your memory files'
      disabled={!isOwner || act.isPending || snapshot.isLoading}
      onChange={decide}
    />
  );
}

function WebResearch() {
  const memory = useMemory();
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const research = memory.data?.research;
  const isOwner = snapshot.data?.membership?.role === 'owner';
  const decidedLine = useDecidedLine(research?.decidedAt ?? null, research?.decidedBy ?? null, isOwner);
  if (!research) return null;
  const onText = 'When a draft needs facts you haven’t supplied, PostRiff looks them up.';
  const offText = 'Drafts use only what you supply.';
  const disclosure = 'A search query drawn from your message goes to Exa, and the pages it finds, or a link you paste, are read through Jina Reader. Neither receives your sources, memory files or drafts.';

  // No switch applies on the person's own machine (always on) or when research is off for everyone here.
  if (!research.hosted || research.enabled === false) {
    const on = research.enabled !== false;
    return (
      <AccessStrip
        title='Web research'
        on={on}
        badge={on ? 'On' : 'Off'}
        description={on ? `${onText} ${disclosure}` : offText}
        note={on ? 'Always on when drafting on your own machine.' : research.hosted ? 'Web research is unavailable right now.' : 'Turned off on this machine (POSTRIFF_RESEARCH=0).'}
        ariaLabel='Web research'
        disabled
      />
    );
  }

  function decide(web: boolean) {
    act.mutate(
      { revision: snapshot.data?.revision ?? 0, action: 'research_egress', payload: { web, confirmed: true } },
      {
        onSuccess: () => {
          invalidate('memory');
          toast.success(web ? 'Web research is on. PostRiff looks facts up when a draft needs them.' : 'Web research is off. Drafts use only what you supply.');
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The research choice could not be saved.')
      }
    );
  }

  return (
    <AccessStrip
      title='Web research'
      on={research.web}
      badge={research.web ? 'On' : 'Off'}
      description={`${research.web ? onText : `${offText} Turn this on and PostRiff looks up the facts a draft needs.`} ${disclosure}`}
      note={isOwner ? decidedLine ?? 'Nothing is sent until you turn this on.' : ['Only an owner can change this.', decidedLine].filter(Boolean).join(' ')}
      switchLabel='Allow'
      ariaLabel='Let PostRiff look facts up on the web'
      disabled={!isOwner || act.isPending || snapshot.isLoading}
      onChange={decide}
    />
  );
}

export function MemoryView() {
  const memory = useMemory();
  const { api, workspaceId } = useWorkspaceApi();
  const files = memory.data?.files ?? [];
  const [selected, setSelected] = useState('VOICE.md');
  const file = files.find((f) => f.name === selected) ?? files[0];
  const reduce = useReducedMotion();

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
      <div className='mb-4 flex flex-col gap-3 empty:hidden'>
        <CloudSharing />
        <WebResearch />
        <LearningPanel />
      </div>
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
          {files.length > 0 && (
            <FileTree
              ariaLabel='Memory files'
              value={file?.name ?? null}
              // The folder row only expands and collapses; the panel follows files.
              onValueChange={(value) => {
                if (files.some((f) => f.name === value)) setSelected(value);
              }}
              defaultExpandedIds={['memory']}
              classNames={{ label: 'font-mono text-[13px]' }}
            >
              <FileTreeFolder value='memory' name='memory/'>
                {files.map((item) => (
                  <FileTreeFile key={item.name} value={item.name} name={item.name} />
                ))}
              </FileTreeFolder>
            </FileTree>
          )}
          <p className='text-muted-foreground mt-2 border-t px-2 pt-2 text-xs leading-relaxed'>Preferences you accept appear in VOICE.md under “Learned from how you edit”; the rest is generated from your profile and brand context.</p>
        </div>

        <div className='bg-card ring-foreground/10 flex flex-col overflow-hidden rounded-xl ring-1'>
          <div className='flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3'>
            <div className='flex min-w-0 flex-col gap-1'>
              <div className='flex flex-wrap items-center gap-2'>
                <span className='font-mono text-sm font-semibold'>{file?.name ?? '…'}</span>
                {file && <Badge variant='secondary'>{file.source}</Badge>}
                <Badge variant='outline'>Read every draft</Badge>
              </div>
              {file?.purpose && <p className='text-muted-foreground text-xs'>{file.purpose}</p>}
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
            <AnimatePresence mode='wait'>
              <motion.pre
                key={file.name}
                initial={{ opacity: 0, y: 4, filter: 'blur(4px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                exit={{ opacity: 0, y: -4, filter: 'blur(4px)' }}
                transition={reduce ? { duration: 0 } : { duration: 0.18, ease: EASE_OUT }}
                className='overflow-x-auto px-5 py-4 font-sans text-sm leading-relaxed whitespace-pre-wrap'
              >
                {file.body}
              </motion.pre>
            </AnimatePresence>
          )}
          <div className='text-muted-foreground border-t px-4 py-2.5 text-xs'>Workspace only. Never quoted verbatim in a public post. Included in the export package, given to writing routes on your machine, and to the cloud model only when access is allowed above.</div>
        </div>
      </div>
    </PageContainer>
  );
}
