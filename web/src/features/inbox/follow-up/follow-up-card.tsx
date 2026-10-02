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
import { errorCode } from '@/lib/growth-v2/request';
import type { RelationshipsApi } from '@/lib/growth-v2/relationships';
import { useRelationship, useRelationshipChange, useRelationshipRefresh } from '@/lib/growth-v2/relationships-hooks';
import {
  browserZone,
  dueInput,
  editChanges,
  followUpHref,
  followUpLine,
  historyLine,
  nextStates,
  platformName,
  replyRouteView,
  snoozeChoices,
  stateTone,
  zoneChoices
} from '@/lib/growth-v2/relationships-model';
import type { RelationshipDetail, RelationshipEditInput, RelationshipState, RelationshipWrite } from '@/lib/growth-v2/relationships-types';
import { useResultsRefresh } from '@/lib/growth-v2/results-hooks';
import { relativeTime, timeDefaults } from '@/lib/time';
import { cn } from '@/lib/utils';
import { currentCopy, currentLang, describeProblem, focusComposer, when, type FollowUpProblem } from './copy';
import { usePanelFocus, useReturnFocus } from './focus';
import { WonResultPicker } from './won-result-picker';

type Run = (api: RelationshipsApi, w: string) => Promise<RelationshipWrite>;
/** The last change that can be undone, offered in place (not only in a passing toast) while nothing else changed. */
type Undoable = { message: string; revision: number; undo: (revision: number) => Run };

const NOTE_LIMIT = 500;

/**
 * One follow-up, editable in place: stage, reminder, owner, next step, due time in its zone, notes, linked
 * conversations and history. Every change sends the revision it started from; a conflict asks to reload instead of
 * overwriting. Stage and owner change only when the person applies them. Snooze, close and "not relevant" offer Undo
 * here and in a toast. Replying is the Inbox composer (exact approval) or, on a platform Rafii can't reply on, an
 * honest "Open on …" link — never a direct success. Mount it with `key={relationshipId}` so nothing typed for one
 * follow-up can carry over to another.
 */
