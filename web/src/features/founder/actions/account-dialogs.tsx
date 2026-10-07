'use client';

import { useId, useMemo, useState } from 'react';
import { FilterSelect, SegmentedControl } from '@/components/rafii';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { FIELD_CLASS } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { stateLabel, whenDateTime } from '../customers/kit/format';
import { ConfirmActionDialog } from './confirm-action-dialog';
import { BLOCK_REASONS, CREDIT_REASONS, GRANT_EXPIRY_DAYS, LIFT_REASONS, REFUND_REASONS, blockRequest, creditsRequest, grantExpiry, refundRequest, unblockRequest } from './model';
import type { ActiveBlock, BlockReason, CreditReason, FounderAction, LiftReason, RefundReason, RequestCheck } from './types';

/**
 * The Customer 360 action dialogs: block / lift a block, adjust credits, prepare a refund intent. Each only gathers the
 * founder's choices; `ConfirmActionDialog` previews them on the server and confirms. No identifier here is free text the
 * page made up: the person and workspace ids come from the customer record.
 */
export interface WorkspaceChoice {
  id: string;
  label: string;
}

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onExecuted?: (action: FounderAction) => void;
}

function TextField({ label, value, onChange, help, placeholder, decimal = false, mono = false }: { label: string; value: string; onChange: (value: string) => void; help?: string; placeholder?: string; decimal?: boolean; mono?: boolean }) {
  const id = useId();
  const helpId = useId();
  return (
    <div className='flex flex-col gap-2 text-sm'>
      <Label htmlFor={id} className='text-foreground font-medium'>
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        inputMode={decimal ? 'decimal' : undefined}
        autoComplete='off'
        spellCheck={false}
        aria-describedby={help ? helpId : undefined}
        className={cn(FIELD_CLASS, mono && 'font-mono')}
      />
      {help && (
        <p id={helpId} className='text-muted-foreground text-xs'>
          {help}
        </p>
      )}
    </div>
  );
}

function WorkspaceField({ workspaces, value, onChange }: { workspaces: WorkspaceChoice[]; value: string; onChange: (value: string) => void }) {
  if (workspaces.length === 1) {
    return (
      <p className='text-sm'>
        Workspace <span className='font-medium'>{workspaces[0].label}</span>
      </p>
    );
  }
  return <FilterSelect label='Workspace' value={value} onChange={onChange} options={workspaces.map((workspace) => ({ value: workspace.id, label: workspace.label }))} />;
}

/** UTC midnight today: a grant's expiry stays the same while the founder edits, so a retried preview is the same request. */
function today(): Date {
  const now = new Date();
  now.setUTCHours(0, 0, 0, 0);
  return now;
}

export function BlockAccountDialog({ open, onOpenChange, onExecuted, customerId, workspaces }: DialogProps & { customerId: string; workspaces: WorkspaceChoice[] }) {
  const [scope, setScope] = useState<'user' | 'workspace'>('user');
  const [workspaceId, setWorkspaceId] = useState(workspaces[0]?.id ?? '');
  const [reason, setReason] = useState<BlockReason>('abuse');
  const [approval, setApproval] = useState('');
  const check = blockRequest({ targetType: scope, targetId: scope === 'user' ? customerId : workspaceId, reasonCode: reason, approvalRef: approval });
  const form = (
    <div className='flex flex-col gap-4'>
      {workspaces.length > 0 && (
        <SegmentedControl
          label='What to block'
          size='sm'
          value={scope}
          onChange={setScope}
          options={[
            { value: 'user', label: 'This person' },
            { value: 'workspace', label: 'One workspace' }
          ]}
        />
      )}
      {scope === 'workspace' && <WorkspaceField workspaces={workspaces} value={workspaceId} onChange={setWorkspaceId} />}
      <p className='text-muted-foreground text-xs leading-relaxed'>
        {scope === 'user'
          ? 'Their sign-ins and API tokens are refused, and the workspaces they own are frozen: publishing and automations pause. Nothing is deleted.'
          : 'This workspace is frozen for everyone in it; its members keep their other workspaces. Nothing is deleted.'}
      </p>
      <FilterSelect label='Reason' value={reason} onChange={(value) => setReason(value as BlockReason)} options={BLOCK_REASONS} />
      <TextField label='Approval reference' value={approval} onChange={setApproval} placeholder='ticket-1042' help='A ticket or decision id kept with the block: letters, digits and . _ : / # -, no names or messages.' mono />
    </div>
  );
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      onExecuted={onExecuted}
      kind='account_block'
      title='Block this account'
      intro='The server previews exactly who is refused and what is frozen. Nothing changes until you confirm.'
      form={form}
      check={check}
      confirmLabel='Block account'
      destructive
    />
  );
}

