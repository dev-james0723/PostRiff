'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { parseAsString, parseAsStringLiteral, useQueryStates } from 'nuqs';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Panel, SelectField, StatTile } from '@/features/workspace/rafii-parts';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { errorMessage, isFeatureDisabled } from '@/lib/coworker/api';
import { useCoworkerFlag, useEngagementSummary, usePrepareWeek, useSlotAction, useWeek, useWeekly } from '@/lib/coworker/hooks';
import { queueDraftHref } from '@/lib/coworker/safe-href';
import type { Recipe, Slot, Week } from '@/lib/coworker/types';
import { cn } from '@/lib/utils';
import { dayLabel, nextAction, summarizeSlots, weekStateLabel, type NextAction } from '../present';
import { QueryProblem, ToneChip, WhyRafiiExplainer } from '../parts';
import { OpportunitiesPanel } from './opportunities-panel';
import { RecipeForm, RecipeSummary } from './recipe-form';
import { SlotCard } from './slot-card';

const TABS = ['week', 'opportunities', 'setup'] as const;
type Tab = (typeof TABS)[number];
const BLOCKED_WEEK = new Set(['needs_input', 'needs_source', 'needs_asset', 'channel_unavailable', 'approval_expired']);

const infoContent = {
  title: 'How the weekly review works',
  sections: [
    { title: 'You review every post', description: 'Rafii plans next week from your weekly plan, drafts what it can and checks each draft. Accepting a post moves it to Queue → Drafts; nothing is scheduled until it is approved there.' },
    { title: 'Honest states', description: '“Scheduled” and “Published” appear only when Queue has a publishing job or the platform confirmed the post.' },
    { title: 'What the checks mean', description: 'The meaning check compares the draft with your approved sources: a number, name or story that is not in them blocks “Ready”. Style and voice notes are advice only.' }
  ]
};

/**
 * The weekly review (coworker spec §12, §19): one place to see next week as a task list. The header says what is
 * ready, what is blocked and the single most useful next step; the week is grouped by day; each post shows its
 * state, draft and checks with Accept / Redo / Skip. Setup (owner) and Opportunities (when listening is on) sit
 * in their own tabs.
 */
