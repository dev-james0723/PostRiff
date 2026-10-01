'use client';

import { useCallback, useId, useMemo, useState, type ReactNode } from 'react';
import { SegmentedControl } from '@/components/rafii';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FIELD_CLASS } from '@/features/workspace/rafii-parts';
import { useFounderScope } from '../customers/kit/api';
import { usdMicro, whenDateTime } from '../customers/kit/format';
import { ConfirmActionDialog } from './confirm-action-dialog';
import { isUuid, reconcileRequest, unavailableReason } from './model';
import type { FounderAction } from './types';

/**
 * Reconcile one unknown-cost usage reservation (`POST /usage/reconcile/preview|confirm`, capability `usage.reconcile`):
 * the founder records the provider's actual cost and the evidence (a gateway request id); `failed` never charges the
 * customer, `completed` charges within what they approved, and either way the provider cost is booked. The AI cost
 * page's queue opens it through `useReconcileAction`.
 */
export interface ReconcileTarget {
  workspaceId?: string | null;
  reservationId?: string | null;
  estimatedUsdMicro?: number | null;
  provider?: string | null;
  model?: string | null;
  at?: string | null;
}

function Field({ label, help, children }: { label: string; help: string; children: (ids: { id: string; helpId: string }) => ReactNode }) {
  const id = useId();
  const helpId = useId();
  return (
    <div className='flex flex-col gap-2 text-sm'>
      <Label htmlFor={id} className='text-foreground font-medium'>
        {label}
      </Label>
      {children({ id, helpId })}
      <p id={helpId} className='text-muted-foreground text-xs'>
        {help}
      </p>
    </div>
  );
}

export function ReconcileDialog({ open, onOpenChange, target, onExecuted }: { open: boolean; onOpenChange: (open: boolean) => void; target: ReconcileTarget | null; onExecuted?: (action: FounderAction) => void }) {
  const [outcome, setOutcome] = useState<'failed' | 'completed'>('failed');
  const [actualText, setActualText] = useState('');
  const [evidence, setEvidence] = useState('');
  const check = reconcileRequest({ workspaceId: target?.workspaceId ?? undefined, reservationId: target?.reservationId ?? undefined, outcome, actualText, evidence });
  const form = (
    <div className='flex flex-col gap-4'>
      {target && (
        <dl className='rafii-quiet grid grid-cols-[minmax(6.5rem,auto)_minmax(0,1fr)] gap-x-3 gap-y-1.5 rounded-[var(--rafii-radius-control)] p-3 text-xs'>
          <dt className='text-muted-foreground'>Reservation</dt>
          <dd className='min-w-0 font-mono break-all'>{target.reservationId ?? 'Not recorded'}</dd>
          <dt className='text-muted-foreground'>Provider · model</dt>
          <dd className='min-w-0 break-words'>{[target.provider, target.model].filter(Boolean).join(' · ') || 'Not recorded'}</dd>
          <dt className='text-muted-foreground'>Estimated</dt>
          <dd>{typeof target.estimatedUsdMicro === 'number' ? usdMicro(target.estimatedUsdMicro) : 'Not recorded'}</dd>
          <dt className='text-muted-foreground'>Since</dt>
          <dd>{whenDateTime(target.at)}</dd>
        </dl>
      )}
      <SegmentedControl
        label='Did the person get the result?'
        size='sm'
        widths='content'
        value={outcome}
        onChange={setOutcome}
        options={[
          { value: 'failed', label: 'No: charge nothing' },
          { value: 'completed', label: 'Yes: charge within approval' }
        ]}
      />
      <Field label='Actual provider cost (US$)' help="From the provider's own record, for example the gateway request log. Booked as Rafii's cost either way.">
        {({ id, helpId }) => <Input id={id} value={actualText} onChange={(event) => setActualText(event.target.value)} placeholder='0.0123' inputMode='decimal' autoComplete='off' spellCheck={false} aria-describedby={helpId} className={FIELD_CLASS} />}
      </Field>
      <Field label='Provider evidence' help='A request id or reference from that record. No names, emails or messages.'>
        {({ id, helpId }) => <Input id={id} value={evidence} onChange={(event) => setEvidence(event.target.value)} placeholder='gateway req 3f2a91' autoComplete='off' spellCheck={false} aria-describedby={helpId} className={`${FIELD_CLASS} font-mono`} />}
      </Field>
    </div>
  );
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      onExecuted={onExecuted}
      kind='reconcile'
      title='Reconcile this usage'
      intro='The server previews what is booked, released and charged. Nothing changes until you confirm, and each reservation is finalised once.'
      form={form}
      check={check}
      confirmLabel='Reconcile'
    />
  );
}

export interface ReconcileAction {
  /** Open the dialog for one queue row. */
  start: (target: ReconcileTarget) => void;
  /** Render this once next to the queue. */
  dialog: ReactNode;
  /** Why reconciling is off here (Demo, missing capability), or null. */
  disabledReason: string | null;
  /** Whether a row carries the ids a reconciliation needs. */
  canStart: (target: ReconcileTarget) => boolean;
}

/**
 * For the AI cost page's reconcile queue (slice B): `const reconcile = useReconcileAction()`, a button per row calling
 * `reconcile.start(row)` (disabled with `reconcile.disabledReason`), and `{reconcile.dialog}` rendered once.
 */
export function useReconcileAction(onExecuted?: (action: FounderAction) => void): ReconcileAction {
  const scope = useFounderScope();
  const [target, setTarget] = useState<ReconcileTarget | null>(null);
  const [open, setOpen] = useState(false);
  const disabledReason = unavailableReason({ kind: 'reconcile', mode: scope.mode, capabilities: scope.capabilities });
  const start = useCallback((next: ReconcileTarget) => {
    setTarget(next);
    setOpen(true);
  }, []);
  const canStart = useCallback((next: ReconcileTarget) => disabledReason === null && isUuid(next.workspaceId) && isUuid(next.reservationId), [disabledReason]);
  // One dialog per reservation: a new row starts with empty fields.
  const dialog = useMemo(() => <ReconcileDialog key={target?.reservationId ?? 'none'} open={open} onOpenChange={setOpen} target={target} onExecuted={onExecuted} />, [open, target, onExecuted]);
  return { start, dialog, disabledReason, canStart };
}
