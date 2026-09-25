'use client';

import { Button } from '@/components/ui/button';
import { useSnapshot } from '@/lib/api/hooks';
import { VoiceSamplesCard } from '@/features/workspace/brand/voice-samples-card';
import { ProposalReviewCard } from '@/features/workspace/brand/proposal-review-card';
import { VoiceSetup } from '@/features/workspace/voice-setup';
import type { VoiceLearningRequest } from './voice-learning-intent';

/** Chat and Brand & voice share exactly the same samples, grants and provisional profile. */
export function VoiceLearningPanel({ request, onClose }: { request: VoiceLearningRequest; onClose: () => void }) {
  const snapshot = useSnapshot();
  const state = snapshot.data?.state;
  const owner = snapshot.data?.membership?.role === 'owner';
  return <section aria-label='Review writing samples with Rafii' className='border-border space-y-4 rounded-xl border p-3'>
    <div className='flex items-center justify-between gap-3'><h2 className='font-semibold'>Learn my writing style</h2><Button size='sm' variant='ghost' aria-label='Close sample review' onClick={onClose}>Close</Button></div>
    <p className='whitespace-pre-wrap text-sm'>{request.instructions}</p>
    <p className='text-muted-foreground text-xs'>You decide each step separately: keeping samples, analysis, the profile, and use in drafts.</p>
    {snapshot.isPending ? <p role='status'>Checking your workspace…</p> : snapshot.isError || !snapshot.data ? <p role='alert'>Couldn’t load your workspace. <button type='button' className='underline' onClick={() => void snapshot.refetch()}>Retry</button></p> : !owner ? <p>Only an owner can import posts. Nothing was read.</p> : <>
      <VoiceSamplesCard state={state} revision={snapshot.data.revision} isOwner={owner} preferredPlatform={request.platform} analysisRequest={request.instructions} autoPropose />
      {state?.speaker?.provisional && (state.speaker.activeRevision ? <ProposalReviewCard state={state} workspaceRevision={snapshot.data.revision} isOwner={owner} sample={state.workspace?.sample === true} query={snapshot} /> : <VoiceSetup />)}
      {state?.speaker?.activeRevision && !state.speaker.provisional && <p role='status' className='text-sm' title={`Revision ${state.speaker.activeRevision}`}>Writing DNA approved. Each sample still needs permission for the model you draft with.</p>}
    </>}
  </section>;
}