export function WeeklyView() {
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const isOwner = checkAccess(access, { permission: 'owner' });
  const listeningOn = useCoworkerFlag('RAFII_LISTENING_ENABLED') === true;
  const engagementOn = useCoworkerFlag('RAFII_ENGAGEMENT_COPILOT_ENABLED') === true;
  const [params, setParams] = useQueryStates(
    { tab: parseAsStringLiteral(TABS).withDefault('week'), week: parseAsString, recipe: parseAsString },
    { history: 'replace', scroll: false }
  );
  const weekly = useWeekly();
  const prepare = usePrepareWeek();
  const recipes = weekly.data?.recipes ?? [];
  const recipe: Recipe | null = recipes.find((r) => r.id === params.recipe) ?? recipes.find((r) => r.status === 'active') ?? recipes[0] ?? null;
  const weeks = useMemo(() => (weekly.data?.weeks ?? []).filter((w) => !recipe || w.recipeId === recipe.id), [weekly.data, recipe]);
  const listedWeek = weeks.find((w) => w.id === params.week) ?? weeks[0] ?? null;
  const detail = useWeek(listedWeek?.id ?? null);
  const week: Week | null = detail.data?.week ?? listedWeek;
  const slotAction = useSlotAction(week?.id ?? null);
  const [focusSlot, setFocusSlot] = useState<string | null>(null);

  const tab: Tab = params.tab === 'opportunities' && !listeningOn ? 'week' : params.tab;

  useEffect(() => {
    if (!focusSlot) return;
    const node = document.getElementById(`slot-${focusSlot}`);
    if (!node) return;
    node.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    node.focus({ preventScroll: true });
  }, [focusSlot]);

  async function onPrepare() {
    if (!recipe) return;
    try {
      const result = await prepare.mutateAsync(recipe.id);
      void setParams({ week: result.week.id, tab: 'week' });
      if (!result.verified && result.advanced) {
        toast.warning('Rafii could not confirm the week’s state after preparing. Refresh to see it.');
        return;
      }
      const s = summarizeSlots(result.week.slots);
      if (!result.advanced && s.waiting > 0) {
        // The server stops drafting once the week is in review; say so instead of reporting success.
        toast.warning(`Rafii did not draft ${s.waiting === 1 ? 'the waiting post' : `${s.waiting} waiting posts`}: the rest of this week is already in review. Skip it, or write it in Ideas.`);
        return;
      }
      if (result.week.state === 'ready_for_review') toast.success(`Next week is ready for review: ${s.ready + s.needsRevision} post${s.ready + s.needsRevision === 1 ? '' : 's'}. Nothing is scheduled.`);
      else if (s.blocked > 0) toast.message(`Next week is planned. ${s.blocked} post${s.blocked === 1 ? ' needs' : 's need'} you before Rafii can finish.`);
      else toast.success('Next week is planned.');
    } catch (err) {
      toast.error(errorMessage(err, 'The week could not be prepared.'));
    }
  }

  const action = nextAction({ hasRecipe: Boolean(recipe), canSetUp: isOwner, week });
  // The next-step card carries "prepare" / "draft waiting posts" when that is the step; otherwise the header offers it quietly.
  const headerAction =
    recipe && recipe.status === 'active' && canEdit && action.kind !== 'prepare' && action.kind !== 'continue' ? (
      <Button variant='glass' size='control' disabled={prepare.isPending} onClick={() => void onPrepare()} aria-describedby='prepare-hint'>
        {prepare.isPending ? <Icons.spinner className='size-4 animate-spin motion-reduce:animate-none' aria-hidden /> : <Icons.sparkles className='size-4' aria-hidden />}
        {prepare.isPending ? 'Preparing…' : 'Prepare next week now'}
      </Button>
    ) : undefined;

  if (weekly.isError && isFeatureDisabled(weekly.error)) {
    return (
      <PageContainer pageTitle='Weekly' pageAccent='review' width='reading'>
        <StateMessage kind='unsupported' title='The weekly review is not turned on for this workspace yet.' description='Your drafts, Queue and automations work as before.' />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      pageTitle='Weekly'
      pageAccent='review'
      pageDescription='Next week as a task list: what is ready, what is blocked, and what to do next. Nothing is scheduled until you approve it in Queue.'
      infoContent={infoContent}
      pageHeaderAction={headerAction}
    >
      <span id='prepare-hint' className='sr-only'>
        Plans next week and drafts what it can. Uses the weekly drafting limit. Nothing is scheduled.
      </span>
      {prepare.isPending && (
        <p role='status' className='rafii-quiet text-foreground rounded-[var(--rafii-radius-control)] px-4 py-3 text-sm'>
          Rafii is planning and drafting next week. This can take a minute; you can leave this page.
        </p>
      )}
      {weekly.isPending ? (
        <StateMessage kind='loading' title='Loading your week…' />
      ) : weekly.isError ? (
        <QueryProblem error={weekly.error} onRetry={() => void weekly.refetch()} what='The weekly review' />
      ) : (
        <div className='flex flex-col gap-5'>
          <NextStepCard
            action={action}
            week={week}
            recipe={recipe}
            canEdit={canEdit}
            preparing={prepare.isPending}
            onPrepare={() => void onPrepare()}
            onSetup={() => void setParams({ tab: 'setup' })}
            onFocus={(slotId) => {
              void setParams({ tab: 'week' });
              setFocusSlot(null);
              window.setTimeout(() => setFocusSlot(slotId), 0);
            }}
          />
          {engagementOn && <InboxSummary />}
          <SegmentedControl<Tab>
            label='Weekly sections'
            pattern='tabs'
            widths='content'
            value={tab}
            onChange={(value) => void setParams({ tab: value })}
            // Only the open tab's panel is rendered, so only its tab points at a panel.
            panelIds={(listeningOn ? ['week', 'opportunities', 'setup'] : ['week', 'setup']).map((name) => (name === tab ? `weekly-panel-${name}` : undefined)) as string[]}
            options={[
              { value: 'week', label: 'This week' },
              ...(listeningOn ? [{ value: 'opportunities' as const, label: 'Opportunities' }] : []),
              { value: 'setup', label: recipe ? 'Weekly plan' : 'Set up' }
            ]}
            className='self-start'
          />
          {tab === 'week' && (
            <section id='weekly-panel-week' role='tabpanel' aria-label='This week' className='flex flex-col gap-5'>
              {!recipe ? (
                <StateMessage
                  kind='empty'
                  title='No weekly plan yet.'
                  description={isOwner ? 'Set up which accounts, how often and what for. Rafii prepares the week from it.' : 'An owner sets up the weekly plan.'}
                  action={
                    isOwner ? (
                      <Button variant='action' size='control' onClick={() => void setParams({ tab: 'setup' })}>
                        Set up your week
                      </Button>
                    ) : undefined
                  }
                />
              ) : !week ? (
                <StateMessage kind='empty' title='No week prepared yet.' description={recipe.status === 'paused' ? 'The weekly plan is paused. Resume it in Weekly plan to prepare a week.' : 'Prepare next week to see its posts here.'} />
              ) : (
                <WeekBoard
                  week={week}
                  weeks={weeks}
                  loadingDrafts={detail.isPending}
                  draftsError={detail.isError ? errorMessage(detail.error) : null}
                  onPickWeek={(id) => void setParams({ week: id })}
                  canEdit={canEdit}
                  action={slotAction}
                  focusSlot={focusSlot}
                />
              )}
              <WhyRafiiExplainer />
              <p className='text-muted-foreground text-xs'>
                Voice, brand and strategy notes that shape these drafts are in{' '}
                <Link href='/app/workspace/personalization' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
                  Personalization
                </Link>
                .
              </p>
            </section>
          )}
          {tab === 'opportunities' && listeningOn && (
            <section id='weekly-panel-opportunities' role='tabpanel' aria-label='Opportunities'>
              <OpportunitiesPanel canEdit={canEdit} />
            </section>
          )}
          {tab === 'setup' && (
            <section id='weekly-panel-setup' role='tabpanel' aria-label='Weekly plan' className='flex flex-col gap-4'>
              {recipes.length > 1 && (
                <SelectField label='Weekly plan' value={recipe?.id ?? ''} onChange={(e) => void setParams({ recipe: e.target.value, week: null })} className='max-w-sm'>
                  {recipes.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                      {r.status === 'paused' ? ' (paused)' : ''}
                    </option>
                  ))}
                </SelectField>
              )}
              <RecipeForm key={`${recipe?.id ?? 'new'}:${recipe?.version ?? 0}`} recipe={recipe} isOwner={isOwner} onSaved={(saved) => void setParams({ recipe: saved.id })} />
              {recipe && !isOwner && <RecipeSummary recipe={recipe} />}
            </section>
          )}
        </div>
      )}
    </PageContainer>
  );
}

