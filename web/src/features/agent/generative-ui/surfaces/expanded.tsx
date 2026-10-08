'use client';

/**
 * The expanded surface (D-A21 `expanded`): the SAME artifact session in a full-height dialog for dense tables and forms on
 * desktop and tablet. It is not a new conversation, artifact or stream; closing it returns focus to the Expand control. Escape
 * closes only this dialog (it carries `data-rafii-generated-dialog`, which the Rafii panel's Escape handling skips).
 */
import type { ReactNode } from 'react';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogHeader } from '@/components/rafii/rafii-dialog';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { GeneratedArtifact } from './artifact';
import { GENERATED_DIALOG_ATTR } from './selectors';
import type { ArtifactSession } from './session';

export function ExpandedArtifact({ session, open, onOpenChange, runId, onContinue, title = 'Interactive view', nativeResult }: {
  session: ArtifactSession;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runId: string | null;
  onContinue?: (request: ContinueRequest) => void;
  title?: string;
  nativeResult?: ReactNode;
}) {
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <RafiiDialogContent size='xl' className='md:h-[min(58rem,94dvh)]' {...{ [GENERATED_DIALOG_ATTR]: '' }}>
          <RafiiDialogHeader title={title} closeLabel='Close interactive view' />
          <RafiiDialogBody>
            <GeneratedArtifact session={session} surface='expanded' runId={runId} onContinue={(request) => {
              onOpenChange(false);
              onContinue?.(request);
            }} nativeResult={nativeResult} />
          </RafiiDialogBody>
        </RafiiDialogContent>
      )}
    </RafiiDialog>
  );
}
