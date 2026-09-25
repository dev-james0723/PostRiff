'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { ActionSwapIcon } from '@/components/motion/action-swap';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import type { InfobarContent } from '@/components/ui/infobar';
import { Icons } from '@/components/icons';
import { ApiError } from '@/lib/api/client';
import { useMemory, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SectionUnavailable } from './brand/brand-parts';
import { BrandLoadError, BrandSkeleton, BrandStaleNotice } from './brand/brand-states';
import { WhatDraftsRead } from '@/features/memory/what-drafts-read';
const MEMORY_HREF = '/app/workspace/memory';
import { IdentityCard } from './brand/identity-card';
import { ProposalReviewCard } from './brand/proposal-review-card';
import { RevisionHistory } from './brand/revision-history';
import { VoiceCard } from './brand/voice-card';
import { VoiceStatusStrip } from './brand/voice-status-strip';
import { VoiceSamplesCard } from './brand/voice-samples-card';
import { activeProfile, canExportPackage, voiceStatus } from './brand/voice-model';
import { VoiceSetup } from './voice-setup';

const infoContent: InfobarContent = {
  title: 'About Brand & voice',
  sections: [
    {
      title: 'What a voice changes',
      description: 'Every draft uses your approved voice and your brand context.',
      links: [{ title: 'See the files on Memory', url: MEMORY_HREF }]
    },
    {
      title: 'Your samples stay yours',
      description: 'Rafii analyses only samples you select and allow. It learns writing form, never facts about you.'
    },
    {
      title: 'Approving a voice',
      description: 'Anyone who can edit may propose a voice; only an owner approves it. A new revision sends drafts back for review and holds scheduled posts until approved again.'
    },
    {
      title: 'Sources',
      description: 'Material drafts may draw from is added in Ideas.',
      links: [{ title: 'Open Ideas', url: '/app/ideas' }]
    }
  ]
};

type ExportState = 'idle' | 'loading' | 'success' | 'error';

function ExportPackageButton() {
  const { api, workspaceId } = useWorkspaceApi();
  const [state, setState] = useState<ExportState>('idle');

  // A finished state rests for a moment, then the label returns; the timer never outlives the page.
  useEffect(() => {
    if (state !== 'success' && state !== 'error') return;
    const timer = window.setTimeout(() => setState('idle'), 1800);
    return () => window.clearTimeout(timer);
  }, [state]);

  async function exportPackage() {
    setState('loading');
    try {
      downloadBlob(await api.exportProfile(workspaceId), 'postriff-personal-voice.zip');
      setState('success');
    } catch (err) {
      setState('error');
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t download the voice package.');
    }
  }

  return (
    <Button variant='glass' size='control' disabled={state === 'loading'} aria-busy={state === 'loading' || undefined} onClick={() => void exportPackage()}>
      <ActionSwapIcon value={state} className='size-4'>
        {state === 'loading' ? <Icons.spinner className='size-4 motion-safe:animate-spin' /> : state === 'success' ? <Icons.check className='size-4' /> : state === 'error' ? <Icons.warning className='size-4' /> : <Icons.download className='size-4' />}
      </ActionSwapIcon>
      {state === 'loading' ? 'Preparing…' : state === 'success' ? 'Downloaded' : state === 'error' ? 'Try again' : 'Download voice package'}
    </Button>
  );
}

export function BrandView() {
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const memory = useMemory();
  const state = snapshot.data?.state;
  const isOwner = snapshot.data?.membership?.role === 'owner';
  const status = voiceStatus(state);
  const exportable = canExportPackage(activeProfile(state));
  const sample = state?.workspace?.sample === true;

  const samples = snapshot.data ? <VoiceSamplesCard state={state} revision={snapshot.data.revision} isOwner={isOwner} /> : null;

  const side = (
    <div className='flex min-w-0 flex-col gap-4 md:gap-5'>
      <WhatDraftsRead showMemoryLink data-tour='brand-drafts-read' />
      <RevisionHistory state={state} query={snapshot} />
    </div>
  );

  return (
    <PageContainer
      pageTitle='Brand & voice'
      infoContent={infoContent}
      access={canEdit}
      accessFallback={
        <StateMessage kind='permission' title='Only owners, admins and editors can change the voice.' className='w-full max-w-md' />
      }
      pageHeaderAction={exportable ? <ExportPackageButton /> : undefined}
    >
      {snapshot.isPending ? (
        <BrandSkeleton />
      ) : !snapshot.data ? (
        <BrandLoadError query={snapshot} />
      ) : (
        <div className='flex min-w-0 flex-col gap-4 md:gap-5'>
          {snapshot.isError && <BrandStaleNotice query={snapshot} updatedAt={snapshot.dataUpdatedAt} />}
          <VoiceStatusStrip state={state} isOwner={isOwner} memory={memory} />
          <div className='grid gap-4 md:gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'>
            {/* Action first: a waiting proposal, then setup or Learn my voice, then the approved profile. */}
            <div className='flex min-w-0 flex-col gap-4 md:gap-5'>
              {status.kind === 'active' ? (
                <>
                  {status.waiting && <ProposalReviewCard state={state} workspaceRevision={snapshot.data.revision} isOwner={isOwner} sample={sample} query={snapshot} />}
                  {samples}
                  {/* One card for the approved profile: who speaks, then how they sound. */}
                  <Surface material='quiet' padding='none' className='flex flex-col' data-tour='voice-setup'>
                    <IdentityCard state={state} query={snapshot} material='canvas' />
                    <VoiceCard state={state} query={snapshot} isOwner={isOwner} material='canvas' className='pt-0 md:pt-0' />
                  </Surface>
                </>
              ) : (
                <>
                  <div className='flex min-w-0 flex-col gap-3' data-tour='voice-setup'>
                    {sample && <StateMessage kind='permission' layout='inline' className='rafii-quiet rounded-[var(--rafii-radius-card)] px-4 py-3' title='Sample workspace: changes aren’t saved.' />}
                    {status.kind === 'unavailable' ? (
                      <Surface material='quiet'>
                        <SectionUnavailable message='Couldn’t load the voice.' query={snapshot} />
                      </Surface>
                    ) : (
                      <VoiceSetup />
                    )}
                  </div>
                  {samples}
                </>
              )}
            </div>
            {side}
          </div>
        </div>
      )}
    </PageContainer>
  );
}
