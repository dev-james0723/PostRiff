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
    <div className='flex items-center justify-between gap-3'><h2 className='font-semibold'>Learn my writing style</h2><Button size='sm' variant='ghost' onClick={onClose}>Close sample review</Button></div>
    <p className='whitespace-pre-wrap text-sm'>{request.instructions}</p>
    <p className='text-muted-foreground text-xs'>First review the retrieved posts. Retaining samples, allowing analysis, approving the Writing DNA profile, and allowing future generation are separate decisions. Nothing in this workflow publishes.</p>
    {snapshot.isPending ? <p role='status'>Checking your workspace…</p> : snapshot.isError || !snapshot.data ? <p role='alert'>Your workspace could not be verified. <button type='button' className='underline' onClick={() => void snapshot.refetch()}>Retry</button></p> : !owner ? <p>An owner must authorize social-post retrieval and sample use. No posts were read for this request.</p> : <>
      <VoiceSamplesCard state={state} revision={snapshot.data.revision} isOwner={owner} preferredPlatform={request.platform} analysisRequest={request.instructions} autoPropose />
      {state?.speaker?.provisional && (state.speaker.activeRevision ? <ProposalReviewCard state={state} workspaceRevision={snapshot.data.revision} isOwner={owner} sample={state.workspace?.sample === true} query={snapshot} /> : <VoiceSetup />)}
      {state?.speaker?.activeRevision && !state.speaker.provisional && <p role='status' className='text-sm'>Writing DNA revision {state.speaker.activeRevision} is approved. Individual samples still need generation permission for the exact writer you choose.</p>}
    </>}
  </section>;
}
