'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useChannels } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { shouldRetry } from '@/lib/coworker/api';
import { useCoworkerApi, usePerformance } from '@/lib/coworker/hooks';
import type { GrowthExperiment, GrowthGoal, GrowthProof } from '@/lib/coworker/growth-types';
import { QueryProblem } from '@/features/coworker/parts';
import { cn } from '@/lib/utils';
import { ProofRevisions } from './proof-v2';

const queryKey = (w: string) => ['coworker', w, 'growth-loop'] as const;
const field = 'rafii-focus rafii-quiet min-h-11 w-full rounded-xl border border-border px-3 text-base';
const label = (s: string) => s.replaceAll('_', ' ');
const value = (n: number | null | undefined) => n == null ? 'Unavailable' : n.toLocaleString();
const date = (n: number) => new Date(n * 1000).toLocaleDateString(undefined, { timeZone: 'UTC' });

function useGrowth() {
  const { api, w, enabled } = useCoworkerApi();
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const query = useQuery({ queryKey: queryKey(w), queryFn: () => api.growthLoop(w), enabled, retry: shouldRetry, staleTime: 30_000 });
  async function run(action: () => Promise<{ verified: boolean }>) {
    if (pending) return false;
    setPending(true);
    try {
      const result = await action();
      if (!result.verified) throw new Error('The saved change could not be verified. Refresh before retrying.');
      await client.invalidateQueries({ queryKey: queryKey(w) });
      await client.invalidateQueries({ queryKey: ['coworker', w, 'performance'] });
      return true;
    } catch (error) { toast.error(error instanceof Error ? error.message : 'That change could not be saved.'); return false; }
    finally { setPending(false); }
  }
  return { api, w, query, run, pending };
}

function GoalReadout({ goal, compact = false }: { goal: GrowthGoal; compact?: boolean }) {
  return <div className='flex flex-col gap-3'>
    <div className='flex flex-wrap items-center justify-between gap-2'>
      <h3 className='text-base font-medium'>{goal.name}</h3>
      <span className='text-muted-foreground text-xs'>{label(goal.displayStatus)} · by {date(goal.targetAt)}</span>
    </div>
    <dl className='grid grid-cols-3 gap-3'>
      {([['Baseline', goal.baselineValue], ['Current', goal.currentValue], ['Target', goal.targetValue]] as const).map(([name, n]) => <div key={name}>
        <dt className='text-muted-foreground text-xs'>{name}</dt><dd className='mt-1 text-lg tabular-nums'>{value(n)}</dd>
      </div>)}
    </dl>
    {!compact && <p className='text-muted-foreground text-xs'>{label(goal.primaryMetric)} · {goal.currentValueAt ? `Read ${date(goal.currentValueAt)}` : 'No reading'}{goal.change == null ? '' : ` · +${value(goal.change)} since activation`}</p>}
    <p className={cn('text-muted-foreground', compact ? 'text-xs' : 'text-sm')} role='status'>{label(goal.coverage.status)}: {goal.coverage.reason}</p>
    {!compact && <details className='text-muted-foreground text-xs'><summary className='rafii-focus min-h-8 cursor-pointer'>Metric definition and source</summary><p className='py-2'>{goal.providerMetricDefinition} Baseline: user declared. Source: {goal.source || 'Unavailable'}; confidence: {label(goal.confidence)}.</p></details>}
  </div>;
}

export function GrowthHome() {
  const growth = useGrowth();
  if (growth.query.isPending) return null;
  if (growth.query.error) return <QueryProblem what='Growth' error={growth.query.error} onRetry={() => void growth.query.refetch()} />;
  const data = growth.query.data;
  if (!data) return null;
  const latest = data.proofs.filter(p => p.frequency === 'weekly').at(-1);
  return <Surface material='glass' className='p-5' as='section' aria-label='Growth'>
    <div className='mb-4 flex items-center justify-between gap-3'><h2 className='text-sm font-medium'>Growth</h2><Link className='rafii-focus text-muted-foreground text-xs underline underline-offset-4' href='/app/analytics#growth-goal'>Manage goal</Link></div>
    {data.goal ? <GoalReadout goal={data.goal} compact /> : <><p className='mb-3 text-sm'>Choose the outcome you want Rafii to help improve each week.</p><Link className='rafii-focus inline-flex min-h-11 items-center rounded-xl border border-border px-4 text-sm' href='/app/analytics#growth-goal'>Set a growth goal</Link></>}
    <p className='text-muted-foreground mt-4 text-sm'>{data.weekly.activeRecipes ? `${data.weekly.activeRecipes} active weekly recipe${data.weekly.activeRecipes === 1 ? '' : 's'} preparing work for review.` : 'Rafii needs a weekly recipe to prepare your next week.'}</p>
    <Link className='rafii-focus mt-2 inline-flex min-h-11 items-center text-sm underline underline-offset-4' href={data.goal?.coverage.status === 'unavailable' ? data.goal.nextAction.href : data.weekly.href}>{data.goal?.coverage.status === 'unavailable' ? data.goal.nextAction.label : data.weekly.nextAction}</Link>
    {latest && <p className='text-muted-foreground mt-3 border-t border-border pt-3 text-xs'>Last weekly recap: {latest.counts.approvedPosts} approved · {latest.counts.verifiedPublishedPosts} verified published. <Link className='rafii-focus underline' href={latest.href}>See the evidence</Link></p>}
  </Surface>;
}

