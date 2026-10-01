'use client';

import { useId, useRef, useState, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FIELD_CLASS } from '@/features/workspace/rafii-parts';
import { randomKey, signInHref } from '@/lib/founder/api';
import { whenDateTime } from '../customers/kit/format';
import { postAction, useActionRefresh } from './api';
import { ActionSummary } from './facts';
import { BLOCKER_COPY, KIND_LABEL, PREVIEW_MINUTES, STATE_LABEL, TYPED_BLOCK, actionFailure, confirmBody, confirmPath, typedConfirmationOk, type ActionFailure } from './model';
import type { ActionKind, FounderAction, RequestCheck } from './types';

/**
 * The one confirm dialog for every founder action (CONTRACTS §8.F): the founder fills the form, the server previews the
 * exact target, its current value and the effect, and only an explicit confirm — with a second factor from the last five
 * minutes, the preview id and its revision, and for a block the typed word — changes anything. Every answer is shown as
 * fixed copy (`model.actionFailure`): a step-up asks the founder to sign in again, a policy refusal names its reason, an
 * expired or moved preview asks for a new one, and an unknown outcome retries with the same request id (it runs once).
 * Focus returns to the control that opened the dialog (Base UI's default) and the dialog is named by its title.
 */
export interface ConfirmActionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kind: ActionKind;
  title: string;
  intro: ReactNode;
  /** The inputs shown before the preview. */
  form: ReactNode;
  /** The inputs as a preview request, or why they are not complete yet. */
  check: RequestCheck;
  confirmLabel: string;
  /** The first step's button; "Preview" unless the step itself is the whole action (a refund intent is recorded). */
  previewLabel?: string;
  /** Blocks and reversals read as destructive. */
  destructive?: boolean;
  onExecuted?: (action: FounderAction) => void;
}

