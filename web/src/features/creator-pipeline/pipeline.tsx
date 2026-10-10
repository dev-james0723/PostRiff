'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { ApiError } from '@/lib/api/client';
import { createPipelineApi, readPending, savePending, clearPending, safeHref, type Preview, type Platform, type CreateRequest, type Entry } from '@/lib/agent-runtime/creator-pipeline';
import { OpportunityFeed } from './opportunity-feed';

export function CreatorPipeline() {
  const { user } = useAuth(); const { workspaceId } = useWorkspaceApi(); const access = useWorkspaceAccess();
  const boundary = `${user?.id}:${workspaceId}:${access.role}:${[...access.permissions].sort().join(',')}`;
  return <PipelineWorkspace key={boundary} boundary={boundary} />;
}
const box = 'rounded-xl border border-border bg-card p-4 space-y-3';
function PipelineWorkspace({ boundary }: { boundary: string }) {
  const { user, getToken } = useAuth(); const { workspaceId, api: workspaceApi } = useWorkspaceApi(); const access = useWorkspaceAccess();
  const canEdit = Boolean(user && checkAccess(access, { permission: 'edit' }));
  const api = useMemo(() => createPipelineApi(getToken), [getToken]); const scope = `${user?.id}:${workspaceId}`;
  const [pending, setPending] = useState(() => readPending(scope));
  const [suggestionId, setSuggestionId] = useState(pending?.suggestionId ?? '');
  const [platforms, setPlatforms] = useState<Platform[]>(pending?.platforms ?? ['Threads']);
  const [ceiling, setCeiling] = useState(String((pending?.budgetCeilingUsdMicro ?? 0) / 1_000_000));
  const [preview, setPreview] = useState<Preview | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [created, setCreated] = useState<string | null>(null); const lock = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { if (!pending) setSuggestionId(new URLSearchParams(window.location.search).get('suggestion') ?? ''); }, []);
  const list = useQuery({ queryKey: ['creator-pipeline', boundary], queryFn: ({ signal }) => api.list(workspaceId, signal), enabled: canEdit, retry: false });
  const snapshot = useQuery({ queryKey: ['creator-suggestions', boundary], queryFn: () => workspaceApi.snapshot(workspaceId), enabled: canEdit, retry: false });
  const items = !list.error && list.data?.workspaceId === workspaceId ? list.data.items : [];
  const suggestions = !snapshot.error && snapshot.data?.state.workspace?.id === workspaceId ? snapshot.data.state.raffi?.suggestions?.filter((s) => ['open', 'accepted'].includes(s.status)) ?? [] : [];
  async function review() {
    if (lock.current || pending || !canEdit) return; lock.current = true; setBusy(true); setError(''); setPreview(null); setCreated(null);
    try {
      const value = await api.preview(workspaceId, { suggestionId, platforms, budgetCeilingUsdMicro: Math.round(Number(ceiling) * 1_000_000) });
      if (alive.current && value.workspaceId === workspaceId) setPreview(value);
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : 'Could not load the preview.'); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function submit() {
    if (lock.current || !canEdit || (!pending && !preview?.canCreate)) return;
    const request: CreateRequest = pending ?? { suggestionId: preview!.suggestionId, platforms: preview!.platforms, budgetCeilingUsdMicro: preview!.budgetCeilingUsdMicro, digest: preview!.digest, idempotencyKey: `creator-${crypto.randomUUID()}` };
    lock.current = true; setBusy(true); setError('');
    try {
      savePending(scope, request); setPending(request);
      const value = await api.create(workspaceId, request);
      clearPending(scope);
      if (alive.current) { setPending(null); setPreview(null); setCreated(safeHref(value.href)); await list.refetch(); }
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && ![408, 429].includes(e.status)) { clearPending(scope); if (alive.current) { setPending(null); setPreview(null); } }
      if (alive.current) setError(e instanceof Error ? e.message : 'Result unknown. Reconcile this same request before starting another.');
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  if (!canEdit) return <PageContainer><h1>Creator Pipeline</h1><p role='status'>Your current role cannot open creator tasks.</p></PageContainer>;
  return <PageContainer><div className='mx-auto w-full max-w-4xl space-y-6'>
    <header><h1 className='text-2xl'>Creator Pipeline</h1><p className='text-muted-foreground'>Turn a supported suggestion into an exact draft approval, then follow its saved result.</p></header>
    <OpportunityFeed workspaceId={workspaceId} boundary={boundary} disabled={busy || Boolean(pending) || Boolean(preview)} onPrepare={(id) => { setSuggestionId(id); setCreated(null); document.getElementById('prepare-creator-task')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }} onRefresh={() => { void snapshot.refetch(); void list.refetch(); }} />
    <section id='prepare-creator-task' className={box} aria-label='Prepare a creator task'>
      <h2 className='text-lg'>Prepare a creator task</h2>
      <fieldset disabled={busy || Boolean(pending) || Boolean(preview)} className='space-y-3'>
        <label className='block'>Suggestion<select aria-label='Suggestion' className='block max-w-full rounded border bg-background p-2' value={suggestionId} onChange={(e) => setSuggestionId(e.target.value)}><option value=''>Choose a suggestion</option>{suggestions.map((s) => <option key={s.id} value={s.id}>{s.reason}</option>)}</select></label>
        <div className='flex flex-wrap gap-4'>{(['LinkedIn', 'Instagram', 'Threads'] as Platform[]).map((p) => <label key={p}><input type='checkbox' aria-label={p} checked={platforms.includes(p)} onChange={(e) => setPlatforms(e.target.checked ? [...platforms, p] : platforms.filter((v) => v !== p))} /> {p}</label>)}</div>
        <label className='block'>Task spending ceiling (USD)<input className='ml-2 w-24 rounded border bg-background p-2' aria-label='Task spending ceiling (USD)' type='number' min='0' max='10' step='0.01' value={ceiling} onChange={(e) => setCeiling(e.target.value)} /></label>
        <p className='text-sm text-muted-foreground'>Start at $0 to require a separate spending approval before any paid writing. A ceiling is a limit, not a price estimate.</p>
        <Button onClick={review} disabled={!suggestionId || platforms.length === 0}>Review task</Button>
      </fieldset>
      {preview && <section aria-label='Exact task preview' className='space-y-3'>
        <h3 className='font-medium'>Exact task preview</h3><p>{preview.observation}</p><p>Expected benefit (estimate): {preview.expectedBenefit.text}</p>
        <p>{preview.effort}</p><p>{preview.cost.text}</p><p>Spending ceiling: ${(preview.budgetCeilingUsdMicro / 1_000_000).toFixed(2)}</p>
        <dl><dt>Source</dt><dd className='break-words'>{preview.source.type} {preview.source.id}, revision {preview.source.revision}</dd><dt>Confirmed facts and draft request</dt><dd><pre className='whitespace-pre-wrap break-words text-sm'>{JSON.stringify({ source: preview.source, inputs: preview.inputs }, null, 2)}</pre></dd></dl>
        <ul className='list-inside list-disc'>{preview.permissions.map((p) => <li key={p}>{p}</li>)}</ul>
        {!preview.canCreate && <p role='alert'>Current permission: {preview.permissionReason}</p>}
        <p>Creating saves a task awaiting your exact approval in Task Center. It does not write, schedule or publish a post.</p>
        <Button disabled={busy || Boolean(pending) || !preview.canCreate} onClick={submit}>Create approval task</Button> <Button variant='outline' disabled={busy || Boolean(pending)} onClick={() => setPreview(null)}>Back</Button>
      </section>}
      {pending && <section aria-label='Reconcile pending request'><p>Result unknown. The original selection, digest and request key are retained. Check the same request before starting another.</p><p>Spending ceiling: ${(pending.budgetCeilingUsdMicro / 1_000_000).toFixed(2)}</p><Button disabled={busy} onClick={submit}>Reconcile same request</Button></section>}
      {error && <p role='alert'>{error}</p>}{created && <p role='status'>Task saved. <Link className='underline' href={created}>Review in Task Center</Link></p>}
    </section>
    <section aria-label='Your creator experiments' className='space-y-3'><div className='flex items-center justify-between'><h2 className='text-lg'>Your creator experiments</h2><Button variant='outline' disabled={busy} onClick={() => list.refetch()}>Refresh results</Button></div>
      {list.error && <p role='alert'>{list.error instanceof Error ? list.error.message : 'Results unavailable.'}</p>}
      {!list.error && items.length === 0 && <p>No creator task results yet.</p>}{items.map((entry) => <PipelineEntry key={entry.taskId} entry={entry} />)}
      {list.data?.hasMore && <p>Showing the 20 most recent entries. Older tasks remain in Task Center.</p>}
    </section>
  </div></PageContainer>;
}
export function PipelineEntry({ entry }: { entry: Entry }) {
  return <article className={box}><h3 className='font-medium'>{entry.title}</h3><p>Draft task: {entry.state.replaceAll('_', ' ')}</p><p>Observed when suggested: {entry.observation}</p>{entry.source && <p>Source: {entry.source.type} · revision {entry.source.revision}{entry.recordedAt ? ` · recorded ${new Date(entry.recordedAt * 1000).toISOString()}` : ''}</p>}<p>Expected benefit (estimate): {entry.expectedBenefit.text}</p>
    {safeHref(entry.href) && <Link className='underline' href={entry.href}>Open Task Center</Link>}
    {entry.resultsTruncated && <p>More results exist than shown here. Inspect the full queue before assessing publication.</p>}<p>Saved drafts: {entry.drafts.length}</p>{entry.drafts.map((d) => safeHref(d.href) && <p key={d.id}><Link className='underline' href={d.href}>Edit {d.platform} draft · revision {d.revision}</Link></p>)}
    {entry.jobs.length === 0 && <p>Publication not verified. Review and schedule saved drafts in the existing queue.</p>}
    {entry.jobs.map((j) => <div key={j.id}><p>{j.verified && j.verifiedAt && j.providerReference ? 'Provider publication verified' : 'Publication not verified'} · {j.platform} · {j.state}</p>{j.verifiedAt && <p>Verified: {new Date(j.verifiedAt * 1000).toISOString()}</p>}{safeHref(j.href) && <Link className='underline' href={j.href}>Inspect publishing receipt</Link>}</div>)}
    <details><summary>Experiment and observed outcomes</summary><p>{entry.experiment.hypothesis}</p>{entry.measurement.truncated && <p>Showing the first 40 native post readings. Open Analytics for full coverage.</p>}<p>Measurement: {entry.measurement.status}. {entry.measurement.reason}</p>{entry.measurement.posts?.map((p) => <div key={`${p.provider}:${p.jobId}`}><p>{p.provider} · {p.jobId}</p>{Object.entries(p.metrics).map(([key, metric]) => <p key={key}>{metric.nativeName}: {metric.availability === 'available' && metric.value !== null ? metric.value : 'Unavailable'} · definition {metric.definitionVersion} · {new Date(metric.observedAt * 1000).toISOString()} · period {metric.readOffset ?? 'not recorded'}</p>)}</div>)}<Link className='underline' href='/app/analytics'>Compare in Analytics</Link></details>
  </article>;
}
