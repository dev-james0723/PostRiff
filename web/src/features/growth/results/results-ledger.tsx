'use client';

import { useId, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogClose, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { FIELD_CLASS, SelectField, StatusChip, TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { errorMessage, idempotencyKey } from '@/lib/growth-v2/request';
import { useAmendResult, useDeclareResult, useResultsLedger, useReverseResult, useTrackingLinks } from '@/lib/growth-v2/results-hooks';
import type { ResultFilters, ResultItem } from '@/lib/growth-v2/results-types';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { amountText, checkDeclaration, duration, formatMoney, isoToLocal, type DeclarationForm, type ResultsCopy } from './present';
import { useResultsCopy } from './use-results-copy';

const DECLARABLE = ['lead', 'booking', 'newsletter_signup', 'sale'] as const;
const KINDS = ['lead', 'booking', 'newsletter_signup', 'sale', 'click'] as const;

/** The ledger: every result with its source, times, link and correction state; the person's own declarations can be
 * edited (a new version) or reversed (kept, marked reversed). Connected tools correct their own events. */
export function ResultsLedger() {
  const { copy, locale } = useResultsCopy();
  const [filters, setFilters] = useState<ResultFilters>({});
  const ledger = useResultsLedger(filters);
  const [editing, setEditing] = useState<ResultItem | 'new' | null>(null);
  const [reversing, setReversing] = useState<ResultItem | null>(null);
  const pages = ledger.data?.pages ?? [];
  const items = pages.flatMap((page) => page.items);
  const canEdit = pages[0]?.canEdit ?? false;
  const filtered = Object.values(filters).some(Boolean);
  const choose = (key: keyof ResultFilters) => (event: ChangeEvent<HTMLSelectElement>) =>
    setFilters((current) => ({ ...current, [key]: event.target.value || undefined }) as ResultFilters);

  return (
    <>
      <div className='flex flex-wrap items-end justify-between gap-3'>
        <div className='grid w-full grid-cols-2 gap-3 sm:flex sm:w-auto sm:flex-wrap'>
          <SelectField label={copy.ledger.source} value={filters.provenance ?? ''} onChange={choose('provenance')} className='sm:w-52'>
            <option value=''>{copy.ledger.all}</option>
            <option value='user_declared'>{copy.classes.user_declared}</option>
            <option value='first_party_reported'>{copy.classes.first_party_reported}</option>
          </SelectField>
          <SelectField label={copy.ledger.type} value={filters.type ?? ''} onChange={choose('type')} className='sm:w-44'>
            <option value=''>{copy.ledger.all}</option>
            {KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {copy.kindNames[kind]}
              </option>
            ))}
          </SelectField>
          <SelectField label={copy.ledger.link} value={filters.attribution ?? ''} onChange={choose('attribution')} className='sm:w-52'>
            <option value=''>{copy.ledger.all}</option>
            <option value='associated'>{copy.ledger.associated}</option>
            <option value='not_associated'>{copy.ledger.notAssociated}</option>
          </SelectField>
          <SelectField label={copy.ledger.status} value={filters.status ?? ''} onChange={choose('status')} className='sm:w-40'>
            <option value=''>{copy.ledger.all}</option>
            <option value='active'>{copy.ledger.active}</option>
            <option value='reversed'>{copy.ledger.reversed}</option>
          </SelectField>
        </div>
        {canEdit && (
          <Button variant='action' size='control' onClick={() => setEditing('new')}>
            <Icons.add /> {copy.ledger.record}
          </Button>
        )}
      </div>
      {!canEdit && pages.length > 0 && <p className='text-muted-foreground text-xs'>{copy.ledger.viewOnly}</p>}
      {ledger.isPending ? (
        <StateMessage kind='loading' layout='inline' title={copy.ledger.loading} />
      ) : ledger.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.ledger.error}
          description={errorMessage(ledger.error)}
          action={
            <Button variant='glass' onClick={() => void ledger.refetch()}>
              <Icons.refresh /> {copy.retry}
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title={filtered ? copy.ledger.emptyFiltered : copy.ledger.empty} description={filtered ? undefined : copy.ledger.emptyDescription} />
      ) : (
        <ul className='flex flex-col gap-2' aria-label={copy.tabs.ledger}>
          {items.map((item) => (
            <LedgerRow key={item.id} item={item} copy={copy} locale={locale} canEdit={canEdit} onEdit={() => setEditing(item)} onReverse={() => setReversing(item)} />
          ))}
        </ul>
      )}
      {ledger.hasNextPage && (
        <Button variant='glass' className='self-start' onClick={() => void ledger.fetchNextPage()} disabled={ledger.isFetchingNextPage} aria-busy={ledger.isFetchingNextPage || undefined}>
          {copy.loadMore}
        </Button>
      )}
      <RafiiDialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <RafiiDialogContent size='sm'>
          {editing !== null && <ResultForm key={editing === 'new' ? 'new' : editing.id} item={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />}
        </RafiiDialogContent>
      </RafiiDialog>
      <RafiiDialog open={reversing !== null} onOpenChange={(open) => !open && setReversing(null)}>
        <RafiiDialogContent size='sm'>{reversing && <ReverseForm key={reversing.id} item={reversing} onDone={() => setReversing(null)} />}</RafiiDialogContent>
      </RafiiDialog>
    </>
  );
}

