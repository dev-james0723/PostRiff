import {useEffect,useState,useRef} from 'react';
import type {Access,AlphaState,Snapshot} from './types';
import {api,readLocal,writeLocal} from './api';
import {pendingKey,retainedEdit,recoveryLabel,submission,reconcileEdits,type PendingEdit} from './runtime-state';
import './runtime.css';
type Act=(action:string,payload:Record<string,unknown>)=>Promise<Snapshot|undefined>;
interface Enrollment {id:string;code:string;name:string;workspaceId:string;expiresAt:number}
declare global {interface Window {postriffDesktop?:{status:()=>Promise<{desktop:boolean;protectedStorage:boolean;deviceId:string|null}>;pair:(input:Record<string,unknown>)=>Promise<Snapshot&{canceled?:boolean}>}}}
export default function RuntimePanel({state,access,revision,act,onSnapshot,busy}:{state:AlphaState;access:Access;revision:number;act:Act;onSnapshot:(next:Snapshot)=>void;busy:boolean}){
 const runtime=state.phase3!;
 const [sources,setSources]=useState<string[]>([]),[enrollment,setEnrollment]=useState<Enrollment|null>(null),[message,setMessage]=useState(''),[name,setName]=useState('My desktop');
 const [pending,setPending]=useState<Record<string,PendingEdit>>(()=>readLocal(pendingKey(state.workspace.id),{}));
 const [online,setOnline]=useState(navigator.onLine);
 useEffect(()=>{const change=()=>setOnline(navigator.onLine);window.addEventListener('online',change);window.addEventListener('offline',change);return()=>{window.removeEventListener('online',change);window.removeEventListener('offline',change);};},[]);
 const active=runtime.jobs.some(j=>['waiting','running'].includes(j.status));
 const pendingRef=useRef(pending);
 function savePending(next:Record<string,PendingEdit>){pendingRef.current=next;setPending(next);try{writeLocal(pendingKey(state.workspace.id),next);}catch{setMessage('Device storage is unavailable. Keep this page open and copy your unsent text before leaving.');}}
 useEffect(()=>{const next=reconcileEdits(pendingRef.current,runtime.operations??[]);if(next!==pendingRef.current)savePending(next);},[runtime.operations]);
 useEffect(()=>{
  if(busy)return;
  let disposed=false,inFlight=false;
  const refresh=async()=>{
   if(disposed||inFlight||!navigator.onLine||document.visibilityState==='hidden')return;
   inFlight=true;
   try{const next=await api.get(access);if(!disposed&&next.revision>=revision)onSnapshot(next);}
   catch{if(!disposed)setMessage('Connection lost or session ended. Unsent edits are retained; sign in again if needed.');}
   finally{inFlight=false;}
  };
  void refresh();
  const timer=window.setInterval(()=>void refresh(),active?1000:5000);
  window.addEventListener('online',refresh);window.addEventListener('focus',refresh);document.addEventListener('visibilitychange',refresh);
  return()=>{disposed=true;clearInterval(timer);window.removeEventListener('online',refresh);window.removeEventListener('focus',refresh);document.removeEventListener('visibilitychange',refresh);};
 },[active,busy,access.workspaceId,access.token,revision]);
 async function sync(id:string){
  const edit=pendingRef.current[id];if(!edit)return;
  const sent=submission(edit);
  savePending({...pendingRef.current,[id]:{...edit,submitted:sent}});
  const result=await act('p3_sync_edit',{...sent});
  if(result)savePending(reconcileEdits(pendingRef.current,result.state.phase3?.operations??[]));
 }
 async function pair(){if(!enrollment||!window.postriffDesktop)return;try{const result=await window.postriffDesktop.pair({workspaceId:access.workspaceId,token:access.token,expectedRevision:revision,enrollmentId:enrollment.id,code:enrollment.code,name:enrollment.name});if(!result.canceled){onSnapshot(result);setEnrollment(null);setMessage('Paired locally. Hosted cross-device acceptance remains pending.');}}catch(e){setMessage(e instanceof Error?e.message:'Pairing failed.');}}
 return <details className="p3-runtime"><summary>Writing runtime & devices <span>{runtime.routes.find(r=>r.id===runtime.selected)?.label}</span></summary>
 <div className="p3-body">
 <p className="helper">Your voice, sources and edits stay with this workspace. Local conformance preview is synthetic. Real model routes require qualification and exact usage consent.</p>
 <label>Writing runtime<select value={runtime.selected} disabled={busy} onChange={e=>void act('p3_select',{route:e.target.value})}>{runtime.routes.map(r=><option key={r.id} value={r.id}>{r.label} · {r.status}</option>)}</select></label>
 <p role="status">{runtime.routes.find(r=>r.id===runtime.selected)?.detail}</p>
 {state.contentTypes && <label>Private template for this request<select value={runtime.templateId||''} disabled={busy} onChange={e=>void act('p3_select_template',{templateId:e.target.value||null})}><option value="">No saved template selected</option>{state.contentTypes.templates.filter(t=>!t.archived).map(t=><option key={t.id} value={t.id}>{t.name} · revision {t.revision}</option>)}</select></label>}
 <fieldset><legend>Sources for this request</legend>{state.sources.filter(s=>s.active).map(s=><label className="p3-source" key={s.id}><input type="checkbox" checked={sources.includes(s.id)} onChange={e=>setSources(e.target.checked?[...sources,s.id]:sources.filter(id=>id!==s.id))}/>{s.title} · {runtime.sourceVisibility[s.id]||'local_only'}</label>)}<p className="helper">Only selected approved facts are included. Agent chat history and saved memory are inaccessible. No file scanning.</p></fieldset>
 {runtime.selected==='managed'&&<details><summary>Review managed-source permissions</summary><p>These choices permit only the reviewed material in a future managed request. Pairing does not transfer it. Actual execution is still blocked.</p><button disabled={busy} onClick={()=>void act('p3_profile_visibility',{voiceRevision:state.speaker.activeRevision,allowCloud:true,confirmed:true})}>Allow this voice revision in managed requests</button>{state.sources.filter(s=>sources.includes(s.id)&&s.active).map(s=><button key={s.id} disabled={busy} onClick={()=>void act('p3_source_visibility',{sourceId:s.id,visibility:'provider_allowed',confirmed:true})}>Allow selected facts: {s.title}</button>)}</details>}
 <button disabled={busy||!state.speaker.activeRevision} onClick={()=>void act('p3_prepare',{route:runtime.selected,sourceIds:sources,operation:'draft',idempotencyKey:crypto.randomUUID()})}>Review two-draft request</button>
 {state.profileSetup.request&&<button disabled={busy} onClick={()=>void act('p3_prepare',{route:runtime.selected,sourceIds:sources,operation:'profile',idempotencyKey:crypto.randomUUID()})}>Review voice-builder request</button>}
 {runtime.jobs.slice().reverse().map(job=><article className="p3-job" id={`runtime-${job.id}`} key={job.id}>
 <h3>{recoveryLabel(job.status)}</h3><p>{runtime.routes.find(r=>r.id===job.route)?.label} · usage: {job.usage.provenance}{job.usage.modelRequests===0?' · 0 model requests':''}</p>
 <details><summary>Exact approved context</summary><pre>{JSON.stringify(job.manifest,null,2)}</pre></details>
 {job.status==='prepared'&&<button disabled={busy||job.route!=='fixture'} onClick={()=>void act('p3_start',{runId:job.id,inputHash:job.inputHash,consent:true})}>Start synthetic preview · $0</button>}
 {['waiting','running','prepared'].includes(job.status)&&<button disabled={busy} onClick={()=>void act('p3_cancel',{runId:job.id})}>Interrupt request</button>}
 <div role="log" aria-label="Runtime progress">{job.events.filter(e=>e.text).map(e=><p key={e.id}>{e.text}</p>)}</div>
 {job.artifact?.variants?.map(v=><section key={v.platform}><h4>{v.platform} · {v.language}</h4><p className="p3-draft">{v.text}</p></section>)}
 {job.artifact?.fields&&<pre>{JSON.stringify(job.artifact,null,2)}</pre>}
 {job.status==='completed'&&<button disabled={busy} onClick={()=>void act('p3_apply',{runId:job.id,artifactHash:job.artifactHash})}>Keep candidate for review</button>}
 </article>)}
 <details><summary>Devices · local pairing</summary><p>Pairing grants draft/profile jobs only. Hosted pairing is pending; signing in here is a local account simulation.</p>
 <label>Device name<input maxLength={60} value={name} onChange={e=>setName(e.target.value)}/></label>
 <button disabled={busy} onClick={async()=>{const result=await act('p3_enroll',{name});if(result?.runtimeResult?.enrollment)setEnrollment(result.runtimeResult.enrollment as Enrollment);}}>Create five-minute enrollment</button>
 {enrollment&&<div><p>Workspace {enrollment.workspaceId}<br/>Device {enrollment.name}<br/>Single-use code: <strong>{enrollment.code}</strong></p>{window.postriffDesktop?<button onClick={()=>void pair()}>Confirm in desktop</button>:<p>Open the local desktop to confirm. Hosted cross-device pairing is not configured.</p>}</div>}
 {runtime.devices.map(d=><p key={d.id}>{d.name} · {d.connection} · last seen {new Date(d.lastSeen*1000).toLocaleString()} {d.status!=='revoked'&&<button disabled={busy} onClick={()=>void act('p3_revoke',{deviceId:d.id})}>Revoke</button>}</p>)}
 </details>
 <details><summary>Offline edits & conflict recovery</summary><p role="status">{online?'Connection available':'Offline'} · unsent edits stay in this browser/device. Synchronize each edit explicitly.</p>
 {state.variants.map(v=><section key={v.id}><label>{v.platform} · {v.language}<textarea value={pending[v.id]?.text??v.text} onChange={e=>savePending({...pendingRef.current,[v.id]:retainedEdit(pendingRef.current[v.id],v,e.target.value)})}/></label>
 {pending[v.id]&&<><p>{pending[v.id].variantRevision===v.revision?'Unsent local edit':'Conflict: saved revision changed. Your local edit is retained below.'}</p>{pending[v.id].submitted&&<p>Previous save awaiting confirmation. Retry checks that same save before sending newer text.</p>}{pending[v.id].variantRevision!==v.revision&&<><details><summary>Compare saved text</summary><p className="p3-draft">{v.text}</p></details><button onClick={()=>savePending({...pending,[v.id]:{variantId:v.id,text:pendingRef.current[v.id].text,variantRevision:v.revision,idempotencyKey:crypto.randomUUID()}})}>Use my text against this saved revision</button></>}
 <button disabled={busy||!online||(!pending[v.id].submitted&&pending[v.id].variantRevision!==v.revision)} onClick={()=>void sync(v.id)}>{pending[v.id].submitted?'Check previous save':'Synchronize this edit'}</button></>}
 </section>)}
 </details>
 {message&&<p role="status">{message}</p>}
 </div></details>;
}
