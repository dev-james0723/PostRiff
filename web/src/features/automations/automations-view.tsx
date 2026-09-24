'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusChip, type StatusTone } from '@/features/queue/status-chip';
import { ApiError } from '@/lib/api/client';
import { useModels } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { languageLabel } from '@/lib/locales';
import { useTimeZone } from '@/lib/preferences';
import { cn } from '@/lib/utils';
import { AutomationBuilder, blankInitial, initialFromAutomation, initialFromBrief, type BuilderInitial } from './automation-builder';
import { runLabel, runText, runsPerWeek, scheduleSummary, statusText, usd, weeklyCeilingMicro } from './schedule';
import { useAutomations, type Automation } from './use-automations';

const infoContent = {
  title: 'How automations work',
  sections: [
    { title: 'Drafts, never posts', description: 'An automation prepares drafts on a schedule. Each draft waits in its conversation for your review; nothing is scheduled or published without your approval.' },
    { title: 'The owner activates', description: 'Editors can create and edit automations. Only a workspace owner activates, pauses, resumes or cancels one. Changing anything except the name returns it to draft.' },
    { title: 'Exactly what you chose', description: 'Each run drafts for the accounts, languages, content type and writer you saved. Apps, times or instructions written inside the brief are treated as text, not settings.' },
    { title: 'Budget', description: 'Each run stays under its cost limit; a run whose quote is higher is held, never charged. A disconnected account is skipped with a note.' }
  ]
};

const STATUS_TONE: Record<string, StatusTone> = { active: 'success', draft: 'neutral', paused: 'warning', cancelled: 'neutral' };
const RUN_TONE: Record<string, StatusTone> = { quiet: 'neutral', success: 'success', attention: 'warning', failure: 'danger' };
const WEEK = 7 * 86400;