function LedgerRow({ item, copy, locale, canEdit, onEdit, onReverse }: { item: ResultItem; copy: ResultsCopy; locale: string; canEdit: boolean; onEdit: () => void; onReverse: () => void }) {
  const withdrawn = item.status === 'reversed';
  const details = [
    `${copy.item.occurred} ${formatDateTime(item.occurredAt)}`,
    item.lagSeconds !== null && item.lagSeconds >= 60 ? copy.item.lag(duration(item.lagSeconds, copy)) : '',
    copy.attribution[item.attribution] + (item.link ? ` (${item.link.label})` : ''),
    item.campaignRef ? `${copy.item.campaign}: ${item.campaignRef}` : '',
    item.connection ? copy.item.via(item.connection.label) : ''
  ].filter(Boolean);
  return (
    <li className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4 sm:flex-row sm:items-start sm:justify-between'>
      <div className='flex min-w-0 flex-col gap-1.5'>
        <div className='flex flex-wrap items-center gap-2'>
          <span className={cn('text-foreground text-sm font-medium', withdrawn && 'line-through decoration-1')}>
            {copy.kindNames[item.type]}
            {item.quantity > 1 ? ` ${copy.item.quantity(item.quantity)}` : ''}
          </span>
          {item.amount && <span className={cn('text-foreground text-sm tabular-nums', withdrawn && 'line-through decoration-1')}>{formatMoney(item.amount.minor, item.amount.currency, locale)}</span>}
          <StatusChip icon={null}>{copy.classes[item.provenance]}</StatusChip>
          {withdrawn && <StatusChip status='warning'>{copy.item.reversed}</StatusChip>}
          {item.amended && <StatusChip icon={null}>{copy.item.edited}</StatusChip>}
          {item.test && <StatusChip icon={null}>{copy.item.test}</StatusChip>}
        </div>
        <p className='text-muted-foreground text-xs leading-relaxed text-pretty'>{details.join(' · ')}</p>
        {item.note && <p className='text-foreground text-sm break-words whitespace-pre-wrap'>{item.note}</p>}
      </div>
      {canEdit && item.editable && (
        <div className='flex shrink-0 flex-wrap gap-2'>
          <Button variant='glass' onClick={onEdit}>
            <Icons.edit /> {copy.item.edit}
          </Button>
          <Button variant='quiet' onClick={onReverse}>
            {copy.item.reverse}
          </Button>
        </div>
      )}
    </li>
  );
}

function initialForm(item: ResultItem | null): DeclarationForm {
  if (!item) return { type: 'lead', occurredAt: isoToLocal(Date.now() / 1000), amount: '', currency: '', quantity: '1', note: '', linkId: '', campaignRef: '' };
  return {
    type: item.type === 'click' ? 'lead' : item.type,
    occurredAt: isoToLocal(item.occurredAt),
    amount: item.amount ? amountText(item.amount.minor, item.amount.currency) : '',
    currency: item.amount ? item.amount.currency.toUpperCase() : '',
    quantity: String(item.quantity),
    note: item.note ?? '',
    linkId: item.linkId ?? '',
    campaignRef: item.campaignRef ?? ''
  };
}

