'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
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
import { activeProfile, canExportPackage, voiceStatus } from './brand/voice-model';
import { VoiceSetup } from './voice-setup';

const infoContent: InfobarContent = {
  title: 'About Brand & voice',
  sections: [
    {
      title: 'What a voice changes',
      description:
        'The tone goes into every draft request. The observations and sample become VOICE.md, and what you are building, for whom and the speaker become IDENTITY.md. Writing routes read those files before drafting.',
      links: [{ title: 'See the files on Memory', url: MEMORY_HREF }]
    },
    {
      title: 'What it never does',
      description:
        'PostRiff does not analyse your sample to set the tone or observations; writing routes read it in VOICE.md only as an example of how you write. Nothing here infers your experience, credentials or results; unknowns stay listed as unknown.'
    },
    {
      title: 'Before a voice is approved',
      description: 'Drafts and previews work. Scheduling waits for an approved voice. Anyone who can edit may propose one; only an owner approves it.'
    },
    {
      title: 'When the voice changes',
      description:
        'Approving a new revision marks every draft for review and holds approved or scheduled posts; each needs a new approval to go out. Earlier revisions stay listed.'
    },
    {
      title: 'Downloading a voice package',
      description: 'The download button appears only for a voice approved field by field. A voice set up on this page does not create that package yet.'
    },
    {
      title: 'Sources',
      description: 'Material drafts may draw from is added and reviewed in Ideas, not here.',
      links: [{ title: 'Open Ideas', url: '/app/ideas' }]
    }
  ]
};

function ExportPackageButton() {
  const { api, workspaceId } = useWorkspaceApi();
  const [state, setState] = useState<ButtonState>('idle');

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
      toast.success('Voice package downloaded.');
    } catch (err) {
      setState('error');
      toast.error(err instanceof ApiError ? err.message : 'The voice package could not be downloaded.');
    }
  }

  return (
    <StatefulButton variant='outline' state={state} loadingText='Preparing…' successText='Downloaded' errorText='Try again' onClick={() => void exportPackage()}>
      Download voice package
    </StatefulButton>
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

  const side = (
    <div className='flex min-w-0 flex-col gap-4'>
      <WhatDraftsRead showMemoryLink data-tour='brand-drafts-read' />
      <RevisionHistory state={state} query={snapshot} />
    </div>
  );

  return (
    <PageContainer
      pageTitle='Brand & voice'
      pageDescription='Who speaks in this workspace and how they sound. Drafts are written from it; nothing here is inferred by a model.'
      infoContent={infoContent}
      access={canEdit}
      accessFallback={
        <div className='text-muted-foreground max-w-sm text-center text-sm'>
          Brand & voice is set up by owners, admins and editors. Ask one of them if the voice needs a change.
        </div>
      }
      pageHeaderAction={exportable ? <ExportPackageButton /> : undefined}
    >
      {snapshot.isPending ? (
        <BrandSkeleton />
      ) : !snapshot.data ? (
        <BrandLoadError query={snapshot} />
      ) : (
        <div className='flex min-w-0 flex-col gap-4'>
          {snapshot.isError && <BrandStaleNotice query={snapshot} updatedAt={snapshot.dataUpdatedAt} />}
          <VoiceStatusStrip state={state} isOwner={isOwner} memory={memory} />
          <div className='grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]'>
            {status.kind === 'active' ? (
              <div className='flex min-w-0 flex-col gap-4' data-tour='voice-setup'>
                {status.waiting && (
                  <ProposalReviewCard state={state} workspaceRevision={snapshot.data.revision} isOwner={isOwner} sample={sample} query={snapshot} />
                )}
                <IdentityCard state={state} query={snapshot} />
                <VoiceCard state={state} query={snapshot} isOwner={isOwner} />
              </div>
            ) : (
              <div className='flex min-w-0 flex-col gap-3' data-tour='voice-setup'>
                {sample && (
                  <Alert>
                    <Icons.lock />
                    <AlertTitle>This sample workspace is read-only</AlertTitle>
                    <AlertDescription>You can look through voice setup here, but nothing is saved in a sample workspace.</AlertDescription>
                  </Alert>
                )}
                {status.kind === 'unavailable' ? (
                  <div className='bg-card ring-foreground/10 rounded-xl p-4 ring-1'>
                    <SectionUnavailable message='The voice could not be read from this workspace, so setup is not shown.' query={snapshot} />
                  </div>
                ) : (
                  <VoiceSetup />
                )}
              </div>
            )}
            {side}
          </div>
        </div>
      )}
    </PageContainer>
  );
}
