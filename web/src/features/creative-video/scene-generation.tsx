'use client';

import { Button } from '@/components/ui/button';
import type { CreativeAspect, CreativeProvider, CreativeQuoteReply, CreativeScene, CreativeSettings } from '@/lib/api/creative-video';
import { formatCredits } from './intelligence';
import { formatUsd, unresolved } from './scene-edit';
import { RunwayAttribution, SceneQuote } from './scene-quote';

const stateLabel = {
  submitting: 'Submitting the generation request',
  pending: 'Waiting for the provider',
  unknown: 'The provider outcome needs reconciliation',
  failed: 'Generation failed',
  cancelling: 'Cancellation requested',
  cancelled: 'Generation cancelled',
  completed: 'Generation completed'
} as const;

const reasonLabels = new Map([
  ['provider_output_unusable', 'The provider returned footage that Rafii could not use.'],
  ['authorization_changed', 'Workspace authorization changed before the footage could be accepted.'],
  ['submission_reconciled_without_clip', 'Billing reconciliation finished without an attached clip.'],
  ['submission_unknown', 'The provider has not confirmed whether it accepted the request.'],
  ['request_declined', 'The provider declined the generation request.'],
  ['provider_content_filtered', 'The provider filtered the requested footage.'],
  ['provider_operation_unavailable', 'The provider could not locate the saved operation.']
]);

export function SceneGeneration({ scene, provider, aspect, hasReference, cloudAllowed, canApprove, canEdit, dirty, busy, pending, historical, savedSettings, onSettings, onQuote, onGenerate, onPoll, onCancel }: {
  scene: CreativeScene; provider: CreativeProvider; aspect: CreativeAspect; hasReference: boolean; cloudAllowed: boolean; canApprove: boolean; canEdit: boolean;
  dirty: boolean; busy: boolean; pending: boolean; historical: boolean;
  savedSettings?: CreativeSettings; onSettings: (settings: CreativeSettings) => void;
  onQuote: (settings: CreativeSettings) => Promise<CreativeQuoteReply>; onGenerate: (quoteId: string) => void;
  onPoll: () => void; onCancel: () => void;
}) {
  const generation = scene.generation;
  let reason: string | null = null;
  if (historical) reason = 'Open the current project to request footage.';
  else if (!canApprove && !canEdit) reason = 'A workspace editor can prepare a scene.';
  else if (scene.clipId) reason = 'This scene already has footage. A new take requires a separate approval.';
  else if (pending) reason = 'Check the saved request for its latest status.';
  else if (generation?.state === 'failed' || generation?.state === 'cancelled') reason = 'Prepare another take or revise the scene direction to request new footage.';
  return <section className='grid gap-4 border-t pt-4' aria-label='Scene production'>
    <h3 className='font-medium'>Produce this scene</h3>
    {generation && <div className='rafii-quiet grid gap-2 rounded-lg px-3 py-3 text-sm' role='status'>
      <p className='font-medium'>{stateLabel[generation.state] || 'Check the saved request'}</p>
      {generation.model && <p className='break-words'>{generation.model}</p>}
      {generation.provider === 'runway' && <RunwayAttribution />}
      {generation.reason && reasonLabels.has(generation.reason) && <p>{reasonLabels.get(generation.reason)}</p>}
      {typeof generation.estimatedMilliCredits === 'number' && <p>Quoted · {formatCredits(generation.estimatedMilliCredits)} AI Credits</p>}
      {typeof generation.actualUsdMicro === 'number' && <p>Recorded cost · {formatUsd(generation.actualUsdMicro)}</p>}
      {generation.settlementState && <p>Settlement · {generation.settlementState.replaceAll('_', ' ')}</p>}
      {generation.state === 'completed' && generation.actualUsdMicro == null && <p className='text-muted-foreground'>Actual provider cost pending reconciliation.</p>}
      {unresolved(scene) && (canApprove || canEdit && generation.mediaKind === 'composed') && !historical && <div className='flex flex-wrap gap-2'>
        <Button variant='glass' size='lg' disabled={busy || dirty} onClick={onPoll}>Check generation</Button>
        {generation.cancellable && <Button variant='quiet' size='lg' disabled={busy || dirty} onClick={() => {
          if (window.confirm('Cancel this take? The provider may already have finished it. Its output may be lost, and usage already incurred may still be charged within your approved limit.')) onCancel();
        }}>Cancel generation</Button>}
      </div>}
    </div>}
    {reason ? <p className='text-sm text-muted-foreground'>{reason}</p> : <>
      {!cloudAllowed && <p className='text-sm text-muted-foreground'>This workspace allows local composition only.</p>}
      <SceneQuote models={provider.models ?? []} durationMs={scene.durationMs} aspect={aspect} hasReference={hasReference} localOnly={!canApprove} cloudAllowed={cloudAllowed}
        disabled={busy || dirty} savedSettings={savedSettings} onSettings={onSettings} onQuote={onQuote} onGenerate={onGenerate} />
    </>}
  </section>;
}