function NextStepCard({
  action,
  week,
  recipe,
  canEdit,
  preparing,
  onPrepare,
  onSetup,
  onFocus
}: {
  action: NextAction;
  week: Week | null;
  recipe: Recipe | null;
  canEdit: boolean;
  preparing: boolean;
  onPrepare: () => void;
  onSetup: () => void;
  onFocus: (slotId: string) => void;
}) {
  const s = week ? summarizeSlots(week.slots) : null;
  const accepted = week?.slots.find((slot) => slot.status === 'accepted');
  let button: ReactNode = null;
  if (action.kind === 'setup') {
    button = (
      <Button variant='action' size='control' onClick={onSetup}>
        {action.label}
      </Button>
    );
  } else if ((action.kind === 'prepare' || action.kind === 'continue') && canEdit && recipe?.status === 'active') {
    button = (
      <Button variant='action' size='control' disabled={preparing} onClick={onPrepare} aria-describedby='prepare-hint'>
        {preparing ? 'Preparing…' : action.label}
      </Button>
    );
  } else if (action.kind === 'queue') {
    button = (
      <Link href={queueDraftHref(accepted?.variantId)} className={buttonVariants({ variant: 'action', size: 'control' })}>
        {action.label}
      </Link>
    );
  } else if (action.slotId) {
    button = (
      <Button variant='action' size='control' onClick={() => onFocus(action.slotId as string)}>
        {action.label}
      </Button>
    );
  }
  return (
    <Panel
      material='glass'
      eyebrow={week ? `Week of ${dayLabel(week.weekOf)}` : 'Next step'}
      title={<span data-next-action={action.kind}>{action.kind === 'none' || !button ? action.label : 'Next: ' + action.label.charAt(0).toLowerCase() + action.label.slice(1)}</span>}
      titleId='weekly-next-heading'
      description={action.why}
      actions={button}
    >
      {week && s && (
        <div className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center gap-2'>
            <ToneChip tone={BLOCKED_WEEK.has(week.state) ? 'attention' : week.state === 'ready_for_review' ? 'success' : 'neutral'} icon={BLOCKED_WEEK.has(week.state) ? 'warning' : 'calendarEvent'}>
              {weekStateLabel(week.state)}
            </ToneChip>
            {week.blockedReason && <span className='text-muted-foreground text-sm'>{week.blockedReason}</span>}
          </div>
          <div className='grid grid-cols-2 gap-2 sm:grid-cols-4'>
            <StatTile label='Ready to review' value={s.ready + s.needsRevision} hint={s.needsRevision ? `${s.needsRevision} need${s.needsRevision === 1 ? 's' : ''} revision` : undefined} className='p-3 md:p-4' />
            <StatTile label='Blocked' value={s.blocked} hint={s.blocked ? 'Needs you' : undefined} className='p-3 md:p-4' />
            <StatTile label='Waiting to draft' value={s.waiting} className='p-3 md:p-4' />
            <StatTile label='In Queue or later' value={s.handed} className='p-3 md:p-4' />
          </div>
        </div>
      )}
    </Panel>
  );
}

