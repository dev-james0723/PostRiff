'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { IconArrowUpRight, IconRadar, IconArrowRight } from '@tabler/icons-react';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useWorkspaceAccess } from '@/lib/auth/access';
import { Button } from '@/components/ui/button';
import { GrowthConsent, useGrowthCatalog } from './shared';
import { useGrowthAction } from './studio-parts';
import type { RadarCatalog, RadarEvidence, RadarOpportunity, RadarScan } from '@/lib/growth/radar-types';
import './radar.css';

const money = (micro: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 3 }).format(micro / 1e6);
const words = (value: string) => value.replaceAll('_', ' ');
function useRadarScans(enabled: boolean) {
  const { api, workspaceId } = useWorkspaceApi();
  return useQuery({ queryKey: ['radar-scans', workspaceId], queryFn: () => api.radarScans(workspaceId), enabled, retry: false });
}

export function RadarHome() {
  const growth = useGrowthCatalog();
  const scans = useRadarScans(Boolean(growth.data?.radar));
  if (!growth.data?.radar) return null;
  const latest = scans.data?.scans.find((s) => !s.stale && ['completed', 'partial'].includes(s.status));
  const items = latest?.opportunities.filter((o) => !o.dismissed).slice(0, 3) ?? [];
  return <Link href='/app/radar' className='growth-entry radar-home'>
    <span className='growth-entry-icon'><IconRadar size={24} aria-hidden /></span>
    <span><span className='growth-kicker'>Radar{latest?.notification ? ' · New signals' : ''}</span><strong>Find something worth adding your voice to.</strong><small>{items.length ? items.map((o) => o.title).join(' · ') : 'Explore public signals, review the sources, make an idea your own.'}</small></span>
    <IconArrowUpRight size={22} aria-hidden />
  </Link>;
}

function Evidence({ items }: { items: RadarEvidence[] }) {
  return <ul className='radar-evidence'>{items.map((e) => <li key={e.id}>
    <a href={e.url} target='_blank' rel='noopener noreferrer'>{e.title || 'Open reference'} <IconArrowUpRight size={14} aria-hidden /></a>
    <p>{e.source} · {e.publishedAt ? new Date(e.publishedAt * 1000).toLocaleDateString() : 'Date unavailable'} · {words(e.coverage)}</p>
    {e.excerpt && <blockquote>{e.excerpt}</blockquote>}
    {Object.keys(e.metrics).length > 0 && <small>Native counts: {Object.entries(e.metrics).map(([k, v]) => `${v.toLocaleString()} ${k}`).join(' · ')}</small>}
  </li>)}</ul>;
}

function Opportunity({ op, scanId, index }: { op: RadarOpportunity; scanId: string; index: number }) {
  const action = useGrowthAction();
  const [reviewed, setReviewed] = useState(false);
  return <article className={`radar-card ${index === 0 ? 'is-featured' : ''}`} data-testid='radar-opportunity'>
    <div className='radar-card-top'><span className='growth-kicker'>{String(index + 1).padStart(2, '0')} / {words(op.stage)}</span><span className='radar-tag'>{op.forYou ? 'For you' : 'Explore'}</span></div>
    <h3>{op.title}</h3><p className='radar-why'>{op.whyNow}</p>
    <div className='radar-angle'><span className='growth-kicker'>A question to make your own</span><p>{op.angle}</p></div>
    {op.genomeReasons.length > 0 && <p className='radar-fit'><strong>Why you:</strong> {op.genomeReasons.map((r) => r.text).join(' · ')}</p>}
    <details className='radar-details'><summary>Review {op.evidence.length} {op.evidence.length === 1 ? 'reference' : 'references'} · {op.confidence} confidence</summary>
      <Evidence items={op.evidence} /><p className='radar-note'>Ordering score {op.score}/100 is a guide to review, not a probability of reach. Source independence has not been verified.</p>
      <ul className='radar-reasons'>{op.confidenceReasons.map((r) => <li key={r}>{r}</li>)}</ul>
    </details>
    {op.sourceId ? <Link className='radar-saved' href='/app/ideas'>Saved to Ideas <IconArrowRight size={16} aria-hidden /></Link> : <div className='radar-save'>
      <label><input aria-label='I reviewed the references' type='checkbox' checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />I reviewed the references. I’ll verify facts before drafting.</label>
      <div className='radar-buttons'><Button disabled={!reviewed || action.busy} onClick={() => void action.run('radar_save_idea', { scanId, opportunityId: op.id, confirmed: true })}>Save this idea</Button><Button variant='quiet' disabled={action.busy} onClick={() => void action.run('radar_dismiss', { scanId, opportunityId: op.id })}>Dismiss</Button></div>
    </div>}
    {action.error && <p role='alert'>{action.error}</p>}
  </article>;
}

