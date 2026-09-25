'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { InfoTip, RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/motion/checkbox';
import { StatusChip, type StatusTone } from '@/features/queue/status-chip';
import { ApiError } from '@/lib/api/client';
import { useMe, useModels } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { languageLabel } from '@/lib/locales';
import { useTimeZone } from '@/lib/preferences';
import { cn } from '@/lib/utils';
import type { RecurringOccurrence, RunItem } from '@/lib/api/types';
import { AutomationBuilder, blankInitial, initialFromAutomation, initialFromBrief, type BuilderInitial } from './automation-builder';
import { RunDecisionDialog, type DecisionTarget, type RunDecision } from './run-decision';
import { RunDetail, awaitingApproval, isWorkflowRun, runStatus } from './run-history';
import { ceilingMicro, ceilingText, isTrigger, runLabel, runText, scheduleSummary, statusText, usd } from './schedule';
import { finished, monthStart, spentSince, unseen, useAutomations, type Automation } from './use-automations';
import { policyText, researchRule, stageRules } from './workflow';
import { AUTOMATION_CHANGED, usePanel } from '@/features/site-agent/store';
import { useSiteAgentPageContext } from '@/features/site-agent/use-page-context';

const infoContent = {
  title: 'Automations',
  sections: [
    { title: 'Drafts by default', description: 'Automations built here only draft. One set up in chat can also wait for your approval of each post, or publish automatically once an owner allows it.' },
    { title: 'Owners activate', description: 'Editors create and edit. Only an owner activates, pauses or cancels. Editing anything but the name returns it to draft.' },
    { title: 'Budget', description: 'A run quoted above its cost limit is held, never charged.' },
    { title: 'Late runs', description: 'A run more than a day late, for example after a pause, is skipped rather than caught up.' }
  ]
};

const STATUS_TONE: Record<string, StatusTone> = { active: 'success', draft: 'neutral', paused: 'warning', cancelled: 'neutral' };
const RUN_TONE: Record<string, StatusTone> = { quiet: 'neutral', success: 'success', attention: 'warning', failure: 'danger' };

/** "Paused until Fri 3 Oct" for a pause that resumes on its own. */
function pausedUntilLabel(task: Automation['task']): string | null {
  if (task.status !== 'paused' || !task.pausedUntil) return null;
  try {
    return `Paused until ${new Intl.DateTimeFormat(undefined, { timeZone: task.schedule.timeZone, weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(task.pausedUntil * 1000))}`;
  } catch {
    return `Paused until ${new Date(task.pausedUntil * 1000).toLocaleDateString()}`;
  }
}

