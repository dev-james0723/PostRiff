'use client';

import Link from 'next/link';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { parseAsString, useQueryState } from 'nuqs';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Panel } from '@/features/workspace/rafii-parts';
import { useChannels } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { queueDraftHref } from '@/lib/coworker/safe-href';
import { clearAllContinuations, importBody, readContinuation, type ReadOutcome } from '@/lib/growth-v2/continuation';
import {
  DRAFT_LANGUAGES,
  LANGUAGE_LABELS,
  draftBatch,
  draftLanguage,
  draftingMayContinue,
  slotCostText,
  stepTakesFocus,
  unknownOutcome,
  type DraftLanguage,
  type UnansweredDraft
} from '@/lib/growth-v2/first-week';
import { firstWeekKey, refreshAfterFirstWeek, useFirstWeek, useFirstWeekAction, useFirstWeekApi } from '@/lib/growth-v2/first-week-hooks';
import type { FirstWeekSlot, FirstWeekStep, FirstWeekView } from '@/lib/growth-v2/first-week-types';
import { errorCode, errorMessage, idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { usePreferences } from '@/lib/preferences';
import { useWorkspace } from '@/lib/workspace/provider';
import { useQueryClient } from '@tanstack/react-query';

const PLATFORMS = ['Threads', 'Instagram', 'LinkedIn', 'X', 'Bluesky', 'Mastodon'];
const FIELD = 'rafii-field rounded-lg p-2 text-sm';

function tabStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function languageLabel(tag: string): string {
  return (LANGUAGE_LABELS as Record<string, string>)[tag] ?? tag;
}

/**
 * First Week Ready inside Weekly (PRD R-FWR-01..03): import a consented Post Doctor draft, answer only what is missing,
 * accept one draft, plan up to three posts on one platform, commit the scope, then write/draft and deliver each post.
 * Every state shown here is the server's read model; publishing state comes from Queue.
 */
export function FirstWeekPanel({ canEdit }: { canEdit: boolean }) {
  const journey = useFirstWeek();
  const [continueParam, setContinueParam] = useQueryState('continue', parseAsString.withOptions({ history: 'replace', scroll: false }));
  if (journey.error && isFeatureDisabled(journey.error)) return null;
  if (journey.isPending) return <StateMessage kind='loading' layout='inline' title='Loading your first week…' />;
  if (journey.error) return <StateMessage kind='error' layout='inline' title='Your first week couldn’t load' description={errorMessage(journey.error)} />;
  const view = journey.data;
  if (!view) return null;
  if (view.complete) {
    // A draft kept from Post Doctor is still offered after the first week is done: import it as a new draft, or discard.
    return (
      <div className='flex flex-col gap-3'>
        <ContinuationImport nonce={continueParam} onDone={() => void setContinueParam(null)} canEdit={canEdit} complete />
        <Delivered view={view} />
      </div>
    );
  }
  return (
    <Panel title='Your first week' description='From your own words to a reviewed week. Nothing is scheduled or published until you approve each post in Queue.'>
      <Steps view={view} canEdit={canEdit} readAt={journey.dataUpdatedAt}>
        <ContinuationImport nonce={continueParam} onDone={() => void setContinueParam(null)} canEdit={canEdit} />
      </Steps>
    </Panel>
  );
}

function ContinuationImport({ nonce, onDone, canEdit, complete = false }: { nonce: string | null; onDone: () => void; canEdit: boolean; complete?: boolean }) {
  const { user } = useAuth();
  const { workspaceId, workspaces } = useWorkspace();
  const { api, w } = useFirstWeekApi();
  const client = useQueryClient();
  const [outcome, setOutcome] = useState<ReadOutcome | null>(null);
  // A nonce arrived in the link: the person expects their kept draft, so "missing" is said, never shown as nothing.
  const [requested, setRequested] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const read = readContinuation(tabStorage(), nonce, Date.now());
    setOutcome(read);
    if (nonce) {
      setRequested(true);
      onDone(); // the nonce has been read; keep the URL clean (the tab's pending record survives a refresh)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);
  if (!outcome) return null;
  if (outcome.status === 'missing') {
    if (!requested) return null;
    return (
      <StateMessage
        kind='empty'
        layout='inline'
        title='Your Post Doctor draft isn’t in this tab'
        description={`A kept draft stays only in the browser tab where you checked it, for up to 24 hours. ${complete ? 'Paste it into a new draft instead.' : 'Paste it below to start, or check it again in Post Doctor.'}`}
      />
    );
  }
  if (outcome.status !== 'ready') {
    const text =
      outcome.status === 'expired'
        ? 'The draft you kept expired after 24 hours and was removed from this browser. Paste it again in Post Doctor or below.'
        : outcome.status === 'unavailable'
          ? 'This browser blocks temporary storage, so the draft could not be kept. Paste it below to start.'
          : 'The kept draft could not be read and was removed. Paste it below to start.';
    return <StateMessage kind='empty' layout='inline' title='Your Post Doctor draft isn’t here' description={text} />;
  }
  const record = outcome.record;
  const name = workspaces.find((item) => item.workspaceId === workspaceId)?.name ?? 'this workspace';
  async function importIt() {
    setBusy(true);
    try {
      const result = await api.importContinuation(w, importBody(record));
      clearAllContinuations(tabStorage(), record.nonce);
      client.setQueryData(firstWeekKey(w), result.journey);
      refreshAfterFirstWeek(client, w);
      setOutcome({ status: 'missing' });
      setRequested(false);
      toast.success(result.replayed ? 'Already imported — here it is.' : complete ? 'Draft imported. Find it in Queue → Drafts.' : 'Draft imported');
    } catch (error) {
      toast.error('The draft wasn’t imported', { description: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  }
  function discard() {
    clearAllContinuations(tabStorage(), record.nonce);
    setOutcome({ status: 'missing' });
    setRequested(false);
  }
  return (
    <div className='flex flex-col gap-3 rounded-xl border border-(--rafii-border-subtle) p-4' role='region' aria-label='Import your Post Doctor draft'>
      <p className='text-sm font-medium'>{complete ? 'Your first week is done. Import the draft you kept from Post Doctor as a new draft?' : 'Import the draft you kept from Post Doctor?'}</p>
      <p className='text-muted-foreground text-sm'>
        It goes into <strong>{name}</strong>, signed in as {user?.email ?? user?.name ?? 'you'}. Wrong account or workspace? Switch first — the draft stays in this
        tab until you import or discard it (up to 24 hours).
      </p>
      {record.items.map((item) => (
        <blockquote key={item.kind} lang={record.language === 'other' ? undefined : record.language} className='rafii-paper rounded-lg p-3 text-sm whitespace-pre-wrap'>
          <span className='text-muted-foreground block text-xs'>{item.kind === 'edited' ? 'Your edited version' : 'The version you checked'}</span>
          {item.text}
        </blockquote>
      ))}
      <div className='flex flex-wrap gap-2'>
        <Button variant='action' disabled={busy || !canEdit} onClick={() => void importIt()}>
          {busy ? 'Importing…' : 'Import into this workspace'}
        </Button>
        <Button variant='ghost' disabled={busy} onClick={discard}>
          Discard
        </Button>
      </div>
      {!canEdit && <p className='text-muted-foreground text-xs'>You can view this workspace but not add drafts to it.</p>}
    </div>
  );
}

/** Each step's heading: focus moves to it and it is announced when the journey moves on (keyboard and screen readers). */
const STEP_TITLES: Record<FirstWeekStep, string> = {
  source: 'Start with your own words',
  context: 'What the posts are for',
  accept: 'Accept your first draft',
  plan: 'Plan your week',
  scope: 'Choose this week’s posts',
  review: 'Review your week',
  deliver: 'Deliver your week',
  complete: 'Your first week is delivered'
};

/**
 * The journey's current step. `readAt` is when the shown journey was read (a refetch moves it on even when nothing
 * changed). A new step is always announced; it takes focus only when the control the person used went with the old step
 * (`stepTakesFocus`), so a background refetch never pulls focus away from where they are.
 */
function Steps({ view, canEdit, readAt, children }: { view: FirstWeekView; canEdit: boolean; readAt: number; children?: ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const shown = useRef(view.step);
  // The element in this panel that last had focus; forgotten when focus moves on to something outside it.
  const lastFocused = useRef<Element | null>(null);
  const [announcement, setAnnouncement] = useState('');
  useEffect(() => {
    if (shown.current === view.step) return;
    shown.current = view.step;
    setAnnouncement(`Next step: ${STEP_TITLES[view.step] ?? view.step}`);
    if (stepTakesFocus(document.activeElement, document.body, lastFocused.current)) heading.current?.focus();
  }, [view.step]);
  let body: ReactNode;
  switch (view.step) {
    case 'source':
      body = <StartFromText canEdit={canEdit} />;
      break;
    case 'context':
      body = <Context view={view} canEdit={canEdit} />;
      break;
    case 'accept':
      body = <AcceptDraft view={view} canEdit={canEdit} />;
      break;
    case 'plan':
      body = <PlanWeek view={view} canEdit={canEdit} />;
      break;
    default:
      body = <WeekSlots view={view} canEdit={canEdit} readAt={readAt} />;
  }
  return (
    <div
      className='flex flex-col gap-4'
      onFocus={(event) => {
        lastFocused.current = event.target;
      }}
      onBlur={(event) => {
        if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) lastFocused.current = null;
      }}
    >
      {children}
      <div className='flex flex-col gap-3'>
        <h3 ref={heading} tabIndex={-1} className='rafii-focus text-sm font-medium'>
          {STEP_TITLES[view.step] ?? ''}
        </h3>
        <p role='status' aria-live='polite' className='sr-only'>
          {announcement}
        </p>
        {body}
      </div>
    </div>
  );
}

function StartFromText({ canEdit }: { canEdit: boolean }) {
  const { api, w } = useFirstWeekApi();
  const client = useQueryClient();
  const prefs = usePreferences();
  const [text, setText] = useState('');
  const [platform, setPlatform] = useState('Threads');
  // Detected from the text and the person's own language until they choose one; never a fixed English.
  const [chosen, setChosen] = useState<DraftLanguage | null>(null);
  const language = chosen ?? draftLanguage(text, prefs.locale);
  const [busy, setBusy] = useState(false);
  // One key per input until it is saved: a retry after a lost answer returns the same draft instead of a second one.
  const key = useRef<string | null>(null);
  const changed = () => {
    key.current = null;
  };
  async function start() {
    setBusy(true);
    key.current ??= idempotencyKey('fw-start');
    try {
      const result = await api.start(w, { idempotencyKey: key.current, consent: true, text, platform, language });
      key.current = null;
      client.setQueryData(firstWeekKey(w), result.journey);
      refreshAfterFirstWeek(client, w);
    } catch (error) {
      toast.error('Couldn’t save your draft', { description: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className='flex flex-col gap-2'>
      <Label htmlFor='fw-start'>Start with something you wrote</Label>
      <Textarea
        id='fw-start'
        rows={6}
        maxLength={8000}
        value={text}
        lang={language === 'other' ? undefined : language}
        onChange={(e) => {
          setText(e.target.value);
          changed();
        }}
        placeholder='Paste a draft, a note or an idea in your own words.'
      />
      <div className='flex flex-wrap items-end gap-3'>
        <label className='flex flex-col gap-1 text-sm'>
          Platform
          <select
            className={FIELD}
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value);
              changed();
            }}
          >
            {PLATFORMS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className='flex flex-col gap-1 text-sm'>
          Language
          <select
            className={FIELD}
            value={language}
            onChange={(e) => {
              setChosen(e.target.value as DraftLanguage);
              changed();
            }}
          >
            {DRAFT_LANGUAGES.map((tag) => (
              <option key={tag} value={tag}>
                {LANGUAGE_LABELS[tag]}
              </option>
            ))}
          </select>
        </label>
        <Button variant='action' disabled={!canEdit || busy || !text.trim()} onClick={() => void start()}>
          {busy ? 'Saving…' : 'Use this as my first draft'}
        </Button>
      </div>
      <p className='text-muted-foreground text-xs'>Saved as your own draft and source. Nothing is generated or charged.</p>
    </div>
  );
}

function Context({ view, canEdit }: { view: FirstWeekView; canEdit: boolean }) {
  const [purpose, setPurpose] = useState(view.context.purpose ?? '');
  const [audience, setAudience] = useState(view.context.audience ?? '');
  const [subject, setSubject] = useState(view.context.subject ?? '');
  const needsSubject = view.missingContext.includes('subject');
  const save = useFirstWeekAction((api, w, revision, _: void) =>
    api.setContext(w, { purpose, audience, ...(needsSubject ? { subject } : {}), expectedRevision: revision })
  );
  return (
    <form
      className='flex flex-col gap-3'
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined, { onError: (error) => toast.error('Not saved', { description: errorMessage(error) }) });
      }}
    >
      <p className='text-sm'>A few quick answers so the week fits what you do. Rafii only asks what it doesn’t already know.</p>
      {view.missingContext.includes('purpose') && (
        <label className='flex flex-col gap-1 text-sm'>
          What should these posts do?
          <input className={FIELD} aria-label='What should these posts do?' required maxLength={300} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder='Fill my November workshop' />
        </label>
      )}
      {view.missingContext.includes('audience') && (
        <label className='flex flex-col gap-1 text-sm'>
          Who are they for?
          <input className={FIELD} aria-label='Who are they for?' required maxLength={300} value={audience} onChange={(e) => setAudience(e.target.value)} placeholder='Busy small-business owners' />
        </label>
      )}
      {needsSubject && (
        <label className='flex flex-col gap-1 text-sm'>
          {view.context.mode === 'business' ? 'What is your business?' : 'What do your posts draw on?'}
          <input
            className={FIELD}
            aria-label={view.context.mode === 'business' ? 'What is your business?' : 'What do your posts draw on?'}
            required
            maxLength={300}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder={view.context.mode === 'business' ? 'A bakery that runs weekend classes' : 'Home cooking on a budget'}
          />
        </label>
      )}
      <Button type='submit' variant='action' className='self-start' disabled={!canEdit || save.isPending || (needsSubject && !subject.trim())}>
        {save.isPending ? 'Saving…' : 'Continue'}
      </Button>
    </form>
  );
}

function AcceptDraft({ view, canEdit }: { view: FirstWeekView; canEdit: boolean }) {
  const draft = view.draft!;
  const accept = useFirstWeekAction((api, w, revision, _: void) => api.accept(w, { variantId: draft.variantId, variantRevision: draft.revision, expectedRevision: revision }));
  return (
    <div className='flex flex-col gap-3'>
      <p className='text-sm'>{draft.acceptedRevision ? 'You edited the draft after accepting it. Accept the current version to continue.' : 'Your first draft. Edit it in Drafts if you like, then accept it.'}</p>
      <blockquote lang={draft.language === 'other' ? undefined : draft.language} className='rafii-paper rounded-lg p-3 text-sm whitespace-pre-wrap'>
        {draft.text}
      </blockquote>
      <div className='flex flex-wrap gap-2'>
        <Button variant='action' disabled={!canEdit || accept.isPending} onClick={() => accept.mutate(undefined, { onError: (error) => toast.error('Not accepted', { description: errorMessage(error) }) })}>
          {accept.isPending ? 'Accepting…' : 'Accept this draft'}
        </Button>
        <Link href={queueDraftHref(draft.variantId)} className={buttonVariants({ variant: 'ghost' })}>
          Edit in Drafts
        </Link>
      </div>
      <p className='text-muted-foreground text-xs'>Accepting a draft doesn’t approve or publish it.</p>
    </div>
  );
}

function PlanWeek({ view, canEdit }: { view: FirstWeekView; canEdit: boolean }) {
  const channels = useChannels();
  const [platform, setPlatform] = useState(view.draft?.platform ?? 'Threads');
  const [channelId, setChannelId] = useState<string>('');
  const [posts, setPosts] = useState(3);
  const connected = useMemo(() => (channels.data?.channels ?? []).filter((c) => c.platform === platform), [channels.data, platform]);
  const plan = useFirstWeekAction((api, w, revision, _: void) =>
    api.plan(w, { platform, channelId: channelId || null, postsPerWeek: posts, timeZone: browserZone(), expectedRevision: revision })
  );
  return (
    <div className='flex flex-col gap-3'>
      <p className='text-sm'>Plan next week: up to three posts on one platform. Planning never drafts, spends or schedules anything.</p>
      <div className='flex flex-wrap items-end gap-3'>
        <label className='flex flex-col gap-1 text-sm'>
          Platform
          <select className={FIELD} value={platform} onChange={(e) => { setPlatform(e.target.value); setChannelId(''); }}>
            {PLATFORMS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className='flex flex-col gap-1 text-sm'>
          Account
          <select className={FIELD} value={channelId} onChange={(e) => setChannelId(e.target.value)}>
            <option value=''>Not connected yet</option>
            {connected.map((c) => (
              <option key={c.id} value={c.id}>
                {c.account}
              </option>
            ))}
          </select>
        </label>
        <label className='flex flex-col gap-1 text-sm'>
          Posts
          <select className={FIELD} value={posts} onChange={(e) => setPosts(Number(e.target.value))}>
            {[1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <Button variant='action' disabled={!canEdit || plan.isPending} onClick={() => plan.mutate(undefined, { onError: (error) => toast.error('Not planned', { description: errorMessage(error) }) })}>
          {plan.isPending ? 'Planning…' : 'Plan my week'}
        </Button>
      </div>
      {!channelId && <p className='text-muted-foreground text-xs'>You can plan and write without connecting. Publishing waits until you connect {platform}.</p>}
    </div>
  );
}

const STATUS: Record<string, string> = {
  planned: 'Planned',
  needs_input: 'Needs your answer',
  needs_source: 'Needs a source',
  needs_asset: 'Needs an image',
  drafted: 'Drafted',
  needs_revision: 'Needs a fix',
  ready: 'Ready for review',
  accepted: 'Accepted',
  in_queue: 'In Queue',
  approved: 'Approved',
  scheduled: 'Scheduled',
  published: 'Published (confirmed)',
  failed: 'Didn’t publish',
  rejected: 'Not in this week',
  approval_expired: 'Approval expired'
};

/** The first week's limit is one-time: said wherever drafting is offered, so it never reads as a weekly habit. */
const ONE_TIME = 'This covers this week’s posts only. Rafii won’t plan or draft later weeks unless you turn on weekly drafting in Weekly plan.';

function WeekSlots({ view, canEdit, readAt }: { view: FirstWeekView; canEdit: boolean; readAt: number }) {
  const { w } = useFirstWeekApi();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string[]>(view.scope?.slotIds ?? view.slots.map((s) => s.id));
  const [reason, setReason] = useState('');
  const [credits, setCredits] = useState(300);
  // The request ended without an answer (the 150 s client limit or a dropped connection): drafting may be going on until
  // a read shows that call over (draftingMayContinue). Then the posts still left can be drafted (two per call at most).
  const [unanswered, setUnanswered] = useState<UnansweredDraft | null>(null);
  const uncertain = unanswered !== null && draftingMayContinue(unanswered, view.slots, readAt);
  const draftButton = useRef<HTMLButtonElement>(null);
  const wasUncertain = useRef(uncertain);
  useEffect(() => {
    // The note (and its "Check again") goes once that call is over: focus that fell to the page moves to Draft.
    const active = document.activeElement;
    if (wasUncertain.current && !uncertain && (active === null || active === document.body)) draftButton.current?.focus();
    wasUncertain.current = uncertain;
  }, [uncertain]);
  const scope = useFirstWeekAction((api, w, revision, _: void) => api.scope(w, { slotIds: selected, reason: reason || undefined, expectedRevision: revision }));
  const draft = useFirstWeekAction(async (api, w, revision, _: void) =>
    (await api.draft(w, { confirmed: true, ...(view.billingMode === 'managed_credits' ? { maxCredits: credits } : {}), expectedRevision: revision })).journey
  );
  const toDraft = view.slots.filter((s) => s.committed && s.status === 'planned').length;
  function checkAgain() {
    void client.invalidateQueries({ queryKey: firstWeekKey(w) });
    refreshAfterFirstWeek(client, w);
  }
  const oneTime = view.weeklyDrafting === 'first_week_only' ? ` ${ONE_TIME}` : '';
  return (
    <div className='flex flex-col gap-4'>
      {!view.scope && <p className='text-sm'>Choose the posts this week commits to. Changing it later needs a reason, so the week’s progress stays honest.</p>}
      <ul className='flex flex-col gap-3'>
        {view.slots.map((slot) => {
          const cost = slotCostText(slot, view.billingMode);
          return (
            <li key={slot.id} className='rounded-xl border border-(--rafii-border-subtle) p-3'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <Label className='flex items-center gap-2 text-sm'>
                  {!view.scope && (
                    <Checkbox checked={selected.includes(slot.id)} onCheckedChange={(on) => setSelected((cur) => (on === true ? [...cur, slot.id] : cur.filter((id) => id !== slot.id)))} />
                  )}
                  {slot.day} · {slot.platform} · {languageLabel(slot.language)}
                </Label>
                <span className='text-muted-foreground text-xs'>{STATUS[slot.status] ?? slot.status}</span>
              </div>
              {cost && <p className='text-muted-foreground mt-1 text-xs'>{cost}</p>}
              <SlotBody slot={slot} view={view} canEdit={canEdit} />
            </li>
          );
        })}
      </ul>
      {!view.scope ? (
        <Button variant='action' className='self-start' disabled={!canEdit || !selected.length || scope.isPending}
          onClick={() => scope.mutate(undefined, { onError: (error) => toast.error('Not committed', { description: errorMessage(error) }) })}>
          {scope.isPending ? 'Saving…' : `Commit these ${selected.length} posts`}
        </Button>
      ) : (
        <details className='text-sm'>
          <summary className='cursor-pointer'>Change the committed posts</summary>
          <div className='mt-2 flex flex-col gap-2'>
            {view.slots.map((slot) => (
              <Label key={slot.id} className='flex items-center gap-2'>
                <Checkbox checked={selected.includes(slot.id)} onCheckedChange={(on) => setSelected((cur) => (on === true ? [...cur, slot.id] : cur.filter((id) => id !== slot.id)))} />
                {slot.day} · {slot.platform}
              </Label>
            ))}
            <input className={FIELD} maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} placeholder='Why the plan changes' aria-label='Why the plan changes' />
            <Button variant='glass' className='self-start' disabled={!canEdit || !reason.trim() || scope.isPending}
              onClick={() => scope.mutate(undefined, { onError: (error) => toast.error('Not changed', { description: errorMessage(error) }) })}>
              Save the change
            </Button>
          </div>
        </details>
      )}
      {uncertain && (
        <div role='status' className='flex flex-wrap items-center gap-2 rounded-xl border border-(--rafii-border-subtle) p-3 text-sm'>
          <span>The connection ended before Rafii answered, so these posts may still be drafting. Check again in a moment to see what is ready.</span>
          <Button variant='glass' size='sm' onClick={checkAgain}>
            Check again
          </Button>
        </div>
      )}
      {view.scope && toDraft > 0 && view.billingMode !== 'free_preview' && (
        <div className='flex flex-wrap items-end gap-3'>
          {view.billingMode === 'managed_credits' && view.weeklyDrafting !== 'recurring' && (
            <label className='flex flex-col gap-1 text-sm'>
              Credit limit for this week
              <input className={FIELD} aria-label='Credit limit for this week' type='number' min={1} max={3500} value={credits} onChange={(e) => setCredits(Math.max(1, Math.min(3500, Number(e.target.value) || 1)))} />
            </label>
          )}
          <Button ref={draftButton} variant='action' disabled={!canEdit || draft.isPending || uncertain}
            onClick={() => {
              const sent: UnansweredDraft = { sentAt: Date.now(), batch: draftBatch(view.slots) };
              draft.mutate(undefined, {
                onSuccess: () => setUnanswered(null),
                onError: (error) => (unknownOutcome(error) ? setUnanswered(sent) : toast.error('Drafting stopped', { description: errorMessage(error) }))
              });
            }}>
            {draft.isPending ? 'Drafting…' : `Draft the remaining ${toDraft} post${toDraft === 1 ? '' : 's'}`}
          </Button>
          <p className='text-muted-foreground w-full text-xs'>
            {view.weeklyDrafting === 'recurring'
              ? 'Weekly drafting is on: these posts use your Weekly plan’s limit.'
              : view.billingMode === 'managed_credits'
                ? `Each post is drafted against its own quote inside this limit. Paid work stops at the limit — no silent overage.${oneTime}`
                : `Uses your plan’s writing allowance.${oneTime}`}
          </p>
        </div>
      )}
      {view.scope && toDraft > 0 && view.billingMode === 'free_preview' && (
        <p className='text-muted-foreground text-sm'>
          Free doesn’t include AI drafting. Write the remaining posts yourself below, or <Link href='/app/account/billing' className='underline'>upgrade to Creator</Link> to have
          them drafted.
        </p>
      )}
      <p className='text-muted-foreground text-xs'>
        {view.delivered} of {view.committed} committed posts delivered. “Posted it myself” counts as an assisted handoff, never as a confirmed publication.
      </p>
    </div>
  );
}

function SlotBody({ slot, view, canEdit }: { slot: FirstWeekSlot; view: FirstWeekView; canEdit: boolean }) {
  const [text, setText] = useState('');
  const write = useFirstWeekAction((api, w, revision, _: void) => api.write(w, slot.id, { weekId: view.week!.id, text, expectedRevision: revision }));
  const handoff = useFirstWeekAction((api, w, revision, action: 'export_ready' | 'user_confirmed_used' | 'undo') =>
    api.handoff(w, slot.id, { weekId: view.week!.id, action, expectedRevision: revision })
  );
  const fail = (title: string) => (error: unknown) => toast.error(title, { description: errorCode(error) === 'revision_conflict' ? 'This changed in another tab. Reload and try again.' : errorMessage(error) });
  async function copyToPost(textToCopy: string) {
    // The handoff says the text was taken; it is recorded only when the copy really happened.
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(textToCopy);
    } catch {
      toast.error('Couldn’t copy the post', { description: 'Select the text and copy it yourself, then choose “I posted it” once it’s posted.' });
      return;
    }
    handoff.mutate('export_ready', { onError: fail('Not recorded') });
  }
  if (slot.status === 'rejected') return null;
  return (
    <div className='mt-2 flex flex-col gap-2'>
      {slot.reason && <p className='text-muted-foreground text-sm'>{slot.reason}</p>}
      {slot.question && <p className='text-sm'>{slot.question}</p>}
      {slot.publishBlocker === 'channel_not_connected' && (
        <p className='text-muted-foreground text-xs'>
          Publishing waits for a connected {slot.platform} account. <Link href='/app/channels' className='underline'>Connect one</Link> or post it yourself.
        </p>
      )}
      {slot.draft ? (
        <blockquote lang={slot.language === 'other' ? undefined : slot.language} className='rafii-paper rounded-lg p-3 text-sm whitespace-pre-wrap'>
          {slot.draft.text}
        </blockquote>
      ) : (
        slot.status === 'planned' &&
        slot.committed && (
          <div className='flex flex-col gap-2'>
            <Label htmlFor={`fw-write-${slot.id}`} className='text-sm'>
              Write it yourself
            </Label>
            <Textarea id={`fw-write-${slot.id}`} rows={4} maxLength={8000} value={text} lang={slot.language === 'other' ? undefined : slot.language} onChange={(e) => setText(e.target.value)} />
            <Button variant='glass' className='self-start' disabled={!canEdit || !text.trim() || write.isPending} onClick={() => write.mutate(undefined, { onError: fail('Not saved') })}>
              Save this post
            </Button>
          </div>
        )
      )}
      {slot.draft && slot.committed && (
        <div className='flex flex-wrap gap-2'>
          {slot.nextAction === 'review' || slot.nextAction === 'approve_in_queue' ? (
            <Link href={queueDraftHref(slot.variantId)} className={buttonVariants({ variant: 'glass', size: 'control' })}>
              Review in Queue
            </Link>
          ) : null}
          {(view.billingMode === 'free_preview' || slot.publishBlocker) && slot.status !== 'published' && (
            <>
              <Button variant='ghost' size='control' disabled={!canEdit || handoff.isPending} onClick={() => void copyToPost(slot.draft!.text)}>
                Copy to post myself
              </Button>
              <Button variant='ghost' size='control' disabled={!canEdit || handoff.isPending} onClick={() => handoff.mutate('user_confirmed_used', { onError: fail('Not recorded') })}>
                I posted it
              </Button>
            </>
          )}
          {slot.handoff && (
            <span className='text-muted-foreground text-xs'>
              {slot.handoff.stale ? 'Edited after you copied it — copy the new text.' : slot.handoff.state === 'user_confirmed_used' ? 'You posted it yourself.' : 'Copied — tell Rafii when it’s posted.'}{' '}
              <button type='button' className='underline' disabled={!canEdit} onClick={() => handoff.mutate('undo', { onError: fail('Not undone') })}>
                Undo
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function Delivered({ view }: { view: FirstWeekView }) {
  const published = view.slots.filter((s) => s.committed && s.status === 'published').length;
  const assisted = view.delivered - published;
  const next =
    view.weeklyDrafting === 'first_week_only'
      ? 'Rafii won’t plan or draft another week until you turn on weekly drafting in Weekly plan.'
      : 'Your weekly plan keeps going from here.';
  return (
    <StateMessage
      kind='success'
      layout='inline'
      title='Your first week is delivered'
      description={`${published} published through Rafii (confirmed by the platform)${assisted ? `, ${assisted} posted by you` : ''}. ${next}`}
    />
  );
}
