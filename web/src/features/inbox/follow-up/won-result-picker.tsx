'use client';

/**
 * "Won" needs a result the person declared (R-REL: Rafii never decides that someone bought). The picker lists the
 * person's own current declarations from Business results (never a reversed one, never test traffic), and when the
 * right one is not there it records it in place (saved as "You reported", exactly like Growth → Results) and selects
 * it. Nothing is guessed or pre-selected. Focus moves into the picker when it opens; Escape cancels.
 */
import { useId, useRef, useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { checkDeclaration, formatMoney, isoToLocal, localToIso, type DeclarationForm } from '@/features/growth/results/present';
import { useResultsCopy } from '@/features/growth/results/use-results-copy';
import { errorMessage, idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { pickableResults } from '@/lib/growth-v2/relationships-model';
import { useDeclareResult, useResultsLedger } from '@/lib/growth-v2/results-hooks';
import type { ResultItem } from '@/lib/growth-v2/results-types';
import { formatDateTime, timeDefaults } from '@/lib/time';
import { currentCopy, currentLang } from './copy';
import { usePanelFocus } from './focus';

const DECLARED = { provenance: 'user_declared', status: 'active' } as const;
const TYPES: DeclarationForm['type'][] = ['booking', 'sale', 'lead', 'newsletter_signup'];

/** A new declaration's form, its time in the person's saved zone (the zone Business results lists it in). */
const blank = (zone: string | undefined): DeclarationForm => ({
  type: 'booking',
  occurredAt: isoToLocal(Date.now() / 1000, zone),
  amount: '',
  currency: '',
  quantity: '1',
  note: '',
  linkId: '',
  campaignRef: ''
});

export function WonResultPicker({ busy, onConfirm, onCancel }: { busy: boolean; onConfirm: (resultId: string) => void; onCancel: () => void }) {
  const copy = currentCopy();
  const lang = currentLang();
  const { copy: results, locale } = useResultsCopy();
  const id = useId();
  const zone = timeDefaults().timeZone;
  const ledger = useResultsLedger(DECLARED);
  const declare = useDeclareResult();
  const key = useRef('');
  const panel = usePanelFocus<HTMLDivElement>(onCancel);
  const [picked, setPicked] = useState('');
  const [recorded, setRecorded] = useState('');
  const [recording, setRecording] = useState(false);
  const [form, setForm] = useState<DeclarationForm>(() => blank(zone));
  const [problem, setProblem] = useState<{ message: string; lang: string } | null>(null);
  const items = pickableResults(ledger.data?.pages.flatMap((page) => page.items) ?? []);

  function describe(item: ResultItem): string {
    const [one, many] = results.kinds[item.type];
    const kind = item.quantity === 1 ? one : `${item.quantity} ${many}`;
    const parts = [kind.charAt(0).toUpperCase() + kind.slice(1), formatDateTime(item.occurredAt)];
    if (item.amount) parts.push(formatMoney(item.amount.minor, item.amount.currency, locale));
    return item.note ? `${parts.join(' · ')} — ${item.note}` : parts.join(' · ');
  }

  async function record() {
    setProblem(null);
    const check = checkDeclaration(form, results, (local) => localToIso(local, zone));
    if (!check.ok) {
      setProblem({ message: check.message, lang });
      return;
    }
    key.current ||= idempotencyKey('won-result');
    try {
      const saved = await declare.mutateAsync({ ...check.value, idempotencyKey: key.current });
      key.current = '';
      setRecorded(saved.result.id);
      setPicked(saved.result.id);
      setRecording(false);
      setForm(blank(zone));
    } catch (error) {
      setProblem({ message: errorMessage(error), lang: 'en' }); // the server's own words
    }
  }

  if (ledger.isError && isFeatureDisabled(ledger.error)) {
    return (
      <div ref={panel} lang={lang} className='flex flex-col gap-2'>
        <StateMessage kind='unsupported' layout='inline' title={copy.wonUnavailable} />
        <Button type='button' variant='quiet' size='sm' className='h-9 self-start' onClick={onCancel}>{copy.cancel}</Button>
      </div>
    );
  }

  const amountAllowed = form.type === 'booking' || form.type === 'sale';
  // Confirm only a result that is still listed as current (or the one just recorded here, before the list refreshes).
  const confirmable = Boolean(picked) && (picked === recorded || items.some((item) => item.id === picked));
  return (
    <div ref={panel} lang={lang} role='group' aria-label={copy.wonTitle} className='flex flex-col gap-3'>
      <p className='text-muted-foreground text-xs leading-relaxed'>{copy.wonHint}</p>
      <fieldset className='flex flex-col gap-2' disabled={busy || declare.isPending}>
        <legend className='mb-1 text-sm font-medium'>{copy.wonPick}</legend>
        {ledger.isPending && <StateMessage kind='loading' layout='inline' title={copy.wonLoading} />}
        {ledger.isError && !isFeatureDisabled(ledger.error) && <p role='alert' lang='en' className='text-destructive text-sm'>{errorMessage(ledger.error)}</p>}
        {ledger.isSuccess && items.length === 0 && <p className='text-muted-foreground text-sm'>{copy.wonNone}</p>}
        {items.map((item) => (
          <label key={item.id} className='flex min-h-9 items-start gap-2 text-sm'>
            <input type='radio' name={`${id}-won`} aria-label={describe(item)} value={item.id} checked={picked === item.id} onChange={() => setPicked(item.id)} className='mt-1' />
            <span>{describe(item)}</span>
          </label>
        ))}
        {ledger.hasNextPage && (
          <Button type='button' variant='quiet' size='sm' className='h-9 self-start' disabled={ledger.isFetchingNextPage} onClick={() => void ledger.fetchNextPage()}>
            {copy.wonMore}
          </Button>
        )}
      </fieldset>

      {recording ? (
        <form
          className='flex flex-col gap-2 rounded-xl border border-(--rafii-border-subtle) p-3'
          onSubmit={(event) => {
            event.preventDefault();
            void record();
          }}
        >
          <p className='text-sm font-medium'>{results.form.title}</p>
          <p className='text-muted-foreground text-xs'>{results.form.intro}</p>
          <Label htmlFor={`${id}-type`}>{results.form.type}</Label>
          <NativeSelect id={`${id}-type`} size='sm' value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value as DeclarationForm['type'], amount: '', currency: '' })}>
            {TYPES.map((type) => (
              <NativeSelectOption key={type} value={type}>{results.kinds[type][0]}</NativeSelectOption>
            ))}
          </NativeSelect>
          <Label htmlFor={`${id}-when`}>{results.form.occurredAt}</Label>
          <Input id={`${id}-when`} type='datetime-local' required value={form.occurredAt} aria-describedby={`${id}-zone`} onChange={(event) => setForm({ ...form, occurredAt: event.target.value })} />
          <p id={`${id}-zone`} className='text-muted-foreground text-xs'>{results.form.zone(zone ?? Intl.DateTimeFormat().resolvedOptions().timeZone)}</p>
          {amountAllowed && (
            <div className='flex flex-wrap gap-2'>
              <div className='flex min-w-0 flex-1 flex-col gap-1'>
                <Label htmlFor={`${id}-amount`}>{results.form.amount}</Label>
                <Input id={`${id}-amount`} inputMode='decimal' autoComplete='off' value={form.amount} onChange={(event) => setForm({ ...form, amount: event.target.value })} />
              </div>
              <div className='flex w-24 flex-col gap-1'>
                <Label htmlFor={`${id}-currency`}>{results.form.currency}</Label>
                <Input id={`${id}-currency`} maxLength={3} autoComplete='off' placeholder='USD' value={form.currency} onChange={(event) => setForm({ ...form, currency: event.target.value })} />
              </div>
            </div>
          )}
          <div className='flex flex-wrap gap-2'>
            <Button type='submit' variant='glass' size='sm' className='h-9' disabled={declare.isPending}>{declare.isPending ? results.form.saving : copy.wonRecordAndSelect}</Button>
            <Button type='button' variant='quiet' size='sm' className='h-9' onClick={() => { setRecording(false); setProblem(null); }}>{results.form.cancel}</Button>
          </div>
        </form>
      ) : (
        <Button type='button' variant='quiet' size='sm' className='h-9 self-start' disabled={busy} onClick={() => setRecording(true)}>
          {results.form.title}
        </Button>
      )}

      {problem && <p role='alert' lang={problem.lang} className='text-destructive text-sm'>{problem.message}</p>}
      <div className='flex gap-2'>
        <Button type='button' variant='glass' size='sm' className='h-9' disabled={busy || !confirmable} onClick={() => onConfirm(picked)}>{copy.confirm}</Button>
        <Button type='button' variant='quiet' size='sm' className='h-9' onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </div>
  );
}
