'use client';

import { useEffect, useMemo, useState, type ReactNode, useRef } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { TodoList, type TodoItem, type TodoItemStatus } from '@/components/agents/todo-list';
import { Icons } from '@/components/icons';
import { LevelBadge } from '@/components/app/level-badge';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { StatefulButton } from '@/components/motion/button';
import { Checkbox } from '@/components/motion/checkbox';
import { Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SuccessCheck } from '@/components/ui/success-check';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Run, SchedulePlan, Snapshot } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT } from '@/lib/ease';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { approvePlan, defaultPlanAccount, variantForRow, type ApproveStep, type PlanRow } from './plan';
import { Destination } from './variant-card';

interface RowState {
  include: boolean;
  localTime: string;
  channelId: string;
  assetId: string;
  alt: string;
}

/** One approval attempt as its checklist shows it: the rows it covers and how far the chain got. */
interface Approval {
  apply: boolean;
  rows: { platform: string; localTime: string }[];
  step: ApproveStep | null;
  outcome: 'running' | 'succeeded' | 'failed';
}

const READY = 'Ready for posting';

/** How long the finished checklist stays before the done row replaces it. */
const SUCCESS_HOLD_MS = 900;

/** Badge tone per job state; the label is always the job's own state. */
const JOB_STATUS: Record<string, AnimatedBadgeStatus> = {
  scheduled: 'info',
  approved: 'info',
  claimed: 'info',
  submitting: 'loading',
  provider_accepted: 'loading',
  uncertain: 'loading',
  published: 'success',
  verified: 'success',
  failed: 'danger',
  canceled: 'neutral'
};

/** Acknowledgement checkboxes: the motion Checkbox renders its own label, sized down to the card's small print. */
const ACK = 'items-start gap-2 [&>span]:pt-0.5 [&>span]:text-xs';

function describeWhen(localTime: string) {
  const parsed = new Date(localTime);
  if (Number.isNaN(parsed.getTime())) return '—';
  const diff = (parsed.getTime() - Date.now()) / 60_000;
  const when = new Intl.DateTimeFormat('en', { weekday: 'short', hour: '2-digit', minute: '2-digit' }).format(parsed);
  if (diff < 0) return `${when} · already passed`;
  if (diff < 60) return `${when} · in ${Math.round(diff)} min`;
  if (diff < 60 * 36) return `${when} · in ${Math.floor(diff / 60)}h ${Math.round(diff % 60)}m`;
  return `${when} · in ${Math.round(diff / 60 / 24)} days`;
}

/** Checklist items from the chain's latest step: done before it, working on it, waiting after it. */
function approvalItems(approval: Approval): TodoItem[] {
  const count = approval.rows.length;
  const items: TodoItem[] = [
    ...(approval.apply ? [{ id: 'apply', title: 'Save the candidates as drafts' }] : []),
    ...approval.rows.map((row, index) => ({ id: `row-${index}`, title: `Prepare the exact ${row.platform} review`, detail: describeWhen(row.localTime) })),
    { id: 'approve', title: `Approve ${count} destination${count === 1 ? '' : 's'}` }
  ];
  const offset = approval.apply ? 1 : 0;
  const step = approval.step;
  const current = !step || step.id === 'apply' ? 0 : step.id === 'row' ? offset + step.index : offset + count;
  return items.map((item, index) => {
    const status: TodoItemStatus =
      approval.outcome === 'succeeded' || index < current ? 'completed' : index > current ? 'pending' : approval.outcome === 'failed' ? 'cancelled' : 'in-progress';
    return { ...item, status };
  });
}

/** Plan rows settle in one after another when the card first shows them. */
function RowReveal({ index, className, children }: { index: number; className?: string; children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: EASE_OUT, delay: Math.min(index, 5) * 0.05 }}>
      <div className={className}>{children}</div>
    </motion.div>
  );
}

/**
 * The agent's proposed schedule, one row per destination. Approving replays the exact
 * review → approve chain per row (`approvePlan`); the card only assembles the inputs and
 * shows what still blocks each row. Nothing here publishes.
 */
