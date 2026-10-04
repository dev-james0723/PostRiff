'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { parseAsStringLiteral, useQueryState } from 'nuqs';
import { IconArrowRight, IconChartDots3, IconDna2, IconMessageCircle2, IconCheck, IconClock, IconArrowUpRight } from '@tabler/icons-react';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { GrowthOverview, Postmortem } from '@/lib/growth/types';
import { GrowthConsent, useGrowthCatalog } from './shared';
import { EmptyGrowth, GrowthHero, useGrowthAction } from './studio-parts';
import { AudienceMiner } from './audience-miner';
import { readingState } from './measurement-state';

const VIEWS = ['results', 'audience', 'patterns'] as const;
const TABS = [{ id: 'results', label: 'Your results', icon: IconChartDots3 }, { id: 'audience', label: 'Your audience', icon: IconMessageCircle2 }, { id: 'patterns', label: 'Your patterns', icon: IconDna2 }] as const;

export function GrowthStudio() {
  const { workspaceId } = useWorkspaceApi();
  return <Studio key={workspaceId} />;
}

function Studio() {
  const catalog = useGrowthCatalog();
  const { api, workspaceId } = useWorkspaceApi();
  const [view, setView] = useQueryState('view', parseAsStringLiteral(VIEWS).withDefault('results'));
  const overview = useQuery({ queryKey: ['growth-overview', workspaceId], queryFn: () => api.growthOverview(workspaceId), enabled: catalog.data?.postmortem === true, retry: false });
  return <PageContainer pageTitle='Growth Studio'>
    <div className='growth-studio'>
      <GrowthHero eyebrow='Your creative practice, evolving' title='Make every post' accent='a little more you.' description='See what resonates, listen to your audience, and decide what to carry into your next idea.' />
      <div className='growth-tabs' role='tablist' aria-label='Growth Studio views'>
        {TABS.map(({ id, label, icon: Icon }, i) => <button key={id} id={`tab-${id}`} role='tab' aria-selected={view === id} aria-controls={`panel-${id}`} tabIndex={view === id ? 0 : -1} onClick={() => void setView(id)} onKeyDown={(event) => {
          const next = event.key === 'ArrowRight' ? (i + 1) % TABS.length : event.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : null;
          if (next !== null) { event.preventDefault(); void setView(TABS[next].id); document.getElementById(`tab-${TABS[next].id}`)?.focus(); }
        }}><Icon size={18} aria-hidden />{label}</button>)}
      </div>
      {catalog.isPending ? <p role='status' className='growth-loading'>Opening your studio…</p> : catalog.isError ? <p role='alert'>Your growth settings could not be loaded. <Button variant='quiet' onClick={() => void catalog.refetch()}>Try again</Button></p> : !catalog.data?.postmortem && !catalog.data?.audienceMiner ? <EmptyGrowth title='Growth Studio is not enabled here yet.'><p>Your drafts and existing analytics are still available.</p><Link href='/app/analytics'>Open analytics <IconArrowRight size={16} aria-hidden /></Link></EmptyGrowth> : <>
        {catalog.data && <details className='growth-permission'><summary>AI permissions & daily allowances</summary><GrowthConsent catalog={catalog.data} onChange={() => void catalog.refetch()} /></details>}
        <section key={view} id={`panel-${view}`} role='tabpanel' aria-labelledby={`tab-${view}`} className='growth-view'>
          {view === 'audience' ? <AudienceMiner /> : !catalog.data?.postmortem ? <EmptyGrowth title='Postmortems are not enabled here yet.'><p>Your normal analytics remain available.</p></EmptyGrowth> : overview.isPending ? <p role='status' className='growth-loading'>Gathering verified readings…</p> : overview.isError ? <p role='alert'>Readings could not be loaded. <Button variant='quiet' onClick={() => void overview.refetch()}>Try again</Button></p> : overview.data ? view === 'results' ? <Results data={overview.data} onRefresh={() => void overview.refetch()} /> : <Patterns data={overview.data} /> : <EmptyGrowth title='Postmortems are not enabled here yet.'><p>Your normal analytics remain available.</p></EmptyGrowth>}
        </section>
      </>}
    </div>
  </PageContainer>;
}

