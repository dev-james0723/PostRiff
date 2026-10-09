'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { IconArrowUpRight, IconArrowRight, IconMessageCircle2, IconCheck, IconQuote, IconMessages } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { FeatureReadinessNotice } from '@/components/feature-readiness-notice';
import type { FeatureReadiness } from '@/lib/feature-readiness';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useGrowthCatalog } from './shared';
import { EmptyGrowth, useGrowthAction } from './studio-parts';
import { AUDIENCE_REASON_COPY, GROWTH_REASON_COPY, requestErrorMessage, requestKeyAfterError } from './readiness-copy';
import type { AudienceCluster } from '@/lib/growth/types';

const SCHEMA_OUTAGE: FeatureReadiness = { state: 'temporarily_unavailable', reasonCodes: ['growth_schema_unavailable'], canRead: false, canRun: false, lastSuccessfulReadAt: null, nextStep: { kind: 'retry' } };

export function AudienceMiner({ readiness }: { readiness: FeatureReadiness }) {
  const catalog = useGrowthCatalog();
  const { api, workspaceId } = useWorkspaceApi();
  const query = useQuery({ queryKey: ['growth-audience', workspaceId], queryFn: () => api.audienceInsights(workspaceId), enabled: readiness.canRead, retry: false });
  const access = useWorkspaceAccess();
  const [days, setDays] = useState(14);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [summary, setSummary] = useState('');
  const [filter, setFilter] = useState('all');
  const request = useRef<string | null>(null);
  if (!readiness.canRead) return <FeatureReadinessNotice readiness={readiness} reasons={GROWTH_REASON_COPY} onRetry={() => void catalog.refetch()} />;
  if (query.error instanceof ApiError && query.error.code === 'growth_schema_unavailable')
    return <FeatureReadinessNotice readiness={SCHEMA_OUTAGE} reasons={GROWTH_REASON_COPY} onRetry={() => void query.refetch()} />;
  async function analyze() {
    setBusy(true); setError(''); request.current ??= crypto.randomUUID();
    try {
      const result = await api.analyzeAudience(workspaceId, { days, confirmed, requestKey: request.current });
      setSummary(`${result.analyzed} of ${result.available} eligible comments analyzed. ${result.withheld} held out for sensitivity or uncertainty.${result.partial ? ' This is a bounded sample, not the full audience.' : ''}`);
      await query.refetch();
    } catch (err) {
      // A failed run can be retried with a fresh key; an uncertain one keeps its key so nothing is sent twice.
      request.current = requestKeyAfterError(request.current, err);
      if (request.current === null) setConfirmed(false);
      setError(requestErrorMessage(err, 'Audience analysis could not be completed.'));
    }
    finally { setBusy(false); }
  }
  const canRun = checkAccess(access, { permission: 'edit' }) && readiness.canRun;
  const owner = access.role === 'owner';
  const categories = [...new Set(query.data?.clusters.map((c) => c.category) ?? [])];
  const clusters = query.data?.clusters.filter((c) => filter === 'all' || c.category === filter) ?? [];
  const reason = query.data?.reason ? AUDIENCE_REASON_COPY[query.data.reason] : null;
  return <div className='growth-audience'>
    {readiness.state !== 'ready' && <FeatureReadinessNotice className='is-compact' readiness={readiness} reasons={GROWTH_REASON_COPY} onRetry={() => void catalog.refetch()} />}
    <div className='growth-section-heading'><div><p className='growth-kicker'>Listen / Notice / Create</p><h3>The conversation is the starting point.</h3></div><IconMessages size={32} aria-hidden /></div>
    <div className='growth-audience-brief'><div><span className='growth-kicker'>Audience Miner</span><h4>They’re already telling you<br /><em>what to make next.</em></h4><p>Find the questions, requests and different perspectives inside your own post’s comments.</p></div><div className='growth-audience-count'><strong>{query.data?.eligibleComments ?? '—'}</strong><span>eligible comments<br />in the last 30 days</span></div></div>
    {query.isPending && <p className='growth-loading' role='status'>Looking for eligible conversations…</p>}
    {query.isError && <p role='alert' className='growth-error'>Comments could not be loaded. <Button variant='quiet' onClick={() => void query.refetch()}>Try again</Button></p>}
    {query.data && <>
      <div className='growth-audience-controls'><label>Look back<select aria-label='Audience window' value={days} disabled={busy} onChange={(e) => { setDays(Number(e.target.value)); request.current = null; setConfirmed(false); }}>{[7,14,30].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select></label><p>Up to {query.data.maximumPerRun} comments per analysis.<br />Two analyses per workspace each day.</p></div>
      {canRun && <><label className='growth-check'><input type='checkbox' aria-label='Analyze these eligible comments with the allowed AI models within my daily allowance.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />Analyze these eligible comments with the allowed AI models within my daily allowance.</label><Button className='growth-primary' disabled={busy || !confirmed || !query.data.audienceConsent || !query.data.eligibleComments} onClick={() => void analyze()}>{busy ? 'Finding the useful threads…' : 'Find audience insights'}<IconArrowUpRight size={17} aria-hidden /></Button></>}
      {!query.data.audienceConsent && <p className='growth-footnote'>{owner ? 'Allow comment analysis in AI permissions above to analyze these comments.' : 'The owner must allow comment analysis in AI permissions above.'}</p>}
      <p className='growth-footnote'>{query.data.coverage}</p>
      {summary && <p role='status' className='growth-success'>{summary}</p>}
      {query.data.clusters.length > 0 ? <>
        <div className='growth-audience-filters' role='group' aria-label='Audience categories'>{['all', ...categories].map((category) => <button key={category} aria-pressed={filter === category} onClick={() => setFilter(category)}>{category.replaceAll('_',' ')}<span>{category === 'all' ? query.data.clusters.reduce((n,c) => n + c.count,0) : query.data.clusters.filter((c) => c.category === category).reduce((n,c) => n + c.count,0)}</span></button>)}</div>
        <div className='growth-cluster-grid'>{clusters.map((cluster, i) => <Cluster key={cluster.id} cluster={cluster} index={i} />)}</div>
      </> : <EmptyGrowth title='A good question can become a great post.'><p>{query.data.eligibleComments ? 'Run an analysis to find themes in the eligible comments.' : reason?.detail ?? 'There are no eligible comments yet. Comments must belong to your own posts on an authorized Threads or Instagram account.'}</p><Link href='/app/inbox'>Go to your inbox <IconArrowRight size={16} aria-hidden /></Link></EmptyGrowth>}
      {query.data.conversion.suggestedTopics > 0 && <p className='growth-footnote'>{query.data.conversion.writtenTopics} of {query.data.conversion.suggestedTopics} distinct suggested topics used in a draft. Saved ideas count after you develop them into content.</p>}
      <p className='growth-footnote'>{query.data.notice}</p>
    </>}
    {error && <p role='alert' className='growth-error'>{error}</p>}
  </div>;
}

function Cluster({ cluster, index }: { cluster: AudienceCluster; index: number }) {
  const action = useGrowthAction();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const [confirmed, setConfirmed] = useState(false);
  return <article className={`growth-cluster tone-${index % 3}`}>
    <div className='growth-cluster-top'><span className='growth-kicker'>{cluster.category.replaceAll('_', ' ')}</span><span className='growth-cluster-number'>{String(index + 1).padStart(2, '0')}</span></div>
    <h4>{cluster.label}</h4><p className='growth-cluster-count'><IconMessageCircle2 size={16} aria-hidden />{cluster.count} {cluster.count === 1 ? 'comment' : 'comments'} · {cluster.needsReplyCount} asking for a reply</p>
    {cluster.suggestion && <div className='growth-topic'><span className='growth-kicker'>An idea to explore</span><h5>{cluster.suggestion.title}</h5><p>{cluster.suggestion.question}</p></div>}
    <details className='growth-evidence'><summary><IconQuote size={17} aria-hidden />Read the evidence <span>{cluster.examples.length} examples</span></summary>{cluster.examples.map((e) => <blockquote key={e.id}>{e.text}</blockquote>)}<small>Private excerpts. These are audience questions, not verified facts.</small></details>
    {cluster.sourceId ? <Link href='/app/ideas' className='growth-saved'><IconCheck size={18} aria-hidden />Saved to Ideas<IconArrowUpRight size={16} aria-hidden /></Link> : canEdit && cluster.suggestion && <><label className='growth-check'><input type='checkbox' aria-label='Save this topic for me to develop and fact-check.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />Save this topic for me to develop and fact-check.</label><Button className='growth-save-button' variant='glass' disabled={!confirmed || action.busy} onClick={() => void action.run('audience_suggestion_create', { clusterId: cluster.id, confirmed })}>Save this idea<IconArrowRight size={16} aria-hidden /></Button></>}
    {action.error && <p role='alert' className='growth-error'>{action.error}</p>}
  </article>;
}
