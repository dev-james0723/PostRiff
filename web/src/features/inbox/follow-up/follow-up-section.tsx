'use client';

import { parseAsString, useQueryState } from 'nuqs';
import { useId, useState } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { Thread } from '@/lib/api/types';
import type { RelationshipDetail } from '@/lib/growth-v2/relationships-types';
import { errorCode, errorMessage, idempotencyKey } from '@/lib/growth-v2/request';
import { followUpsOff, useRelationshipChange, useRelationshipList } from '@/lib/growth-v2/relationships-hooks';
import { browserZone, dueInput, isConflict, zoneChoices } from '@/lib/growth-v2/relationships-model';
import { timeDefaults } from '@/lib/time';
import { currentCopy } from './copy';
import { DueFields, FollowUpCard } from './follow-up-card';

/**
 * "Follow up" inside an open conversation: the follow-ups linked to it, or a way to start one (or add this
 * conversation to an existing one). Hidden when the deployment has follow-ups off. Starting a follow-up never
 * contacts anyone; replying stays the composer below.
 */
export function FollowUpSection({ thread, canEdit }: { thread: Thread; canEdit: boolean }) {
  const copy = currentCopy();
  const linked = useRelationshipList({ thread: thread.threadId, state: 'all', limit: 5 });
  const [focusId] = useQueryState('relationship', parseAsString);
  const [mode, setMode] = useState<'idle' | 'create' | 'existing'>('idle');
  const [createdId, setCreatedId] = useState<string | null>(null);
  const items = linked.data?.relationships ?? [];
  const target = createdId ?? focusId;

  if (followUpsOff(linked)) return null;
  if (thread.tombstoned && items.length === 0) return null;

  return (
    <section aria-label={copy.section} className='flex flex-col gap-2' data-tour='inbox-follow-up'>
      <h3 className='text-muted-foreground text-xs font-medium'>{copy.section}</h3>
      {linked.isPending ? (
        <StateMessage kind='loading' layout='inline' title={copy.loading} />
      ) : linked.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={errorMessage(linked.error, copy.failed)}
          action={<Button variant='glass' size='sm' className='h-9' onClick={() => void linked.refetch()}>{copy.reload}</Button>}
        />
      ) : items.length > 0 ? (
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
            <Button variant='glass' size='control' onClick={() => setMode('create')}>
              <Icons.add className='size-4' aria-hidden />
              {copy.track}
            </Button>
            <Button variant='quiet' size='control' onClick={() => setMode('existing')}>{copy.link}</Button>
          </div>
          <p className='text-muted-foreground text-xs leading-relaxed'>{copy.trackHint}</p>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Start a follow-up, from this conversation or on its own (a name is then required). One idempotency key per form, so a
 * retried submit makes one record.
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
  const change = useRelationshipChange();
  const id = useId();
  const zone = timeDefaults().timeZone ?? browserZone();
  const [key] = useState(() => idempotencyKey('rel-create'));
  const [name, setName] = useState(thread?.author ? `@${thread.author.replace(/^@/, '')}` : '');
  const [interest, setInterest] = useState('');
  const [nextAction, setNextAction] = useState('');
  const [local, setLocal] = useState('');
  const [timeZone, setTimeZone] = useState(zone);
  const [askFold, setAskFold] = useState(false);
  const [fold, setFold] = useState<0 | 1>(0);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit() {
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
          due: dueInput(local, timeZone, askFold ? fold : undefined)
        })
      );
      onCreated(result.relationship);
    } catch (cause) {
      const code = errorCode(cause);
      if (code === 'due_time_ambiguous') setAskFold(true);
      setProblem(isConflict(code) ? copy.conflict : errorMessage(cause, copy.failed));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
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
        onLocal={(value) => { setLocal(value); setAskFold(false); }}
        onZone={(value) => { setTimeZone(value); setAskFold(false); }}
        onFold={setFold}
        onClear={() => { setLocal(''); setAskFold(false); }}
      />
      <p className='text-muted-foreground text-xs leading-relaxed'>{copy.remindersNote}</p>
      {problem && <p role='alert' className='text-destructive text-sm'>{problem}</p>}
      <div className='flex gap-2'>
        <Button type='submit' variant='glass' size='control' disabled={saving || (!thread && !name.trim())}>{saving ? copy.creating : copy.create}</Button>
        <Button type='button' variant='quiet' size='control' disabled={saving} onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/** Add this conversation to a follow-up that already exists (same workspace; the server refuses anything else). */
function AddToExisting({ thread, onDone, onCancel }: { thread: Thread; onDone: (id: string) => void; onCancel: () => void }) {
  const copy = currentCopy();
  const open = useRelationshipList({ state: 'open', limit: 50 });
  const change = useRelationshipChange();
  const id = useId();
  const [choice, setChoice] = useState('');
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
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
      setProblem(isConflict(errorCode(cause)) ? copy.conflict : errorMessage(cause, copy.failed));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3.5'>
      {open.isPending ? (
        <StateMessage kind='loading' layout='inline' title={copy.loading} />
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
      {problem && <p role='alert' className='text-destructive text-sm'>{problem}</p>}
      <div className='flex gap-2'>
        <Button variant='glass' size='control' disabled={saving || !chosen} onClick={() => void link()}>{copy.link}</Button>
        <Button variant='quiet' size='control' disabled={saving} onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </div>
  );
}