export function ConfirmActionDialog(props: ConfirmActionDialogProps) {
  // Each opening starts a fresh flow (a new preview, new request ids); state from a previous opening never leaks in.
  const [generation, setGeneration] = useState(0);
  const [wasOpen, setWasOpen] = useState(props.open);
  if (props.open !== wasOpen) {
    setWasOpen(props.open);
    if (props.open) setGeneration((value) => value + 1);
  }
  return (
    <RafiiDialog open={props.open} onOpenChange={(next) => props.onOpenChange(next)}>
      <RafiiDialogContent size='md'>
        <ActionFlow key={generation} {...props} />
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/** A fresh second factor means a new sign-in; the founder comes back to this page (and this customer) afterwards. */
function signInAgain() {
  window.location.assign(signInHref(`${window.location.pathname}${window.location.search}`));
}

function FailureNote({ failure, onSignIn, onRetry, onPreviewAgain }: { failure: ActionFailure; onSignIn: () => void; onRetry?: () => void; onPreviewAgain?: () => void }) {
  const kind = failure.stepUp || failure.code === 'SCOPE_DENIED' ? 'permission' : failure.code === 'POLICY_DISABLED' ? 'unsupported' : 'error';
  let action: ReactNode = null;
  if (failure.stepUp) {
    action = (
      <Button variant='glass' size='sm' onClick={onSignIn}>
        <Icons.login /> Sign in again
      </Button>
    );
  } else if (onRetry) {
    action = (
      <Button variant='glass' size='sm' onClick={onRetry}>
        <Icons.refresh /> Retry the same confirmation
      </Button>
    );
  } else if (onPreviewAgain) {
    action = (
      <Button variant='glass' size='sm' onClick={onPreviewAgain}>
        <Icons.refresh /> Preview again
      </Button>
    );
  }
  return <StateMessage kind={kind} layout='inline' title={failure.title} description={failure.description} action={action} />;
}

function ActionFlow({ open, onOpenChange, kind, title, intro, form, check, confirmLabel, previewLabel = 'Preview', destructive = false, onExecuted }: ConfirmActionDialogProps) {
  const refresh = useActionRefresh();
  const typedId = useId();
  const typedHelpId = useId();
  const [preview, setPreview] = useState<FounderAction | null>(null);
  const [done, setDone] = useState<{ action: FounderAction; replayed: boolean } | null>(null);
  const [failure, setFailure] = useState<ActionFailure | null>(null);
  const [busy, setBusy] = useState<'preview' | 'confirm' | null>(null);
  const [typed, setTyped] = useState('');
  // A retry of the same payload reuses its request id, so the server answers it once (CONTRACTS §8.F idempotency).
  const previewKey = useRef<{ signature: string; requestId: string } | null>(null);
  const confirmKey = useRef<{ previewId: string; requestId: string } | null>(null);

  async function runPreview() {
    if (!check.ok || busy) return;
    const signature = JSON.stringify(check.request);
    if (previewKey.current?.signature !== signature) previewKey.current = { signature, requestId: randomKey() };
    const { requestId } = previewKey.current;
    setBusy('preview');
    setFailure(null);
    try {
      const response = await postAction(check.request.path, { ...check.request.body, requestId });
      setPreview(response.data.action);
      setTyped('');
      refresh(kind);
    } catch (error) {
      setFailure(actionFailure(error));
    } finally {
      setBusy(null);
    }
  }

  async function runConfirm() {
    const path = preview ? confirmPath(preview) : null;
    if (!preview || !path || busy || !typedConfirmationOk(kind, typed)) return;
    if (confirmKey.current?.previewId !== preview.previewId) confirmKey.current = { previewId: preview.previewId, requestId: randomKey() };
    const { requestId } = confirmKey.current;
    setBusy('confirm');
    setFailure(null);
    try {
      const response = await postAction(path, confirmBody(preview, requestId, typed));
      setDone({ action: response.data.action, replayed: response.data.replayed });
      onExecuted?.(response.data.action);
    } catch (error) {
      setFailure(actionFailure(error));
    } finally {
      setBusy(null);
      refresh(kind);
    }
  }

  function startOver() {
    setPreview(null);
    setFailure(null);
    setTyped('');
    previewKey.current = null;
    confirmKey.current = null;
  }

  const stage = done ? 'done' : preview ? 'review' : 'form';
  const confirmable = preview !== null && preview.execution.allowed && confirmPath(preview) !== null;
  const stillOpen = preview?.state === 'previewed';
  const needsTyped = kind === 'account_block';
  const canConfirm = confirmable && stillOpen && typedConfirmationOk(kind, typed) && busy === null && !failure?.previewAgain;

  return (
    <>
      <RafiiDialogHeader eyebrow={KIND_LABEL[kind]} title={title} intro={intro} />
      <RafiiDialogBody className='flex flex-col gap-4'>
        {stage === 'form' && (
          <>
            {form}
            {!check.ok && <p className='text-muted-foreground text-xs'>{check.reason}</p>}
          </>
        )}
        {stage === 'review' && preview && (
          <>
            <ActionSummary action={preview} />
            {confirmable ? (
              stillOpen ? (
                <p className='text-muted-foreground text-xs leading-relaxed'>
                  Valid until {whenDateTime(preview.expiresAt)}. Confirming needs a second-factor check from the last {PREVIEW_MINUTES} minutes; the server checks the record again and refuses if it moved.
                </p>
              ) : (
                <StateMessage kind='stale' layout='inline' title='This preview is no longer open' description={BLOCKER_COPY.preview_expired} />
              )
            ) : (
              <StateMessage kind='unsupported' layout='inline' title='Recorded, not carried out' description={(preview.execution.blocker && BLOCKER_COPY[preview.execution.blocker]) || 'This action cannot be confirmed from the browser.'} />
            )}
            {confirmable && stillOpen && needsTyped && (
              <div className='flex flex-col gap-2'>
                <Label htmlFor={typedId}>Type {TYPED_BLOCK} to confirm</Label>
                <Input id={typedId} value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete='off' spellCheck={false} aria-describedby={typedHelpId} className={`${FIELD_CLASS} font-mono`} />
                <p id={typedHelpId} className='text-muted-foreground text-xs'>
                  The customer is refused from their next request on. Nothing is deleted; lifting the block restores everything.
                </p>
              </div>
            )}
          </>
        )}
        {stage === 'done' && done && (
          <>
            <StateMessage
              kind='success'
              layout='inline'
              title={done.action.state === 'executed' ? 'Done' : STATE_LABEL[done.action.state] ?? 'Recorded'}
              description={done.replayed ? 'This confirmation had already run; nothing ran twice.' : 'Recorded in the customer audit trail and the Control audit log.'}
            />
            <ActionSummary action={done.action} showResult />
          </>
        )}
        {failure && (
          <FailureNote
            failure={failure}
            onSignIn={signInAgain}
            onRetry={failure.retrySame && stage === 'review' ? () => void runConfirm() : undefined}
            onPreviewAgain={failure.previewAgain && stage === 'review' ? startOver : undefined}
          />
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <div className='flex flex-col-reverse gap-2 sm:flex-row sm:justify-end'>
          {stage === 'form' && (
            <>
              <Button variant='quiet' size='control' onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button variant='action' size='control' disabled={!open || !check.ok || busy !== null} onClick={() => void runPreview()}>
                {busy === 'preview' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : <Icons.eye aria-hidden />} {previewLabel}
              </Button>
            </>
          )}
          {stage === 'review' && (
            <>
              <Button variant='quiet' size='control' disabled={busy !== null} onClick={startOver}>
                Edit
              </Button>
              {confirmable ? (
                <Button variant={destructive ? 'destructive' : 'action'} size='control' disabled={!canConfirm} onClick={() => void runConfirm()}>
                  {busy === 'confirm' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : <Icons.check aria-hidden />} {confirmLabel}
                </Button>
              ) : (
                <Button variant='action' size='control' onClick={() => onOpenChange(false)}>
                  Close
                </Button>
              )}
            </>
          )}
          {stage === 'done' && (
            <Button variant='action' size='control' onClick={() => onOpenChange(false)}>
              Close
            </Button>
          )}
        </div>
      </RafiiDialogFooter>
    </>
  );
}
