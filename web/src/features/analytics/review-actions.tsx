'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { useCoworkerApi } from '@/lib/coworker/hooks';
import { errorMessage } from '@/lib/coworker/api';
import { ApiError } from '@/lib/api/client';
import { growthLoopQueryKey } from '@/features/growth/growth-loop';
import type { ClassificationTag, ReviewInput, ReviewProjection, ReviewSnapshot } from '@/lib/analytics/review-contract';

const field = 'rafii-field rafii-focus mt-1 w-full min-w-0 rounded-md border p-2';

export function ReviewActions({projection:p,scope,onScope,refresh,visible=true}:{projection:ReviewProjection;scope:ReviewInput;onScope:(v:Partial<ReviewInput>)=>void;refresh:()=>Promise<void>;visible?:boolean}) {
  const {api,w,enabled}=useCoworkerApi();
  const cache=useQueryClient();
  const views=useQuery({queryKey:['review-views',w,p.resolvedContext.rightsEpoch,p.workspaceRevision],enabled,retry:false,queryFn:()=>api.reviewViews(w)});
  const [busy,setBusy]=useState<string|null>(null),[message,setMessage]=useState(''),[error,setError]=useState('');
  const [viewId,setViewId]=useState(''),[name,setName]=useState('');
  const [jobId,setJobId]=useState(''),[tagKind,setTagKind]=useState<ClassificationTag['kind']>('theme'),[tagLabel,setTagLabel]=useState(''),[tagId,setTagId]=useState('');
  const [notes,setNotes]=useState(''),[frequency,setFrequency]=useState<'weekly'|'monthly'>('weekly');
  const [viewsOpen,setViewsOpen]=useState(false),[reportOpen,setReportOpen]=useState(false);
  const scopeKey=JSON.stringify(scope);
  const [savedReport,setSavedReport]=useState<{scopeKey:string;record:ReviewSnapshot}|null>(null);
  const report=savedReport?.scopeKey===scopeKey?savedReport.record:null;
  const setReport=(record:ReviewSnapshot|null)=>setSavedReport(record?{scopeKey,record}:null);
  const keys=useRef(new Map<string,string>());
  function key(body:unknown){const hash=JSON.stringify(body);if(!keys.current.has(hash))keys.current.set(hash,crypto.randomUUID());return keys.current.get(hash)!;}
  async function run(label:string,action:()=>Promise<void>){if(busy)return;setBusy(label);setError('');setMessage('');try{await action();}catch(e){setError(errorMessage(e,'This action could not be verified. Retry the same request.'));if(e instanceof ApiError&&[401,403,409,410].includes(e.status)){setReport(null);await refresh();}}finally{setBusy(null);}}
  const selected=views.data?.views.find(v=>v.id===viewId);
  const publications=[...new Map(p.nativeResults.filter(e=>e.accessState==='allowed'&&e.displayPermission==='allowed').map(e=>[e.publicationBinding.jobId,e.publicationBinding])).values()];
  const publication=publications.find(b=>b.jobId===jobId)??publications[0];
  const currentClass=publication?views.data?.classifications[publication.jobId]:undefined;
  const fixedScope:ReviewInput={...scope,relativeDateRule:undefined,publicationPeriod:p.resolvedContext.publicationPeriod,comparison:p.resolvedContext.comparison,cutoffAt:p.resolvedContext.cutoffAt};
  async function saveView(archive=false){
    if(!views.data)return;
    const filterDefinition=archive&&selected?selected.filterDefinition:{...scope,cutoffAt:undefined};
    const body={...(selected?{id:selected.id}:{}),name:name.trim()||selected?.name||'My content review',filterDefinition,expectedRevision:selected?.revision??0,archive};
    const saved=await api.saveReviewView(w,{...body,workspaceRevision:views.data.workspaceRevision,idempotencyKey:key(body)});
    if(!saved.verified)throw new Error('The Saved View write was not verified.');
    setViewId(archive?'':saved.record.id);setName(archive?'':saved.record.name);setMessage(archive?'Saved View archived.':filterDefinition.relativeDateRule?'Saved View saved. Relative dates resolve when reopened.':'Saved View saved. Fixed publication dates remain fixed.');
    await views.refetch();await refresh();
  }
  async function classify(tags:ClassificationTag[],source:'human'|'ai_suggestion'='human'){
    if(!publication||!views.data)return;
    const body={jobId:publication.jobId,manifestDigest:publication.manifestDigest,tags,source,confirmed:true,expectedRevision:currentClass?.version??0};
    const saved=await api.classifyReviewContent(w,{...body,workspaceRevision:views.data.workspaceRevision,idempotencyKey:key(body)});
    if(!saved.verified)throw new Error('The classification was not verified.');
    setMessage(`Classification version ${saved.record.version} saved for one publication. Existing reports stay fixed.`);
    setTagLabel('');setTagId('');await views.refetch();await refresh();
  }
  async function saveReport(){
    if(p.workspaceRevision===null)return;
    const body={scope:fixedScope,contextDigest:p.contextDigest,basisDigest:p.basisDigest,humanNotes:notes?[notes]:[],frequency,...(report?{snapshotId:report.snapshotId,expectedVersion:report.version}:{})};
    const saved=await api.createReviewSnapshot(w,{...body,workspaceRevision:p.workspaceRevision,idempotencyKey:key(body)});
    if(!saved.verified)throw new Error('The report was not verified.');
    setReport(saved.record);setMessage(`Fixed report version ${saved.record.version} saved.`);await views.refetch();await refresh();
  }
  async function exportReport(format:'markdown'|'csv'|'pdf'){
    if(!report)return;
    // Revalidate through the authenticated endpoint immediately before rendering.
    const output=await api.exportReviewSnapshot(w,report.snapshotId,report.version,format);
    if(output.payloadDigest!==report.payloadDigest)throw new Error('Report contents changed. Reopen the saved version.');
    const url=URL.createObjectURL(new Blob([output.content],{type:output.contentType}));
    if(format==='pdf'){
      const frame=document.createElement('iframe');frame.title='Fixed report PDF print preview';frame.style.cssText='position:fixed;width:1px;height:1px;left:-10000px';document.body.appendChild(frame);
      frame.addEventListener('load',()=>{frame.contentWindow?.focus();frame.contentWindow?.print();},{once:true});frame.src=url;
      setTimeout(()=>{frame.remove();URL.revokeObjectURL(url);},60000);setMessage('Fixed report opened for Print / Save as PDF.');
    }else{const link=document.createElement('a');link.href=url;link.download=output.filename;link.click();URL.revokeObjectURL(url);setMessage(`${format==='csv'?'CSV':'Markdown'} downloaded from the saved version.`);}
  }
  if(!visible)return null;
  return <div className='space-y-4 border-t pt-4'>
    <details open={viewsOpen} onToggle={e=>setViewsOpen(e.currentTarget.open)}><summary className='rafii-focus cursor-pointer text-sm font-medium'>Saved Views and classifications</summary>
      <div className='mt-3 grid min-w-0 gap-3 sm:grid-cols-2'>
        <label className='text-sm'>Saved View<select className={field} value={viewId} onChange={e=>{const v=views.data?.views.find(v=>v.id===e.target.value);setViewId(e.target.value);setName(v?.name??'');if(v&&!v.blockedReason)onScope(v.filterDefinition);}}><option value=''>New Saved View</option>{views.data?.views.map(v=><option key={v.id} value={v.id} disabled={Boolean(v.blockedReason)}>{v.name}{v.blockedReason?' · unavailable':''}</option>)}</select></label>
        <label className='text-sm'>View name<input aria-label='View name' className={field} value={name} maxLength={120} onChange={e=>setName(e.target.value)}/></label>
        <div className='flex flex-wrap gap-2 sm:col-span-2'><Button variant='quiet' disabled={Boolean(busy)||!views.data} onClick={()=>void run('view',()=>saveView())}>{selected?'Update Saved View':'Save current view'}</Button>{selected&&<Button variant='quiet' disabled={Boolean(busy)} onClick={()=>void run('archive',()=>saveView(true))}>Archive Saved View</Button>}</div>
        <label className='text-sm'>Classify publication<select className={field} value={publication?.jobId??''} onChange={e=>setJobId(e.target.value)}><option value='' disabled>Choose a qualified publication</option>{publications.map(b=><option key={b.jobId} value={b.jobId}>{b.provider} · {b.nativePostId}</option>)}</select></label>
        <label className='text-sm'>Classification kind<select className={field} value={tagKind} onChange={e=>setTagKind(e.target.value as ClassificationTag['kind'])}><option value='theme'>Theme</option><option value='campaign'>Campaign</option><option value='series'>Series</option></select></label>
        <label className='text-sm'>Classification ID<input aria-label='Classification ID' className={field} placeholder='e.g. piano-series' value={tagId} maxLength={80} onChange={e=>setTagId(e.target.value)}/></label>
        <label className='text-sm'>Classification label<input aria-label='Classification label' className={field} value={tagLabel} maxLength={120} onChange={e=>setTagLabel(e.target.value)}/></label>
        <p className='text-muted-foreground text-xs sm:col-span-2'>Current version {currentClass?.version??0}: {currentClass?.tags.join(', ')||'Unclassified'}. Confirming replaces the classifications for this one publication. Earlier versions remain available in fixed reports.</p>
        <div className='flex flex-wrap gap-2 sm:col-span-2'><Button variant='quiet' disabled={Boolean(busy)||!publication||!tagId||!tagLabel||!views.data} onClick={()=>void run('classification',()=>classify([{tagId,kind:tagKind,label:tagLabel}]))}>Confirm classification</Button><Button variant='quiet' disabled={Boolean(busy)||!publication||!currentClass||!views.data} onClick={()=>void run('classification',()=>classify([]))}>Clear classification</Button></div>
        {views.data?.suggestions.filter(s=>s.jobId===publication?.jobId&&s.manifestDigest===publication?.manifestDigest).map(s=><div key={s.id} className='rounded-lg border p-3 text-sm sm:col-span-2'>Suggested: {s.tags.map(t=>`${t.kind}: ${t.label}`).join(', ')}. <Button variant='quiet' disabled={Boolean(busy)} onClick={()=>void run('classification',()=>classify(s.tags,'ai_suggestion'))}>Confirm reviewed suggestion</Button></div>)}
        <label className='text-sm'>Classification filter<select aria-label='Classification filter' className={field} value={scope.tagSelection?.[0]?.tagId??''} onChange={e=>{const t=views.data?.tags.find(t=>t.tagId===e.target.value);onScope({...scope,cutoffAt:undefined,tagSelection:t?[{tagId:t.tagId,kind:t.kind,classificationVersion:views.data!.classificationVersion}]:[]});}}><option value=''>All classifications</option>{views.data?.tags.map(t=><option key={t.tagId} value={t.tagId}>{t.kind} · {t.label}</option>)}</select></label>
        <label className='text-sm'>Aggregate<select className={field} value={scope.aggregation??'median'} onChange={e=>onScope({...scope,cutoffAt:undefined,aggregation:e.target.value as 'median'|'mean'})}><option value='median'>Median</option><option value='mean'>Mean</option></select></label>
      </div>{views.error&&<p role='alert' className='mt-3 text-sm'>{errorMessage(views.error,'Saved Views are unavailable.')}</p>}
    </details>
    <div><h3 className='text-sm font-medium'>Observations and one next test</h3>{!p.takeaways.length?<p className='text-muted-foreground text-sm'>Too few comparable publications for a takeaway. Collect comparable readings before choosing a treatment.</p>:<div className='mt-2 space-y-3'>{p.takeaways.map(t=><article key={t.id} className='rounded-lg border p-3 text-sm'><p>{t.statement}</p><p className='text-muted-foreground mt-1 text-xs'>{t.sampleSize} posts · {t.actualPeriod.start} → {t.actualPeriod.end} · {t.supportBindings.length} supporting / {t.counterEvidenceBindings.length} counter-evidence readings · causal=false</p><details className='mt-2'><summary className='rafii-focus cursor-pointer'>Exact sources</summary><ul className='mt-2 break-all text-xs'>{[...t.supportBindings,...t.counterEvidenceBindings].map(e=><li key={e.observationId}>{e.publicationBinding.jobId} · {e.observationId} · {e.value} · {e.observedAt}</li>)}</ul></details>{t.nextStep.kind==='propose'&&t.nextStep.hypothesisId?<Button variant='quiet' disabled={Boolean(busy)} onClick={()=>void run('experiment',async()=>{const body={hypothesisId:t.nextStep.hypothesisId!,minimumPerArm:5,windowDays:14,reviewScope:fixedScope,reviewContextDigest:p.contextDigest,reviewBasisDigest:p.basisDigest};const saved=await api.proposeGrowthExperiment(w,{...body,idempotencyKey:key(body)});if(!saved.verified)throw new Error('Experiment proposal not verified.');setMessage('Existing Growth Loop experiment proposed. Owner acceptance and preparation remain separate.');await cache.invalidateQueries({queryKey:growthLoopQueryKey(w)});await refresh();})}>Propose this controlled test</Button>:<Link className='rafii-focus mt-2 inline-block underline' href={t.nextStep.href}>{t.nextStep.label}</Link>}</article>)}</div>}</div>
    <details open={reportOpen} onToggle={e=>setReportOpen(e.currentTarget.open)}><summary className='rafii-focus cursor-pointer text-sm font-medium'>Fixed weekly / monthly report</summary><div className='mt-3 space-y-3'>
      <label className='block text-sm'>Report frequency<select className={field} value={frequency} onChange={e=>setFrequency(e.target.value as 'weekly'|'monthly')}><option value='weekly'>Weekly</option><option value='monthly'>Monthly</option></select></label>
      <label className='block text-sm'>Human notes<textarea aria-label='Human notes' className={field} value={notes} maxLength={4000} rows={4} onChange={e=>setNotes(e.target.value)}/></label>
      <Button variant='quiet' disabled={Boolean(busy)} onClick={()=>void run('report',saveReport)}>{report?'Save new report version':'Save fixed report'}</Button>
      <label className='block text-sm'>Reopen a saved version<select aria-label='Reopen a saved version' className={field} value={report?`${report.snapshotId}:${report.version}`:''} onChange={e=>{const [id,v]=e.target.value.split(':');if(id)void run('reopen',async()=>{setReport(null);const saved=await api.reviewSnapshot(w,id,Number(v));setReport(saved);setNotes(saved.humanNotes.join('\n'));setFrequency(saved.frequency);});}}><option value=''>Choose a fixed report</option>{views.data?.snapshots.map(s=><option key={`${s.snapshotId}:${s.version}`} value={`${s.snapshotId}:${s.version}`}>{s.snapshotId} · v{s.version} · {s.generatedAt}</option>)}</select></label>
      {report&&<div className='rounded-lg border p-3'><p className='break-all text-sm'>{report.snapshotId} · v{report.version} · payload {report.payloadDigest}</p><p className='text-muted-foreground text-xs'>Native scope: {report.resolvedContext.publicationPeriod.start} → {report.resolvedContext.publicationPeriod.end}. Completed work uses its original workspace-wide UTC proof period. Time Back: {report.timeBack.value===null?'unavailable':`${report.timeBack.value} estimated seconds`}.</p><div className='mt-3 flex flex-wrap gap-2'>{(['markdown','csv','pdf'] as const).map(f=><Button key={f} variant='quiet' disabled={Boolean(busy)} onClick={()=>void run('export',()=>exportReport(f))}>{f==='pdf'?'Print / save PDF':f==='csv'?'Download CSV':'Download Markdown'}</Button>)}</div></div>}
      <p className='text-muted-foreground text-xs'>All formats use the same saved report. Export rechecks current source rights. Files already downloaded cannot be remotely revoked. No model call starts here.</p>
    </div></details>
    <details><summary className='rafii-focus cursor-pointer text-sm font-medium'>Reusable published content ({p.reuseCandidates.length})</summary><div className='mt-3 space-y-3'>{p.reuseCandidates.map(c=><article key={c.contentId} className='rounded-lg border p-3 text-sm'><p className='break-words whitespace-pre-wrap'>{c.text}</p><p className='text-muted-foreground mt-2 break-all text-xs'>{c.provider} · {c.nativePostId} · revision {c.revision} · {c.publicationAt??'Unknown publication time'} · {c.language??'Unknown language'} · {c.formatId??'Unknown format'} · content only; performance status is separate.</p><Link href={c.nextStep.href} className='rafii-focus mt-2 inline-block underline'>{c.nextStep.label}</Link></article>)}</div><p className='text-muted-foreground mt-2 text-xs'>No history import or automatic repost. Review current facts and rights before creating a new draft.</p></details>
    <details><summary className='rafii-focus cursor-pointer text-sm font-medium'>Trends provenance and follow-up</summary><div className='mt-3 space-y-3 text-sm'>{p.trendProvenance.map(t=><div key={t.jobId} className='break-all rounded-lg border p-3'><p>Verified publication {t.verifiedNativeIdentity.nativePostId} · job {t.jobId} · {t.horizon}</p>{t.receiptBindings.map((b,i)=><p key={i}>Receipt {String(b.trust_receipt_id??'unavailable')} → opportunity {String(b.opportunity_id??'unavailable')} revision {String(b.opportunity_revision??'unknown')} → angle {String(b.angle_id??'unknown')}. Treatment follows the frozen approved manifest; causal=false.</p>)}</div>)}{p.trendLearning?<><p>Separate workspace scope: currently permitted retained client views. {p.trendLearning.denominator.exposures} exposures · {p.trendLearning.denominator.accepted} accepted · {p.trendLearning.denominator.dismissed} dismissed. Views are not unique people.</p>{p.trendLearning.exposures.map(e=><div key={e.exposure_id} className='rounded-lg border p-3'><p>Exposure {e.exposure_id} · {e.decision} · opportunity {e.opportunity_id} v{e.opportunity_revision}</p>{e.outcomes.map((o,i)=><p key={i}>Publication {o.job_id??'not published'} · {o.state} · {o.value===null?'unknown':o.value} · treatment {o.treatment_state} · {o.comparison?.reason??'comparison unavailable'} · baseline needs five comparable posts · causal=false.</p>)}</div>)}</>:<p>Current Trends follow-up is unavailable in this workspace. No exposure, adoption or publication is inferred.</p>}</div></details>
    <p className='text-muted-foreground text-sm'>Personalized timing, format and frequency: method unavailable. {p.personalization.sampleSize} eligible posts in this scope; no measured accuracy. {p.personalization.reason} {p.personalization.nextStep}</p>
    <div aria-live='polite'>{busy&&<p role='status' className='text-sm'>Verifying {busy}…</p>}{message&&<p role='status' className='text-sm'>{message}</p>}{error&&<p role='alert' className='text-sm'>{error}</p>}</div>
  </div>;
}
