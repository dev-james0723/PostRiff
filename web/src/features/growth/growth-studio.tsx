'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { parseAsBoolean, parseAsString, parseAsStringLiteral, useQueryState } from 'nuqs';
import { IconArrowRight, IconChartDots3, IconDna2, IconMessageCircle2, IconCheck, IconClock, IconArrowUpRight } from '@tabler/icons-react';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { FeatureReadinessNotice } from '@/components/feature-readiness-notice';
import { readinessCopy, type FeatureReadiness } from '@/lib/feature-readiness';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { GrowthHistoryPost, GrowthOverview, Postmortem } from '@/lib/growth/types';
import { GrowthConsent, growthReadiness, useGrowthCatalog } from './shared';
import { EmptyGrowth, GrowthHero, useGrowthAction } from './studio-parts';
import { AudienceMiner } from './audience-miner';
import { MeasurementEnrollment } from './measurement-enrollment';
import { readingState, readingStateKey } from './measurement-state';
import { GROWTH_REASON_COPY, ageLabel, metricValue, requestErrorMessage, requestKeyAfterError } from './readiness-copy';
import './growth-readiness.css';

const VIEWS = ['results', 'audience', 'patterns'] as const;
const HORIZONS = ['1h', '24h', '7d'] as const;
const TABS = [{ id: 'results', label: 'Your results', icon: IconChartDots3 }, { id: 'audience', label: 'Your audience', icon: IconMessageCircle2 }, { id: 'patterns', label: 'Your patterns', icon: IconDna2 }] as const;

/** A Growth endpoint that answered 503 growth_schema_unavailable: an honest outage, never a reconnect. */
function schemaOutage(error: unknown): FeatureReadiness | null {
  if (!(error instanceof ApiError) || error.code !== 'growth_schema_unavailable') return null;
  return { state: 'temporarily_unavailable', reasonCodes: ['growth_schema_unavailable'], canRead: false, canRun: false, lastSuccessfulReadAt: null, nextStep: { kind: 'retry' } };
}

export function GrowthStudio() {
  const { workspaceId } = useWorkspaceApi();
  return <Studio key={workspaceId} />;
}

function Studio() {
  const catalog = useGrowthCatalog();
  const { api, workspaceId } = useWorkspaceApi();
  const [view, setView] = useQueryState('view', parseAsStringLiteral(VIEWS).withDefault('results'));
  // The owner's consent step links here with ?permissions=true, which opens the permission panel.
  const [permissions, setPermissions] = useQueryState('permissions', parseAsBoolean.withDefault(false));
  const readiness = growthReadiness(catalog.data);
  const tab = readiness[view];
  const overview = useQuery({ queryKey: ['growth-overview', workspaceId], queryFn: () => api.growthOverview(workspaceId), enabled: Boolean(catalog.data) && readiness.studio.canRead && readiness.results.canRead, retry: false });
  const outage = schemaOutage(overview.error);
  const refreshAll = () => { void catalog.refetch(); void overview.refetch(); };
  return <PageContainer pageTitle='Growth Studio'>
    <div className='growth-studio'>
      <GrowthHero eyebrow='Your creative practice, evolving' title='Make every post' accent='a little more you.' description='See what resonates, listen to your audience, and decide what to carry into your next idea.' />
      {catalog.data && <GrowthStatus readiness={readiness.studio.canRead ? tab : readiness.studio} latest={readiness.measurement.lastSuccessfulReadAt ?? readiness.results.lastSuccessfulReadAt} />}
      <div className='growth-tabs' role='tablist' aria-label='Growth Studio views'>
        {TABS.map(({ id, label, icon: Icon }, i) => <button key={id} id={`tab-${id}`} role='tab' aria-selected={view === id} aria-controls={`panel-${id}`} tabIndex={view === id ? 0 : -1} onClick={() => void setView(id)} onKeyDown={(event) => {
          const next = event.key === 'ArrowRight' ? (i + 1) % TABS.length : event.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : null;
          if (next !== null) { event.preventDefault(); void setView(TABS[next].id); document.getElementById(`tab-${TABS[next].id}`)?.focus(); }
        }}><Icon size={18} aria-hidden />{label}</button>)}
      </div>
      {catalog.data && readiness.studio.canRead && <details className='growth-permission' id='growth-permissions' open={permissions} onToggle={(event) => { const open = event.currentTarget.open; if (open !== permissions) void setPermissions(open || null); }}><summary>AI permissions & daily allowances</summary><GrowthConsent catalog={catalog.data} onChange={() => void catalog.refetch()} /></details>}
      <section key={view} id={`panel-${view}`} role='tabpanel' aria-labelledby={`tab-${view}`} className='growth-view'>
        {catalog.isPending ? <p role='status' className='growth-loading'>Opening your studio…</p>
          : catalog.isError ? <p role='alert'>Your growth settings could not be loaded. <Button variant='quiet' onClick={() => void catalog.refetch()}>Try again</Button></p>
          : !readiness.studio.canRead ? <FeatureReadinessNotice readiness={readiness.studio} reasons={GROWTH_REASON_COPY} onRetry={() => void catalog.refetch()}><Link className='feature-readiness-action' href='/app/analytics'>Open analytics</Link></FeatureReadinessNotice>
          : view === 'audience' ? <AudienceMiner readiness={readiness.audience} />
          : !tab.canRead ? <FeatureReadinessNotice readiness={tab} reasons={GROWTH_REASON_COPY} onRetry={() => void catalog.refetch()} />
          : outage ? <FeatureReadinessNotice readiness={outage} reasons={GROWTH_REASON_COPY} onRetry={refreshAll} />
          : overview.isPending ? <p role='status' className='growth-loading'>Gathering verified readings…</p>
          : overview.isError || !overview.data ? <p role='alert'>Readings could not be loaded. <Button variant='quiet' onClick={() => void overview.refetch()}>Try again</Button></p>
          : view === 'results' ? <Results data={overview.data} readiness={readiness.results} measurement={readiness.measurement} onRefresh={refreshAll} />
          : <Patterns data={overview.data} readiness={readiness.patterns} />}
      </section>
    </div>
  </PageContainer>;
}