function InboxSummary() {
  const engagement = useEngagementSummary();
  if (!engagement.data) return null;
  const needs = engagement.data.counts.needs_reply ?? 0;
  const review = engagement.data.counts.review ?? 0;
  return (
    <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between'>
      <p className='text-sm'>
        <span className='text-foreground font-medium'>Inbox: </span>
        <span className='text-muted-foreground'>{needs || review ? `${needs} need${needs === 1 ? 's' : ''} a reply · ${review} to review` : 'Nothing waiting for a reply.'}</span>
      </p>
      <Link href='/app/inbox' className={cn(buttonVariants({ variant: 'glass', size: 'default' }), 'min-h-11 w-fit px-3')}>
        Open Inbox
      </Link>
    </div>
  );
}

function WeekBoard({
  week,
  weeks,
  loadingDrafts,
  draftsError,
  onPickWeek,
  canEdit,
  action,
  focusSlot
}: {
  week: Week;
  weeks: Week[];
  loadingDrafts: boolean;
  draftsError: string | null;
  onPickWeek: (id: string) => void;
  canEdit: boolean;
  action: ReturnType<typeof useSlotAction>;
  focusSlot: string | null;
}) {
  const days = useMemo(() => {
    const map = new Map<string, Slot[]>();
    for (const slot of week.slots.toSorted((a, b) => a.localTime.localeCompare(b.localTime))) {
      const list = map.get(slot.day) ?? [];
      list.push(slot);
      map.set(slot.day, list);
    }
    return [...map.entries()].toSorted(([a], [b]) => a.localeCompare(b));
  }, [week.slots]);

  return (
    <div className='flex flex-col gap-5'>
      {weeks.length > 1 && (
        <SelectField label='Week' value={week.id} onChange={(e) => onPickWeek(e.target.value)} className='max-w-xs'>
          {weeks.map((w) => (
            <option key={w.id} value={w.id}>
              Week of {dayLabel(w.weekOf)}
            </option>
          ))}
        </SelectField>
      )}
      {loadingDrafts && <p className='text-muted-foreground text-xs' role='status'>Loading drafts…</p>}
      {draftsError && <StateMessage kind='partial' layout='inline' title='Drafts could not be loaded.' description={draftsError} />}
      {days.length === 0 && <StateMessage kind='empty' title='This week has no posts planned.' description='Check the weekly plan: every account may be set to zero posts.' />}
      {days.map(([day, slots]) => (
        <section key={day} aria-labelledby={`day-${day}`} className='flex flex-col gap-2'>
          <h3 id={`day-${day}`} className='rafii-serif text-foreground text-lg'>
            {dayLabel(day)}
            <span className='text-muted-foreground ml-2 font-sans text-xs'>
              {slots.length} post{slots.length === 1 ? '' : 's'}
            </span>
          </h3>
          <div className='flex flex-col gap-2'>
            {slots.map((slot) => (
              <SlotCard key={slot.id} slot={slot} weekState={week.state} canEdit={canEdit} action={action} highlight={focusSlot === slot.id} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
