import {useEffect,useState} from 'react';
import {api} from './api';
type State={state:string;profile:string|null;identitySignals:string[];liveTestVerified:boolean};
type Preview={manifest:{profile:string;text:string;audience:string;timing:string};hash:string;state:string};
export default function ZhihuConnection(){
 const [state,setState]=useState<State|null>(null),[profile,setProfile]=useState(''),[text,setText]=useState('这是一条发布流程测试，用来检查文字是否完整显示。'),[preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[consent,setConsent]=useState(false),[result,setResult]=useState<{state:string;evidence?:{permalink:string}}|null>(null);
 const [reconcileHash,setReconcileHash]=useState(''),[reconcileUrl,setReconcileUrl]=useState('');
 async function refresh(){const s=await api<State>('/api/connections/zhihu/status');setState(s);if(s.profile)setProfile(s.profile);}
 useEffect(()=>{refresh().catch(()=>setMessage('Zhihu status unavailable.'));},[]);
 async function action(operation:string,body:unknown){setBusy(true);setMessage('');try{
  const value=await api<Record<string,unknown>>('/api/connections/zhihu/'+operation,{method:'POST',body:JSON.stringify(body)});
  if(operation==='preview'){setPreview(value as unknown as Preview);setConsent(false);}
  else if(operation==='publish'||operation==='reconcile'){setResult(value as unknown as {state:string;evidence?:{permalink:string}});if(typeof value.hash==='string')setReconcileHash(value.hash);}
  else {setMessage(operation==='login'?'Sign in in the dedicated browser. Complete any phone, QR or CAPTCHA step yourself, then close that browser and verify here.':'Profile verified for 15 minutes. Each post checks identity again.');await refresh();}
 }catch(e){setMessage(e instanceof Error?e.message:'Zhihu operation unavailable.');}finally{setBusy(false);}}
 function changed(){setPreview(null);setConsent(false);setResult(null);}
 return <section aria-label="Zhihu browser connection" className="setup-panel"><h3>Connect Zhihu in your browser</h3>
 <p>No OAuth or API key. Use the dedicated browser to sign in to your intended Zhihu account. Passwords and login codes stay in that browser.</p>
 <p role="status">{state?.state==='connected_identity'?'Profile verified':'Login and profile verification required'} · {state?.liveTestVerified?'A live text test has been verified':'Live posting not yet verified'}</p>
 <fieldset disabled={busy} className="setup-fields"><button className="button" onClick={()=>action('login',{})}>Open Zhihu sign-in</button>
 <label className="field">Public profile URL or handle<input value={profile} onChange={e=>{setProfile(e.target.value);changed();}} placeholder="https://www.zhihu.com/people/your-handle" autoComplete="off"/></label>
 <button className="button" disabled={!profile.trim()} onClick={()=>action('verify',{profile})}>Verify after closing sign-in browser</button>
 <h3>Test a text 想法</h3><label className="field">Exact post text<textarea value={text} maxLength={1000} onChange={e=>{setText(e.target.value);changed();}}/></label>
 <button className="button" disabled={!profile.trim()||!text.trim()} onClick={()=>action('preview',{profile,text})}>Preview test post</button>
 {preview&&<div aria-label="Zhihu exact publication preview"><p><strong>{preview.manifest.profile}</strong><br/>Public 想法 · Publish now · No media or derivatives</p><p style={{whiteSpace:'pre-wrap'}}>{preview.manifest.text}</p>
 <label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> I approve publishing this exact text publicly to this profile now.</label>
 <button className="button" disabled={!consent||state?.state!=='connected_identity'||state?.profile!==preview.manifest.profile} onClick={()=>action('publish',{manifest:preview.manifest,approvedHash:preview.hash,publicationConsent:true})}>Publish approved test</button></div>}
 <details><summary>Reconcile an uncertain test</summary><p>This checks an existing post without submitting again.</p><label className="field">Attempt hash<input value={reconcileHash} onChange={e=>setReconcileHash(e.target.value)}/></label><label className="field">Zhihu post permalink<input value={reconcileUrl} onChange={e=>setReconcileUrl(e.target.value)}/></label><button className="button" disabled={!reconcileHash||!reconcileUrl} onClick={()=>action('reconcile',{hash:reconcileHash,permalink:reconcileUrl})}>Verify existing post</button></details>
 </fieldset>{message&&<p role="status">{message}</p>}{result&&<p role="status">{result.state}{result.evidence&&<> · <a href={result.evidence.permalink} target="_blank" rel="noreferrer">View verified post</a></>}</p>}
 <p className="hint">This pilot supports text 想法 only. Articles and answers use the draft handoff. No recurring schedule is enabled.</p></section>;
}
