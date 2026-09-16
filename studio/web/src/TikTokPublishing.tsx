import {useEffect,useState} from 'react';
import {api} from './api';
type Manifest={account:string;caption:string;visibility:string;dueUtc:string|null;dueLocal:string;timezone:string;sourceName:string;sha256:string;duration:number;width:number;height:number;comments:boolean;duet:boolean;stitch:boolean};
type Job={id:string;state:string;hash:string;manifest:Manifest;result:{reason?:string}|null};
type Status={workerRunning:boolean;paused:boolean;jobs:Job[]};
const endpoint='/api/tiktok-publishing';
export default function TikTokPublishing(){
 const [status,setStatus]=useState<Status|null>(null),[path,setPath]=useState(''),[caption,setCaption]=useState(''),[visibility,setVisibility]=useState(''),[when,setWhen]=useState(''),[mode,setMode]=useState('now'),[rights,setRights]=useState(false),[derivatives,setDerivatives]=useState(false),[review,setReview]=useState<Job|null>(null),[approved,setApproved]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;
 async function refresh(){try{setStatus(await api<Status>(endpoint));}catch(e){setError(e instanceof Error?e.message:'Queue unavailable.');}}
 useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>clearInterval(timer);},[]);
 async function action(work:()=>Promise<void>){setBusy(true);setError('');try{await work();await refresh();}catch(e){setError(e instanceof Error?e.message:'Operation failed.');}finally{setBusy(false);}}
 async function prepare(){await action(async()=>{if(mode==='schedule'&&!when)throw Error('Choose a scheduled time.'); const due=mode==='schedule'?new Date(when):null;if(due&&Number.isNaN(due.valueOf()))throw Error('Invalid scheduled time.');setReview(await api<Job>(endpoint+'/reviews',{method:'POST',body:JSON.stringify({path,caption,visibility,dueUtc:due?.toISOString()||null,timezone:zone,comments:false,duet:false,stitch:false,rightsConfirmed:rights,derivatives:derivatives?'none':''})}));setApproved(false);});}
 return <section className="setup-panel" aria-label="TikTok publishing"><h3>TikTok · upload and schedule</h3><p>Account: <strong>@jamesaucreates</strong> · saved browser session. One private upload was verified. This connection uses the unofficial uploader; OAuth setup below is separate.</p>
 <p>Keep Studio running and this Mac awake for scheduled posts. Jobs over five minutes late require a new review. Uncertain submissions stop for a TikTok check.</p>
 {error&&<p role="alert" className="error-banner">{error}</p>}
 <p>{status?.workerRunning?'Scheduler running':'Scheduler unavailable'}{status?.paused?' · Paused':''}</p>
 <button className="button" disabled={busy||!status} onClick={()=>void action(async()=>{await api(endpoint+'/control',{method:'POST',body:JSON.stringify({paused:!status?.paused})});})}>{status?.paused?'Resume queue':'Pause queue'}</button>
 {!review?<form onSubmit={e=>{e.preventDefault();void prepare();}}><fieldset className="setup-fields" disabled={busy}>
 <label className="field">Local MP4 path<input required value={path} onChange={e=>setPath(e.target.value)} placeholder="/Users/…/video.mp4"/></label>
 <label className="field">Caption<textarea required maxLength={2200} value={caption} onChange={e=>setCaption(e.target.value)}/></label>
 <label className="field">Who can watch?<select required value={visibility} onChange={e=>setVisibility(e.target.value)}><option value="">Choose visibility</option><option value="private">Only me</option><option value="public">Everyone</option></select></label>
 <label className="field">Timing<select value={mode} onChange={e=>setMode(e.target.value)}><option value="now">After approval</option><option value="schedule">Schedule</option></select></label>
 {mode==='schedule'&&<label className="field">Date and time · {zone}<input required type="datetime-local" value={when} onChange={e=>setWhen(e.target.value)}/><small>The next review shows the resolved time, offset, and UTC. Check daylight-saving transitions carefully.</small></label>}
 <p>Comments, Duet, and Stitch are off for this integration.</p>
 <label className="check-field"><input type="checkbox" required checked={rights} onChange={e=>setRights(e.target.checked)}/> I have permission to publish this video and its audio.</label>
 <label className="check-field"><input type="checkbox" required checked={derivatives} onChange={e=>setDerivatives(e.target.checked)}/> Post this video only, with no derivatives or reposts.</label>
 <button className="button primary" type="submit">Prepare video preview</button></fieldset></form>:<div className="callout">
 <h4>Approve this exact post</h4><video controls preload="metadata" style={{width:'100%',maxHeight:320}} src={`${endpoint}/${review.id}/video`}/>
 <p><strong>{review.manifest.account}</strong> · {review.manifest.visibility==='private'?'Only me':'Everyone'}</p><p>{review.manifest.caption}</p>
 <p>{review.manifest.sourceName} · {review.manifest.duration.toFixed(1)} seconds · {review.manifest.width}×{review.manifest.height}</p>
 <p>{review.manifest.dueLocal} ({review.manifest.timezone}){review.manifest.dueUtc&&<> · UTC: {review.manifest.dueUtc}</>}</p><p>Comments, Duet, Stitch off. No derivatives.</p>
 <label className="check-field"><input type="checkbox" checked={approved} onChange={e=>setApproved(e.target.checked)}/> I approve this exact video, caption, account, visibility, and time.</label>
 <button className="button primary" disabled={busy||!approved} onClick={()=>void action(async()=>{await api(`${endpoint}/${review.id}/approve`,{method:'POST',body:JSON.stringify({hash:review.hash})});setReview(null);setApproved(false);})}>{review.manifest.dueUtc?'Approve scheduled post':'Approve and upload'}</button>
 <button className="button" disabled={busy} onClick={()=>void action(async()=>{await api(`${endpoint}/${review.id}/cancel`,{method:'POST',body:'{}'});setReview(null);})}>Discard review</button></div>}
 <h4>Publishing queue</h4>{status?.jobs.length===0&&<p>No TikTok jobs yet.</p>}{status?.jobs.map(job=><article key={job.id} className="callout"><strong>{job.manifest.sourceName}</strong><p>{job.manifest.caption}</p><p>{job.state.replaceAll('_',' ')} · {job.manifest.visibility==='private'?'Only me':'Everyone'} · {job.manifest.dueLocal}</p>{job.result?.reason&&<p>{job.result.reason}</p>}{job.state==='submitted'&&<p>TikTok acknowledged submission. Confirm the video and visibility in TikTok before reporting it as published.</p>}{['review','queued','needs_review'].includes(job.state)&&<button className="button" disabled={busy} onClick={()=>void action(async()=>{await api(`${endpoint}/${job.id}/cancel`,{method:'POST',body:'{}'});})}>Cancel</button>}{job.state==='review'&&<button className="button" onClick={()=>{setReview(job);setApproved(false);}}>Review</button>}</article>)}
 </section>;
}