/** The server's reason a daily watch cannot run here (`radar/service.py recurring_unavailable`); null when it can. */
type MonitoringCatalog = RadarCatalog & { monitoringBlocked?: string | null };

/**
 * What the daily-watch panel may truthfully say. On a credit plan every scan needs its own confirmed credit limit,
 * and no recurring credit authorization exists yet, so the cron never runs (or charges) a watch there.
 */
export function monitorNotice(catalog: MonitoringCatalog): { canEnable: boolean; text: string } {
  if (catalog.monitoringBlocked === 'recurring_credit_authorization_unavailable') {
    return {
      canEnable: false,
      text: catalog.monitor.enabled
        ? 'Paused: on a credit plan each scan needs your confirmation, so the daily watch does not run and nothing is charged. Run scans yourself, or turn the watch off.'
        : 'Not available on credit plans yet: a daily watch would spend credits without asking you each time. Run scans yourself; each one shows its credit limit first.'
    };
  }
  if (!catalog.monitoringAvailable) return { canEnable: false, text: 'Daily monitoring is not enabled yet.' };
  if (!catalog.paidMonitoring) return { canEnable: false, text: 'Available with an active paid plan.' };
  return { canEnable: true, text: `One Quick scan daily, between 8am and 10pm in your time zone, within your plan’s included Radar allowance: up to ${money(catalog.monitorMaximumUsdMicro)} of provider cost per scan. Results appear here.` };
}