export function GrowthAnalytics() {
  const growth = useGrowth();
  const channels = useChannels();
  const owner = checkAccess(useWorkspaceAccess(), { permission: 'owner' });
  const performance = usePerformance();
  const [form, setForm] = useState({ name: '', goalType: 'consistency', primaryMetric: 'verified_posts', baseline: '0', target: '12', targetAt: '', channelId: '' });
  const [showForm, setShowForm] = useState(false);
  const goalKey = useRef<string | null>(null);
  const proposalKeys = useRef(new Map<string, string>());
  const opened = useRef(new Set<string>());
  const data = growth.query.data;
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('proof');
    if (id && data?.proofs.some(p => p.id === id) && !opened.current.has(id)) {
      opened.current.add(id);
      void growth.api.growthProofAction(growth.w, id, 'opened').catch(() => opened.current.delete(id));
      document.getElementById(id)?.scrollIntoView({ block: 'center' });
    }
  }, [data, growth.api, growth.w]);
  if (growth.query.error) return <QueryProblem what='Growth Loop' error={growth.query.error} onRetry={() => void growth.query.refetch()} />;
  if (!data) return <p className='text-muted-foreground text-sm' role='status'>Loading growth outcomes…</p>;
  const goal = data.goal;
  const unused = performance.data?.hypotheses.filter(h => !data.experiments.some(e => e.hypothesisId === h.id) && ['candidate', 'supported', 'experiment'].includes(h.status)) || [];
  return <div className='flex flex-col gap-6'>
    <Surface material='glass' className='p-5 sm:p-6' as='section' id='growth-goal' aria-labelledby='growth-title'>
      <div className='mb-4 flex flex-wrap items-center justify-between gap-3'><h2 id='growth-title' className='text-lg font-medium'>Growth Goal</h2><span className='text-muted-foreground text-xs'>One primary outcome</span></div>
      {goal ? <GoalReadout goal={goal} /> : <p className='text-muted-foreground text-sm'>A declared goal connects your weekly plan to covered outcomes.</p>}
      {owner && <div className='mt-4 flex flex-wrap gap-2'>
        {goal && goal.status !== 'archived' && <Button variant='glass' disabled={growth.pending} onClick={() => void growth.run(() => growth.api.growthGoalStatus(growth.w, goal.id, goal.status === 'active' ? 'paused' : 'active'))}>{goal.status === 'active' ? 'Pause goal' : 'Resume goal'}</Button>}
        {goal && goal.status !== 'archived' && <Button variant='glass' disabled={growth.pending} onClick={() => void growth.run(() => growth.api.growthGoalStatus(growth.w, goal.id, 'archived'))}>Archive goal</Button>}
        {(!goal || goal.status !== 'active') && <Button variant='glass' onClick={() => setShowForm(!showForm)}>Set a growth goal</Button>}
      </div>}
      {owner && (showForm || !goal) && <form className='mt-5 grid gap-4 sm:grid-cols-2' onSubmit={async event => {
        event.preventDefault();
        goalKey.current ||= crypto.randomUUID();
        if (await growth.run(() => growth.api.createGrowthGoal(growth.w, { name: form.name, goalType: form.goalType, primaryMetric: form.primaryMetric,
          baselineValue: form.baseline === '' ? null : Number(form.baseline), targetValue: Number(form.target), targetAt: form.targetAt,
          channelId: form.channelId || undefined, idempotencyKey: goalKey.current! }))) { goalKey.current = null; setShowForm(false); }
      }}>
        <label className='grid gap-2 text-sm sm:col-span-2'>Goal name<input aria-label="Goal name" className={field} value={form.name} maxLength={120} required onChange={e => { goalKey.current = null; setForm({ ...form, name: e.target.value }); }} /></label>
        <label className='grid gap-2 text-sm'>Outcome<select className={field} value={form.goalType} onChange={e => { goalKey.current = null; setForm({ ...form, goalType: e.target.value, primaryMetric: data.metricOptions[e.target.value][0] }); }}>{Object.keys(data.metricOptions).map(k => <option key={k} value={k}>{label(k)}</option>)}</select></label>
        <label className='grid gap-2 text-sm'>Native metric<select className={field} value={form.primaryMetric} onChange={e => { goalKey.current = null; setForm({ ...form, primaryMetric: e.target.value }); }}>{data.metricOptions[form.goalType].map(k => <option key={k} value={k}>{label(k)}</option>)}</select></label>
        <label className='grid gap-2 text-sm sm:col-span-2'>Account<select className={field} value={form.channelId} required={form.primaryMetric !== 'verified_posts'} onChange={e => { goalKey.current = null; setForm({ ...form, channelId: e.target.value }); }}><option value=''>{form.primaryMetric === 'verified_posts' ? 'All workspace accounts' : 'Choose one connected account'}</option>{channels.data?.channels.map(c => <option key={c.id} value={c.id}>{c.platform} · {c.account || c.id}</option>)}</select></label>
        <label className='grid gap-2 text-sm'>Baseline (your declared starting value)<input aria-label='Baseline' className={field} type='number' min='0' value={form.baseline} onChange={e => { goalKey.current = null; setForm({ ...form, baseline: e.target.value }); }} /></label>
        <label className='grid gap-2 text-sm'>Target<input aria-label='Target' className={field} type='number' min='0' required value={form.target} onChange={e => { goalKey.current = null; setForm({ ...form, target: e.target.value }); }} /></label>
        <label className='grid gap-2 text-sm'>Target date<input aria-label='Target date' className={field} type='date' required value={form.targetAt} onChange={e => { goalKey.current = null; setForm({ ...form, targetAt: e.target.value }); }} /></label>
        <div className='flex items-end'><Button type='submit' variant='glass' disabled={growth.pending}>{growth.pending ? 'Saving…' : 'Save growth goal'}</Button></div>
        <p className='text-muted-foreground text-xs sm:col-span-2'>Covered outcomes are added to your declared baseline from activation onward. Missing provider metrics stay Unavailable.</p>
      </form>}
      {!owner && <p className='text-muted-foreground mt-3 text-xs'>A workspace owner manages goals and experiment decisions.</p>}
    </Surface>

    <section aria-labelledby='growth-lab-title' className='flex flex-col gap-3' id='growth-lab'>
      <h2 id='growth-lab-title' className='text-lg font-medium'>Growth Lab</h2>
      <p className='text-muted-foreground text-sm'>Test account-specific performance hypotheses. Strategy changes only after you choose to use a measured result.</p>
      {unused.map(h => <Surface key={h.id} material='quiet' className='p-4'><p className='text-sm'>{h.statement}</p><p className='text-muted-foreground my-2 text-xs'>{h.why}</p>{owner && <Button variant='glass' disabled={growth.pending} onClick={() => {
        if (!proposalKeys.current.has(h.id)) proposalKeys.current.set(h.id, crypto.randomUUID());
        void growth.run(() => growth.api.proposeGrowthExperiment(growth.w, { hypothesisId: h.id, minimumPerArm: 5, windowDays: 14, idempotencyKey: proposalKeys.current.get(h.id)! }));
      }}>Design an experiment</Button>}</Surface>)}
      {data.experiments.map(e => <ExperimentCard key={e.id} experiment={e} owner={owner} pending={growth.pending} act={action => void growth.run(() => growth.api.growthExperimentAction(growth.w, e.id, action))} repeat={() => void growth.run(() => growth.api.proposeGrowthExperiment(growth.w, { hypothesisId: e.hypothesisId, minimumPerArm: e.minimumPerArm, windowDays: e.windowDays, idempotencyKey: crypto.randomUUID() }))} />)}
      {!unused.length && !data.experiments.length && <Surface material='quiet' className='p-4'><p className='text-muted-foreground text-sm'>No comparable hypothesis yet. Collect verified posts with covered metrics; at least five posts per group are needed.</p><Link className='rafii-focus mt-2 inline-flex min-h-11 items-center text-sm underline' href='/app/weekly'>Prepare your week</Link></Surface>}
      {Boolean(performance.error) && <QueryProblem what='Performance hypotheses' error={performance.error} hideWhenOff onRetry={() => void performance.refetch()} />}
    </section>

    <section aria-labelledby='proof-title' className='flex flex-col gap-3' id='proof-history'>
      <div className='flex flex-wrap items-center justify-between gap-3'><h2 id='proof-title' className='text-lg font-medium'>Proof of value</h2>{owner && <div className='flex flex-wrap gap-2'>{(['weekly', 'monthly'] as const).map(f => <Button key={f} variant='glass' disabled={growth.pending} onClick={() => void growth.run(() => growth.api.generateGrowthProof(growth.w, f))}>Generate {f} recap</Button>)}</div>}</div>
      <p className='text-muted-foreground text-sm'>Completed reporting periods (UTC), backed by approved work and verified outcomes. Your existing notification settings control delivery.</p>
      <ProofRevisions owner={owner} />
      {data.proofs.toReversed().map(p => <ProofCard key={p.id} proof={p} open={() => { void growth.api.growthProofAction(growth.w, p.id, 'opened').catch(() => {}); }} act={async () => { if (await growth.run(() => growth.api.growthProofAction(growth.w, p.id, 'acted'))) window.location.assign('/app/weekly'); }} />)}
      {!data.proofs.length && <p className='text-muted-foreground text-sm'>Your first recap will show accepted work, publishing verification and the data actually covered.</p>}
    </section>
  </div>;
}

