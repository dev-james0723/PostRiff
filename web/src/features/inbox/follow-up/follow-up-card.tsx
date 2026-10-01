'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { useMembers } from '@/lib/api/hooks';
import { errorCode, errorMessage } from '@/lib/growth-v2/request';
import type { RelationshipsApi } from '@/lib/growth-v2/relationships';
import { useRelationship, useRelationshipChange, useRelationshipRefresh } from '@/lib/growth-v2/relationships-hooks';
import {
  browserZone,
  dueInput,
  followUpHref,
  followUpLine,
  isConflict,
  nextStates,
  platformName,
  replyRouteView,
  snoozeChoices,
  stateTone,
  zoneChoices
} from '@/lib/growth-v2/relationships-model';
import type { RelationshipDetail, RelationshipEditInput, RelationshipState, RelationshipWrite } from '@/lib/growth-v2/relationships-types';
import { relativeTime, timeDefaults } from '@/lib/time';
import { cn } from '@/lib/utils';
import { currentCopy, focusComposer, when } from './copy';
import { WonResultPicker } from './won-result-picker';

type Run = (api: RelationshipsApi, w: string) => Promise<RelationshipWrite>;

const NOTE_LIMIT = 500;

/**
 * One follow-up, editable in place: stage, reminder, owner, next step, due time in its zone, notes, linked
 * conversations and history. Every change sends the revision this card shows; a conflict asks to reload instead of
 * overwriting. Snooze, close and "not relevant" offer Undo. Replying is the Inbox composer (exact approval) or, on a
 * platform Rafii can't reply on, an honest "Open on …" link — never a direct success.
 */