function Results({ data, onRefresh }: { data: GrowthOverview; onRefresh: () => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const catalog = useGrowthCatalog();
  const [selectedId, setSelectedId] = useState(data.posts[0]?.jobId ?? '');
  const [horizon, setHorizon] = useState<'1h' | '24h' | '7d'>('24h');
  const [report, setReport] = useState<Postmortem | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<string | null>(null);
  const selected = data.posts.find((p) => p.jobId === selectedId) ?? data.posts[0];
  const saved = data.reports.find((r) => r.jobId === selected?.jobId && r.horizon === horizon);
  const shown = saved ?? (report && selected && report.jobId === selected.jobId && report.horizon === horizon ? report : null);
  const staleBasis = saved?.status === 'stale' ? saved.basisDigest : null;
  useEffect(() => { request.current = null; setConfirmed(false); setReport(null); setError(''); }, [selected?.jobId, horizon, staleBasis]);
  async function review() {
    if (!selected) return;
    setBusy(true); setError(''); request.current ??= crypto.randomUUID();
    try { setReport(await api.postmortem(workspaceId, { jobId: selected.jobId, horizon, confirmed, requestKey: request.current })); onRefresh(); }
    catch (err) { setError(err instanceof Error ? err.message : 'This review could not be completed.'); }
    finally { setBusy(false); }
  }
  const ready = data.posts.filter((p) => p.windows.some((w) => w.available)).length;
  const reading = readingState(selected?.windows.find((w) => w.horizon === horizon));
  if (!selected) return data.measurement?.analyticsConnections === 0 ? <EmptyGrowth title='Native post analytics are unavailable.'><p>Connect an owned Threads or Instagram account with analytics permission before Rafii can measure your verified publications.</p><Link href='/app/channels'>Connect analytics <IconArrowRight size={16} aria-hidden /></Link></EmptyGrowth> : data.measurement?.enabled === false ? <EmptyGrowth title='Post readings are not enabled.'><p>Metric collection is disabled. Your existing analytics remain available.</p><Link href='/app/analytics'>Open analytics <IconArrowRight size={16} aria-hidden /></Link></EmptyGrowth> : <EmptyGrowth title='Your first field note is still ahead.'><p>After a publication is verified, its own platform readings will appear here at one hour, one day and one week.</p><Link href='/app/queue'>See your drafts <IconArrowRight size={16} aria-hidden /></Link></EmptyGrowth>;
  return <>
    <div className='growth-section-heading'><div><p className='growth-kicker'>01 / Observe</p><h3>What happened after publish.</h3></div><span className='growth-count'><strong>{ready}</strong> posts with readings</span></div>
    <div className='growth-results-layout'>
      <aside className='growth-post-list' aria-label='Choose a publication'>{data.posts.map((p) => <button key={p.jobId} className={selected.jobId === p.jobId ? 'is-selected' : ''} aria-pressed={selected.jobId === p.jobId} disabled={busy} onClick={() => setSelectedId(p.jobId)}>
        <span className='growth-post-meta'>{p.platform}<span>{new Date(p.at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span></span>
        <strong>{p.title || 'Published post'}</strong><span className='growth-windows'>{p.windows.map((w) => <span key={w.horizon} data-available={w.available}><span aria-hidden>{w.available ? '●' : '○'}</span> {w.horizon}<span className='sr-only'> {readingState(w).label}</span></span>)}</span>
      </button>)}</aside>
      <div className='growth-report-paper'>
        <div className='growth-report-top'><span className='growth-kicker'>Field note / {selected.platform}</span><div className='growth-horizons' role='group' aria-label='Reading window'>{(['1h','24h','7d'] as const).map((h) => <button key={h} aria-pressed={horizon === h} disabled={busy} onClick={() => setHorizon(h)}>{h}</button>)}</div></div>
        <h3 className='growth-post-title'>{selected.title || 'Your published post'}</h3>
        {shown && shown.status !== 'stale' ? <Report key={shown.id} report={shown} /> : <div className='growth-review-start'>
          <IconClock size={28} aria-hidden /><h4>{shown?.status === 'stale' ? 'There’s new evidence to review.' : reading.title}</h4>
          <p>{reading.detail}</p>
          {selected.windows.find((w) => w.horizon === horizon)?.available && checkAccess(access, { permission: 'edit' }) && <>
            <label className='growth-check'><input type='checkbox' aria-label='Use the allowed AI models to review these readings within my daily allowance.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />Use the allowed AI models to review these readings within my daily allowance.</label>
            <Button className='growth-primary' disabled={busy || !confirmed || !catalog.data?.allowedRoutes.includes(catalog.data.summaryRoute)} onClick={() => void review()}>{busy ? 'Reviewing this window…' : 'Review this result'}<IconArrowUpRight size={17} aria-hidden /></Button>
            {!catalog.data?.allowedRoutes.includes(catalog.data.summaryRoute) && <p>Allow the explanation model in AI permissions above first.</p>}
          </>}
        </div>}
        {error && <p role='alert' className='growth-error'>{error}</p>}
      </div>
    </div>
    <p className='growth-footnote'>{data.notice} Up to {data.coverage.maximumPosts} recent verified publications are included.</p>
  </>;
}

function Report({ report }: { report: Postmortem }) {
  const action = useGrowthAction();
  const catalog = useGrowthCatalog();
  const owner = useWorkspaceAccess().role === 'owner' && catalog.data?.genome === true;
  const [lesson, setLesson] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  return <div className='growth-report-body'>
    <dl className='growth-metric-row'>{Object.entries(report.reading.metrics).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value.value === null ? '—' : value.value.toLocaleString()}</dd><dd className='growth-metric-note'>{value.multiple != null ? `${value.multiple}× your median` : value.median === 0 ? 'Median is zero; no ratio' : `${value.baselineCount} comparable posts; need 3`}</dd></div>)}</dl>
    <div className='growth-comparison'><div className='growth-comparison-head'><span>Before publish</span><span>What we observed</span></div>
      {report.comparisons.length ? report.comparisons.map((row) => <div className='growth-comparison-row' key={row.dimension + row.metric}><span><strong>{row.label}</strong><small>{row.levelName}</small></span><span><b className={`growth-tag is-${row.status}`}>{row.status.replaceAll('_', ' ')}</b><small>{row.metric} · {row.outcome.percentile}th percentile in your cohort</small></span></div>) : <p className='growth-footnote'>This window needs a matching saved judgment and at least three comparable posts before advice can be compared.</p>}
    </div>
    {report.explanation && <div className='growth-observation'><span className='growth-kicker'>A useful next step</span><p>{report.explanation.nextStep}</p><small>{report.explanation.text}</small></div>}
    {report.lessons.length > 0 && <div className='growth-lesson'><div className='growth-section-heading'><div><p className='growth-kicker'>02 / Carry it forward</p><h4>A lesson for your Genome?</h4></div><IconDna2 size={24} aria-hidden /></div>
      {report.status === 'approved' ? <p className='growth-success'><IconCheck size={18} aria-hidden />Saved as a new Genome version. You can restore an older version in Brand & voice.</p> : report.status === 'dismissed' ? <p>Kept as an observation. Your Genome was not changed.</p> : <>
        {report.lessons.map((l) => <label key={l.id} aria-label={l.label} className={`growth-lesson-choice ${lesson === l.id ? 'is-selected' : ''}`}><input type='radio' aria-label={l.label} name={`lesson-${report.id}`} checked={lesson === l.id} disabled={!owner || l.grade === 'conflicting'} onChange={() => { setLesson(l.id); setConfirmed(false); }} /><span><strong>{l.label}</strong><small>{l.text}</small><span className={`growth-tag is-${l.grade}`}>{l.grade} · {l.evidenceIds.length} supporting / {l.counterEvidenceIds.length} counterexamples</span></span></label>)}
        {owner && <><label className='growth-check'><input type='checkbox' aria-label='I reviewed this lesson. Save a new Genome version; limited evidence stays an observation.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I reviewed this lesson. Save a new Genome version; limited evidence stays an observation.</label><div className='growth-actions'><Button className='growth-primary' disabled={!lesson || !confirmed || action.busy} onClick={() => void action.run('postmortem_lesson_approve', { reportId: report.id, lessonId: lesson, confirmed })}>Save to my Genome<IconArrowRight size={17} aria-hidden /></Button><Button variant='quiet' disabled={action.busy} onClick={() => void action.run('postmortem_dismiss', { reportId: report.id })}>Keep as observation</Button></div></>}
      </>}
      <Link className='growth-text-link' href='/app/workspace/brand'>Open Brand & voice <IconArrowUpRight size={15} aria-hidden /></Link>
    </div>}
    {action.error && <p role='alert' className='growth-error'>{action.error}</p>}
    <p className='growth-footnote'>{report.notice}</p>
  </div>;
}

function Patterns({ data }: { data: GrowthOverview }) {
  const action = useGrowthAction();
  const owner = useWorkspaceAccess().role === 'owner';
  const [selected, setSelected] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const c = data.calibration;
  const version = c.versions.find((v) => v.id === selected) ?? c.versions[0];
  return <div className='growth-patterns'><div className='growth-section-heading'><div><p className='growth-kicker'>03 / Learn, deliberately</p><h3>Your history sets the context.</h3></div><IconDna2 size={32} aria-hidden /></div>
    <div className='growth-pattern-grid'><div className='growth-pattern-progress'><span className='growth-kicker'>Comparable publications</span><p><strong>{c.largestCohort}</strong><span> / {c.minimumPosts}</span></p><div className='growth-progress-track' aria-hidden><span style={{ transform: `scaleX(${Math.min(1, c.largestCohort / c.minimumPosts)})` }} /></div><p>One account, platform, language, format, metric and model. Enough evidence before personalizing.</p></div><div><h4>Learn from the past.<br /><em>Check against what comes next.</em></h4><p>Older publications fit the levels and weights. Newer publications test them. An owner reviews each proposed version before it influences Post Doctor.</p><p className='growth-footnote'>This calibrates associations with observed outcomes, separately from the writing-quality rubric.</p></div></div>
    <div className='growth-actions'><Button className='growth-primary' disabled={!owner || !c.available || action.busy} onClick={() => void action.run('creator_calibration_propose', {})}>Prepare a calibration<IconArrowRight size={17} aria-hidden /></Button><Link className='growth-text-link' href='/app/workspace/brand'>Review Creator Genome <IconArrowUpRight size={16} aria-hidden /></Link></div>
    {!c.available && <p className='growth-footnote'>Not enough evidence for a validated personal calibration yet. Existing Post Doctor feedback remains available.</p>}
    {version && <section className='growth-calibration-review'><label>Calibration version<select aria-label='Calibration version' value={version.id} onChange={(e) => { setSelected(e.target.value); setConfirmed(false); }}>{c.versions.map((v, i) => <option key={v.id} value={v.id}>Version {c.versions.length - i} · {v.status}</option>)}</select></label>
      {version.candidates.map((candidate, i) => <div key={i}><h4>{candidate.cohort[0]} · {candidate.metric} · {candidate.postCount} publications</h4><ul>{candidate.dimensions.map((d) => <li key={d.id}>{d.id} — holdout Spearman {d.holdoutSpearman}; weight {d.weight}; {d.trainCount} training / {d.holdoutCount} held out</li>)}</ul></div>)}
      {owner && ['proposed', 'superseded'].includes(version.status) && <><label className='growth-check'><input type='checkbox' aria-label='I reviewed the evidence and want this version used.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I reviewed the evidence and want this version used.</label><Button className='growth-primary' disabled={!confirmed || action.busy} onClick={() => void action.run(version.status === 'superseded' ? 'creator_calibration_restore' : 'creator_calibration_approve', { calibrationId: version.id, confirmed })}>{version.status === 'superseded' ? 'Restore this calibration' : 'Use this calibration'}</Button></>}
    </section>}
    {action.error && <p role='alert' className='growth-error'>{action.error}</p>}
  </div>;
}