export function PlanCard({ run, plan, snapshot, onApproved }: { run: Run; plan: SchedulePlan; snapshot: Snapshot; onApproved?: (jobs: number) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const access = useWorkspaceAccess();
  const canApprove = checkAccess(access, { permission: 'approve' });
  const state = snapshot.state;
  const channels = useMemo(() => state.phase2?.channels ?? [], [state.phase2?.channels]);
  const assets = useMemo(() => (state.phase2?.assets ?? []).filter((a) => !a.deleted), [state.phase2?.assets]);
  const voiceActive = Boolean(state.speaker?.activeRevision);
  const timeZone = plan.timeZone;
  const variants = run.artifact?.variants ?? [];
  const unknowns = Array.from(new Set(variants.flatMap((v) => v.unknowns)));
  const warnings = Array.from(new Set(variants.flatMap((v) => v.warnings ?? [])));

  const [rows, setRows] = useState<RowState[]>([]);
  const [checks, setChecks] = useState({ unknowns: false, warnings: false, rights: false });
  const [progress, setProgress] = useState<string | null>(null);
  const [justApproved, setJustApproved] = useState<number | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [saving, setSaving] = useState(false);
  const reduce = useReducedMotion();

  // Rows already scheduled from this run (survives reloads): a live job for the row's variant.
  const scheduled = useMemo(() => {
    const jobs = (state.phase2?.jobs ?? []).filter((job) => job.state !== 'canceled' && job.state !== 'failed');
    return plan.destinations.map((d) => {
      const variant = run.status === 'applied' ? variantForRow(state, run, d) : undefined;
      return variant ? (jobs.find((job) => job.manifest.variantId === variant.id) ?? null) : null;
    });
  }, [plan, run, state]);
  const scheduledCount = scheduled.filter(Boolean).length;

  useEffect(() => {
    setRows(
      plan.destinations.map((d) => {
        const ready = defaultPlanAccount(channels, d, READY);
        return { include: Boolean(ready && d.localTime), localTime: d.localTime ?? '', channelId: ready?.id ?? '', assetId: '', alt: '' };
      })
    );
  }, [plan, channels]);

  // A failed checklist stays on screen until the reader acts again.
  function clearFailed() {
    setApproval((current) => (current?.outcome === 'failed' ? null : current));
  }

  function update(index: number, patch: Partial<RowState>) {
    clearFailed();
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  const blockers = plan.destinations.map((d, index) => {
    const row = rows[index];
    if (!row) return null;
    if (scheduled[index]) return null;
    const channel = channels.find((c) => c.id === row.channelId);
    if (!channel) return `No ${d.platform} account connected`;
    if (channel.displayState && channel.displayState !== READY) return `${channel.account}: ${channel.displayState}`;
    if (!row.localTime) return 'Choose a time';
    if (d.platform === 'Instagram' && !row.assetId) return 'Instagram needs an image';
    if (row.assetId && !row.alt.trim()) return 'Describe the image (alt text)';
    return null;
  });
  const included = rows.map((row, index) => row.include && !blockers[index] && !scheduled[index]);
  const count = included.filter(Boolean).length;
  // Done = this session just approved, or the snapshot shows jobs for this run and nothing approvable is left.
  const done = justApproved !== null ? { jobs: justApproved } : scheduledCount > 0 && count === 0 ? { jobs: scheduledCount } : null;
  const needsUnknowns = unknowns.length > 0;
  const needsWarnings = warnings.length > 0;
  const ready = count > 0 && voiceActive && checks.rights && (!needsUnknowns || checks.unknowns) && (!needsWarnings || checks.warnings);
  // While the finished checklist is held, nothing can start a second approval or save.
  const holding = approval?.outcome === 'succeeded';
  const inFlight = useRef(false);

  async function approve() {
    // Same-tick double clicks: state-based disabling has not re-rendered yet.
    if (inFlight.current) return;
    inFlight.current = true;
    const selected: PlanRow[] = plan.destinations
      .map((d, index) => ({ d, row: rows[index], ok: included[index] }))
      .filter((item) => item.ok)
      .map(({ d, row }) => ({ platform: d.platform, language: d.language, localTime: row.localTime, channelId: row.channelId, assetId: row.assetId || undefined, alt: row.alt }));
    setApproval({ apply: run.status !== 'applied', rows: selected.map((row) => ({ platform: row.platform, localTime: row.localTime })), step: null, outcome: 'running' });
    setProgress('Starting…');
    try {
      const result = await approvePlan({
        api,
        workspaceId,
        run,
        snapshot,
        rows: selected,
        timeZone,
        onProgress: (message, step) => {
          setProgress(message);
          if (step) setApproval((current) => (current ? { ...current, step } : current));
        }
      });
      client.setQueryData(keys.snapshot(workspaceId), result.snapshot);
      void client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
      onApproved?.(result.jobs);
      toast.success(`${result.jobs} post${result.jobs === 1 ? '' : 's'} scheduled. See them in the Queue and Calendar.`);
      // Every step is done: hold the finished checklist a moment, then the done row takes over.
      setProgress(null);
      setApproval((current) => (current ? { ...current, outcome: 'succeeded' } : current));
      await new Promise((resolve) => setTimeout(resolve, SUCCESS_HOLD_MS));
      setJustApproved(result.jobs);
      setApproval(null);
    } catch (err) {
      // A row that could not start names itself on the error; otherwise the chain stopped at its latest step.
      const failedAt = err instanceof Error && 'step' in err ? (err.step as ApproveStep) : null;
      setApproval((current) => (current ? { ...current, step: failedAt ?? current.step, outcome: 'failed' } : current));
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : 'The plan could not be approved.');
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    } finally {
      inFlight.current = false;
      setProgress(null);
    }
  }

  async function saveDrafts() {
    if (!run.artifactHash || run.status === 'applied' || inFlight.current) return;
    inFlight.current = true;
    clearFailed();
    setSaving(true);
    setProgress('Adding the candidates to your drafts…');
    try {
      const result = await api.applyRun(workspaceId, run.runId, snapshot.revision, run.artifactHash);
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      toast.success(`${result.variants ?? ''} candidate${result.variants === 1 ? '' : 's'} saved as drafts. Nothing is scheduled.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The drafts could not be saved.');
    } finally {
      inFlight.current = false;
      setProgress(null);
      setSaving(false);
    }
  }

  return (
    <Surface material='glass' padding='none' className='flex flex-col overflow-hidden' data-tour='plan-card'>
      <div className='flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3'>
        <span className='flex flex-col gap-1'>
          <span className='rafii-eyebrow'>Schedule plan</span>
          <span className='text-foreground flex items-center gap-2 text-base'>
            <Icons.calendar className='size-4' />
            {plan.destinations.length} post{plan.destinations.length === 1 ? '' : 's'}, <em className='rafii-serif'>each its own job.</em>
          </span>
        </span>
        <span className='text-muted-foreground text-xs'>{timeZone} · nothing publishes until you approve</span>
      </div>

      <div className='divide-border/60 flex flex-col divide-y'>
        {plan.destinations.map((d, index) => {
          const row = rows[index];
          if (!row) return null;
          const candidates = channels.filter((c) => c.platform === d.platform);
          const blocker = blockers[index];
          const job = scheduled[index];
          if (job) {
            return (
              <RowReveal key={`${d.platform}-${index}`} index={index} className='flex flex-wrap items-center justify-between gap-3 px-4 py-3'>
                <div className='flex items-center gap-3'>
                  <Icons.circleCheck className='text-foreground size-4' />
                  <div className='flex flex-col gap-0.5'>
                    <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                      {d.platform}
                      <span className='text-muted-foreground font-normal'>{job.manifest.account}</span>
                      <AnimatedBadge status={JOB_STATUS[job.state] ?? 'neutral'} size='sm'>
                        {job.state.replace(/_/g, ' ')}
                      </AnimatedBadge>
                    </span>
                    <span className='text-muted-foreground text-xs'>{describeWhen(job.manifest.timing.local)}</span>
                  </div>
                </div>
                <Link href='/app/queue' className={buttonVariants({ size: 'control', variant: 'quiet' })}>
                  Open in Queue
                </Link>
              </RowReveal>
            );
          }
          return (
            <RowReveal key={`${d.platform}-${index}`} index={index} className={cn('grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] md:items-center', !row.include && 'opacity-60')}>
              <div className='flex items-start gap-3'>
                <Checkbox className='mt-0.5' checked={row.include} disabled={Boolean(blocker) || Boolean(done)} onCheckedChange={(v) => update(index, { include: v })} aria-label={`Include ${d.platform}`} />
                <div className='flex min-w-0 flex-col gap-1'>
                  <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                    <Destination platform={d.platform} language={d.language} account={candidates.find((c) => c.id === row.channelId)?.account} />
                    {candidates.length > 0 ? <LevelBadge level='Assisted' /> : <LevelBadge level='Unsupported' label='Not connected' />}
                  </span>
                  {blocker ? (
                    <span className='text-foreground inline-flex items-start gap-1.5 text-xs'>
                      <Icons.info aria-hidden className='mt-0.5 size-3.5 shrink-0' />
                      <span>
                        {blocker}
                        {blocker.startsWith('No ') && (
                          <>
                            {' · '}
                            <Link href='/app/channels' className='underline underline-offset-2'>
                              connect
                            </Link>
                          </>
                        )}
                      </span>
                    </span>
                  ) : (
                    <span className='text-muted-foreground text-xs'>{describeWhen(row.localTime)}{d.assumed ? ' · time assumed from your message' : ''}</span>
                  )}
                </div>
              </div>
              <div className='flex flex-col gap-1.5'>
                <Input type='datetime-local' value={row.localTime} disabled={Boolean(done)} onChange={(e) => update(index, { localTime: e.target.value })} aria-label={`${d.platform} time`} />
                {candidates.length > 0 && (
                  <Select value={row.channelId} onValueChange={(value) => update(index, { channelId: String(value) })}>
                    <SelectTrigger aria-label={`${d.platform} account`} disabled={Boolean(done)}>
                      <SelectValue>{candidates.find((c) => c.id === row.channelId)?.account ?? 'Choose an account'}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {candidates.map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.account}
                          {c.displayState ? ` · ${c.displayState}` : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
              <div className='flex flex-col gap-1.5'>
                {d.platform === 'Instagram' ? (
                  <>
                    <Select value={row.assetId || '__none'} onValueChange={(value) => update(index, { assetId: String(value) === '__none' ? '' : String(value) })}>
                      <SelectTrigger aria-label='Image' disabled={Boolean(done)}>
                        <SelectValue>{row.assetId ? `Image · ${assets.find((a) => a.id === row.assetId)?.hash.slice(0, 8) ?? row.assetId}` : 'Choose an image'}</SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value='__none'>No image yet</SelectItem>
                        {assets.map((a) => (
                          <SelectItem key={a.id} value={a.id}>
                            {a.mime} · {a.hash.slice(0, 8)}…
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {row.assetId && <Input value={row.alt} maxLength={300} placeholder='Alt text for the image' disabled={Boolean(done)} onChange={(e) => update(index, { alt: e.target.value })} />}
                    {assets.length === 0 && (
                      <span className='text-muted-foreground text-xs'>
                        Upload one in the{' '}
                        <Link href='/app/library' className='underline underline-offset-2'>
                          Library
                        </Link>
                        .
                      </span>
                    )}
                  </>
                ) : (
                  <span className='text-muted-foreground text-xs'>Text only</span>
                )}
              </div>
            </RowReveal>
          );
        })}
      </div>

      {(plan.unsupported.length > 0 || plan.warnings.length > 0) && (
        <ul className='text-muted-foreground border-border/60 flex flex-col gap-1 border-t px-4 py-2 text-xs'>
          {plan.unsupported.map((platform) => (
            <li key={platform} className='flex items-start gap-2'>
              <Icons.info className='mt-0.5 size-3.5 shrink-0' />
              {platform} is not available for drafting yet, so it was left out of this plan.
            </li>
          ))}
          {plan.warnings.map((warning, i) => (
            <li key={i} className='flex items-start gap-2'>
              <Icons.warning className='mt-0.5 size-3.5 shrink-0' />
              {warning}
            </li>
          ))}
        </ul>
      )}

      <div className='rafii-quiet flex flex-col gap-3 rounded-none px-4 py-3'>
        {done ? (
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='flex items-center gap-2 text-sm'>
              {/* transitions.dev success check: it celebrates an approval made in this view; a reload shows it at rest. */}
              <SuccessCheck animate={justApproved !== null} className='text-foreground size-4' />
              {done.jobs} post{done.jobs === 1 ? '' : 's'} approved and waiting for their time.
              {count > 0 && <span className='text-muted-foreground'> {count} row{count === 1 ? '' : 's'} still unscheduled.</span>}
            </span>
            <div className='flex gap-2'>
              <Link href='/app/queue' className={buttonVariants({ size: 'control', variant: 'glass' })}>
                Open Queue
              </Link>
              <Link href='/app/calendar' className={buttonVariants({ size: 'control', variant: 'glass' })}>
                Open Calendar
              </Link>
            </div>
          </div>
        ) : !voiceActive ? (
          <div className='flex flex-wrap items-center justify-between gap-2 text-sm'>
            <span>Scheduling needs an active voice profile, so every post is checked against whose words it carries.</span>
            <Link href='/app/workspace/brand' className={buttonVariants({ size: 'control', variant: 'action' })}>
              Set up your voice
            </Link>
          </div>
        ) : (
          <>
            <div className='flex flex-col gap-1.5'>
              {needsUnknowns && (
                <Checkbox
                  className={ACK}
                  checked={checks.unknowns}
                  onCheckedChange={(v) => {
                    clearFailed();
                    setChecks((c) => ({ ...c, unknowns: v }));
                  }}
                  label={`Confirm the ${unknowns.length} unknown${unknowns.length === 1 ? '' : 's'} stay out of the drafts: ${unknowns.join(' ')}`}
                />
              )}
              {needsWarnings && (
                <Checkbox
                  className={ACK}
                  checked={checks.warnings}
                  onCheckedChange={(v) => {
                    clearFailed();
                    setChecks((c) => ({ ...c, warnings: v }));
                  }}
                  label={`I acknowledge: ${warnings.join('; ')}`}
                />
              )}
              <Checkbox
                className={ACK}
                checked={checks.rights}
                onCheckedChange={(v) => {
                  clearFailed();
                  setChecks((c) => ({ ...c, rights: v }));
                }}
                label='I have the rights to publish these texts (and any image) on the selected accounts.'
              />
            </div>
            {approval && (
              <motion.div initial={reduce ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: EASE_OUT }}>
                <TodoList items={approvalItems(approval)} title='Scheduling this plan' defaultOpen collapseOnComplete={false} />
              </motion.div>
            )}
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <span className='text-muted-foreground flex items-center gap-1.5 text-xs'>
                <Icons.shieldCheck className='size-3.5' />
                {progress ?? 'Approval binds the exact text, media, account and time of each row.'}
              </span>
              <div className='flex gap-2'>
                <StatefulButton
                  variant='outline'
                  size='sm'
                  className='rafii-glass min-h-11 rounded-[var(--rafii-radius-control)] border-0 px-4'
                  state={saving ? 'loading' : 'idle'}
                  loadingText='Saving…'
                  disabled={Boolean(progress) || holding || run.status === 'applied' || !run.artifactHash}
                  onClick={() => void saveDrafts()}
                >
                  {run.status === 'applied' ? 'Saved as drafts' : 'Just save drafts'}
                </StatefulButton>
                {canApprove ? (
                  <StatefulButton
                    variant='primary'
                    size='sm'
                    className='min-h-11 rounded-[var(--rafii-radius-control)] px-4'
                    state={approval?.outcome === 'running' ? 'loading' : holding ? 'success' : 'idle'}
                    loadingText='Approving…'
                    successText='Scheduled'
                    disabled={!ready || Boolean(progress) || holding}
                    onClick={() => void approve()}
                  >
                    {count > 0 ? `Review & approve all ${count}` : 'Review & approve'}
                  </StatefulButton>
                ) : (
                  <Badge variant='outline'>Ask an approver to schedule</Badge>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Surface>
  );
}
