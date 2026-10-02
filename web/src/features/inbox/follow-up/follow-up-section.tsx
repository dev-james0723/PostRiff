'use client';

import { parseAsString, useQueryState } from 'nuqs';
import { useId, useRef, useState } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { Thread } from '@/lib/api/types';
import type { RelationshipDetail } from '@/lib/growth-v2/relationships-types';
import { errorCode, idempotencyKey } from '@/lib/growth-v2/request';
import { followUpsOff, useRelationshipChange, useRelationshipList, useRelationshipRefresh } from '@/lib/growth-v2/relationships-hooks';
import { browserZone, canonicalId, dueInput, zoneChoices } from '@/lib/growth-v2/relationships-model';
import { timeDefaults } from '@/lib/time';
import { currentCopy, currentLang, describeProblem, type FollowUpProblem } from './copy';
import { DueFields, FollowUpCard } from './follow-up-card';
import { usePanelFocus, useReturnFocus } from './focus';

/**
 * "Follow up" inside an open conversation: the follow-ups linked to it, or a way to start one (or add this
 * conversation to an existing one). Hidden when the deployment has follow-ups off. Starting a follow-up never
 * contacts anyone; replying stays the composer below.
 */
export function FollowUpSection({ thread, canEdit }: { thread: Thread; canEdit: boolean }) {
  const copy = currentCopy();
  const lang = currentLang();
  const linked = useRelationshipList({ thread: thread.threadId, state: 'all', limit: 5 });
  const [focusId] = useQueryState('relationship', parseAsString);
  const [mode, setMode] = useState<'idle' | 'create' | 'existing'>('idle');
  const [createdId, setCreatedId] = useState<string | null>(null);
  const trackButton = useRef<HTMLButtonElement>(null);
  const linkButton = useRef<HTMLButtonElement>(null);
  useReturnFocus(mode === 'create', trackButton);
  useReturnFocus(mode === 'existing', linkButton);
  const items = linked.data?.relationships ?? [];
  const target = createdId ?? canonicalId(focusId);

  if (followUpsOff(linked)) return null;
  // Nothing to show: no follow-up yet and this person can't start one (or the comment is gone).
  if (linked.isSuccess && items.length === 0 && (thread.tombstoned || !canEdit)) return null;

  return (
    <section lang={lang} aria-label={copy.section} className='flex flex-col gap-2' data-tour='inbox-follow-up'>
      <h3 className='text-muted-foreground text-xs font-medium'>{copy.section}</h3>
      {linked.isPending ? (
        <StateMessage kind='loading' layout='inline' title={copy.loading} />
      ) : !linked.data ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.listFailed}
          action={<Button variant='glass' size='sm' className='h-9' onClick={() => void linked.refetch()}>{copy.reload}</Button>}
        />
      ) : (
        <>
          {/* A failed refresh keeps what was loaded (and anything typed below), with a notice. */}
          {linked.isError && (
            <p role='status' className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
              {copy.staleNotice}
              <Button variant='quiet' size='sm' className='h-9' onClick={() => void linked.refetch()}>{copy.reload}</Button>
            </p>
          )}
          {items.length > 0 ? (
            items.map((item) => (
              <FollowUpCard key={item.id} relationshipId={item.id} threadId={thread.threadId} canEdit={canEdit} focusOnLoad={item.id === target} />
            ))
          ) : mode === 'create' ? (
            <FollowUpCreate thread={thread} onCreated={(created) => { setMode('idle'); setCreatedId(created.id); }} onCancel={() => setMode('idle')} />
          ) : mode === 'existing' ? (
            <AddToExisting thread={thread} onDone={(id) => { setMode('idle'); setCreatedId(id); }} onCancel={() => setMode('idle')} />
          ) : canEdit ? (
            <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2.5'>
              <div className='flex flex-wrap gap-2'>
                <Button ref={trackButton} variant='glass' size='control' onClick={() => setMode('create')}>
                  <Icons.add className='size-4' aria-hidden />
                  {copy.track}
                </Button>
                <Button ref={linkButton} variant='quiet' size='control' onClick={() => setMode('existing')}>{copy.link}</Button>
              </div>
              <p className='text-muted-foreground text-xs leading-relaxed'>{copy.trackHint}</p>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * Start a follow-up, from this conversation or on its own (a name is then required). One idempotency key per form, so a
 * retried submit makes one record. Focus moves to the first field when it opens; Escape cancels.
 */
export function FollowUpCreate({
  thread = null,
  onCreated,
  onCancel
}: {
  thread?: Thread | null;
  onCreated: (created: RelationshipDetail) => void;
  onCancel: () => void;
}) {
  const copy = currentCopy();
  const lang = currentLang();
  const change = useRelationshipChange();
  const refresh = useRelationshipRefresh();
  const id = useId();
  const panel = usePanelFocus<HTMLFormElement>(onCancel);
  const zone = timeDefaults().timeZone ?? browserZone();
  const [key] = useState(() => idempotencyKey('rel-create'));
  const [name, setName] = useState(thread?.author ? `@${thread.author.replace(/^@/, '')}` : '');
  const [interest, setInterest] = useState('');
  const [nextAction, setNextAction] = useState('');
  const [local, setLocal] = useState('');
  const [timeZone, setTimeZone] = useState(zone);
  const [askFold, setAskFold] = useState(false);
  const [fold, setFold] = useState<0 | 1 | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<FollowUpProblem | null>(null);

  async function submit() {
    if (askFold && fold === null) {
      setProblem({ message: copy.chooseOccurrence, conflict: false, lang });
      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      const result = await change((api, w) =>
        api.create(w, {
          idempotencyKey: key,
          ...(thread ? { threadId: thread.threadId } : {}),
          displayName: name.trim() || undefined,
          interest: interest.trim() || undefined,
          nextAction: nextAction.trim() || undefined,
          due: dueInput(local, timeZone, askFold && fold !== null ? fold : undefined)
        })
      );
      onCreated(result.relationship);
    } catch (cause) {
      if (errorCode(cause) === 'due_time_ambiguous') {
        setAskFold(true);
        setFold(null);
      }
      setProblem(describeProblem(cause, copy));
    } finally {
      setSaving(false);
    }
  }

  const resetFold = () => {
    setAskFold(false);
    setFold(null);
  };

  return (
    <form
      ref={panel}
      lang={lang}
      className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-3.5'
      aria-label={copy.track}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-name`}>{copy.name}</Label>
        <Input id={`${id}-name`} value={name} maxLength={120} required={!thread} onChange={(event) => setName(event.target.value)} />
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-interest`}>{copy.interest}</Label>
        <Input id={`${id}-interest`} value={interest} maxLength={300} onChange={(event) => setInterest(event.target.value)} />
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-next`}>{copy.nextAction}</Label>
        <Input id={`${id}-next`} value={nextAction} maxLength={200} onChange={(event) => setNextAction(event.target.value)} />
      </div>
      <DueFields
        id={id}
        local={local}
        timeZone={timeZone}
        zones={zoneChoices(zone, browserZone())}
        askFold={askFold}
        fold={fold}
        onLocal={(value) => { setLocal(value); resetFold(); }}
        onZone={(value) => { setTimeZone(value); resetFold(); }}
        onFold={setFold}
        onClear={() => { setLocal(''); resetFold(); }}
      />
      <p className='text-muted-foreground text-xs leading-relaxed'>{copy.remindersNote}</p>
      {problem && (
        <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-sm'>
          <span lang={problem.lang}>{problem.message}</span>
          {/* A conflict here means this request was already used (e.g. an earlier submit did go through): reload to see it. */}
          {problem.conflict && (
            <Button type='button' variant='quiet' size='sm' className='h-9' onClick={() => { setProblem(null); void refresh(); }}>{copy.reload}</Button>
          )}
        </p>
      )}
      <div className='flex gap-2'>
        <Button type='submit' variant='glass' size='control' disabled={saving || (!thread && !name.trim()) || (askFold && fold === null)}>{saving ? copy.creating : copy.create}</Button>
        <Button type='button' variant='quiet' size='control' disabled={saving} onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/**
 * Add this conversation to a follow-up that already exists (same workspace; the server refuses anything else). A list
 * that couldn't load says so (never "no follow-ups"); a conflict offers a reload.
 */
function AddToExisting({ thread, onDone, onCancel }: { thread: Thread; onDone: (id: string) => void; onCancel: () => void }) {
  const copy = currentCopy();
  const open = useRelationshipList({ state: 'open', limit: 50 });
  const change = useRelationshipChange();
  const id = useId();
  const panel = usePanelFocus<HTMLFormElement>(onCancel);
  const [choice, setChoice] = useState('');
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<FollowUpProblem | null>(null);
  const candidates = (open.data?.relationships ?? []).filter((item) => !item.threadIds.includes(thread.threadId));
  const chosen = candidates.find((item) => item.id === choice);

  async function link() {
    if (!chosen) return;
    setSaving(true);
    setProblem(null);
    try {
      const result = await change((api, w) => api.linkThread(w, chosen.id, chosen.revision, thread.threadId));
      onDone(result.relationship.id);
    } catch (cause) {
      setProblem(describeProblem(cause, copy));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      ref={panel}
      className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3.5'
      aria-label={copy.link}
      onSubmit={(event) => {
        event.preventDefault();
        void link();
      }}
    >
      {open.isPending ? (
        <StateMessage kind='loading' layout='inline' title={copy.loading} />
      ) : !open.data ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.listFailed}
          action={<Button type='button' variant='glass' size='sm' className='h-9' onClick={() => void open.refetch()}>{copy.reload}</Button>}
        />
      ) : candidates.length === 0 ? (
        <p className='text-muted-foreground text-sm'>{copy.empty}</p>
      ) : (
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-existing`}>{copy.link}</Label>
          <NativeSelect id={`${id}-existing`} value={choice} onChange={(event) => setChoice(event.target.value)}>
            <NativeSelectOption value=''>—</NativeSelectOption>
            {candidates.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.displayName}</NativeSelectOption>)}
          </NativeSelect>
        </div>
      )}
      {problem && (
        <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-sm'>
          <span lang={problem.lang}>{problem.message}</span>
          {problem.conflict && (
            <Button type='button' variant='quiet' size='sm' className='h-9' onClick={() => { setProblem(null); setChoice(''); void open.refetch(); }}>{copy.reload}</Button>
          )}
        </p>
      )}
      <div className='flex gap-2'>
        <Button type='submit' variant='glass' size='control' disabled={saving || !chosen}>{copy.link}</Button>
        <Button type='button' variant='quiet' size='control' disabled={saving} onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}