/** Declare (new) or amend (an existing declaration, as a new version at the revision the person saw). */
function ResultForm({ item, onDone }: { item: ResultItem | null; onDone: () => void }) {
  const { copy } = useResultsCopy();
  const id = useId();
  const declare = useDeclareResult();
  const amend = useAmendResult();
  const links = useTrackingLinks();
  const linkChoices = (links.data?.pages ?? []).flatMap((page) => page.items).filter((link) => link.status === 'active' || link.id === item?.linkId);
  const [form, setForm] = useState<DeclarationForm>(() => initialForm(item));
  const [problem, setProblem] = useState<{ field?: keyof DeclarationForm; message: string } | null>(null);
  // One key per intent: a retry after a lost answer replays instead of recording the result twice.
  const intent = useRef(idempotencyKey(item ? 'result-amend' : 'result-declare'));
  const busy = declare.isPending || amend.isPending;
  const money = form.type === 'booking' || form.type === 'sale';
  const set = (field: keyof DeclarationForm) => (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const value = event.target.value;
    setForm((current) => ({ ...current, [field]: value }));
    setProblem(null);
  };
  const invalid = (field: keyof DeclarationForm) => (problem?.field === field ? { 'aria-invalid': true as const, 'aria-describedby': `${id}-problem` } : {});

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const checked = checkDeclaration(money ? form : { ...form, amount: '', currency: '' }, copy);
    if (!checked.ok) {
      setProblem({ field: checked.field, message: checked.message });
      return;
    }
    try {
      if (item) await amend.mutateAsync({ id: item.id, body: { ...checked.value, idempotencyKey: intent.current, expectedRevision: item.revision } });
      else await declare.mutateAsync({ ...checked.value, idempotencyKey: intent.current });
      onDone();
    } catch (error) {
      setProblem({ message: errorMessage(error) });
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className='flex min-h-0 flex-1 flex-col' noValidate>
      <RafiiDialogHeader title={item ? copy.form.amendTitle : copy.form.title} intro={copy.form.intro} closeLabel={copy.form.cancel} />
      <RafiiDialogBody className='flex flex-col gap-4'>
        <SelectField label={copy.form.type} value={form.type} onChange={set('type')}>
          {DECLARABLE.map((kind) => (
            <option key={kind} value={kind}>
              {copy.kindNames[kind]}
            </option>
          ))}
        </SelectField>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-when`}>{copy.form.occurredAt}</Label>
          <Input id={`${id}-when`} type='datetime-local' value={form.occurredAt} onChange={set('occurredAt')} className={FIELD_CLASS} required {...invalid('occurredAt')} />
        </div>
        {money && (
          <div className='grid grid-cols-[1fr_7rem] gap-3'>
            <div className='flex flex-col gap-2'>
              <Label htmlFor={`${id}-amount`}>{copy.form.amount}</Label>
              <Input id={`${id}-amount`} inputMode='decimal' autoComplete='off' value={form.amount} onChange={set('amount')} className={cn(FIELD_CLASS, 'tabular-nums')} {...invalid('amount')} />
            </div>
            <div className='flex flex-col gap-2'>
              <Label htmlFor={`${id}-currency`}>{copy.form.currency}</Label>
              <Input id={`${id}-currency`} maxLength={3} autoComplete='off' value={form.currency} onChange={set('currency')} className={cn(FIELD_CLASS, 'uppercase')} placeholder='USD' {...invalid('currency')} />
            </div>
          </div>
        )}
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-quantity`}>{copy.form.quantity}</Label>
          <Input id={`${id}-quantity`} type='number' min={1} max={1000} step={1} inputMode='numeric' value={form.quantity} onChange={set('quantity')} className={cn(FIELD_CLASS, 'w-32')} {...invalid('quantity')} />
        </div>
        <SelectField label={copy.form.link} value={form.linkId} onChange={set('linkId')}>
          <option value=''>{copy.form.noLink}</option>
          {linkChoices.map((link) => (
            <option key={link.id} value={link.id}>
              {link.label}
            </option>
          ))}
        </SelectField>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-campaign`}>{copy.form.campaign}</Label>
          <Input id={`${id}-campaign`} maxLength={80} autoComplete='off' value={form.campaignRef} onChange={set('campaignRef')} className={FIELD_CLASS} {...invalid('campaignRef')} />
        </div>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-note`}>{copy.form.note}</Label>
          <Textarea id={`${id}-note`} maxLength={500} rows={3} value={form.note} onChange={set('note')} className={TEXTAREA_CLASS} aria-describedby={`${id}-note-hint`} />
          <p id={`${id}-note-hint`} className='text-muted-foreground text-xs'>
            {copy.form.noteHint}
          </p>
        </div>
        {problem && (
          <p id={`${id}-problem`} role='alert' className='text-destructive text-sm'>
            {problem.message}
          </p>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row justify-end'>
        <RafiiDialogClose render={<Button type='button' variant='quiet' size='control' disabled={busy} />}>{copy.form.cancel}</RafiiDialogClose>
        <Button type='submit' variant='action' size='control' disabled={busy} aria-busy={busy || undefined}>
          {busy ? copy.form.saving : item ? copy.form.saveEdit : copy.form.save}
        </Button>
      </RafiiDialogFooter>
    </form>
  );
}

function ReverseForm({ item, onDone }: { item: ResultItem; onDone: () => void }) {
  const { copy } = useResultsCopy();
  const id = useId();
  const reverse = useReverseResult();
  const [note, setNote] = useState('');
  const [problem, setProblem] = useState('');
  const intent = useRef(idempotencyKey('result-reverse'));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem('');
    try {
      await reverse.mutateAsync({ id: item.id, body: { idempotencyKey: intent.current, expectedRevision: item.revision, note: note.trim() || null } });
      onDone();
    } catch (error) {
      setProblem(errorMessage(error));
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className='flex min-h-0 flex-1 flex-col'>
      <RafiiDialogHeader title={copy.reverse.title} intro={copy.reverse.intro} closeLabel={copy.form.cancel} />
      <RafiiDialogBody className='flex flex-col gap-2'>
        <Label htmlFor={`${id}-why`}>{copy.reverse.reason}</Label>
        <Textarea id={`${id}-why`} maxLength={500} rows={2} value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA_CLASS} />
        {problem && (
          <p role='alert' className='text-destructive text-sm'>
            {problem}
          </p>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row justify-end'>
        <RafiiDialogClose render={<Button type='button' variant='quiet' size='control' disabled={reverse.isPending} />}>{copy.form.cancel}</RafiiDialogClose>
        <Button type='submit' variant='destructive' size='control' disabled={reverse.isPending} aria-busy={reverse.isPending || undefined}>
          {reverse.isPending ? copy.reverse.working : copy.reverse.confirm}
        </Button>
      </RafiiDialogFooter>
    </form>
  );
}