export function UnblockAccountDialog({ open, onOpenChange, onExecuted, block }: DialogProps & { block: ActiveBlock | null }) {
  const [reason, setReason] = useState<LiftReason>('resolved');
  const targetType = block?.userId ? 'user' : 'workspace';
  const targetId = block?.userId ?? block?.workspaceId ?? '';
  const check: RequestCheck = block ? unblockRequest({ targetType, targetId, reasonCode: reason }) : { ok: false, reason: 'There is no active block to lift.' };
  const form = (
    <div className='flex flex-col gap-4'>
      {block && (
        <p className='text-sm leading-relaxed'>
          {targetType === 'user' ? 'This person' : 'This workspace'} has been blocked since {whenDateTime(block.blockedAt)} for {stateLabel(block.reasonCode)}.
        </p>
      )}
      <FilterSelect label='Why the block is lifted' value={reason} onChange={(value) => setReason(value as LiftReason)} options={LIFT_REASONS} />
    </div>
  );
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      onExecuted={onExecuted}
      kind='account_unblock'
      title='Lift this block'
      intro='Sign-ins, API tokens, publishing and automations resume exactly as they were. Preview first.'
      form={form}
      check={check}
      confirmLabel='Lift block'
    />
  );
}

export function AdjustCreditsDialog({ open, onOpenChange, onExecuted, workspaces }: DialogProps & { workspaces: WorkspaceChoice[] }) {
  const [workspaceId, setWorkspaceId] = useState(workspaces[0]?.id ?? '');
  const [operation, setOperation] = useState<'grant' | 'reverse'>('grant');
  const [creditsText, setCreditsText] = useState('');
  const [days, setDays] = useState<string>(String(GRANT_EXPIRY_DAYS[0]));
  const [grantId, setGrantId] = useState('');
  const [reason, setReason] = useState<CreditReason>('goodwill');
  const expiresAt = useMemo(() => grantExpiry(Number(days), today()), [days]);
  const check = creditsRequest({ workspaceId, operation, creditsText, reasonCode: reason, ...(operation === 'grant' ? { expiresAt } : { grantId }) });
  const form = (
    <div className='flex flex-col gap-4'>
      <WorkspaceField workspaces={workspaces} value={workspaceId} onChange={setWorkspaceId} />
      <SegmentedControl
        label='Grant or take back'
        size='sm'
        value={operation}
        onChange={setOperation}
        options={[
          { value: 'grant', label: 'Grant' },
          { value: 'reverse', label: 'Take back' }
        ]}
      />
      <TextField label='Credits' value={creditsText} onChange={setCreditsText} placeholder='5' help='In credits, in steps of 0.1, at most 50,000.' decimal />
      {operation === 'grant' ? (
        <FilterSelect label='Expires after' value={days} onChange={setDays} options={GRANT_EXPIRY_DAYS.map((value) => ({ value: String(value), label: `${value} days` }))} />
      ) : (
        <TextField label='Grant id' value={grantId} onChange={setGrantId} placeholder='3f7c…' help='The credit grant to take back; the preview shows what is left of it.' mono />
      )}
      <FilterSelect label='Reason' value={reason} onChange={(value) => setReason(value as CreditReason)} options={CREDIT_REASONS} />
    </div>
  );
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      onExecuted={onExecuted}
      kind='credits_adjust'
      title='Adjust credits'
      intro='The preview shows the wallet now and after. Goodwill credit always expires; nothing changes until you confirm.'
      form={form}
      check={check}
      confirmLabel={operation === 'grant' ? 'Grant credits' : 'Take back credits'}
      destructive={operation === 'reverse'}
    />
  );
}

export function RefundIntentDialog({ open, onOpenChange, onExecuted, workspaces }: DialogProps & { workspaces: WorkspaceChoice[] }) {
  const [workspaceId, setWorkspaceId] = useState(workspaces[0]?.id ?? '');
  const [payment, setPayment] = useState('');
  const [amountText, setAmountText] = useState('');
  const [currency, setCurrency] = useState('usd');
  const [reason, setReason] = useState<RefundReason>('requested_by_customer');
  const validated = refundRequest({ workspaceId, paymentIntentId: payment, amountText, currency, reasonCode: reason });
  const check = validated.ok ? { ...validated, request: { ...validated.request, path: '/actions/refunds/execute/preview' } } : validated;
  const form = (
    <div className='flex flex-col gap-4'>
      <WorkspaceField workspaces={workspaces} value={workspaceId} onChange={setWorkspaceId} />
      <TextField label='Payment reference' value={payment} onChange={setPayment} placeholder='pi_3Nf…' help='The payment intent of the charge to refund.' mono />
      <div className='grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_8rem]'>
        <TextField label='Amount' value={amountText} onChange={setAmountText} placeholder='12.50' decimal />
        <TextField label='Currency' value={currency} onChange={setCurrency} placeholder='usd' mono />
      </div>
      <FilterSelect label='Reason' value={reason} onChange={(value) => setReason(value as RefundReason)} options={REFUND_REASONS} />
    </div>
  );
  return (
    <ConfirmActionDialog
      open={open}
      onOpenChange={onOpenChange}
      onExecuted={onExecuted}
      kind='refund_intent'
      title='Preview a refund'
      intro='Review the exact payment, amount and refundable balance. A refund reaches Stripe only after a fresh second factor and your typed REFUND confirmation.'
      form={form}
      check={check}
      previewLabel='Preview refund'
      confirmLabel='Confirm refund'
    />
  );
}