export function FollowUpCard({
  relationshipId,
  threadId,
  canEdit,
  focusOnLoad = false,
  onReply
}: {
  relationshipId: string;
  /** The conversation open beside this card, when its composer is on the page. */
  threadId?: string | null;
  canEdit: boolean;
  /** Move keyboard focus to this card's heading once it has loaded (just started, or opened from a link). */
  focusOnLoad?: boolean;
  /** Open this conversation's composer in the Inbox (it loads the conversation when it isn't loaded yet). */
  onReply?: (threadId: string) => void;
}) {
  const copy = currentCopy();
  const lang = currentLang();
  const query = useRelationship(relationshipId);
  const change = useRelationshipChange();
  const refresh = useRelationshipRefresh();
  const refreshResults = useResultsRefresh();
  const members = useMembers();
  const headingId = useId();
  const [pending, setPending] = useState<string | null>(null);
  const [problem, setProblem] = useState<FollowUpProblem | null>(null);
  const [editing, setEditing] = useState(false);
  const [editSession, setEditSession] = useState(0);
  const [snoozing, setSnoozing] = useState(false);
  const [winning, setWinning] = useState(false);
  const [stage, setStage] = useState<RelationshipState | ''>('');
  const [ownerChoice, setOwnerChoice] = useState<string | null>(null);
  const [undoable, setUndoable] = useState<Undoable | null>(null);
  const [note, setNote] = useState('');
  // A chosen stage, owner or "won" belongs to the version it was chosen on: Reload, or any newer version, starts again
  // from what the server holds now, so a choice made before a conflict (409) is never applied to the newer version.
  const revision = query.data?.relationship.revision ?? null;
  const [choicesRevision, setChoicesRevision] = useState(revision);
  if (revision !== choicesRevision) {
    setChoicesRevision(revision);
    setStage('');
    setOwnerChoice(null);
    setWinning(false);
  }
  const heading = useRef<HTMLHeadingElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const snoozeButton = useRef<HTMLButtonElement>(null);
  const stageSelect = useRef<HTMLSelectElement>(null);
  const focused = useRef(false);
  // The toast that carries the current Undo: it goes when that Undo is used here or replaced, so the two never disagree.
  const undoToast = useRef<string | number | null>(null);
  const loaded = Boolean(query.data);
  // Focus goes back to the control that opened an inline panel when it closes (save or cancel).
  useReturnFocus(editing, editButton, heading);
  useReturnFocus(snoozing, snoozeButton, heading);
  useReturnFocus(winning, stageSelect, heading);
  const snoozePanel = usePanelFocusWhen<HTMLDivElement>(snoozing, () => setSnoozing(false));

  useEffect(() => {
    if (!focusOnLoad || !loaded || focused.current) return;
    focused.current = true;
    heading.current?.focus();
  }, [focusOnLoad, loaded]);

  // Only a first load that failed replaces the card; a failed background refresh keeps it (and anything typed in it).
  if (query.isPending) return <StateMessage kind='loading' layout='inline' title={copy.loading} />;
  if (!query.data) {
    return (
      <div lang={lang}>
        <StateMessage
          kind='error'
          layout='inline'
          title={describeProblem(query.error, copy).message}
          action={<Button variant='glass' size='sm' className='h-9' onClick={() => void query.refetch()}>{copy.reload}</Button>}
        />
      </div>
    );
  }
  const rel: RelationshipDetail = query.data.relationship;
  const busy = pending !== null;
  const zone = timeDefaults().timeZone ?? browserZone();
  const thread = rel.threads.find((item) => item.threadId === threadId) ?? rel.threads[0] ?? null;
  const route = replyRouteView(thread?.replyRoute ?? rel.replyRoute, copy);
  const activeMembers = (members.data?.members ?? []).filter((member) => member.status === 'active');
  const terminal = rel.state === 'won' || rel.state === 'closed';
  const currentOwner = rel.owner?.userId ?? '';
  const ownerValue = ownerChoice ?? currentOwner;
  const ownerName = rel.owner ? (rel.owner.active ? rel.owner.displayName || rel.owner.userId.slice(0, 8) : copy.formerMember) : copy.unassigned;
  const offerUndo = undoable && undoable.revision === rel.revision ? undoable : null;

  async function run(label: string, task: Run, after?: (result: RelationshipWrite) => void) {
    setPending(label);
    setProblem(null);
    setUndoable(null); // a new change replaces the last undo offer
    if (undoToast.current !== null) toast.dismiss(undoToast.current);
    undoToast.current = null;
    try {
      const result = await change(task);
      after?.(result);
      return result;
    } catch (cause) {
      // A result reversed meanwhile must leave the "won" picker: re-read the person's results.
      if (errorCode(cause) === 'result_required') void refreshResults();
      setProblem(describeProblem(cause, copy));
      return null;
    } finally {
      setPending(null);
    }
  }

  function withUndo(message: string, undo: (revision: number) => Run) {
    return (result: RelationshipWrite) => {
      const revision = result.relationship.revision;
      setUndoable({ message, revision, undo });
      undoToast.current = toast(<span lang={lang}>{message}</span>, {
        action: { label: <span lang={lang}>{copy.undo}</span>, onClick: () => void run('undo', undo(revision)) }
      });
    };
  }

  const snooze = (until: number) =>
    run('snooze', (api, w) => api.snooze(w, rel.id, rel.revision, until), (result) => {
      setSnoozing(false);
      withUndo(copy.snoozedToast, (revision) => (api, w) => api.unsnooze(w, rel.id, revision))(result);
    });
  /** The stage the person chose, applied only when they confirm it (a select never saves on its own). */
  const applyStage = (target: RelationshipState) => {
    if (target === 'won') {
      setWinning(true);
      return;
    }
    void run('state', (api, w) => api.transition(w, rel.id, rel.revision, target), (result) => {
      setStage('');
      if (target === 'closed') withUndo(copy.closedToast, (revision) => (api, w) => api.reopen(w, rel.id, revision))(result);
    });
  };
  const dismissReminder = () =>
    run('dismiss', (api, w) => api.dismissFollowUp(w, rel.id, rel.revision),
      withUndo(copy.dismissedToast, (revision) => (api, w) => api.restoreFollowUp(w, rel.id, revision)));
  const resetChoices = () => {
    setStage('');
    setOwnerChoice(null);
    setWinning(false);
  };
  const reloadAfterConflict = async () => {
    setProblem(null);
    resetChoices();
    await refresh();
  };

  return (
    <section lang={lang} aria-labelledby={headingId} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-3.5' data-follow-up={rel.id}>
      <header className='flex flex-wrap items-center gap-2'>
        <h3 id={headingId} ref={heading} tabIndex={-1} className='rafii-focus text-foreground min-w-0 flex-1 truncate rounded-sm text-sm font-medium'>
          {rel.displayName}
        </h3>
        <AnimatedBadge size='sm' status={stateTone(rel.state)} showIcon={false} layout={false} contentKey={rel.state} className='rafii-glass border-0'>
          {copy.states[rel.state]}
        </AnimatedBadge>
        {rel.won?.reversed && (
          <AnimatedBadge size='sm' status='warning' showIcon={false} layout={false} className='rafii-glass border-0'>
            {copy.wonWithdrawn}
          </AnimatedBadge>
        )}
      </header>

      {query.isError && (
        <p role='status' className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
          {copy.staleNotice}
          <Button variant='quiet' size='sm' className='h-9' onClick={() => { resetChoices(); void query.refetch(); }}>{copy.reload}</Button>
        </p>
      )}

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

      {canEdit && offerUndo && (
        <p role='status' className='rafii-glass flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-1.5 text-sm'>
          <span className='min-w-0 flex-1'>{offerUndo.message}</span>
          <Button variant='quiet' size='sm' className='h-9' disabled={busy} onClick={() => void run('undo', offerUndo.undo(offerUndo.revision))}>
            {copy.undo}
          </Button>
        </p>
      )}

      {rel.suggestion && canEdit && (
        <div className='rafii-glass flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
          <Icons.sparkles className='text-muted-foreground size-4 shrink-0' aria-hidden />
          <span className='min-w-0 flex-1'>
            {copy.suggested(copy.states[rel.suggestion.state])}
            <span className='text-muted-foreground'> · {copy.reasons[rel.suggestion.reason] ?? copy.reasons.due_passed}</span>
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
          key={editSession}
          rel={rel}
          zone={zone}
          onCancel={() => setEditing(false)}
          onSaved={() => setEditing(false)}
          onReload={async () => {
            await refresh();
            setEditSession((session) => session + 1); // start again from what the server holds now
          }}
        />
      ) : (
        <dl className='grid gap-2 text-sm sm:grid-cols-[auto_minmax(0,1fr)] sm:gap-x-4'>
          {rel.interest && (<><dt className='text-muted-foreground'>{copy.interest}</dt><dd className='break-words'>{rel.interest}</dd></>)}
          {rel.nextAction && (<><dt className='text-muted-foreground'>{copy.nextAction}</dt><dd className='break-words'>{rel.nextAction}</dd></>)}
          <dt className='text-muted-foreground'>{copy.due}</dt>
          <dd>{rel.due ? `${when(rel.due.at, rel.due.timeZone)} (${rel.due.timeZone})` : copy.noDue}</dd>
          <dt className='text-muted-foreground'>{copy.owner}</dt>
          <dd>
            {canEdit && members.isSuccess ? (
              <div className='flex flex-wrap items-center gap-2'>
                <NativeSelect size='sm' aria-label={copy.owner} value={ownerValue} disabled={busy} onChange={(event) => setOwnerChoice(event.target.value)}>
                  <NativeSelectOption value=''>{copy.unassigned}</NativeSelectOption>
                  {rel.owner && !rel.owner.active && <NativeSelectOption value={rel.owner.userId} disabled>{copy.formerMember}</NativeSelectOption>}
                  {rel.owner?.active && !activeMembers.some((member) => member.userId === rel.owner!.userId) && (
                    <NativeSelectOption value={rel.owner.userId}>{ownerName}</NativeSelectOption>
                  )}
                  {activeMembers.map((member) => (
                    <NativeSelectOption key={member.userId} value={member.userId}>{member.displayName || member.userId.slice(0, 8)}</NativeSelectOption>
                  ))}
                </NativeSelect>
                {ownerChoice !== null && ownerChoice !== currentOwner && (
                  <Button variant='glass' size='sm' className='h-9' disabled={busy}
                    onClick={() => void run('assign', (api, w) => api.assign(w, rel.id, rel.revision, ownerChoice || null), () => setOwnerChoice(null))}>
                    {copy.assign}
                  </Button>
                )}
              </div>
            ) : (
              <span>
                {ownerName}
                {canEdit && members.isPending && <span className='text-muted-foreground'> · {copy.membersLoading}</span>}
                {canEdit && members.isError && <span className='text-muted-foreground'> · {copy.membersFailed}</span>}
              </span>
            )}
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
          ) : onReply ? (
            <Button variant='glass' size='control' onClick={() => onReply(thread.threadId)}>
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
          <Button ref={editButton} variant='quiet' size='control' disabled={busy} onClick={() => setEditing(true)}>
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
              <NativeSelect ref={stageSelect} size='sm' aria-label={copy.chooseStage} value={stage} disabled={busy || winning}
                onChange={(event) => setStage(event.target.value as RelationshipState | '')}>
                <NativeSelectOption value=''>{copy.state}: {copy.states[rel.state]}</NativeSelectOption>
                {nextStates(rel.state).map((target) => (
                  <NativeSelectOption key={target} value={target}>{copy.states[target]}</NativeSelectOption>
                ))}
              </NativeSelect>
              <Button variant='glass' size='sm' className='h-9' disabled={busy || winning || !stage} onClick={() => stage && applyStage(stage)}>
                {copy.changeStage}
              </Button>
              <Button ref={snoozeButton} variant='quiet' size='sm' className='h-9' disabled={busy} aria-expanded={snoozing} onClick={() => setSnoozing((open) => !open)}>
                {copy.snooze}
              </Button>
            </>
          )}
        </div>
      )}
      {snoozing && !terminal && (
        <div ref={snoozePanel} role='group' aria-label={copy.snooze} className='flex flex-wrap gap-2'>
          {snoozeChoices(Date.now() / 1000, rel.due?.timeZone ?? zone, copy).map((choice) => (
            <Button key={choice.label} variant='glass' size='sm' className='h-9' disabled={busy} onClick={() => void snooze(choice.until)}>
              {choice.label}
            </Button>
          ))}
          <Button variant='quiet' size='sm' className='h-9' onClick={() => setSnoozing(false)}>{copy.cancel}</Button>
        </div>
      )}
      {winning && (
        <WonResultPicker
          busy={busy}
          onCancel={() => {
            setWinning(false);
            setStage('');
          }}
          onConfirm={(resultId) =>
            void run('won', (api, w) => api.transition(w, rel.id, rel.revision, 'won', { wonResultId: resultId }), () => {
              setWinning(false);
              setStage('');
            })
          }
        />
      )}
      {rel.won && (
        rel.won.reversed ? (
          <div role='note' className='rafii-glass flex flex-col gap-1 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
            <span className='text-foreground flex items-center gap-2 font-medium'>
              <Icons.warning className='size-4 shrink-0' aria-hidden />
              {copy.wonWithdrawn}
            </span>
            <span className='text-muted-foreground text-xs leading-relaxed'>{copy.wonWithdrawnHint}</span>
          </div>
        ) : (
          <p className='text-muted-foreground text-xs'>{copy.states.won} · {copy.provenance[rel.won.provenance ?? ''] ?? copy.provenance.unknown}</p>
        )
      )}

      {problem && (
        <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-sm'>
          <span lang={problem.lang}>{problem.message}</span>
          {problem.conflict && (
            <Button variant='quiet' size='sm' className='h-9' onClick={() => void reloadAfterConflict()}>{copy.reload}</Button>
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
                  <span className='text-muted-foreground'>{platformName(item.provider, copy.thePlatform)}</span>
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
                {historyLine(item, copy)} · {relativeTime(item.at)}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

/** `usePanelFocus` for a panel that stays in this component: focus moves in when it opens, Escape closes it. */
function usePanelFocusWhen<P extends HTMLElement>(open: boolean, onCancel: () => void) {
  const ref = useRef<P>(null);
  const cancel = useRef(onCancel);
  useEffect(() => {
    cancel.current = onCancel;
  }, [onCancel]);
  useEffect(() => {
    const panel = ref.current;
    if (!open || !panel) return;
    panel.querySelector<HTMLElement>('button:not([disabled])')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      cancel.current();
    };
    panel.addEventListener('keydown', onKey);
    return () => panel.removeEventListener('keydown', onKey);
  }, [open]);
  return ref;
}

/**
 * Name, interest, next step and the due time in its zone. The edit starts from what the card showed — its values and
 * its revision — and saving sends only the fields the person changed, at that revision: if someone else changed the
 * follow-up meanwhile the server answers 409 and the editor offers a reload instead of overwriting their change. A
 * repeated local time asks which occurrence, with nothing pre-selected.
 */
function FollowUpEditor({
  rel,
  zone,
  onCancel,
  onSaved,
  onReload
}: {
  rel: RelationshipDetail;
  zone: string;
  onCancel: () => void;
  onSaved: () => void;
  onReload: () => Promise<void>;
}) {
  const copy = currentCopy();
  const lang = currentLang();
  const change = useRelationshipChange();
  const id = useId();
  const panel = usePanelFocus<HTMLFormElement>(onCancel);
  const [start] = useState(() => ({
    revision: rel.revision,
    values: { displayName: rel.displayName, interest: rel.interest ?? '', nextAction: rel.nextAction ?? '' }
  }));
  const [name, setName] = useState(start.values.displayName);
  const [interest, setInterest] = useState(start.values.interest);
  const [nextAction, setNextAction] = useState(start.values.nextAction);
  const [local, setLocal] = useState(rel.due?.local ?? '');
  const [timeZone, setTimeZone] = useState(rel.due?.timeZone ?? zone);
  const [dueDirty, setDueDirty] = useState(false);
  const [askFold, setAskFold] = useState(false);
  const [fold, setFold] = useState<0 | 1 | null>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<FollowUpProblem | null>(null);

  async function save() {
    if (askFold && fold === null) {
      setProblem({ message: copy.chooseOccurrence, conflict: false, lang });
      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      const body: RelationshipEditInput = editChanges(start.values, { displayName: name, interest, nextAction });
      if (dueDirty) body.due = dueInput(local, timeZone, askFold && fold !== null ? fold : undefined);
      if (Object.keys(body).length > 0) await change((api, w) => api.update(w, rel.id, start.revision, body));
      onSaved();
    } catch (cause) {
      if (errorCode(cause) === 'due_time_ambiguous') {
        setAskFold(true);
        setFold(null);
      }
      setProblem(describeProblem(cause, copy, copy.editConflict));
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
        onLocal={(value) => { setLocal(value); setDueDirty(true); resetFold(); }}
        onZone={(value) => { setTimeZone(value); setDueDirty(true); resetFold(); }}
        onFold={setFold}
        onClear={() => { setLocal(''); setDueDirty(true); resetFold(); }}
      />
      {problem && (
        <p role='alert' className='text-destructive flex flex-wrap items-center gap-2 text-sm'>
          <span lang={problem.lang}>{problem.message}</span>
          {problem.conflict && (
            <Button type='button' variant='quiet' size='sm' className='h-9' onClick={() => void onReload()}>{copy.reload}</Button>
          )}
        </p>
      )}
      <div className='flex gap-2'>
        <Button type='submit' variant='glass' size='control' disabled={saving || !name.trim() || (askFold && fold === null)}>{saving ? copy.saving : copy.save}</Button>
        <Button type='button' variant='quiet' size='control' disabled={saving} onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/**
 * A wall time and its IANA zone. The repeated-hour choice appears only when the server asks for it, and nothing is
 * chosen for the person: they pick the first or the second occurrence.
 */
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
  fold: 0 | 1 | null;
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
        <div role='radiogroup' aria-label={copy.repeatedTime} aria-required='true' className='flex flex-col gap-1.5 text-sm'>
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
