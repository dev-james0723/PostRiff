'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { useChannels, useSnapshot } from '@/lib/api/hooks';
import { useCoworkerApi } from '@/lib/coworker/hooks';
import { errorMessage } from '@/lib/coworker/api';
import { useWorkspace } from '@/lib/workspace/provider';
import { REVIEW_SCHEMA_VERSION, REVIEW_STATE_LABELS, reviewContextInputSchema, reviewDisplayState, type MetricEvidence, type ReviewInput, type ReviewProjection } from '@/lib/analytics/review-contract';
import { ReviewActions } from './review-actions';

function inputFromLocation(): Partial<ReviewInput> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = new URLSearchParams(window.location.search).get('reviewScope');
    if (!raw || raw.length > 16000) return {};
    const parsed = reviewContextInputSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : {};
  } catch { return {}; }
}

export function ReviewPanel({ destination = 'growth' }: { destination?: 'growth' | 'analytics' }) {
  const { workspaceId } = useWorkspace();
  return workspaceId ? <ReviewScope key={workspaceId} destination={destination} /> : null;
}

function Evidence({ evidence }: { evidence: MetricEvidence }) {
  const state = reviewDisplayState(evidence);
  return <details className='rounded-lg border p-3'>
    <summary className='rafii-focus cursor-pointer text-sm'>
      <span className='font-medium'>{evidence.nativeName}: {evidence.value === null ? '—' : evidence.value.toLocaleString()}</span>
      <span className='text-muted-foreground'> · {REVIEW_STATE_LABELS[state] ?? state}</span>
    </summary>
    <dl className='mt-3 grid gap-1 break-words text-xs'>
      <div><dt className='inline font-medium'>Publication: </dt><dd className='inline'>{evidence.publicationBinding.publicationAt}</dd></div>
      <div><dt className='inline font-medium'>Observed: </dt><dd className='inline'>{evidence.observedAt ?? 'Unknown'}</dd></div>
      <div><dt className='inline font-medium'>Stored: </dt><dd className='inline'>{evidence.ingestedAt ?? 'Unknown'}</dd></div>
      <div><dt className='inline font-medium'>Definition: </dt><dd className='inline'>{evidence.provider} / {evidence.definitionVersion} / {evidence.unit}</dd></div>
      <div><dt className='inline font-medium'>Window: </dt><dd className='inline'>{evidence.readOffset ?? 'Unknown'} · cumulative at observation</dd></div>
      {evidence.reason && <div><dt className='inline font-medium'>Comparison excluded: </dt><dd className='inline'>{REVIEW_STATE_LABELS[evidence.reason] ?? evidence.reason.replaceAll('_', ' ')}</dd></div>}
      {evidence.sourceRef && <div><dt className='inline font-medium'>Native method: </dt><dd className='inline'>{evidence.sourceRef}</dd></div>}
      <div><dt className='inline font-medium'>Last attempt: </dt><dd className='inline'>{evidence.lastAttemptState ?? evidence.collectionState}</dd></div>
    </dl>
  </details>;
}

