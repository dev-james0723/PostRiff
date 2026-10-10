'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/session';
import { ApiError } from '@/lib/api/client';
import { createOpportunityApi, opportunityHref, type Opportunity } from '@/lib/agent-runtime/opportunity-feed';

const date = (value: number | null) => typeof value === 'number' && Number.isFinite(value) ? new Date(value * 1000).toISOString().slice(0, 10) : 'Not recorded';
function Comparison({ item }: { item: Opportunity }) {
  const value = item.measurement?.comparison;
  return value ? <p className='break-words text-sm'>Account: {value.accountLabel} ({value.accountId}) · {value.provider} · language {value.language ?? 'not recorded'} · content type {value.contentTypeId ?? 'not recorded'}. Compare {value.dimension}: {value.armA.replaceAll('_', ' ')} versus {value.armB.replaceAll('_', ' ')}.</p> : null;
}
export function OpportunityFeed({ workspaceId, boundary, disabled, onPrepare, onRefresh }: { workspaceId: string; boundary: string; disabled: boolean; onPrepare: (id: string) => void; onRefresh: () => void }) {
  const { getToken } = useAuth(); const api = useMemo(() => createOpportunityApi(getToken), [getToken]);
  const feed = useQuery({ queryKey: ['opportunity-feed', boundary], queryFn: ({ signal }) => api.list(workspaceId, signal), retry: false });
  const [review, setReview] = useState<Opportunity | null>(null); const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(false);
  const [message, setMessage] = useState(''); const [error, setError] = useState(''); const lock = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const current = !feed.error && feed.data?.workspaceId === workspaceId ? feed.data : null;
  const items = current?.items ?? [];
  const reviewed = review && items.find((item) => item.id === review.id && item.digest === review.digest);
  async function refresh() {
    if (lock.current || disabled) return; lock.current = true; setBusy(true); setError('');
    try { await api.refresh(workspaceId); if (alive.current) { await feed.refetch(); onRefresh(); setUnknown(false); setReview(null); } }
    catch (e) { if (alive.current) { setError(e instanceof Error ? e.message : 'Could not refresh sources.'); await feed.refetch(); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function decide(item: Opportunity, decision: 'dismiss' | 'experiment') {
    if (lock.current || disabled || unknown || (decision === 'experiment' && (!reviewed || reviewed.digest !== item.digest))) return;
    lock.current = true; setBusy(true); setMessage(''); setError('');
    try {
      const result = await api.decide(workspaceId, item, decision);
      if (alive.current && result.workspaceId === workspaceId && result.verified) { setMessage(result.note); setReview(null); await feed.refetch(); onRefresh(); }
      else if (alive.current) { setUnknown(true); setError('Decision unconfirmed. Refresh current source records before another action.'); }
    } catch (e) {
      if (alive.current) {
        const ambiguous = !(e instanceof ApiError && e.status >= 400 && e.status < 500 && ![408, 429].includes(e.status));
        setUnknown(ambiguous); setError(ambiguous ? 'Decision outcome unknown. Refresh source records before another action; nothing is automatically retried.' : e instanceof Error ? e.message : 'Decision unavailable.');
        if (!ambiguous) { setReview(null); await feed.refetch(); }
      }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  return <section aria-label='Opportunity Feed' className='space-y-4'>
    <div className='flex flex-wrap items-center justify-between gap-3'><div><h2 className='text-lg'>Opportunity Feed</h2><p className='text-sm text-muted-foreground'>Specific signals from your existing work and permitted sources.</p></div><Button variant='outline' disabled={busy || disabled} onClick={refresh}>Refresh opportunities</Button></div>
    {feed.isPending && <p role='status'>Loading current sources…</p>}
    {feed.error && <p role='alert'>{feed.error instanceof Error ? feed.error.message : 'Opportunities unavailable.'}</p>}
    {error && <p role='alert'>{error}</p>}{message && <p role='status'>{message}</p>}
    {current && <p className='text-sm text-muted-foreground'>{current.coverage}</p>}
    {current && !items.length && <p>No supported opportunities right now. Refresh checks existing records and makes no model or provider call.</p>}
    {items.map((item) => <article key={item.id} aria-label={item.title} className='space-y-3 rounded-xl border border-border bg-card p-4'>
      <div className='flex flex-wrap items-start justify-between gap-2'><h3 className='font-medium'>{item.title}</h3><span className='text-xs text-muted-foreground'>{item.state.replaceAll('_', ' ')}</span></div>
      <p>{item.reason}</p><p className='text-sm'>Source: {item.source} · recorded {date(item.observedAt)}{item.expiresAt ? ` · expires ${date(item.expiresAt)}` : ''}</p>
      <p className='text-sm'>Expected benefit (estimate): {item.expectedBenefit.text}</p>
      {item.task && <p className='text-sm'>Existing task: {item.task.state.replaceAll('_', ' ')}. Its receipt remains in Task Center.</p>}
      {item.measurement && <p className='text-sm'>Observed: {item.measurement.metric} · {item.measurement.window} reading window · definition {item.measurement.definitionVersion} · {item.measurement.samples.a} / {item.measurement.samples.b} posts · {date(item.measurement.dateRange[0])} to {date(item.measurement.dateRange[1])}. Causation is not established.</p>}
      <Comparison item={item} />
      {item.state === 'experiment' && <p className='text-sm'>Experiment defined. Outcome: {item.experiment?.outcome ?? 'unmeasured'}.</p>}
      <details><summary>Evidence and action preview</summary><p className='mt-2 text-sm'>{item.preview}</p><p className='text-sm'>{item.cost.text}</p><ul className='list-inside list-disc text-sm'>{item.permissions.map(p => <li key={p}>{p}</li>)}</ul><ul className='list-inside list-disc break-words text-sm'>{item.evidence.map((e, index) => <li key={index}>{e.type ?? e.entityType ?? 'Source'}: {e.id ?? e.entityId ?? (e.url ? 'Public source in the original listening panel' : 'See original source')}{e.revision ? ` · revision ${e.revision}` : ''}</li>)}</ul></details>
      <div className='flex flex-wrap gap-3'>
        {item.action.kind === 'open' && opportunityHref(item.action.href) && <Link className='underline' href={item.action.href}>{item.action.label}</Link>}
        {item.action.kind === 'prepare_task' && <Button disabled={disabled || busy || unknown} onClick={() => item.action.kind === 'prepare_task' && onPrepare(item.action.suggestionId)}>{item.action.label}</Button>}
        {item.action.kind === 'experiment' && <Button disabled={disabled || busy || unknown} onClick={() => { setReview(item); setMessage(''); setError(''); }}>{item.action.label}</Button>}
        {item.canDismiss !== false && <Button variant='outline' disabled={disabled || busy || unknown} onClick={() => decide(item, 'dismiss')}>Dismiss {item.dismissalScope === 'person' ? 'for me' : 'for workspace'}</Button>}
      </div>
    </article>)}
    {review && <section aria-label='Exact experiment preview' className='space-y-3 rounded-xl border border-border p-4'>
      <h3 className='font-medium'>Exact experiment preview</h3><p>{review.title}</p><Comparison item={review} /><p>{review.preview}</p><p>Use {review.measurement?.metric} at the same {review.measurement?.window} reading window and definition {review.measurement?.definitionVersion}. Expected benefit is unmeasured.</p>
      <p>This saves an experiment in the existing strategy record. It does not generate content, schedule posts or adopt a writing rule.</p>
      {!reviewed && <p role='alert'>This evidence changed. Refresh opportunities before deciding.</p>}
      <Button disabled={!reviewed || disabled || busy || unknown} onClick={() => decide(review, 'experiment')}>Confirm experiment</Button> <Button variant='outline' disabled={busy || unknown} onClick={() => setReview(null)}>Close preview</Button>
    </section>}
    {current?.hasMore && <p>Showing the first 50 current opportunities. Original panels retain the full source history.</p>}
    <div className='flex flex-wrap gap-4'>{current?.sourceLinks.map(link => opportunityHref(link.href) && <Link key={link.href} className='underline' href={link.href}>{link.label}</Link>)}</div>
  </section>;
}
