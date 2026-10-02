'use client';

import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { CreditLimitField } from '@/features/agent/credit-limit-field';
import type { useDraftHandoff } from './use-draft';

export function DraftCreditApproval({ draft }: { draft: ReturnType<typeof useDraftHandoff> }) {
  return <RafiiDialog open={Boolean(draft.creditApproval)} onOpenChange={open => { if (!open) draft.cancelApproval(); }}>
    <RafiiDialogContent size='sm'>
      <RafiiDialogHeader title='Review this draft’s maximum' />
      <RafiiDialogBody>
        <p className='mb-3 text-sm'>Draft from the selected material. The server binds this exact request; you pay the actual cost within your approved maximum.</p>
        <CreditLimitField value={draft.maximum} onChange={draft.setMaximum} availableMilliCredits={draft.availableMilliCredits} disabled={draft.busy} estimate={draft.estimate.estimate} estimating={draft.estimate.loading} estimateError={draft.estimate.error} />
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <Button variant='quiet' disabled={draft.busy} onClick={draft.cancelApproval}>Keep editing</Button>
        <Button variant='action' disabled={draft.busy || draft.approvalInvalid} onClick={() => void draft.approve()}>{draft.busy ? 'Starting…' : 'Approve maximum & draft'}</Button>
      </RafiiDialogFooter>
    </RafiiDialogContent>
  </RafiiDialog>;
}