function ReviewScope({ destination }: { destination: 'growth' | 'analytics' }) {
  const { api, w, enabled } = useCoworkerApi();
  const channels = useChannels();
  const snapshot = useSnapshot();
  const cache = useQueryClient();
  const [input, setInput] = useState<Partial<ReviewInput>>(inputFromLocation);
  const accounts = useMemo(() => channels.data?.channels ?? [], [channels.data]);
  const channelIds = input.channelIds ?? accounts.filter((a) => a.connectionState === 'connected').map((a) => a.id).slice(0, 8);
  const storedZone = snapshot.data?.state.timeZone;
  const timezone = input.relativeDateRule?.timezone ?? input.publicationPeriod?.timezone ?? (typeof storedZone === 'string' ? storedZone : 'UTC');
  const scope = useMemo<ReviewInput>(() => ({
    ...input, channelIds, ...(input.publicationPeriod ? {} : { relativeDateRule: input.relativeDateRule ?? { kind: 'this_week', timezone } }),
    horizon: input.horizon ?? '24h', aggregation: input.aggregation ?? 'median', comparison: input.comparison ?? { kind: 'none' }
  }), [input, channelIds, timezone]);
  const scopeKey = JSON.stringify(scope);
  const epoch = JSON.stringify([channels.data?.channels,snapshot.data?.state.accountDeletion]);
  const query = useQuery({
    queryKey: ['review', w, REVIEW_SCHEMA_VERSION, scopeKey, epoch],
    enabled: enabled && Boolean(channels.data && snapshot.data), retry: false, staleTime: 0,
    queryFn: async () => {
      const result = await api.review(w, scope);
      if (result.resolvedContext.workspaceId !== w) throw new Error('Review response belongs to a different workspace.');
      cache.setQueryData(['review-evidence', w, result.contextDigest, REVIEW_SCHEMA_VERSION, result.resolvedContext.rightsEpoch], result);
      return result;
    }
  });
  const result = !query.isFetching && !query.error && query.data?.resolvedContext.workspaceId === w ? query.data : null;
  const [lastProjection,setLastProjection]=useState<ReviewProjection|null>(null);
  useEffect(()=>{if(result)setLastProjection(result);},[result]);
  const actionProjection=result??lastProjection;
  const formats = [...new Set((snapshot.data?.state.phase2?.jobs ?? []).map((j) => (j.manifest as unknown as {contentType?:{formatId?:string}})?.contentType?.formatId).filter((f): f is string => Boolean(f)))];
  const change = (patch: Partial<ReviewInput>) => setInput((old) => ({ ...old, ...patch, cutoffAt: undefined }));
  const relative = input.relativeDateRule?.kind ?? 'this_week';
  const error = query.error ?? channels.error ?? snapshot.error;
  const shared = result ? { ...scope, relativeDateRule: undefined, publicationPeriod: result.resolvedContext.publicationPeriod, cutoffAt: result.resolvedContext.cutoffAt } : scope;
  return <section aria-label='Evidence review' className='min-w-0 rounded-xl border bg-card p-4 sm:p-5'>
    <div className='mb-4'><h2 className='text-lg font-semibold'>Review your published content</h2><p className='text-muted-foreground text-sm'>A fixed post-age window, each platform’s own numbers and a traceable next step.</p></div>
    <div className='grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4'>
      <label className='text-sm'>Account<select className='rafii-field rafii-focus mt-1 w-full min-w-0 rounded-md border p-2' value={channelIds.length === 1 ? channelIds[0] : ''} onChange={(e) => change({ channelIds: e.target.value ? [e.target.value] : accounts.map((a) => a.id).slice(0,8) })}>
        <option value=''>Accounts shown separately</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.platform} · {a.account}</option>)}
      </select></label>
      <label className='text-sm'>Publication dates<select className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={input.publicationPeriod ? 'fixed' : relative} onChange={(e) => change({ publicationPeriod: undefined, relativeDateRule: { kind: e.target.value as NonNullable<ReviewInput['relativeDateRule']>['kind'], timezone } })}>
        {input.publicationPeriod && <option value='fixed'>Fixed UTC period</option>}<option value='this_week'>This week</option><option value='last_week'>Last week</option><option value='this_month'>This month</option><option value='last_month'>Last month</option>
      </select></label>
      <label className='text-sm'>Post age<select className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={scope.horizon} onChange={(e) => change({ horizon: e.target.value as ReviewInput['horizon'] })}><option value='1h'>1 hour</option><option value='24h'>24 hours</option><option value='7d'>7 days</option></select></label>
      <label className='text-sm'>Timezone<input aria-label='Review timezone' className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={timezone} onChange={(e) => change({ publicationPeriod: undefined, relativeDateRule: { kind: relative, timezone: e.target.value } })} /></label>
    </div>
    <details className='mt-3'><summary className='rafii-focus cursor-pointer text-sm'>Language, format and comparison</summary>
      <div className='mt-3 grid gap-3 sm:grid-cols-3'>
        <label className='text-sm'>Language<input aria-label='Language' placeholder='All languages (unknown stays unknown)' className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={input.language ?? ''} onChange={(e) => change({ language: e.target.value || null })} /></label>
        <label className='text-sm'>Format<select className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={input.formatIds?.[0] ?? ''} onChange={(e) => change({ formatIds: e.target.value ? [e.target.value] : [] })}><option value=''>Formats shown separately</option>{formats.map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
        <label className='text-sm'>Comparison<select className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={input.comparison?.kind ?? 'none'} onChange={(e) => {
          if (e.target.value === 'none' || !result) return change({ comparison: { kind: 'none' } });
          const p = result.resolvedContext.publicationPeriod; const end = new Date(p.start); const start = new Date(end.getTime() - (Date.parse(p.end) - Date.parse(p.start)));
          change({ comparison: { kind: 'previous_period', publicationPeriod: { start: start.toISOString().replace('.000Z','Z'), end: p.start, timezone: p.timezone } } });
        }}><option value='none'>No comparison</option><option value='previous_period' disabled={!result}>Previous period</option></select></label>
      </div>
      <div className='mt-3 grid gap-3 sm:grid-cols-3'>
        <label className='text-sm'>Native metric<select aria-label='Native metric filter' className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' value={input.nativeMetric?.length===1?JSON.stringify(input.nativeMetric[0]):''} onChange={e=>change({nativeMetric:e.target.value?[JSON.parse(e.target.value)]:undefined})}><option value=''>Native metrics shown separately</option>{query.data?.resolvedContext.nativeMetric.map(m=><option key={JSON.stringify(m)} value={JSON.stringify(m)}>{m.provider} · {m.nativeName}</option>)}</select></label>
        <label className='text-sm'>UTC publication start<input aria-label='UTC publication start' className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' placeholder='YYYY-MM-DDTHH:mm:ssZ' value={input.publicationPeriod?.start??result?.resolvedContext.publicationPeriod.start??''} onChange={e=>change({relativeDateRule:undefined,publicationPeriod:{start:e.target.value,end:input.publicationPeriod?.end??result?.resolvedContext.publicationPeriod.end??e.target.value,timezone}})}/></label>
        <label className='text-sm'>UTC publication end (excluded)<input aria-label='UTC publication end excluded' className='rafii-field rafii-focus mt-1 w-full rounded-md border p-2' placeholder='YYYY-MM-DDTHH:mm:ssZ' value={input.publicationPeriod?.end??result?.resolvedContext.publicationPeriod.end??''} onChange={e=>change({relativeDateRule:undefined,publicationPeriod:{start:input.publicationPeriod?.start??result?.resolvedContext.publicationPeriod.start??e.target.value,end:e.target.value,timezone}})}/></label>
      </div>
    </details>
    <div className='mt-4 space-y-3' aria-live='polite'>
      {error ? <div role='alert'><p>{errorMessage(error,'Unable to read this scope.')}</p><Button variant='quiet' onClick={() => { void channels.refetch(); void snapshot.refetch(); void query.refetch(); }}>Retry current reading</Button></div> : !result ? <p role='status'>Loading the current scope…</p> : <>
        <p className='text-muted-foreground break-words text-xs'>{result.resolvedContext.publicationPeriod.start} → {result.resolvedContext.publicationPeriod.end} (end excluded) · {result.resolvedContext.publicationPeriod.timezone} · cumulative at {result.resolvedContext.horizon}.</p>
        <p className='text-sm'>{result.coverage.eligible} of {result.coverage.publications} publications have qualified readings. {result.coverage.missing} metric readings excluded or missing. Promotion status unknown.</p>
        {!channelIds.length ? <p>No connected account. <Link className='underline' href='/app/channels'>Open Channels</Link></p> : !result.groups.length ? <p>No comparable native readings in this scope. <Link className='underline' href='/app/channels'>Check analytics permissions</Link>. Collection start is unknown; HistoryImport is off.</p> :
          <div className='overflow-x-auto rounded-lg border'><table className='w-full text-left text-sm'><caption className='sr-only'>Native metrics by account, language, format and definition</caption><thead><tr>{['Account / cohort','Native metric','Aggregation','Current','Previous','Samples'].map((h) => <th key={h} scope='col' className='p-2 font-medium'>{h}</th>)}</tr></thead><tbody>{result.groups.map((g) => <tr key={JSON.stringify(g.cohort)} className='border-t'><td className='p-2'>{g.cohort.provider} · {g.cohort.connectionId}<small className='block'>{g.cohort.language ?? 'Unknown language'} · {g.cohort.formatId ?? 'Unknown format'}</small></td><td className='p-2'>{g.cohort.nativeName}</td><td className='p-2'>{g.aggregation}</td><td className='p-2'>{g.value ?? '—'}</td><td className='p-2'>{g.baselineValue ?? '—'}</td><td className='p-2'>{g.sampleSize} / {g.baselineSampleSize} · need {g.minimumSample} each</td></tr>)}</tbody></table></div>}
        {result.comparisons.map((c) => <p key={JSON.stringify(c.cohort)} className='text-sm'>{c.cohort.nativeName}: {c.relativeChange === null ? (REVIEW_STATE_LABELS[c.reason ?? 'unavailable'] ?? c.reason?.replaceAll('_',' ')) : `${(c.relativeChange * 100).toFixed(1)}% relative difference`}. Descriptive, causal=false.</p>)}
        {result.nativeResults.length > 0 && <details><summary className='rafii-focus cursor-pointer text-sm'>Metric sources, missing values and exact reading times ({result.nativeResults.length})</summary><div className='mt-3 grid min-w-0 gap-2 sm:grid-cols-2'>{result.nativeResults.map((e,i) => <Evidence key={`${e.publicationBinding.jobId}:${e.nativeName}:${i}`} evidence={e} />)}</div></details>}
        <div className='flex flex-wrap items-center gap-3'><Link className='rafii-focus text-sm underline' href={`/app/${destination}?reviewScope=${encodeURIComponent(JSON.stringify(shared))}`}>Open this scope in {destination === 'growth' ? 'Growth Studio' : 'Analytics'}</Link><span className='text-muted-foreground text-xs'>Filters and reads start no paid work.</span></div>
      </>}
    </div>
    {actionProjection&&<ReviewActions key={actionProjection.resolvedContext.rightsEpoch} visible={Boolean(result)} projection={actionProjection} scope={scope} onScope={setInput} refresh={async()=>{await Promise.all([query.refetch(),snapshot.refetch(),channels.refetch()]);}} />}
  </section>;
}