function ExperimentCard({ experiment: e, owner, pending, act, repeat }: { experiment: GrowthExperiment; owner: boolean; pending: boolean; act: (action: string) => void; repeat: () => void }) {
  const actions: Record<string, [string, string][]> = { proposed: [['accept', 'Run experiment'], ['dismiss', 'Dismiss'], ['not_now', 'Not now']], accepted: [['prepare', 'Prepare design'], ['cancel', 'Cancel']], preparing: [['start', 'Start observing approved posts'], ['cancel', 'Cancel']], running: [['measure', 'Measure results'], ['cancel', 'Stop experiment']], measuring: [['measure', 'Measure results']], complete: [['apply', 'Use as a planning preference'], ['keep', 'Keep as hypothesis only'], ['reject_result', 'Reject result'], ['revoke', 'Revoke planning preference']] };
  return <Surface material='glass' className='p-5' as='article' aria-label={`Experiment: ${e.statement}`}>
    <div className='flex flex-wrap justify-between gap-2'><h3 className='text-sm font-medium'>{e.statement}</h3><span className='text-muted-foreground text-xs'>{label(e.status)}{e.decision ? ` · ${label(e.decision)}` : ''}</span></div>
    <p className='text-muted-foreground mt-2 text-xs'>{e.cohort.provider} · {e.cohort.language} · {label(e.cohort.contentTypeId)} · {e.metric} · {e.minimumPerArm} measured posts per arm · {e.windowDays} days</p>
    {e.endAt && <p className='text-muted-foreground mt-2 text-xs'>Observation window ends {date(e.endAt)}. No early winner.</p>}
    <details className='mt-3 text-sm'><summary className='rafii-focus min-h-11 cursor-pointer'>See design and evidence</summary><div className='text-muted-foreground flex flex-col gap-2 py-3'>
      <p>Variant: {label(e.variantFactor)}; control: {label(e.controlFactor)}. Account: {e.cohort.connectionId}. Hypothesis revision {e.hypothesisRevision}. Definition: {e.cohort.definitionVersion}.</p>
      {e.limitations.map(l => <p key={l}>{l}</p>)}
      {e.result && <><p>{e.result.interpretation}</p><p>Samples: {e.result.samples.variant} variant / {e.result.samples.control} control; {e.result.missing} missing. Median: {value(e.result.medianVariant)} / {value(e.result.medianControl)}.</p><p>{e.result.evidenceIds.length} supporting posts · {e.result.counterEvidenceIds.length} counter-evidence posts. Causal: false.</p><p className='break-all text-xs'>Supporting job IDs: {e.result.evidenceIds.join(', ') || 'None'}. Counter-evidence job IDs: {e.result.counterEvidenceIds.join(', ') || 'None'}.</p></>}
      <Link className='rafii-focus inline-flex min-h-11 items-center underline' href='/app/analytics#post-performance-heading'>See posts and provider readings</Link>
    </div></details>
    {owner && <div className='mt-3 flex flex-wrap gap-2'>{(actions[e.status] || []).map(([action, text]) => <Button key={action} variant='glass' disabled={pending || action === 'measure' && Boolean(e.endAt && e.endAt * 1000 > Date.now()) || action === 'apply' && !e.result?.supportedFactor || action === 'revoke' && e.decision !== 'applied'} onClick={() => act(action)}>{text}</Button>)}</div>}
    {owner && ['complete', 'insufficient_data', 'cancelled', 'dismissed', 'rejected'].includes(e.status) && <Button variant='glass' className='mt-2' disabled={pending} onClick={repeat}>Run another test</Button>}
  </Surface>;
}

