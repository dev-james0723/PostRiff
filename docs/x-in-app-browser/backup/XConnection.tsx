import {useEffect,useState} from 'react';
import {connectionsApi,type XConnection as State,type XBrowserConnection,type XBrowserPreview} from './connectionsApi';

export default function XConnection(){
 const [connection,setConnection]=useState<State|null>(null),[username,setUsername]=useState('jamesaucreates'),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [browser,setBrowser]=useState<XBrowserConnection|null>(null),[text,setText]=useState(''),[schedule,setSchedule]=useState(''),[preview,setPreview]=useState<XBrowserPreview|null>(null),[approve,setApprove]=useState(false);
 async function refresh(){try{setConnection((await connectionsApi.status()).x);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
 useEffect(()=>{void refresh();void connectionsApi.xBrowserStatus().then(setBrowser).catch(()=>{});},[]);
 async function connect(event:React.SubmitEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError('');try{window.location.assign(await connectionsApi.prepareX(username));}catch(cause){setError(cause instanceof Error?cause.message:'X sign-in could not start.');setBusy(false);}}
 async function verify(){setBusy(true);setError('');try{setConnection(await connectionsApi.verifyX());}catch(cause){setError(cause instanceof Error?cause.message:'X connection verification unavailable.');}finally{setBusy(false);}}
 async function browserAction(kind:'login'|'verify'|'preview'|'publish') {setBusy(true);setError('');try{
  if(kind==='login')await connectionsApi.xBrowserLogin();
  if(kind==='verify')setBrowser(await connectionsApi.xBrowserVerify(username));
  if(kind==='preview'){setPreview(await connectionsApi.xBrowserPreview(username,text,schedule?new Date(schedule).toISOString():null));setApprove(false);}
  if(kind==='publish'&&preview){await connectionsApi.xBrowserPublish(preview.manifest,preview.hash);setPreview(null);setApprove(false);}
 }catch(cause){setError(cause instanceof Error?cause.message:'X browser operation unavailable.');}finally{setBusy(false);}}
 return <section className="setup-panel" aria-label="X account connection"><h3>Connect your X identity</h3>
  <div className="callout"><strong>Free browser posting and scheduling</strong><p>Uses X's web composer and native scheduler. No X API plan or developer credits are required.</p>
   <p>{browser?.state==='connected_identity'?<>Dedicated browser verified as <strong>@{browser.username}</strong>.</>:<>The dedicated Chrome profile needs a one-time X sign-in.</>}</p>
   <button type="button" className="button" disabled={busy} onClick={()=>void browserAction(browser?.state==='connected_identity'?'verify':'login')}>{browser?.state==='connected_identity'?'Re-verify browser identity':'Open dedicated X login'}</button>
   {browser?.state!=='connected_identity'&&<button type="button" className="button" disabled={busy} onClick={()=>void browserAction('verify')}>I finished login — verify</button>}
   {browser?.state==='connected_identity'&&<div className="setup-fields"><label className="field">Exact post text<textarea maxLength={280} value={text} onChange={e=>{setText(e.target.value);setPreview(null);setApprove(false);}}/></label><label className="field">Schedule time (leave blank to post now)<input type="datetime-local" value={schedule} onChange={e=>{setSchedule(e.target.value);setPreview(null);setApprove(false);}}/></label><button type="button" className="button" disabled={busy||!text.trim()} onClick={()=>void browserAction('preview')}>Create approval preview</button>{preview&&<div className="callout"><p><strong>{preview.manifest.timing==='scheduled'?'Schedule':'Post now'}:</strong> {preview.manifest.text}</p><p><small>Approval hash: <code>{preview.hash}</code></small></p><label className="check-field"><input type="checkbox" checked={approve} onChange={e=>setApprove(e.target.checked)}/> I approve this exact text, @{username}, public destination, and {preview.manifest.scheduledAt||'immediate timing'}.</label><button type="button" className="button primary" disabled={busy||!approve} onClick={()=>void browserAction('publish')}>{preview.manifest.timing==='scheduled'?'Schedule on X':'Post on X'}</button></div>}</div>}
  </div>
  <p>Studio uses X OAuth 2.0 with PKCE. It requests profile reading, post creation, and a persistent refresh token for owner-approved scheduled delivery. It does not request direct-message or email access.</p>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  {connection?.state==='connected_identity'?<div className="callout"><strong>X identity connected: @{connection.username}</strong><p>{connection.profileUrl} · account {connection.accountId}</p><p>Post delivery remains disabled until a separate non-posting route test and an exact post approval.</p><small>Last verified {connection.verifiedAt} · refresh access expires {connection.expiresAt}</small></div>:<>
    <p className="muted">{connection?.available?`Connection state: ${connection.state.replaceAll('_',' ')}`:'X OAuth client configuration is required. Store the public client ID in Apple Keychain, then restart Studio.'}</p>
    {connection?.state==='configuration_required'&&<p>Native PKCE app · Redirect URI: <code>http://127.0.0.1:4320/callback</code> · Keychain service: <code>James Au Studio X OAuth</code>, account <code>client-id</code>. Never enter a client secret in Studio.</p>}
    <form onSubmit={connect}><fieldset className="setup-fields" disabled={busy||!connection?.available}>
      <label className="field">Exact X handle<input required pattern="[A-Za-z0-9_]{1,15}" autoComplete="off" value={username} onChange={event=>{setUsername(event.target.value);setConsent(false);}}/></label>
      <label className="check-field"><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)}/> Connect @{username||'this account'} with profile access, post-write access, and persistent refresh access. Keep OAuth tokens encrypted on this Mac.</label>
      <button type="submit" className="button primary" disabled={!consent||!username.trim()||!connection?.available}>{busy?'Opening X…':'Continue to X'}</button>
    </fieldset></form>
  </>}
  <button type="button" className="button" onClick={()=>void (connection?.state==='connected_identity'?verify():refresh())} disabled={busy}>{busy?'Checking…':'Check connection'}</button>
 </section>;
}