function Permissions({ catalog, refresh }: { catalog: MonitoringCatalog; refresh: () => void }) {
  const growth = useGrowthCatalog();
  const access = useWorkspaceAccess();
  const action = useGrowthAction();
  const [sources, setSources] = useState(catalog.consent.sources ?? []);
  const [ai, setAi] = useState(catalog.consent.ai ?? false);
  const [topic, setTopic] = useState(catalog.monitor.query ?? '');
  const [timezone, setTimezone] = useState(catalog.monitor.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
  async function save(name: string, payload: Record<string, unknown>) { if (await action.run(name, payload)) refresh(); }
  const monitor = monitorNotice(catalog);
  return <details className='radar-permissions'><summary>Sources, AI permissions & monitoring</summary>
    <div className='radar-permission-grid'><section><h3>Your public sources</h3><p>Only the selected public sources are used. Short evidence excerpts expire after 30 days.</p>
      {catalog.sources.map((s) => <label key={s.id} className='radar-source-option'><input aria-label={s.name} type='checkbox' checked={sources.includes(s.id)} disabled={access.role !== 'owner' || s.status !== 'ready'} onChange={(e) => setSources(e.target.checked ? [...sources, s.id] : sources.filter((v) => v !== s.id))} /><span>{s.name}<small>{s.status === 'ready' ? s.note : words(s.status)}</small></span></label>)}
      <label className='radar-source-option'><input aria-label='Allow Radar AI' type='checkbox' checked={ai} disabled={access.role !== 'owner'} onChange={(e) => setAi(e.target.checked)} /><span>Allow AI to review public evidence with my approved Genome lessons.</span></label>
      <Button variant='glass' disabled={access.role !== 'owner' || action.busy} onClick={() => void save('radar_consent', { sources, ai, confirmed: true })}>Save Radar permissions</Button>
    </section><section><h3>Your AI choices</h3>{growth.data && <GrowthConsent catalog={{ ...growth.data, audienceMiner: false }} onChange={() => { void growth.refetch(); refresh(); }} />}
      <div className='radar-monitor'><h3>A light daily watch</h3><p id='radar-monitor-note'>{monitor.text}</p>
        {catalog.monitor.enabled ? <><p>Watching “{catalog.monitor.query}” · {catalog.monitor.timezone}</p><Button variant='glass' disabled={access.role !== 'owner' || action.busy} onClick={() => void save('radar_watch', { enabled: false })}>{catalog.monitoringBlocked ? 'Turn off daily watch' : 'Pause daily watch'}</Button></> : <>
          <label>Watch topic<input aria-label='Watch topic' className='radar-input' value={topic} maxLength={200} disabled={!monitor.canEnable} onChange={(e) => setTopic(e.target.value)} /></label>
          <label>Time zone<input aria-label='Time zone' className='radar-input' value={timezone} disabled={!monitor.canEnable} onChange={(e) => setTimezone(e.target.value)} /></label>
          <Button variant='glass' aria-describedby='radar-monitor-note' disabled={access.role !== 'owner' || !monitor.canEnable || topic.trim().length < 3 || action.busy} onClick={() => void save('radar_watch', { enabled: true, query: topic, timezone, maximumUsdMicro: catalog.monitorMaximumUsdMicro, confirmed: true })}>Enable daily watch</Button>
        </>}
      </div>
    </section></div>{action.error && <p role='alert'>{action.error}</p>}
  </details>;
}

export function RadarPage() {
  const { api, workspaceId } = useWorkspaceApi();
  const growth = useGrowthCatalog();
  const enabled = Boolean(growth.data?.radar);
  const catalog = useQuery({ queryKey: ['radar-catalog', workspaceId], queryFn: () => api.radarCatalog(workspaceId), enabled, retry: false });
  const scans = useRadarScans(enabled);
  const action = useGrowthAction();
  const [topic, setTopic] = useState('');
  const [mode, setMode] = useState<'quick' | 'deep'>('quick');
  const [useAi, setUseAi] = useState(true);
  const [quote, setQuote] = useState<RadarScan | null>(null);
  const [progress, setProgress] = useState<RadarScan | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [filter, setFilter] = useState('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const requestKey = useRef('');
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const selected = busy && progress ? progress : scans.data?.scans.find((s) => s.id === selectedId) ?? scans.data?.scans[0];
  function changed() { setQuote(null); requestKey.current = ''; }
  async function review() {
    if (!catalog.data) return;
    setBusy(true); setError('');
    try {
      requestKey.current ||= crypto.randomUUID();
      const q = await api.radarQuote(workspaceId, { query: topic, mode, sources: (catalog.data.consent.sources ?? []).filter((id) => catalog.data.sources.some((s) => s.id === id && s.status === 'ready')), useAi: useAi && Boolean(catalog.data.consent.ai), requestKey: requestKey.current });
      setQuote(q);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not prepare this scan.'); }
    finally { setBusy(false); }
  }
  async function scan(q: RadarScan) {
    setBusy(true); setError(''); setSelectedId(q.id); setQuote(null);
    try {
      let result = await api.radarStart(workspaceId, q.id); setProgress(result);
      for (let i = 0; i < 32 && result.status === 'running' && alive.current; i++) {
        if (result.retryAfter) await new Promise((resolve) => setTimeout(resolve, result.retryAfter! * 1000));
        if (!alive.current) break;
        result = await api.radarAdvance(workspaceId, q.id); setProgress(result);
      }
      await scans.refetch(); requestKey.current = '';
    } catch (e) { setError(e instanceof Error ? e.message : 'This scan paused. Review its status before continuing.'); await scans.refetch(); }
    finally { setBusy(false); setProgress(null); }
  }
  const opportunities = selected?.opportunities.filter((o) => !o.dismissed && (filter === 'all' || o.forYou)) ?? [];
  return <div className='growth-studio radar-page'>
    <header className='radar-hero'><div><p className='growth-kicker'><span className='growth-status-dot' />Radar · Your next interesting thing</p><h1>See what’s moving.<br /><em>Find your way in.</em></h1><p>Public signals. Your point of view. Find a question worth exploring, then give it something only you can add.</p></div><div className='radar-orbit' aria-hidden><i /><i /><i /><IconRadar size={36} /><b /><b /><b /></div></header>
    {growth.isPending ? <p role='status'>Loading Radar…</p> : growth.isError ? <p role='alert'>Radar could not load. <Button variant='quiet' onClick={() => void growth.refetch()}>Try again</Button></p> : !enabled ? <div className='growth-empty'><h2>Radar is taking shape.</h2><p>It is not enabled for this workspace yet.</p></div> : <>
      {catalog.isError && <p role='alert'>Source settings could not load. <Button variant='quiet' onClick={() => void catalog.refetch()}>Try again</Button></p>}
      {catalog.data && <>
        <section className='radar-scan-form' aria-label='Start a Radar scan'><div className='radar-form-heading'><span className='growth-kicker'>Start with a curiosity</span><div className='radar-mode' aria-label='Scan depth'>{(['quick', 'deep'] as const).map((v) => <button key={v} disabled={busy} aria-pressed={mode === v} onClick={() => { setMode(v); changed(); }}>{v === 'quick' ? 'Quick' : 'Deep'}</button>)}</div></div>
          <label htmlFor='radar-topic'>What is your audience thinking about?</label><div className='radar-search'><input aria-label='What is your audience thinking about?' id='radar-topic' value={topic} maxLength={200} placeholder='e.g. a more thoughtful way to practise piano' disabled={busy} onChange={(e) => { setTopic(e.target.value); changed(); }} /><Button disabled={busy || topic.trim().length < 3 || !catalog.data.consent.sources?.length} onClick={() => void review()}>Review scan <IconArrowRight size={16} aria-hidden /></Button></div>
          <div className='radar-form-note'><span>{mode === 'quick' ? 'A focused first look · up to 12 items per source' : 'A wider look · up to 40 items per source'}</span><label><input aria-label='Include AI review' type='checkbox' checked={useAi && Boolean(catalog.data.consent.ai)} disabled={busy || !catalog.data.consent.ai} onChange={(e) => { setUseAi(e.target.checked); changed(); }} />Include AI review</label></div>
          {!catalog.data.consent.sources?.length && <p>Open source permissions below to choose where Radar can look.</p>}
          {quote && <div className='radar-quote'><h2>Review your {quote.mode} scan</h2><p>“{quote.query}” · {quote.sources.join(', ')} · {quote.useAi ? 'AI review included' : 'Source collection only'}</p><p>{quote.maximumCredits !== undefined ? `Up to ${quote.maximumCredits} credits.` : `Uses your included allowance, up to ${money(quote.maximumUsdMicro)} in provider costs.`} Fewer than three usable opportunities refunds any reserved scan credits.</p><div className='radar-buttons'><Button disabled={busy} onClick={() => void scan(quote)}>Confirm & scan</Button><Button variant='quiet' onClick={changed}>Edit scan</Button></div></div>}
          {busy && <p role='status'>Scanning selected sources… {progress ? `${progress.steps.filter((s) => s.status === 'completed').length} steps complete.` : 'Preparing your review.'}</p>}
          {error && <p role='alert'>{error}</p>}
        </section>
        <Permissions key={JSON.stringify(catalog.data.consent)} catalog={catalog.data} refresh={() => { changed(); void catalog.refetch(); void scans.refetch(); }} />
      </>}
      {scans.isError && <p role='alert'>Scans could not load. <Button variant='quiet' onClick={() => void scans.refetch()}>Try again</Button></p>}
      <section className='radar-results' aria-labelledby='radar-results-title'><div className='radar-results-heading'><div><p className='growth-kicker'>The signal desk</p><h2 id='radar-results-title'>{selected?.query ?? 'Your next idea starts here.'}</h2></div><div className='radar-mode'><button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All signals</button><button aria-pressed={filter === 'you'} onClick={() => setFilter('you')}>For you</button></div></div>
        {selected && <p className='radar-note'>{words(selected.status)} · {selected.mode} scan · {selected.stale ? 'Permissions or creator context changed. Start a fresh scan.' : selected.notice}</p>}
        {!busy && selected && ['running', 'unknown', 'quoted'].includes(selected.status) && <div className='radar-quote'><p>{selected.status === 'unknown' ? 'An earlier attempt has an unknown outcome. Stop this scan before starting another; the attempt will not be repeated.' : 'This scan is waiting for you.'}</p><div className='radar-buttons'>{selected.status !== 'unknown' && <Button onClick={() => selected.status === 'quoted' ? setQuote(selected) : void scan(selected)}>{selected.status === 'quoted' ? 'Review quote' : 'Continue scan'}</Button>}<Button variant='quiet' disabled={action.busy} onClick={() => void action.run('radar_stop', { scanId: selected.id })}>Stop scan</Button></div></div>}
        {opportunities.length ? <div className='radar-grid'>{opportunities.map((op, i) => <Opportunity key={op.id} op={op} index={i} scanId={selected!.id} />)}</div> : <div className='radar-empty'><IconRadar size={32} aria-hidden /><h3>{filter === 'you' ? 'Your fit will get clearer.' : 'A little curiosity goes a long way.'}</h3><p>{filter === 'you' ? 'For you uses only matching, approved, supported Genome lessons. Explore all signals while your evidence grows.' : 'Choose a topic and your sources. Radar will bring back references you can inspect, with room for your own perspective.'}</p></div>}
        {!!selected?.nativeReferences?.length && <details className='radar-native'><summary>YouTube · native references only</summary><p>These raw counts are displayed separately. They do not enter Radar’s rankings or AI review.</p><Evidence items={selected.nativeReferences} /></details>}
        {!!selected?.sourceResults?.length && <details className='radar-receipt'><summary>Scan receipt</summary><ul>{selected.sourceResults.map((s) => <li key={s.source}>{s.source}: {s.status} · {s.items} items</li>)}</ul><p>{selected.usage.costsVisible === false ? 'Provider cost details are available to the workspace owner.' : selected.usage.actualUsdMicro === null ? `Actual provider cost is not fully known (${selected.usage.unknownAttempts} unknown attempts).` : `Recorded provider cost: ${money(selected.usage.actualUsdMicro)}.`}</p>{selected.refundReason && <p>{selected.refundReason} {selected.chargedCredits === 0 ? 'Reserved credits refunded.' : 'No scan-credit charge is due.'}</p>}<Button variant='quiet' disabled={action.busy} onClick={() => void action.run('radar_forget', { scanId: selected.id })}>Forget this scan</Button></details>}
        {action.error && <p role='alert'>{action.error}</p>}
      </section>
      {(scans.data?.scans.length ?? 0) > 1 && <section className='radar-history'><h2>Earlier curiosities</h2>{scans.data?.scans.map((s) => <button key={s.id} disabled={busy} aria-pressed={selected?.id === s.id} onClick={() => setSelectedId(s.id)}><span>{s.query}</span><small>{s.mode} · {words(s.status)}</small><IconArrowUpRight size={18} aria-hidden /></button>)}</section>}
    </>}
    <footer className='radar-footer'>A starting point for original work. Review sources, check facts, add your own experience.</footer>
  </div>;
}