export function AutomationsView() {
  const params = useSearchParams();
  const router = useRouter();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const isOwner = checkAccess(access, { permission: 'owner' });
  const timeZone = useTimeZone();
  const models = useModels();
  const { snapshot, state, automations, briefs, act, busy } = useAutomations();
  const [builder, setBuilder] = useState<{ key: number; initial: BuilderInitial } | null>(null);
  const [cancelling, setCancelling] = useState<Automation | null>(null);
  const [now] = useState(() => Date.now() / 1000);
  const opened = useRef<string | null>(null);

  const open = (initial: BuilderInitial) => setBuilder((current) => ({ key: (current?.key ?? 0) + 1, initial }));

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

  const live = automations.filter((a) => a.task.status !== 'cancelled');
  const cancelled = automations.filter((a) => a.task.status === 'cancelled');
  const active = live.filter((a) => a.task.status === 'active');
  const waiting = live.filter((a) => statusText(a.task).needsOwner || statusText(a.task).needsEdit);
  const recentDrafts = automations.flatMap((a) => a.drafted).filter((run) => run.scheduledFor >= now - WEEK).length;
  const next = active
    .map((a) => ({ a, at: a.task.nextOccurrence?.scheduledFor ?? (a.task.nextOccurrence ? Date.parse(a.task.nextOccurrence.utc) / 1000 : Infinity) }))
    .toSorted((x, y) => x.at - y.at)[0];
  const weeklyCeiling = active.reduce((sum, a) => sum + weeklyCeilingMicro(a.task.maxCostUsdMicro, a.task.schedule), 0);
  const writerLabel = useMemo(() => new Map((models.data?.models ?? []).map((m) => [m.id, m.label])), [models.data]);

  async function run(action: string, automation: Automation, success: string) {
    try {
      await act(action, { taskId: automation.task.id, confirmed: true });
      toast.success(success);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Rafii could not change this automation.');
    }
  }

  return (
    <PageContainer
      pageEyebrow='Create'
      pageTitle='Automations'
      pageDescription='Rafii prepares drafts on your schedule, for the accounts you choose. Every draft waits for your review.'
      infoContent={infoContent}
      pageHeaderAction={
        canEdit ? (
          <Button variant='action' size='control' onClick={() => open(blankInitial(timeZone))}>
            <Icons.add />
            New automation
          </Button>
        ) : undefined
      }
    >
      {snapshot.isLoading ? (
        <div className='grid gap-3 md:grid-cols-4'>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className='h-20 w-full rounded-[var(--rafii-radius-card)]' />
          ))}
        </div>
      ) : (
        <>
          <section aria-label='Automation summary' className='grid grid-cols-2 gap-3 lg:grid-cols-4'>
            <Tile label='Active' value={String(active.length)} detail={live.length > active.length ? `${live.length - active.length} not running` : 'All running'} />
            <Tile label='Needs you' value={String(waiting.length)} detail={waiting.length ? (isOwner ? 'Activate or review' : 'Waiting for the owner') : 'Nothing waiting'} />
            <Tile label='Drafts this week' value={String(recentDrafts)} detail={recentDrafts ? 'Ready in their conversations' : 'None prepared yet'} />
            <Tile label='Next run' value={next && Number.isFinite(next.at) ? runLabel(next.at * 1000, next.a.task.schedule.timeZone) : '—'} detail={next ? next.a.name : 'Nothing active'} small />
          </section>

          {active.length > 0 && (
            <Surface material='quiet' padding='sm' className='flex flex-wrap items-center gap-x-4 gap-y-1 text-sm'>
              <span className='rafii-eyebrow'>Budget</span>
              <span>
                Active automations can spend at most <span className='font-medium'>{usd(weeklyCeiling)}</span> a week in total.
              </span>
              <Link href='/app/account/billing' className='text-muted-foreground hover:text-foreground ml-auto inline-flex min-h-11 items-center gap-1 text-xs'>
                Usage and credits
                <Icons.arrowRight className='size-3.5' />
              </Link>
            </Surface>
          )}

          {live.length === 0 ? (
            <StateMessage
              kind='empty'
              title='No automations yet'
              description='Tell Rafii what to prepare, when and for which accounts. It drafts on schedule; you review and approve.'
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
                    busy={busy}
                    writer={automation.task.route ? (writerLabel.get(automation.task.route) ?? automation.task.route) : 'No writer'}
                    onEdit={() => open(initialFromAutomation(automation, timeZone))}
                    onActivate={() => void run('raffi_recurrence_activate', automation, 'Automation active. Drafts will wait for your review.')}
                    onPause={() => void run('raffi_recurrence_pause', automation, 'Automation paused.')}
                    onResume={() => void run('raffi_recurrence_resume', automation, 'Automation resumed.')}
                    onCancel={() => setCancelling(automation)}
                    onOpenRun={(conversationId) => router.push(`/app/agent/${encodeURIComponent(conversationId)}`)}
                  />
                </li>
              ))}
            </ul>
          )}

          {briefs.length > 0 && (
            <section className='flex flex-col gap-2' aria-labelledby='automation-briefs'>
              <h2 id='automation-briefs' className='text-base font-semibold'>
                Briefs without a schedule
              </h2>
              <p className='text-muted-foreground text-sm'>Campaign briefs from earlier planning or suggestions. Give one a schedule to turn it into an automation.</p>
              <ul className='flex flex-col gap-2'>
                {briefs.map((campaign) => (
                  <li key={campaign.id}>
                    <Surface material='quiet' radius='control' padding='sm' className='flex flex-wrap items-center gap-3'>
                      <span className='flex min-w-0 flex-[1_1_12rem] flex-col'>
                        <span className='text-sm font-medium'>{campaign.goal}</span>
                        <span className='text-muted-foreground text-xs'>{campaign.audience}{campaign.missingFacts.length ? ` · needs ${campaign.missingFacts.join(' and ')}` : ''}</span>
                      </span>
                      {canEdit && (
                        <Button variant='glass' size='sm' className='min-h-11' onClick={() => open(initialFromBrief(campaign, timeZone))}>
                          Schedule it
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
                        <span className='text-muted-foreground text-xs'>{automation.drafted.length} run{automation.drafted.length === 1 ? '' : 's'} with drafts</span>
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

      <RafiiDialog open={cancelling !== null} onOpenChange={(next) => !next && setCancelling(null)}>
        <RafiiDialogContent size='sm'>
          <RafiiDialogHeader eyebrow='Automation' title='Cancel' accent={cancelling ? `“${cancelling.name}”?` : undefined} intro='No further drafts will be prepared. Drafts it already made stay in their conversations. A cancelled automation cannot be restarted; create a new one instead.' />
          <RafiiDialogBody>
            <p className='text-muted-foreground text-sm'>{cancelling ? scheduleSummary(cancelling.task.schedule) : ''}</p>
          </RafiiDialogBody>
          <RafiiDialogFooter className='flex justify-end gap-2'>
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
                if (target) void run('raffi_recurrence_cancel', target, 'Automation cancelled. No further drafts will be prepared.');
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

function Tile({ label, value, detail, small }: { label: string; value: string; detail: string; small?: boolean }) {
  return (
    <Surface material='glass' padding='sm' className='flex min-w-0 flex-col gap-1'>
      <span className='rafii-eyebrow'>{label}</span>
      <span className={cn('text-foreground font-normal tracking-[-0.02em]', small ? 'text-base leading-snug' : 'text-2xl')}>{value}</span>
      <span className='text-muted-foreground truncate text-xs'>{detail}</span>
    </Surface>
  );
}

interface CardProps {
  automation: Automation;
  canEdit: boolean;
  isOwner: boolean;
  busy: boolean;
  writer: string;
  onEdit: () => void;
  onActivate: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onOpenRun: (conversationId: string) => void;
}

function AutomationCard({ automation, canEdit, isOwner, busy, writer, onEdit, onActivate, onPause, onResume, onCancel, onOpenRun }: CardProps) {
  const { task, campaign, destinations, runs, legacy } = automation;
  const status = statusText(task);
  const labels = task.accountLabels ?? {};
  const platforms = Array.from(new Set(destinations.map((d) => d.platform)));
  const accountsCount = new Set(destinations.map((d) => d.channelId ?? d.platform)).size;
  const languages = Array.from(new Set(destinations.map((d) => d.language)));
  const where = task.destinationLabel ?? (destinations.length === 1 && destinations[0].channelId ? labels[destinations[0].channelId] || destinations[0].platform : `${accountsCount} ${destinations.some((d) => d.channelId) ? 'account' : 'app'}${accountsCount === 1 ? '' : 's'}`);
  const nextAt = task.nextOccurrence?.scheduledFor ?? (task.nextOccurrence ? Date.parse(task.nextOccurrence.utc) / 1000 : null);
  const latest = runs[0];
  const latestText = latest ? runText(latest) : null;
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
        <StatusChip tone={STATUS_TONE[task.status] ?? 'neutral'} size='md'>
          {status.label}
        </StatusChip>
      </div>

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
        <Fact term='Writer'>
          {writer} · {task.reasoning ? `${task.reasoning[0].toUpperCase()}${task.reasoning.slice(1)}` : 'Quick'} · up to {usd(task.maxCostUsdMicro ?? 0)} a run
        </Fact>
        <Fact term={task.status === 'active' ? 'Next run' : 'Schedule'}>
          {task.status === 'active' && nextAt ? runLabel(nextAt * 1000, task.schedule.timeZone) : task.status === 'draft' ? 'Starts after activation' : 'Not running'}
          <span className='text-muted-foreground block text-xs'>
            {runsPerWeek(task.schedule)} run{runsPerWeek(task.schedule) === 1 ? '' : 's'} a week · at most {usd(weeklyCeilingMicro(task.maxCostUsdMicro, task.schedule))} a week
          </span>
        </Fact>
      </dl>

      {(status.needsOwner || status.needsEdit || missing.length > 0 || legacy) && task.status !== 'active' && (
        <p className='text-muted-foreground flex items-start gap-2 text-sm'>
          <Icons.info className='mt-0.5 size-4 shrink-0' />
          <span>
            {missing.length ? `Add the event ${missing.join(' and ')} before it can be activated. ` : ''}
            {legacy ? 'Made with the earlier planner. Edit it to choose days, accounts and a content type. ' : ''}
            {status.detail}
          </span>
        </p>
      )}

      {latest && latestText && (
        <p className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm'>
          <span className='text-muted-foreground'>Last run</span>
          <StatusChip tone={RUN_TONE[latestText.tone]}>{latestText.label}</StatusChip>
          <span className='text-muted-foreground'>{runLabel(latest.scheduledFor * 1000, task.schedule.timeZone)}</span>
          {latestText.detail && <span className='text-muted-foreground'>· {latestText.detail}</span>}
        </p>
      )}

      <div className='flex flex-wrap items-center gap-2'>
        {lastDrafts?.conversationId && (
          <Button variant='glass' size='sm' className='min-h-11' onClick={() => onOpenRun(lastDrafts.conversationId!)}>
            <Icons.chat />
            Review latest drafts
          </Button>
        )}
        {canEdit && (
          <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={onEdit}>
            <Icons.edit />
            Edit
          </Button>
        )}
        {isOwner && task.status === 'draft' && (
          <Button variant='action' size='sm' className='min-h-11' disabled={busy || missing.length > 0} onClick={onActivate}>
            <Icons.bolt />
            Activate
          </Button>
        )}
        {isOwner && task.status === 'active' && (
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

      {runs.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm'>
            <Icons.history className='size-4' />
            Run history ({runs.length})
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className='mt-2 flex flex-col gap-1.5'>
              {runs.slice(0, 12).map((run) => {
                const text = runText(run);
                const skipped = run.skippedDestinations ?? [];
                return (
                  <li key={run.id} className='rafii-quiet flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
                    <span className='min-w-[9.5rem]'>{runLabel(run.scheduledFor * 1000, task.schedule.timeZone)}</span>
                    <StatusChip tone={RUN_TONE[text.tone]}>{text.label}</StatusChip>
                    <span className='text-muted-foreground min-w-0 flex-[1_1_12rem] text-xs'>
                      {text.detail}
                      {skipped.length > 0 && ` Skipped ${skipped.map((s) => s.account || s.platform).join(', ')}: no longer connected.`}
                    </span>
                    {run.state === 'completed' && run.conversationId && (
                      <Button variant='quiet' size='sm' className='min-h-11' onClick={() => onOpenRun(run.conversationId!)}>
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
