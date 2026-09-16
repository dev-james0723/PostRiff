'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { LevelBadge } from '@/components/app/level-badge';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Run, SchedulePlan, Snapshot } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { approvePlan, variantForRow, type PlanRow } from './plan';

interface RowState {
  include: boolean;
  localTime: string;
  channelId: string;
  assetId: string;
  alt: string;
}

const READY = 'Ready for posting';

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
        const candidates = channels.filter((c) => c.platform === d.platform);
        const ready = candidates.find((c) => c.displayState === READY) ?? candidates[0];
        return { include: Boolean(ready && d.localTime), localTime: d.localTime ?? '', channelId: ready?.id ?? '', assetId: '', alt: '' };
      })
    );
  }, [plan, channels]);

  function update(index: number, patch: Partial<RowState>) {
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

  async function approve() {
    const selected: PlanRow[] = plan.destinations
      .map((d, index) => ({ d, row: rows[index], ok: included[index] }))
      .filter((item) => item.ok)
      .map(({ d, row }) => ({ platform: d.platform, language: d.language, localTime: row.localTime, channelId: row.channelId, assetId: row.assetId || undefined, alt: row.alt }));
    setProgress('Starting…');
    try {
      const result = await approvePlan({ api, workspaceId, run, snapshot, rows: selected, timeZone, onProgress: setProgress });
      client.setQueryData(keys.snapshot(workspaceId), result.snapshot);
      void client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
      setJustApproved(result.jobs);
      onApproved?.(result.jobs);
      toast.success(`${result.jobs} post${result.jobs === 1 ? '' : 's'} scheduled. See them in the Queue and Calendar.`);
    } catch (err) {
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : 'The plan could not be approved.');
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    } finally {
      setProgress(null);
    }
  }

  async function saveDrafts() {
    if (!run.artifactHash || run.status === 'applied') return;
    setProgress('Adding the candidates to your drafts…');
    try {
      const result = await api.applyRun(workspaceId, run.runId, snapshot.revision, run.artifactHash);
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      toast.success(`${result.variants ?? ''} candidate${result.variants === 1 ? '' : 's'} saved as drafts. Nothing is scheduled.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The drafts could not be saved.');
    } finally {
      setProgress(null);
    }
  }

  return (
    <div className='bg-card ring-foreground/10 flex flex-col overflow-hidden rounded-xl ring-1'>
      <div className='flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3'>
        <span className='flex items-center gap-2 text-sm font-semibold'>
          <Icons.calendar className='size-4' />
          Schedule plan · {plan.destinations.length} post{plan.destinations.length === 1 ? '' : 's'}
        </span>
        <span className='text-muted-foreground text-xs'>{timeZone} · each row becomes its own job in the Queue</span>
      </div>

      <div className='flex flex-col divide-y'>
        {plan.destinations.map((d, index) => {
          const row = rows[index];
          if (!row) return null;
          const candidates = channels.filter((c) => c.platform === d.platform);
          const blocker = blockers[index];
          const job = scheduled[index];
          if (job) {
            return (
              <div key={`${d.platform}-${index}`} className='flex flex-wrap items-center justify-between gap-3 px-4 py-3'>
                <div className='flex items-center gap-3'>
                  <Icons.circleCheck className='size-4 text-emerald-500' />
                  <div className='flex flex-col gap-0.5'>
                    <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                      {d.platform}
                      <span className='text-muted-foreground font-normal'>{job.manifest.account}</span>
                      <Badge variant='outline'>{job.state.replace(/_/g, ' ')}</Badge>
                    </span>
                    <span className='text-muted-foreground text-xs'>{describeWhen(job.manifest.timing.local)}</span>
                  </div>
                </div>
                <Link href='/app/queue' className={buttonVariants({ size: 'sm', variant: 'ghost' })}>
                  Open in Queue
                </Link>
              </div>
            );
          }
          return (
            <div key={`${d.platform}-${index}`} className={cn('grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)] md:items-center', !row.include && 'opacity-60')}>
              <div className='flex items-start gap-3'>
                <Checkbox className='mt-0.5' checked={row.include} disabled={Boolean(blocker) || Boolean(done)} onCheckedChange={(v) => update(index, { include: v === true })} aria-label={`Include ${d.platform}`} />
                <div className='flex min-w-0 flex-col gap-1'>
                  <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                    {d.platform}
                    <span className='text-muted-foreground font-normal'>{d.language === '繁體中文' ? '繁中' : 'EN'}</span>
                    {candidates.length > 0 ? <LevelBadge level='Assisted' /> : <LevelBadge level='Unsupported' label='Not connected' />}
                  </span>
                  {blocker ? (
                    <span className='text-xs text-amber-700 dark:text-amber-300'>
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
            </div>
          );
        })}
      </div>

      {(plan.unsupported.length > 0 || plan.warnings.length > 0) && (
        <ul className='text-muted-foreground flex flex-col gap-1 border-t px-4 py-2 text-xs'>
          {plan.unsupported.map((platform) => (
            <li key={platform} className='flex items-start gap-2'>
              <Icons.info className='mt-0.5 size-3.5 shrink-0' />
              {platform} is not available for drafting yet, so it was left out of this plan.
            </li>
          ))}
          {plan.warnings.map((warning, i) => (
            <li key={i} className='flex items-start gap-2'>
              <Icons.warning className='mt-0.5 size-3.5 shrink-0 text-amber-500' />
              {warning}
            </li>
          ))}
        </ul>
      )}

      <div className='bg-background/60 flex flex-col gap-3 border-t px-4 py-3'>
        {done ? (
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='flex items-center gap-2 text-sm'>
              <Icons.circleCheck className='size-4 text-emerald-500' />
              {done.jobs} post{done.jobs === 1 ? '' : 's'} approved and waiting for their time.
              {count > 0 && <span className='text-muted-foreground'> {count} row{count === 1 ? '' : 's'} still unscheduled.</span>}
            </span>
            <div className='flex gap-2'>
              <Link href='/app/queue' className={buttonVariants({ size: 'sm', variant: 'outline' })}>
                Open Queue
              </Link>
              <Link href='/app/calendar' className={buttonVariants({ size: 'sm', variant: 'outline' })}>
                Open Calendar
              </Link>
            </div>
          </div>
        ) : !voiceActive ? (
          <div className='flex flex-wrap items-center justify-between gap-2 text-sm'>
            <span>Scheduling needs an active voice profile, so every post is checked against whose words it carries.</span>
            <Link href='/app/workspace/brand' className={buttonVariants({ size: 'sm' })}>
              Set up your voice
            </Link>
          </div>
        ) : (
          <>
            <div className='flex flex-col gap-1.5'>
              {needsUnknowns && (
                <Label className='flex items-start gap-2 text-xs font-normal'>
                  <Checkbox checked={checks.unknowns} onCheckedChange={(v) => setChecks((c) => ({ ...c, unknowns: v === true }))} />
                  <span>
                    Confirm the {unknowns.length} unknown{unknowns.length === 1 ? '' : 's'} stay out of the drafts: {unknowns.join(' ')}
                  </span>
                </Label>
              )}
              {needsWarnings && (
                <Label className='flex items-start gap-2 text-xs font-normal'>
                  <Checkbox checked={checks.warnings} onCheckedChange={(v) => setChecks((c) => ({ ...c, warnings: v === true }))} />
                  <span>I acknowledge: {warnings.join('; ')}</span>
                </Label>
              )}
              <Label className='flex items-start gap-2 text-xs font-normal'>
                <Checkbox checked={checks.rights} onCheckedChange={(v) => setChecks((c) => ({ ...c, rights: v === true }))} />
                <span>I have the rights to publish these texts (and any image) on the selected accounts.</span>
              </Label>
            </div>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <span className='text-muted-foreground flex items-center gap-1.5 text-xs'>
                <Icons.shieldCheck className='size-3.5' />
                {progress ?? 'Approval binds the exact text, media, account and time of each row.'}
              </span>
              <div className='flex gap-2'>
                <Button variant='outline' size='sm' disabled={Boolean(progress) || run.status === 'applied' || !run.artifactHash} onClick={() => void saveDrafts()}>
                  {run.status === 'applied' ? 'Saved as drafts' : 'Just save drafts'}
                </Button>
                {canApprove ? (
                  <Button size='sm' disabled={!ready || Boolean(progress)} onClick={() => void approve()}>
                    {progress ? <Icons.spinner className='size-3.5 animate-spin' /> : null}
                    Review &amp; approve {count > 0 ? `all ${count}` : ''}
                  </Button>
                ) : (
                  <Badge variant='outline'>Ask an approver to schedule</Badge>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