export function AutomationsView() {
  const params = useSearchParams();
  const router = useRouter();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const isOwner = checkAccess(access, { permission: 'owner' });
  const canApproveRole = checkAccess(access, { permission: 'approve' });
  const timeZone = useTimeZone();
  const models = useModels();
  const me = useMe();
  const userId = me.data?.userId ?? null;
  const { snapshot, state, automations, briefs, act, busy } = useAutomations();
  const [builder, setBuilder] = useState<{ key: number; initial: BuilderInitial } | null>(null);
  useSiteAgentPageContext(builder?.initial.taskId ? { selectedEntity: { type: 'automation', id: builder.initial.taskId }, visibleState: { editing: true } } : null);
  const [cancelling, setCancelling] = useState<Automation | null>(null);
  const [activating, setActivating] = useState<Automation | null>(null);
  const [deciding, setDeciding] = useState<DecisionTarget | null>(null);
  const [now] = useState(() => Date.now() / 1000);
  const opened = useRef<string | null>(null);

  const open = (initial: BuilderInitial) => setBuilder((current) => ({ key: (current?.key ?? 0) + 1, initial }));

  // Rafii applied a change to the automation open here: re-read it, so a later save can't quietly restore the old plan.
  // It waits until Rafii's sheet above the builder is closed, so the reopened builder never covers the answer.
  const [reread, setReread] = useState<string | null>(null);
  const rafiiAbove = usePanel((s) => s.above);
  const builderTask = useRef<string | null>(null);
  useEffect(() => {
    builderTask.current = builder?.initial.taskId ?? null;
  }, [builder]);
  useEffect(() => {
    const onChanged = (event: Event) => {
      const taskId = (event as CustomEvent<{ taskId?: string }>).detail?.taskId;
      if (taskId && taskId === builderTask.current) setReread(taskId);
    };
    window.addEventListener(AUTOMATION_CHANGED, onChanged);
    return () => window.removeEventListener(AUTOMATION_CHANGED, onChanged);
  }, []);
  useEffect(() => {
    if (!reread || rafiiAbove) return;
    const found = automations.find((item) => item.task.id === reread);
    if (found && found.task.status !== 'cancelled' && builderTask.current === reread) open(initialFromAutomation(found, timeZone));
    setReread(null);
  }, [reread, rafiiAbove, automations, timeZone]);

  // Deep links: ?new=1 starts a blank automation, ?campaign=<id> schedules a brief, ?edit=<taskId> edits one.
  useEffect(() => {
    if (!state || !canEdit) return;
    const signature = params.toString();
    if (!signature || opened.current === signature) return;
    opened.current = signature;
    const campaignId = params.get('campaign');
    const editId = params.get('edit');
    if (params.get('new') === '1') open(blankInitial(timeZone));
    else if (campaignId) {
      const campaign = state.raffi?.campaignPlanning?.campaigns.find((item) => item.id === campaignId);
      if (campaign) open(initialFromBrief(campaign, timeZone));
    } else if (editId) {
      const found = automations.find((item) => item.task.id === editId);
      if (found && found.task.status !== 'cancelled') open(initialFromAutomation(found, timeZone));
    }
  }, [state, canEdit, params, automations, timeZone]);

  // A deleted automation is cancelled and hidden; its run history stays on the server for audit.
  const visible = automations.filter((a) => !a.task.deletedAt);
  const live = visible.filter((a) => a.task.status !== 'cancelled');
  const cancelled = visible.filter((a) => a.task.status === 'cancelled');
  // Approving posts is its own permission (owner, approvers); sample workspaces refuse every command.
  const canApprove = canApproveRole && !state?.workspace?.sample;
  const active = live.filter((a) => a.task.status === 'active' && !finished(a));
  const waiting = live.filter((a) => statusText(a.task).needsOwner || statusText(a.task).needsEdit);
  const toReview = visible.reduce((sum, a) => sum + unseen(a).length, 0);
  const sinceMonth = monthStart(now);
  const spentThisMonth = automations.reduce((sum, a) => sum + spentSince(a, sinceMonth), 0);
  const next = active
    .map((a) => ({ a, at: a.task.nextOccurrence?.scheduledFor ?? (a.task.nextOccurrence ? Date.parse(a.task.nextOccurrence.utc) / 1000 : Infinity) }))
    .toSorted((x, y) => x.at - y.at)[0];
  const ceiling = active.reduce((sum, a) => sum + ceilingMicro(a.task.maxCostUsdMicro, a.task.schedule), 0);
  const writerLabel = useMemo(() => new Map((models.data?.models ?? []).map((m) => [m.id, m.label])), [models.data]);

  async function run(action: string, automation: Automation, success: string | null, extra: Record<string, unknown> = { confirmed: true }) {
    try {
      await act(action, { taskId: automation.task.id, ...extra });
      if (success) toast.success(success);
      return true;
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Couldn’t update this automation. Try again.');
      return false;
    }
  }

  /** Activation: an `auto` workflow needs the owner's explicit standing permission to publish. */
  function activate(automation: Automation) {
    const policy = automation.task.workflow?.policy;
    if (policy === 'auto') {
      setActivating(automation);
      return;
    }
    // The card's status chip shows the result; no toast.
    void run('raffi_recurrence_activate', automation, null);
  }

  function decide(automation: Automation, occurrence: RecurringOccurrence, item: RunItem, decision: RunDecision) {
    setDeciding({ run: occurrence, item, decision, automationName: automation.name, timeZone: automation.task.schedule.timeZone });
  }

  /** Opening a run's drafts marks that run as seen for the workspace (editors), then navigates. */
  async function openRun(automation: Automation, runId: string, conversationId: string) {
    if (canEdit && automation.runs.find((r) => r.id === runId && !r.seenAt)) await run('raffi_recurrence_seen', automation, null, { occurrenceIds: [runId] });
    router.push(`/app/agent/${encodeURIComponent(conversationId)}`);
  }

  return (
    <PageContainer
      pageTitle='Automations'
      infoContent={infoContent}
      pageHeaderAction={
        // The empty state carries the one "New automation" action when there is nothing yet.
        canEdit && (snapshot.isLoading || live.length > 0) ? (
          <Button variant='action' size='control' onClick={() => open(blankInitial(timeZone))}>
            <Icons.add />
            New automation
          </Button>
        ) : undefined
      }
    >
      {snapshot.isLoading ? (
        <Skeleton className='h-16 w-full rounded-[var(--rafii-radius-card)]' />
      ) : (
        <>
          {/* One compact strip instead of a card per number: counts, the next run and this month's money. */}
          {(live.length > 0 || spentThisMonth > 0) && (
            <Surface as='section' aria-label='Automation summary' material='quiet' padding='sm' className='flex flex-wrap items-center gap-x-8 gap-y-3 px-4'>
              <dl className='flex flex-wrap items-end gap-x-8 gap-y-3'>
                <Stat label='Active' value={String(active.length)} />
                {waiting.length > 0 && <Stat label='Needs you' value={String(waiting.length)} />}
                {toReview > 0 && <Stat label='To review' value={String(toReview)} />}
                {next && Number.isFinite(next.at) && <Stat label='Next run' value={runLabel(next.at * 1000, next.a.task.schedule.timeZone)} title={next.a.name} />}
                <Stat label='Spent this month' value={usd(spentThisMonth)} />
                {active.length > 0 && (
                  <Stat
                    label='Monthly limit'
                    value={usd(ceiling)}
                    tip={<InfoTip label='About the monthly limit' className='-my-3 -ml-2' description='The most your active automations can spend in a month. A countdown counts in full.' />}
                  />
                )}
              </dl>
              <Link href='/app/account/billing' className='rafii-focus text-muted-foreground hover:text-foreground ml-auto inline-flex min-h-11 items-center gap-1 rounded-md text-xs'>
                  Usage
                  <Icons.arrowRight className='size-3.5' />
                </Link>
            </Surface>
          )}

          {live.length === 0 ? (
            <StateMessage
              kind='empty'
              title='No automations yet'
              action={
                canEdit ? (
                  <Button variant='action' size='control' onClick={() => open(blankInitial(timeZone))}>
                    <Icons.add />
                    New automation
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <ul className='flex flex-col gap-3' aria-label='Automations'>
              {live.map((automation) => (
                <li key={automation.task.id}>
                  <AutomationCard
                    automation={automation}
                    canEdit={canEdit}
                    isOwner={isOwner}
                    canApprove={canApprove}
                    busy={busy}
                    spent={spentSince(automation, sinceMonth)}
                    watching={Boolean(userId && automation.task.emailWatchers?.includes(userId))}
                    onWatch={(email) => void run('raffi_recurrence_watch', automation, null, { email })}
                    onSeen={() => void run('raffi_recurrence_seen', automation, null, {})}
                    writer={automation.task.route ? (writerLabel.get(automation.task.route) ?? automation.task.route) : 'No writer'}
                    onEdit={() => open(initialFromAutomation(automation, timeZone))}
                    onActivate={() => activate(automation)}
                    onPause={() => void run('raffi_recurrence_pause', automation, null)}
                    onResume={() => void run('raffi_recurrence_resume', automation, null)}
                    onCancel={() => setCancelling(automation)}
                    onOpenRun={(runId, conversationId) => void openRun(automation, runId, conversationId)}
                    onDecide={(occurrence, item, decision) => decide(automation, occurrence, item, decision)}
                  />
                </li>
              ))}
            </ul>
          )}

          {briefs.length > 0 && (
            <section className='flex flex-col gap-2' aria-labelledby='automation-briefs'>
              <h2 id='automation-briefs' className='text-base font-semibold'>
                Unscheduled briefs
              </h2>
              <ul className='flex flex-col gap-2'>
                {briefs.map((campaign) => (
                  <li key={campaign.id}>
                    <Surface material='quiet' radius='control' padding='sm' className='flex flex-wrap items-center gap-3'>
                      <span className='flex min-w-0 flex-[1_1_12rem] flex-col'>
                        <span className='text-sm font-medium'>{campaign.goal}</span>
                        <span className='text-muted-foreground text-xs'>
                          <span className='hidden md:inline'>{campaign.audience}</span>
                          {campaign.missingFacts.length ? <span><span className='hidden md:inline'> · </span>needs {campaign.missingFacts.join(' and ')}</span> : null}
                        </span>
                      </span>
                      {canEdit && (
                        <Button variant='glass' size='sm' className='min-h-11' onClick={() => open(initialFromBrief(campaign, timeZone))} aria-label={`Schedule “${campaign.goal}”`}>
                          Schedule
                        </Button>
                      )}
                    </Surface>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {cancelled.length > 0 && (
            <Collapsible>
              <CollapsibleTrigger className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm'>
                <Icons.chevronDown className='size-4' />
                Cancelled ({cancelled.length})
              </CollapsibleTrigger>
              <CollapsibleContent>
                <ul className='mt-2 flex flex-col gap-2'>
                  {cancelled.map((automation) => (
                    <li key={automation.task.id}>
                      <Surface material='quiet' radius='control' padding='sm' className='flex flex-wrap items-center gap-3 text-sm'>
                        <span className='min-w-0 flex-[1_1_12rem] truncate'>{automation.name}</span>
                        <span className='text-muted-foreground hidden text-xs md:inline'>{automation.drafted.length} run{automation.drafted.length === 1 ? '' : 's'} with drafts</span>
                        {automation.drafted[0]?.conversationId && (
                          <Button variant='quiet' size='sm' className='min-h-11' onClick={() => router.push(`/app/agent/${encodeURIComponent(automation.drafted[0].conversationId!)}`)}>
                            Latest drafts
                          </Button>
                        )}
                      </Surface>
                    </li>
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          )}
        </>
      )}

      {builder && (
        <AutomationBuilder
          key={builder.key}
          open
          onOpenChange={(next) => {
            if (!next) {
              setBuilder(null);
              if (params.toString()) router.replace('/app/automations');
            }
          }}
          initial={builder.initial}
          isOwner={isOwner}
          act={act}
        />
      )}

      <RunDecisionDialog target={deciding} onClose={() => setDeciding(null)} act={act} />

      <ActivateAutoDialog
        automation={activating}
        busy={busy}
        onClose={() => setActivating(null)}
        onConfirm={async (target, sourceUse) => {
          const ok = await run('raffi_recurrence_activate', target, null, { confirmed: true, publishAuthority: { confirmed: true, sourceUse } });
          if (ok) setActivating(null);
        }}
      />

      <RafiiDialog open={cancelling !== null} onOpenChange={(next) => !next && setCancelling(null)}>
        <RafiiDialogContent size='sm'>
          <RafiiDialogHeader title='Cancel' accent={cancelling ? `“${cancelling.name}”?` : undefined} intro='No more drafts will be prepared, and it can’t be restarted. Drafts it already made stay.' />
          <RafiiDialogBody>
            <p className='text-muted-foreground text-sm'>{cancelling ? scheduleSummary(cancelling.task.schedule) : ''}</p>
          </RafiiDialogBody>
          <RafiiDialogFooter className='flex-row flex-wrap justify-end gap-2'>
            <Button variant='quiet' size='control' onClick={() => setCancelling(null)}>
              Keep it
            </Button>
            <Button
              variant='action'
              size='control'
              disabled={busy}
              onClick={() => {
                const target = cancelling;
                setCancelling(null);
                if (target) void run('raffi_recurrence_cancel', target, 'Automation cancelled');
              }}
            >
              Cancel automation
            </Button>
          </RafiiDialogFooter>
        </RafiiDialogContent>
      </RafiiDialog>
    </PageContainer>
  );
}

/**
 * The owner's standing permission for an `auto` workflow (`publishAuthority`, orchestration §4): required to activate
 * it. `sourceUse` also lets posts built on sources Rafii found publish without a per-source review.
 */
function ActivateAutoDialog({ automation, busy, onClose, onConfirm }: { automation: Automation | null; busy: boolean; onClose: () => void; onConfirm: (automation: Automation, sourceUse: boolean) => Promise<void> }) {
  const [allow, setAllow] = useState(false);
  const [sourceUse, setSourceUse] = useState(false);
  const [shownFor, setShownFor] = useState<string | null>(null);
  const id = automation?.task.id ?? null;
  if (id !== shownFor) {
    setShownFor(id);
    setAllow(false);
    setSourceUse(false);
  }
  const workflow = automation?.task.workflow;
  const rules = workflow ? stageRules(workflow) : [];
  return (
    <RafiiDialog open={automation !== null} onOpenChange={(next) => !next && onClose()}>
      <RafiiDialogContent size='sm'>
        <RafiiDialogHeader
          title='Publish'
          accent='automatically?'
          intro='Posts that pass every safety check publish at their time without asking you. Anything else (unknown claims, unchecked sources, an unverified quote, an account problem) waits for your approval, with the reason.'
        />
        <RafiiDialogBody className='flex flex-col gap-3'>
          {automation && (
            <>
              <p className='text-sm font-medium'>{automation.name}</p>
              <p className='text-muted-foreground text-sm'>{scheduleSummary(automation.task.schedule)}</p>
              {rules.length > 0 && (
                <ol className='flex flex-col gap-0.5 text-sm'>
                  {rules.map((rule) => (
                    <li key={rule.step}>
                      <span className='text-muted-foreground'>{rule.label}</span> {rule.when}
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
          <Checkbox checked={allow} onCheckedChange={setAllow} label='I allow Rafii to publish these posts automatically at their time.' className='min-h-11 items-start gap-2.5 [&>span]:text-sm' />
          {workflow?.research && (
            <Checkbox
              checked={sourceUse}
              onCheckedChange={setSourceUse}
              label='Also publish posts built on sources Rafii finds, without asking me about each source (optional).'
              className='min-h-11 items-start gap-2.5 [&>span]:text-sm'
            />
          )}
          <p className='text-muted-foreground text-xs'>Pause it any time. Editing returns it to draft.</p>
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row flex-wrap justify-end gap-2'>
          <Button variant='quiet' size='control' onClick={onClose}>
            Not now
          </Button>
          <Button variant='action' size='control' disabled={busy || !allow || !automation} onClick={() => automation && void onConfirm(automation, Boolean(workflow?.research) && sourceUse)}>
            <Icons.bolt />
            Activate
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/** One number in the summary strip: a small label over the value. */
function Stat({ label, value, title, tip }: { label: string; value: string; title?: string; tip?: React.ReactNode }) {
  return (
    <div className='flex min-w-0 flex-col gap-0.5'>
      <dt className='text-muted-foreground flex items-center text-xs'>
        {label}
        {tip}
      </dt>
      <dd className='text-foreground text-base font-medium tabular-nums' title={title}>
        {value}
      </dd>
    </div>
  );
}

interface CardProps {
  automation: Automation;
  canEdit: boolean;
  isOwner: boolean;
  canApprove: boolean;
  busy: boolean;
  spent: number;
  watching: boolean;
  onWatch: (email: boolean) => void;
  onSeen: () => void;
  writer: string;
  onEdit: () => void;
  onActivate: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onOpenRun: (runId: string, conversationId: string) => void;
  onDecide: (run: RecurringOccurrence, item: RunItem, decision: RunDecision) => void;
}

function AutomationCard({ automation, canEdit, isOwner, canApprove, busy, spent, watching, onWatch, onSeen, writer, onEdit, onActivate, onPause, onResume, onCancel, onOpenRun, onDecide }: CardProps) {
  const { task, campaign, destinations, runs, legacy } = automation;
  const done = finished(automation);
  const pausedUntil = pausedUntilLabel(task);
  const base = done
    ? { label: 'Finished', detail: task.schedule.kind === 'once' ? 'Its date has passed.' : 'All countdown dates have passed. Edit the event date to reuse it.', needsOwner: false, needsEdit: false }
    : statusText(task);
  const status = pausedUntil ? { ...base, label: pausedUntil, detail: 'Resumes on its own. An owner can resume it sooner.', needsOwner: false } : base;
  const workflow = task.workflow ?? null;
  const policy = workflow ? policyText(workflow.policy) : null;
  const rules = workflow ? stageRules(workflow) : [];
  const research = researchRule(workflow?.research);
  const noPolicy = Boolean(workflow && !workflow.policy);
  const waiting = runs.reduce((sum, r) => sum + awaitingApproval(r).length, 0);
  // Auto-publish posts that failed a safety check wait for approval instead; each says why.
  const heldBack = runs.flatMap((r) => (r.policy === 'auto' ? (r.items ?? []).filter((item) => item.state === 'ready_for_review' && item.publishAt && item.reason).map((item) => ({ runId: r.id, item })) : []));
  const fresh = unseen(automation);
  const labels = task.accountLabels ?? {};
  const platforms = Array.from(new Set(destinations.map((d) => d.platform)));
  const accountsCount = new Set(destinations.map((d) => d.channelId ?? d.platform)).size;
  const languages = Array.from(new Set(destinations.map((d) => d.language)));
  const where = task.destinationLabel ?? (destinations.length === 1 && destinations[0].channelId ? labels[destinations[0].channelId] || destinations[0].platform : `${accountsCount} ${destinations.some((d) => d.channelId) ? 'account' : 'app'}${accountsCount === 1 ? '' : 's'}`);
  const nextAt = task.nextOccurrence?.scheduledFor ?? (task.nextOccurrence ? Date.parse(task.nextOccurrence.utc) / 1000 : null);
  const latest = runs[0];
  const latestText = latest ? (isWorkflowRun(latest) ? { ...runStatus(latest), detail: undefined as string | undefined, v3: true } : { ...runText(latest), v3: false }) : null;
  const lastDrafts = automation.drafted[0];
  const missing = campaign?.missingFacts ?? [];

  return (
    <Surface as='article' material='glass' padding='md' className='flex flex-col gap-4' aria-labelledby={`automation-${task.id}`}>
      <div className='flex flex-wrap items-start gap-3'>
        <span className='rafii-quiet flex size-10 shrink-0 items-center justify-center rounded-xl'>
          <Icons.bolt className='size-5' />
        </span>
        <div className='flex min-w-0 flex-[1_1_14rem] flex-col gap-0.5'>
          <h2 id={`automation-${task.id}`} className='text-foreground text-base font-medium'>
            {automation.name}
          </h2>
          <p className='text-muted-foreground text-sm'>{scheduleSummary(task.schedule)}</p>
        </div>
        <span className='flex flex-wrap items-center gap-1.5'>
          {waiting > 0 && <StatusChip tone='warning' size='md'>{waiting} to approve</StatusChip>}
          {fresh.length > 0 && <StatusChip tone='info' size='md' icon={<Icons.sparkles />}>{fresh.length} new</StatusChip>}
          <StatusChip tone={done ? 'neutral' : (STATUS_TONE[task.status] ?? 'neutral')} size='md' icon={pausedUntil ? <Icons.pause /> : undefined}>
            {status.label}
          </StatusChip>
        </span>
      </div>

      {/* Always visible: where, what, the next run, how posts go out and the money. The rest is under Details. */}
      <dl className='grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 xl:grid-cols-4'>
        <Fact term='Where'>
          <span className='inline-flex items-center gap-2'>
            <span aria-hidden className='flex items-center'>
              {platforms.slice(0, 3).map((platform, index) => (
                <ChannelIcon key={platform} platform={platform} size='sm' className={cn('ring-background rounded-lg ring-2', index > 0 && '-ml-2')} />
              ))}
            </span>
            <span className='min-w-0'>
              {where} · {languages.map((l) => languageLabel(l)).join(', ')}
            </span>
          </span>
        </Fact>
        <Fact term='What'>{legacy ? 'One LinkedIn draft (earlier planner)' : (task.contentLabel ?? 'General writing')}</Fact>
        <Fact term={task.status === 'active' && !done ? 'Next run' : 'Schedule'}>
          {done
            ? 'Finished'
            : task.status === 'active' && isTrigger(task.schedule)
              ? nextAt
                ? 'Starting now'
                : task.schedule.kind === 'on_strong_post'
                  ? 'Watching your posts'
                  : 'Waiting for something new in Ideas'
              : task.status === 'active' && nextAt
                ? runLabel(nextAt * 1000, task.schedule.timeZone)
                : task.status === 'draft'
                  ? 'Starts after activation'
                  : 'Not running'}
          {isTrigger(task.schedule) && (task.skippedEvents ?? 0) > 0 && <span className='text-muted-foreground block text-xs'>{task.skippedEvents} skipped (daily limit)</span>}
        </Fact>
        <Fact term='Budget'>
          Up to {usd(task.maxCostUsdMicro ?? 0)} a run
          <span className='text-muted-foreground block text-xs'>{ceilingText(task.maxCostUsdMicro, task.schedule)}</span>
          <span className='text-muted-foreground block text-xs'>{usd(spent)} spent this month</span>
        </Fact>
        {policy && (
          <Fact term='Publishing'>
            <span className='inline-flex items-center'>
              {policy.label}
              <InfoTip label={`About publishing: ${policy.label}`} className='-my-3' description={policy.detail} />
            </span>
          </Fact>
        )}
      </dl>

      {heldBack.length > 0 && (
        <ul className='flex flex-col gap-1 text-sm' aria-label='Held back for approval'>
          {heldBack.slice(0, 3).map(({ runId, item }) => (
            <li key={`${runId}:${item.key}`} className='text-muted-foreground flex items-start gap-2'>
              <Icons.warning className='mt-0.5 size-4 shrink-0' />
              <span className='min-w-0 break-words'>
                {item.platform} held for approval: {item.reason}
              </span>
            </li>
          ))}
        </ul>
      )}

      {(status.needsOwner || status.needsEdit || missing.length > 0 || legacy || done || noPolicy) && (task.status !== 'active' || done) && (
        <p className='text-muted-foreground flex items-start gap-2 text-sm'>
          <Icons.info className='mt-0.5 size-4 shrink-0' />
          <span>
            {missing.length ? `Add the event ${missing.join(' and ')} to activate. ` : ''}
            {noPolicy ? 'Choose how posts go out in chat to activate. ' : ''}
            {legacy ? 'Made with the earlier planner. Edit it to choose days, accounts and a content type. ' : ''}
            {status.detail}
          </span>
        </p>
      )}

      {latest && latestText && (
        <p className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm'>
          <span className='text-muted-foreground'>Last run</span>
          <StatusChip tone={latestText.v3 ? (latestText.tone as StatusTone) : RUN_TONE[latestText.tone]}>{latestText.label}</StatusChip>
          <span className='text-muted-foreground'>{runLabel((latest.anchorAt ?? latest.scheduledFor) * 1000, task.schedule.timeZone)}</span>
          {latestText.detail && <span className='text-muted-foreground'>· {latestText.detail}</span>}
        </p>
      )}

      <div className='flex flex-wrap items-center gap-2'>
        {lastDrafts?.conversationId && (
          <Button variant='glass' size='sm' className='min-h-11' onClick={() => onOpenRun(lastDrafts.id, lastDrafts.conversationId!)}>
            <Icons.chat />
            Review latest drafts
          </Button>
        )}
        {canEdit && fresh.length > 1 && (
          <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={onSeen}>
            <Icons.checks />
            Mark all as seen
          </Button>
        )}
        {canEdit && (
          <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={onEdit}>
            <Icons.edit />
            Edit
          </Button>
        )}
        {isOwner && task.status === 'draft' && (
          <Button variant='action' size='sm' className='min-h-11' disabled={busy || missing.length > 0 || noPolicy} onClick={onActivate}>
            <Icons.bolt />
            Activate
          </Button>
        )}
        {isOwner && task.status === 'active' && !done && (
          <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={onPause}>
            <Icons.pause />
            Pause
          </Button>
        )}
        {isOwner && task.status === 'paused' && !task.pauseReason && (
          <Button variant='action' size='sm' className='min-h-11' disabled={busy} onClick={onResume}>
            <Icons.play />
            Resume
          </Button>
        )}
        {isOwner && (
          <Button variant='quiet' size='sm' className='min-h-11 sm:ml-auto' disabled={busy} onClick={onCancel}>
            Cancel automation
          </Button>
        )}
      </div>

      <Label className='text-muted-foreground flex min-h-11 items-center justify-between gap-3 text-sm font-normal'>
        <span>Email me when drafts are ready</span>
        <Switch checked={watching} disabled={busy} onCheckedChange={(checked) => onWatch(checked)} aria-label={`Email me when drafts from ${automation.name} are ready`} />
      </Label>

      <Collapsible>
        <CollapsibleTrigger className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm'>
          <Icons.chevronDown className='size-4' />
          Details
        </CollapsibleTrigger>
        <CollapsibleContent>
          <dl className='mt-2 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2'>
            <Fact term='Writer'>
              {writer} · {task.reasoning ? `${task.reasoning[0].toUpperCase()}${task.reasoning.slice(1)}` : 'Quick'}
            </Fact>
            {rules.length > 0 && (
              <Fact term='Each run'>
                <ol className='flex flex-col gap-0.5'>
                  {rules.map((rule) => (
                    <li key={rule.step}>
                      <span className='text-muted-foreground'>{rule.label}</span> {rule.when}
                    </li>
                  ))}
                </ol>
                {task.nextPublish && task.status === 'active' && <span className='text-muted-foreground block text-xs'>Next publish: {runLabel(Date.parse(task.nextPublish), task.schedule.timeZone)}</span>}
              </Fact>
            )}
            {(research || workflow?.content?.instructions) && (
              <Fact term='Research and writing'>
                {research && <span className='block'>{research}</span>}
                {workflow?.content?.instructions && <span className='text-muted-foreground block text-xs'>{workflow.content.instructions}</span>}
                {Object.entries(workflow?.platformNotes ?? {}).map(([platform, note]) => (
                  <span key={platform} className='text-muted-foreground block text-xs'>
                    {platform}: {note}
                  </span>
                ))}
              </Fact>
            )}
          </dl>
        </CollapsibleContent>
      </Collapsible>

      {runs.length > 0 && (
        <Collapsible defaultOpen={canApprove && waiting > 0}>
          <CollapsibleTrigger className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm'>
            <Icons.history className='size-4' />
            Run history ({runs.length})
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className='mt-2 flex flex-col gap-1.5'>
              {runs.slice(0, 12).map((run) => {
                if (isWorkflowRun(run)) {
                  return (
                    <li key={run.id}>
                      <RunDetail run={run} timeZone={task.schedule.timeZone} canApprove={canApprove} busy={busy} onDecide={onDecide} onOpenRun={onOpenRun} />
                    </li>
                  );
                }
                const text = runText(run);
                const skipped = run.skippedDestinations ?? [];
                return (
                  <li key={run.id} className='rafii-quiet flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
                    <span className='min-w-[9.5rem]'>{runLabel(run.scheduledFor * 1000, task.schedule.timeZone)}</span>
                    <StatusChip tone={RUN_TONE[text.tone]}>{text.label}</StatusChip>
                    <span className='text-muted-foreground min-w-0 flex-[1_1_12rem] text-xs'>
                      {run.event?.kind === 'new_source' && `From “${run.event.title ?? 'a new item'}”. `}
                      {run.event?.kind === 'strong_post' && `After a strong ${run.event.platform ?? ''} post: ${run.event.value ?? '?'} ${run.event.metric ?? ''} vs ${run.event.typical ?? '?'} typical. `}
                      {run.evergreen?.jobId && `Refreshed a ${run.evergreen.platform ?? ''} post from ${run.evergreen.publishedAt ?? 'earlier'}. `}
                      {text.detail}
                      {run.state === 'completed' && `${run.draftCount ? `${run.draftCount} draft${run.draftCount === 1 ? '' : 's'}` : 'Drafts'} · ${usd(run.costUsdMicro ?? 0)}${run.seenAt ? '' : ' · new'}`}
                      {skipped.length > 0 && ` Skipped ${skipped.map((s) => s.account || s.platform).join(', ')}: disconnected.`}
                    </span>
                    {run.state === 'completed' && run.conversationId && (
                      <Button variant='quiet' size='sm' className='min-h-11' onClick={() => onOpenRun(run.id, run.conversationId!)}>
                        Open drafts
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </Surface>
  );
}

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className='flex min-w-0 flex-col gap-0.5'>
      <dt className='rafii-eyebrow'>{term}</dt>
      <dd className='text-foreground min-w-0'>{children}</dd>
    </div>
  );
}