/** First-viewport summary: where this tab stands, the next valid step and the latest native reading. */
function GrowthStatus({ readiness, latest }: { readiness: FeatureReadiness; latest: string | null }) {
  const copy = readinessCopy(readiness, GROWTH_REASON_COPY);
  const when = latest ? new Date(latest) : null;
  return <div className='growth-status' data-readiness-state={readiness.state}>
    <span className='growth-status-label'><span className='growth-status-dot' aria-hidden />{readiness.state === 'ready' ? 'Ready to use' : copy.title}</span>
    {copy.action && <span>Next step: <strong>{copy.action}</strong></span>}
    <span>{when && !Number.isNaN(when.getTime()) ? <>Latest reading <time dateTime={latest ?? undefined}>{when.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</time></> : 'No native reading yet'}</span>
  </div>;
}

function Results({ data, readiness, measurement, onRefresh }: { data: GrowthOverview; readiness: FeatureReadiness; measurement: FeatureReadiness; onRefresh: () => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const catalog = useGrowthCatalog();
  const [postParam, setPostParam] = useQueryState('post', parseAsString);
  const [horizon, setHorizon] = useQueryState('window', parseAsStringLiteral(HORIZONS).withDefault('24h'));
  const [report, setReport] = useState<Postmortem | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<string | null>(null);
  const selected = data.posts.find((p) => p.jobId === postParam) ?? data.posts[0];
  const saved = data.reports.find((r) => r.jobId === selected?.jobId && r.horizon === horizon);
  const shown = saved ?? (report && selected && report.jobId === selected.jobId && report.horizon === horizon ? report : null);
  const staleBasis = saved?.status === 'stale' ? saved.basisDigest : null;
  useEffect(() => { request.current = null; setConfirmed(false); setReport(null); setError(''); }, [selected?.jobId, horizon, staleBasis]);
  async function review() {
    if (!selected) return;
    setBusy(true); setError(''); request.current ??= crypto.randomUUID();
    try { setReport(await api.postmortem(workspaceId, { jobId: selected.jobId, horizon, confirmed, requestKey: request.current })); onRefresh(); }
    catch (err) {
      // A failed run lets the person retry with a fresh key; an uncertain one keeps its key so nothing is sent twice.
      request.current = requestKeyAfterError(request.current, err);
      if (request.current === null) setConfirmed(false);
      setError(requestErrorMessage(err, 'This review could not be completed.'));
    }
    finally { setBusy(false); }
  }
  const history = data.history ?? [];
  const notice = readiness.state !== 'ready' ? <FeatureReadinessNotice className='is-compact' readiness={readiness} reasons={GROWTH_REASON_COPY} onRetry={onRefresh} /> : null;
  const enrollment = <MeasurementEnrollment readiness={measurement} onChange={() => void catalog.refetch()} />;
  if (!selected) return <>
    {notice}{enrollment}
    {history.length ? <History posts={history} notice={data.historyNotice} /> : !notice && <EmptyGrowth title='Your first field note is still ahead.'><p>After a publication is verified, its own platform readings will appear here at one hour, one day and one week.</p><Link href='/app/queue'>See your drafts <IconArrowRight size={16} aria-hidden /></Link></EmptyGrowth>}
  </>;
  const ready = data.posts.filter((p) => p.windows.some((w) => w.available)).length;
  const current = selected.windows.find((w) => w.horizon === horizon);
  const reading = readingState(current);
  const consented = Boolean(catalog.data?.allowedRoutes.includes(catalog.data.summaryRoute));
  const canEdit = checkAccess(access, { permission: 'edit' });
  const owner = access.role === 'owner';
  const canReview = Boolean(current?.available) && canEdit && consented && readiness.canRun;
  const blocked = !canEdit ? 'Running a review needs editor access in this workspace.'
    : !consented ? (owner ? 'Allow the explanation model in AI permissions above first.' : 'Ask the workspace owner to allow AI reviews in AI permissions.')
    : !readiness.canRun ? readinessCopy(readiness, GROWTH_REASON_COPY).detail : '';
  return <>
    {notice}{enrollment}
    <div className='growth-section-heading'><div><p className='growth-kicker'>01 / Observe</p><h3>What happened after publish.</h3></div><span className='growth-count'><strong>{ready}</strong> posts with readings</span></div>
    <div className='growth-results-layout'>
      <aside className='growth-post-list' aria-label='Choose a publication'>{data.posts.map((p) => <button key={p.jobId} className={selected.jobId === p.jobId ? 'is-selected' : ''} aria-pressed={selected.jobId === p.jobId} disabled={busy} onClick={() => void setPostParam(p.jobId)}>
        <span className='growth-post-meta'>{p.platform}<span>{new Date(p.at * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span></span>
        <strong>{p.title || 'Published post'}</strong><span className='growth-windows'>{p.windows.map((w) => <span key={w.horizon} data-available={w.available} data-state={readingStateKey(w)}><span aria-hidden>{readingState(w).mark}</span> {w.horizon}<span className='sr-only'> {readingState(w).label}</span></span>)}</span>
      </button>)}</aside>
      <div className='growth-report-paper'>
        <div className='growth-report-top'><span className='growth-kicker'>Field note / {selected.platform}</span><div className='growth-horizons' role='group' aria-label='Reading window'>{HORIZONS.map((h) => <button key={h} aria-pressed={horizon === h} disabled={busy} onClick={() => void setHorizon(h)}>{h}</button>)}</div></div>
        <h3 className='growth-post-title'>{selected.title || 'Your published post'}</h3>
        <p className='growth-window-state'><span className='growth-tag' data-state={readingStateKey(current)}>{horizon} · {reading.label}</span></p>
        {shown && shown.status !== 'stale' ? <Report key={shown.id} report={shown} /> : <div className='growth-review-start'>
          <IconClock size={28} aria-hidden /><h4>{shown?.status === 'stale' ? 'There’s new evidence to review.' : reading.title}</h4>
          <p>{shown?.status === 'stale' ? 'The readings or the AI permission changed since this review. Review the current window again.' : reading.detail}</p>
          {current?.available && (canReview ? <>
            <label className='growth-check'><input type='checkbox' aria-label='Use the allowed AI models to review these readings within my daily allowance.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />Use the allowed AI models to review these readings within my daily allowance.</label>
            <Button className='growth-primary' disabled={busy || !confirmed} onClick={() => void review()}>{busy ? 'Reviewing this window…' : 'Review this result'}<IconArrowUpRight size={17} aria-hidden /></Button>
          </> : blocked ? <p className='growth-footnote'>{blocked}</p> : null)}
        </div>}
        {error && <p role='alert' className='growth-error'>{error}</p>}
      </div>
    </div>
    <p className='growth-footnote'>{data.notice} Up to {data.coverage.maximumPosts} recent verified publications are included.</p>
    {history.length > 0 && <History posts={history} notice={data.historyNotice} />}
  </>;
}

const HISTORY_STATE: Record<GrowthHistoryPost['state'], string> = {
  backfill: 'Imported reading', scheduled: 'Reading scheduled', pending: 'Reading in progress', unavailable: 'Reading unavailable', unscheduled: 'Not scheduled'
};

/** Imported posts: one lifetime reading at its age. Measured zero is 0, an unread metric is a dash. Never reviewed. */
function History({ posts, notice }: { posts: GrowthHistoryPost[]; notice?: string }) {
  return <section className='growth-history' aria-labelledby='growth-history-title'>
    <div className='growth-section-heading'><div><p className='growth-kicker'>Before Rafii / Imported history</p><h3 id='growth-history-title'>Your own posts, read once.</h3></div><span className='growth-count'><strong>{posts.length}</strong> imported posts</span></div>
    <ul className='growth-history-list'>{posts.map((p) => {
      const age = p.state === 'backfill' ? ageLabel(p.ageSeconds) : null;
      return <li key={`${p.connectionId}:${p.providerPostId}`} data-state={p.state}>
        <div className='growth-history-meta'><span>{p.platform}{p.mediaType ? ` · ${p.mediaType.toLowerCase().replaceAll('_', ' ')}` : ''}</span><span>{p.publishedAt ? new Date(p.publishedAt * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Date unknown'}</span></div>
        <p className='growth-history-state'><span className='growth-tag' data-state={p.state === 'backfill' ? 'backfill' : 'unavailable'}>{HISTORY_STATE[p.state] ?? 'Reading unavailable'}</span>{age ? ` Lifetime totals read ${age} after publishing.` : ''}</p>
        <dl className='growth-history-metrics'>{p.metrics.map((m) => <div key={m.metric}><dt>{m.metric}</dt><dd>{m.value === null ? <><span aria-hidden>{metricValue(m.value)}</span><span className='sr-only'>not read</span></> : metricValue(m.value)}</dd></div>)}</dl>
        {p.permalink?.startsWith('https://') && <a className='growth-text-link' href={p.permalink} target='_blank' rel='noopener noreferrer'>Open on {p.platform}<IconArrowUpRight size={14} aria-hidden /></a>}
      </li>;
    })}</ul>
    {notice && <p className='growth-footnote'>{notice}</p>}
  </section>;
}

function Report({ report }: { report: Postmortem }) {
  const action = useGrowthAction();
  const catalog = useGrowthCatalog();
  const isOwner = useWorkspaceAccess().role === 'owner';
  const owner = isOwner && catalog.data?.genome === true;
  const [lesson, setLesson] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  return <div className='growth-report-body'>
    <dl className='growth-metric-row'>{Object.entries(report.reading.metrics).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{metricValue(value.value)}</dd><dd className='growth-metric-note'>{value.multiple != null ? `${value.multiple}× your median` : value.median === 0 ? 'Median is zero; no ratio' : `${value.baselineCount} comparable posts; need 3`}</dd></div>)}</dl>
    <div className='growth-comparison'><div className='growth-comparison-head'><span>Before publish</span><span>What we observed</span></div>
      {report.comparisons.length ? report.comparisons.map((row) => <div className='growth-comparison-row' key={row.dimension + row.metric}><span><strong>{row.label}</strong><small>{row.levelName}</small></span><span><b className={`growth-tag is-${row.status}`}>{row.status.replaceAll('_', ' ')}</b><small>{row.metric} · {row.outcome.percentile}th percentile in your cohort</small></span></div>) : <p className='growth-footnote'>This window needs a matching saved judgment and at least three comparable posts before advice can be compared.</p>}
    </div>
    {report.explanation && <div className='growth-observation'><span className='growth-kicker'>A useful next step</span><p>{report.explanation.nextStep}</p><small>{report.explanation.text}</small></div>}
    {report.lessons.length > 0 && <div className='growth-lesson'><div className='growth-section-heading'><div><p className='growth-kicker'>02 / Carry it forward</p><h4>A lesson for your Genome?</h4></div><IconDna2 size={24} aria-hidden /></div>
      {report.status === 'approved' ? <p className='growth-success'><IconCheck size={18} aria-hidden />Saved as a new Genome version. You can restore an older version in Brand & voice.</p> : report.status === 'dismissed' ? <p>Kept as an observation. Your Genome was not changed.</p> : <>
        {report.lessons.map((l) => <label key={l.id} aria-label={l.label} className={`growth-lesson-choice ${lesson === l.id ? 'is-selected' : ''}`}><input type='radio' aria-label={l.label} name={`lesson-${report.id}`} checked={lesson === l.id} disabled={!owner || l.grade === 'conflicting'} onChange={() => { setLesson(l.id); setConfirmed(false); }} /><span><strong>{l.label}</strong><small>{l.text}</small><span className={`growth-tag is-${l.grade}`}>{l.grade} · {l.evidenceIds.length} supporting / {l.counterEvidenceIds.length} counterexamples</span></span></label>)}
        {owner ? <><label className='growth-check'><input type='checkbox' aria-label='I reviewed this lesson. Save a new Genome version; limited evidence stays an observation.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I reviewed this lesson. Save a new Genome version; limited evidence stays an observation.</label><div className='growth-actions'><Button className='growth-primary' disabled={!lesson || !confirmed || action.busy} onClick={() => void action.run('postmortem_lesson_approve', { reportId: report.id, lessonId: lesson, confirmed })}>Save to my Genome<IconArrowRight size={17} aria-hidden /></Button><Button variant='quiet' disabled={action.busy} onClick={() => void action.run('postmortem_dismiss', { reportId: report.id })}>Keep as observation</Button></div></>
          : <p className='growth-footnote'>{isOwner ? 'Saving lessons to your Genome is switched off here, so this stays an observation.' : 'Only the workspace owner can save a lesson to the Genome. Ask them to review this result.'}</p>}
      </>}
      <Link className='growth-text-link' href='/app/workspace/brand'>Open Brand & voice <IconArrowUpRight size={15} aria-hidden /></Link>
    </div>}
    {action.error && <p role='alert' className='growth-error'>{action.error}</p>}
    <p className='growth-footnote'>{report.notice}</p>
  </div>;
}

function Patterns({ data, readiness }: { data: GrowthOverview; readiness: FeatureReadiness }) {
  const action = useGrowthAction();
  const owner = useWorkspaceAccess().role === 'owner';
  const [selected, setSelected] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const c = data.calibration;
  const version = c.versions.find((v) => v.id === selected) ?? c.versions[0];
  return <div className='growth-patterns'>
    {readiness.state !== 'ready' && <FeatureReadinessNotice className='is-compact' readiness={readiness} reasons={GROWTH_REASON_COPY} />}
    <div className='growth-section-heading'><div><p className='growth-kicker'>03 / Learn, deliberately</p><h3>Your history sets the context.</h3></div><IconDna2 size={32} aria-hidden /></div>
    <div className='growth-pattern-grid'><div className='growth-pattern-progress'><span className='growth-kicker'>Comparable publications</span><p><strong>{c.largestCohort}</strong><span> / {c.minimumPosts}</span></p><div className='growth-progress-track' aria-hidden><span style={{ transform: `scaleX(${Math.min(1, c.largestCohort / Math.max(1, c.minimumPosts))})` }} /></div><p>One account, platform, language, format, metric and model. Enough evidence before personalizing.</p></div><div><h4>Learn from the past.<br /><em>Check against what comes next.</em></h4><p>Older publications fit the levels and weights. Newer publications test them. An owner reviews each proposed version before it influences Post Doctor.</p><p className='growth-footnote'>This calibrates associations with observed outcomes, separately from the writing-quality rubric. Imported history is never used here.</p></div></div>
    <div className='growth-actions'><Button className='growth-primary' disabled={!owner || !c.available || action.busy} onClick={() => void action.run('creator_calibration_propose', {})}>Prepare a calibration<IconArrowRight size={17} aria-hidden /></Button><Link className='growth-text-link' href='/app/workspace/brand'>Review Creator Genome <IconArrowUpRight size={16} aria-hidden /></Link></div>
    {!c.available && <p className='growth-footnote'>Not enough evidence for a validated personal calibration yet. Existing Post Doctor feedback remains available.</p>}
    {!owner && <p className='growth-footnote'>Only the workspace owner can prepare, approve or restore a calibration.</p>}
    {version && <section className='growth-calibration-review'><label>Calibration version<select aria-label='Calibration version' value={version.id} onChange={(e) => { setSelected(e.target.value); setConfirmed(false); }}>{c.versions.map((v, i) => <option key={v.id} value={v.id}>Version {c.versions.length - i} · {v.status}</option>)}</select></label>
      {version.candidates.map((candidate, i) => <div key={i}><h4>{candidate.cohort[0]} · {candidate.metric} · {candidate.postCount} publications</h4><ul>{candidate.dimensions.map((d) => <li key={d.id}>{d.id} — holdout Spearman {d.holdoutSpearman}; weight {d.weight}; {d.trainCount} training / {d.holdoutCount} held out</li>)}</ul></div>)}
      {owner && ['proposed', 'superseded'].includes(version.status) && <><label className='growth-check'><input type='checkbox' aria-label='I reviewed the evidence and want this version used.' checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I reviewed the evidence and want this version used.</label><Button className='growth-primary' disabled={!confirmed || action.busy} onClick={() => void action.run(version.status === 'superseded' ? 'creator_calibration_restore' : 'creator_calibration_approve', { calibrationId: version.id, confirmed })}>{version.status === 'superseded' ? 'Restore this calibration' : 'Use this calibration'}</Button></>}
    </section>}
    {action.error && <p role='alert' className='growth-error'>{action.error}</p>}
  </div>;
}