export function FollowUpCard({
  relationshipId,
  threadId,
  canEdit,
  focusOnLoad = false
}: {
  relationshipId: string;
  /** The conversation open beside this card, when its composer is on the page. */
  threadId?: string | null;
  canEdit: boolean;
  /** Move keyboard focus to this card's heading once it has loaded (just started, or opened from a link). */
  focusOnLoad?: boolean;
}) {
  const copy = currentCopy();
  const query = useRelationship(relationshipId);
  const change = useRelationshipChange();
  const refresh = useRelationshipRefresh();
  const members = useMembers();
  const headingId = useId();
  const [pending, setPending] = useState<string | null>(null);
  const [problem, setProblem] = useState<{ message: string; conflict: boolean } | null>(null);
  const [editing, setEditing] = useState(false);
  const [snoozing, setSnoozing] = useState(false);
  const [winning, setWinning] = useState(false);
  const [note, setNote] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const focused = useRef(false);
  const loaded = Boolean(query.data);

  useEffect(() => {
    if (!focusOnLoad || !loaded || focused.current) return;
    focused.current = true;
    heading.current?.focus();
  }, [focusOnLoad, loaded]);

  if (query.isPending) return <StateMessage kind='loading' layout='inline' title={copy.loading} />;
  if (query.isError || !query.data) {
    return (
      <StateMessage
        kind='error'
        layout='inline'
        title={errorMessage(query.error, copy.failed)}
        action={<Button variant='glass' size='sm' className='h-9' onClick={() => void query.refetch()}>{copy.reload}</Button>}
      />
    );
  }
  const rel: RelationshipDetail = query.data.relationship;
  const busy = pending !== null;
  const zone = timeDefaults().timeZone ?? browserZone();
  const thread = rel.threads.find((item) => item.threadId === threadId) ?? rel.threads[0] ?? null;
  const route = replyRouteView(thread?.replyRoute ?? rel.replyRoute, copy);
  const activeMembers = (members.data?.members ?? []).filter((member) => member.status === 'active');
  const terminal = rel.state === 'won' || rel.state === 'closed';

  async function run(label: string, task: Run, after?: (result: RelationshipWrite) => void) {
    setPending(label);
    setProblem(null);
    try {
      const result = await change(task);
      after?.(result);
      return result;
    } catch (cause) {
      const code = errorCode(cause);
      setProblem({ message: isConflict(code) ? copy.conflict : errorMessage(cause, copy.failed), conflict: isConflict(code) });
      return null;
    } finally {
      setPending(null);
    }
  }

  function withUndo(message: string, undo: (revision: number) => Run) {
    return (result: RelationshipWrite) => {
      toast(message, { action: { label: copy.undo, onClick: () => void run('undo', undo(result.relationship.revision)) } });
    };
  }

  const snooze = (until: number) =>
    run('snooze', (api, w) => api.snooze(w, rel.id, rel.revision, until), (result) => {
      setSnoozing(false);
      withUndo(copy.snoozedToast, (revision) => (api, w) => api.unsnooze(w, rel.id, revision))(result);
    });
  const move = (target: RelationshipState) => {
    if (target === 'won') {
      setWinning(true);
      return;
    }
    void run('state', (api, w) => api.transition(w, rel.id, rel.revision, target),
      target === 'closed' ? withUndo(copy.closedToast, (revision) => (api, w) => api.reopen(w, rel.id, revision)) : undefined);
  };
  const dismissReminder = () =>
    run('dismiss', (api, w) => api.dismissFollowUp(w, rel.id, rel.revision),
      withUndo(copy.dismissedToast, (revision) => (api, w) => api.restoreFollowUp(w, rel.id, revision)));

  return (
    <section aria-labelledby={headingId} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-3.5' data-follow-up={rel.id}>
      <header className='flex flex-wrap items-center gap-2'>
        <h3 id={headingId} ref={heading} tabIndex={-1} className='rafii-focus text-foreground min-w-0 flex-1 truncate rounded-sm text-sm font-medium'>
          {rel.displayName}
        </h3>
        <AnimatedBadge size='sm' status={stateTone(rel.state)} showIcon={false} layout={false} contentKey={rel.state} className='rafii-glass border-0'>
          {copy.states[rel.state]}
        </AnimatedBadge>
      </header>

      <p className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm' aria-live='polite'>
        <Icons.clock className='size-4 shrink-0' aria-hidden />
        <span>{followUpLine(rel, copy, when)}</span>
        {canEdit && rel.followUp.status === 'due' && (
          <Button variant='quiet' size='sm' className='h-9' disabled={busy} onClick={() => void dismissReminder()}>
            {copy.notRelevant}
          </Button>
        )}
        {canEdit && rel.followUp.status === 'snoozed' && (
          <Button variant='quiet' size='sm' className='h-9' disabled={busy} onClick={() => void run('unsnooze', (api, w) => api.unsnooze(w, rel.id, rel.revision))}>
            {copy.unsnooze}
          </Button>
        )}
      </p>

      {rel.suggestion && canEdit && (
        <div className='rafii-glass flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
          <Icons.sparkles className='text-muted-foreground size-4 shrink-0' aria-hidden />
          <span className='min-w-0 flex-1'>
            {copy.suggested(copy.states[rel.suggestion.state])}
            <span className='text-muted-foreground'> · {copy.reasons[rel.suggestion.reason] ?? rel.suggestion.reason}</span>
          </span>
          <Button variant='glass' size='sm' className='h-9' disabled={busy}
            onClick={() => void run('state', (api, w) => api.transition(w, rel.id, rel.revision, rel.suggestion!.state, { suggestionKey: rel.suggestion!.key }))}>
            {copy.apply}
          </Button>
          <Button variant='quiet' size='sm' className='h-9' disabled={busy}
            onClick={() => void run('suggestion', (api, w) => api.dismissSuggestion(w, rel.id, rel.revision, rel.suggestion!.key))}>
            {copy.dismiss}
          </Button>
        </div>
      )}

      {editing ? (
        <FollowUpEditor
          rel={rel}
          zone={zone}
          onCancel={() => setEditing(false)}
          onSaved={() => setEditing(false)}
        />
      ) : (
        <dl className='grid gap-2 text-sm sm:grid-cols-[auto_minmax(0,1fr)] sm:gap-x-4'>
          {rel.interest && (<><dt className='text-muted-foreground'>{copy.interest}</dt><dd className='break-words'>{rel.interest}</dd></>)}
          {rel.nextAction && (<><dt className='text-muted-foreground'>{copy.nextAction}</dt><dd className='break-words'>{rel.nextAction}</dd></>)}
          <dt className='text-muted-foreground'>{copy.due}</dt>
          <dd>{rel.due ? `${when(rel.due.at, rel.due.timeZone)} (${rel.due.timeZone})` : copy.noDue}</dd>
          <dt className='text-muted-foreground'>{copy.owner}</dt>
          <dd>
            {canEdit ? (
              <NativeSelect
                size='sm'
                aria-label={copy.owner}
                value={rel.owner?.userId ?? ''}
                disabled={busy}
                onChange={(event) => void run('assign', (api, w) => api.assign(w, rel.id, rel.revision, event.target.value || null))}
              >
                <NativeSelectOption value=''>{copy.unassigned}</NativeSelectOption>
                {rel.owner && !rel.owner.active && <NativeSelectOption value={rel.owner.userId} disabled>{copy.formerMember}</NativeSelectOption>}
                {activeMembers.map((member) => (
                  <NativeSelectOption key={member.userId} value={member.userId}>{member.displayName || member.userId.slice(0, 8)}</NativeSelectOption>
                ))}
              </NativeSelect>
            ) : rel.owner ? (rel.owner.active ? rel.owner.displayName || rel.owner.userId.slice(0, 8) : copy.formerMember) : copy.unassigned}
          </dd>
        </dl>
      )}

      {/* The one reply action: the Inbox composer (exact approval) or an assisted link. */}
      <div className='flex flex-wrap items-center gap-2'>
        {route.kind === 'direct' && thread ? (
          threadId === thread.threadId ? (
            <Button variant='glass' size='control' onClick={() => focusComposer(thread.threadId)}>
              <Icons.send className='size-4' aria-hidden />
              {copy.reply}
            </Button>
          ) : (
            <Link href={followUpHref(rel.id, thread.threadId)} className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'gap-2')}>
              <Icons.send className='size-4' aria-hidden />
              {copy.reply}
            </Link>
          )
        ) : route.href ? (
          <a href={route.href} target='_blank' rel='noreferrer' className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'gap-2')}>
            {route.label}
            <Icons.externalLink className='size-4' aria-hidden />
          </a>
        ) : null}
        {canEdit && !editing && (
          <Button variant='quiet' size='control' disabled={busy} onClick={() => setEditing(true)}>
            <Icons.edit className='size-4' aria-hidden />
            {copy.edit}
          </Button>
        )}
      </div>
      <p className='text-muted-foreground text-xs leading-relaxed'>{route.kind === 'direct' ? copy.directHint : route.hint} {copy.remindersNote}</p>

      {canEdit && (
        <div className='flex flex-wrap items-center gap-2'>
          {terminal ? (
            <Button variant='glass' size='sm' className='h-9' disabled={busy} onClick={() => void run('reopen', (api, w) => api.reopen(w, rel.id, rel.revision))}>
              {copy.reopen}
            </Button>
          ) : (
            <>
              <NativeSelect size='sm' aria-label={copy.state} value='' disabled={busy} onChange={(event) => event.target.value && move(event.target.value as RelationshipState)}>
                <NativeSelectOption value=''>{copy.state}: {copy.states[rel.state]}</NativeSelectOption>
                {nextStates(rel.state).map((target) => (
                  <NativeSelectOption key={target} value={target}>{copy.states[target]}</NativeSelectOption>
                ))}
              </NativeSelect>
              <Button variant='quiet' size='sm' className='h-9' disabled={busy} aria-expanded={snoozing} onClick={() => setSnoozing((open) => !open)}>
                {copy.snooze}
              </Button>
            </>
          )}
        </div>
      )}
      {snoozing && !terminal && (
        <div role='group' aria-label={copy.snooze} className='flex flex-wrap gap-2'>
          {snoozeChoices(Date.now() / 1000, rel.due?.timeZone ?? zone, copy).map((choice) => (
            <Button key={choice.label} variant='glass' size='sm' className='h-9' disabled={busy} onClick={() => void snooze(choice.until)}>
              {choice.label}
            </Button>
          ))}
        </div>
      )}
      {winning && (
        <WonResultPicker
          busy={busy}
          onCancel={() => setWinning(false)}
          onConfirm={(resultId) => void run('won', (api, w) => api.transition(w, rel.id, rel.revision, 'won', { wonResultId: resultId }), () => setWinning(false))}
        />
      )}
      {rel.won && <p className='text-muted-foreground text-xs'>{copy.states.won} · {copy.provenance[rel.won.provenance ?? ''] ?? copy.provenance.unknown}</p>}

      {problem && (
        <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-sm'>
          {problem.message}
          {problem.conflict && (
            <Button variant='quiet' size='sm' className='h-9' onClick={() => { setProblem(null); void refresh(); }}>{copy.reload}</Button>
          )}
        </p>
      )}

      <section aria-label={copy.notes} className='flex flex-col gap-2'>
        <h4 className='text-muted-foreground text-xs font-medium'>{copy.notes} · {rel.notes.length}</h4>
        {rel.notes.length > 0 && (
          <ul className='flex flex-col gap-1.5'>
            {rel.notes.map((item) => (
              <li key={item.id} className='flex items-start gap-2 text-sm'>
                <span className='min-w-0 flex-1 break-words whitespace-pre-wrap'>{item.text}</span>
                <span className='text-muted-foreground shrink-0 text-xs'>{relativeTime(item.at)}</span>
                {canEdit && (
                  <Button variant='quiet' size='icon-sm' aria-label={copy.removeNote} disabled={busy}
                    onClick={() => void run('note', (api, w) => api.removeNote(w, rel.id, rel.revision, item.id))}>
                    <Icons.close className='size-3.5' />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {canEdit && rel.notes.length < 20 && (
          <form
            className='flex flex-col gap-2 sm:flex-row sm:items-end'
            onSubmit={(event) => {
              event.preventDefault();
              const text = note.trim();
              if (text) void run('note', (api, w) => api.addNote(w, rel.id, rel.revision, text), () => setNote(''));
            }}
          >
            <Label htmlFor={`${headingId}-note`} className='sr-only'>{copy.addNote}</Label>
            <Textarea id={`${headingId}-note`} rows={2} value={note} maxLength={NOTE_LIMIT} placeholder={copy.notePlaceholder} onChange={(event) => setNote(event.target.value)} className='min-h-11' />
            <Button type='submit' variant='glass' size='sm' className='h-9' disabled={busy || !note.trim()}>{copy.addNote}</Button>
          </form>
        )}
      </section>

      {rel.threads.length > 0 && (
        <section aria-label={copy.linkedConversations} className='flex flex-col gap-1.5'>
          <h4 className='text-muted-foreground text-xs font-medium'>{copy.linkedConversations}</h4>
          <ul className='flex flex-col gap-1.5'>
            {rel.threads.map((item) => {
              const itemRoute = replyRouteView(item.replyRoute, copy);
              return (
                <li key={item.threadId} className='flex flex-wrap items-center gap-2 text-sm'>
                  <span className='text-foreground font-medium'>@{item.author.replace(/^@/, '') || '—'}</span>
                  <span className='text-muted-foreground'>{platformName(item.provider)}</span>
                  <span className='text-muted-foreground min-w-0 flex-1 truncate'>{item.excerpt}</span>
                  {itemRoute.kind === 'assisted' && itemRoute.href && (
                    <a href={itemRoute.href} target='_blank' rel='noreferrer' className='rafii-focus text-xs underline underline-offset-2'>{itemRoute.label}</a>
                  )}
                  {canEdit && rel.threads.length > 1 && (
                    <Button variant='quiet' size='sm' className='h-9' disabled={busy}
                      onClick={() => void run('unlink', (api, w) => api.unlinkThread(w, rel.id, rel.revision, item.threadId))}>
                      {copy.unlink}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {rel.history.length > 0 && (
        <details className='text-sm'>
          <summary className='rafii-focus text-muted-foreground w-fit cursor-pointer rounded-sm text-xs'>{copy.history}</summary>
          <ol className='text-muted-foreground mt-2 flex flex-col gap-1 text-xs'>
            {rel.history.map((item, index) => (
              <li key={`${item.kind}-${item.at}-${index}`}>
                {item.kind.replaceAll('_', ' ')}
                {item.from || item.to ? ` · ${item.from ? copy.states[item.from] : ''} → ${item.to ? copy.states[item.to] : ''}` : ''} · {relativeTime(item.at)}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

/** Name, interest, next step and the due time in its zone. A repeated local time asks which occurrence. */
function FollowUpEditor({ rel, zone, onCancel, onSaved }: { rel: RelationshipDetail; zone: string; onCancel: () => void; onSaved: () => void }) {
  const copy = currentCopy();
  const change = useRelationshipChange();
  const id = useId();
  const [name, setName] = useState(rel.displayName);
  const [interest, setInterest] = useState(rel.interest ?? '');
  const [nextAction, setNextAction] = useState(rel.nextAction ?? '');
  const [local, setLocal] = useState(rel.due?.local ?? '');
  const [timeZone, setTimeZone] = useState(rel.due?.timeZone ?? zone);
  const [dueDirty, setDueDirty] = useState(false);
  const [askFold, setAskFold] = useState(false);
  const [fold, setFold] = useState<0 | 1>(0);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      const body: RelationshipEditInput = { displayName: name, interest: interest || null, nextAction: nextAction || null };
      if (dueDirty) body.due = dueInput(local, timeZone, askFold ? fold : undefined);
      await change((api, w) => api.update(w, rel.id, rel.revision, body));
      onSaved();
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
      className='flex flex-col gap-3'
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-name`}>{copy.name}</Label>
        <Input id={`${id}-name`} value={name} maxLength={120} required onChange={(event) => setName(event.target.value)} />
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
        zones={zoneChoices(rel.due?.timeZone, zone, browserZone())}
        askFold={askFold}
        fold={fold}
        onLocal={(value) => { setLocal(value); setDueDirty(true); setAskFold(false); }}
        onZone={(value) => { setTimeZone(value); setDueDirty(true); setAskFold(false); }}
        onFold={setFold}
        onClear={() => { setLocal(''); setDueDirty(true); setAskFold(false); }}
      />
      {problem && <p role='alert' className='text-destructive text-sm'>{problem}</p>}
      <div className='flex gap-2'>
        <Button type='submit' variant='glass' size='control' disabled={saving || !name.trim()}>{saving ? copy.saving : copy.save}</Button>
        <Button type='button' variant='quiet' size='control' disabled={saving} onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/** A wall time and its IANA zone; the repeated-hour choice appears only when the server asks for it. */
export function DueFields({
  id,
  local,
  timeZone,
  zones,
  askFold,
  fold,
  onLocal,
  onZone,
  onFold,
  onClear
}: {
  id: string;
  local: string;
  timeZone: string;
  zones: string[];
  askFold: boolean;
  fold: 0 | 1;
  onLocal: (value: string) => void;
  onZone: (value: string) => void;
  onFold: (value: 0 | 1) => void;
  onClear: () => void;
}) {
  const copy = currentCopy();
  return (
    <fieldset className='flex flex-col gap-2'>
      <legend className='mb-1.5 text-sm font-medium'>{copy.due}</legend>
      <div className='flex flex-wrap items-end gap-2'>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-due`} className='sr-only'>{copy.due}</Label>
          <Input id={`${id}-due`} type='datetime-local' value={local} onChange={(event) => onLocal(event.target.value)} className='w-auto' />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-zone`} className='sr-only'>{copy.timeZone}</Label>
          <NativeSelect id={`${id}-zone`} value={timeZone} onChange={(event) => onZone(event.target.value)}>
            {zones.map((zone) => <NativeSelectOption key={zone} value={zone}>{zone}</NativeSelectOption>)}
          </NativeSelect>
        </div>
        {local && <Button type='button' variant='quiet' size='sm' className='h-9' onClick={onClear}>{copy.clearDue}</Button>}
      </div>
      {askFold && (
        <div role='radiogroup' aria-label={copy.repeatedTime} className='flex flex-col gap-1.5 text-sm'>
          <p>{copy.repeatedTime}</p>
          {([0, 1] as const).map((value) => (
            <label key={value} className='flex min-h-9 items-center gap-2'>
              <input type='radio' name={`${id}-fold`} aria-label={value === 0 ? copy.firstOccurrence : copy.secondOccurrence} checked={fold === value} onChange={() => onFold(value)} />
              {value === 0 ? copy.firstOccurrence : copy.secondOccurrence}
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}