function ProofCard({ proof: p, open, act }: { proof: GrowthProof; open: () => void; act: () => void }) {
  return <Surface material='quiet' className={cn('p-5')} as='article' id={p.id} aria-label={`${p.frequency} proof of value`}>
    <h3 className='text-sm font-medium'>{p.frequency === 'monthly' ? "Rafii's monthly learning" : 'Your week with Rafii'} · {date(p.periodStart)}–{date(p.periodEnd - 1)}</h3>
    <dl className='mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4'>{([['Accepted or approved', p.counts.preparedPosts], ['Approved', p.counts.approvedPosts], ['Verified published', p.counts.verifiedPublishedPosts], ['Experiments completed', p.counts.completedExperiments]] as const).map(([name, n]) => <div key={name}><dt className='text-muted-foreground text-xs'>{name}</dt><dd className='mt-1 text-xl tabular-nums'>{n}</dd></div>)}</dl>
    <p className='text-muted-foreground mt-3 text-xs'>{p.counts.campaigns} campaigns · {p.counts.engagementHandled} engagement items handled · {p.counts.opportunitiesActedOn} opportunities acted on · {p.counts.nextWeekPrepared} next-week posts accepted</p>
    <p className='text-muted-foreground mt-3 text-sm'>Time Back: {p.timeBack.coverage === 'unavailable' ? 'Unavailable' : p.timeBack.byConfidence.length ? p.timeBack.byConfidence.map(t => `${Math.round(t.savedSeconds / 60)} min (${t.confidence})`).join(' · ') : 'No completed Time Back outcomes in this period'}.</p>
    {p.goal && <p className='text-muted-foreground mt-2 text-xs'>Goal at period close: {p.goal.name} · {value(p.goal.currentValue)} · {p.goal.coverage.status}.</p>}
    {p.frequency === 'monthly' && p.historyCoverage !== 'sufficient' && <p className='text-muted-foreground mt-3 text-sm'>Insufficient history to claim a monthly improvement trend.</p>}
    {p.frequency === 'monthly' && p.historyCoverage === 'sufficient' && p.learningSummary && <p className='text-muted-foreground mt-3 text-sm'>Approval rate: {value(p.learningSummary.priorApprovalRate == null ? null : Math.round(p.learningSummary.priorApprovalRate * 100))}% → {value(p.learningSummary.approvalRate == null ? null : Math.round(p.learningSummary.approvalRate * 100))}%. Median edit distance: {value(p.learningSummary.priorMedianEditDistance)} → {value(p.learningSummary.medianEditDistance)}. {p.learningSummary.acceptedPreferenceLearnings} preference learnings accepted.</p>}
    <details className='mt-3 text-sm' onToggle={e => { if (e.currentTarget.open) open(); }}><summary className='rafii-focus min-h-11 cursor-pointer'>See recap evidence</summary><div className='text-muted-foreground flex flex-col gap-2 py-2'>{p.limitations.map(l => <p key={l}>{l}</p>)}<p className='break-all text-xs'>Verified job IDs: {p.counts.evidence.jobIds.join(', ') || 'None'}. Accepted variant IDs: {p.counts.evidence.variantIds.join(', ') || 'None'}.</p><Link className='rafii-focus inline-flex min-h-11 items-center underline' href='/app/queue'>Open Queue receipts</Link></div></details>
    <Button variant='glass' className='mt-2' onClick={act}>Prepare next week</Button>
  </Surface>;
}
