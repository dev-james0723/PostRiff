import {useEffect,useState} from 'react';
import {connectionsApi,type TikTokConnection as State} from './connectionsApi';
import TikTokPublishing from './TikTokPublishing';

export default function TikTokConnection(){
 const [connection,setConnection]=useState<State|null>(null),[username,setUsername]=useState('');
 const [consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function refresh(){try{setConnection((await connectionsApi.status()).tiktok);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
 useEffect(()=>{void refresh();},[]);
 async function verify(){setBusy(true);setError('');try{setConnection(await connectionsApi.verifyTikTok());}catch(cause){setError(cause instanceof Error?cause.message:'Verification unavailable.');}finally{setBusy(false);}}
 async function connect(event:React.SubmitEvent<HTMLFormElement>){event.preventDefault();if(!consent)return;setBusy(true);setError('');try{window.location.assign(await connectionsApi.prepareTikTok(username));}catch(cause){setError(cause instanceof Error?cause.message:'TikTok sign-in could not start.');setBusy(false);}}
 const unresolved=connection?.state==='connection_unresolved';
 return <><TikTokPublishing/><details><summary>Optional official OAuth identity connection</summary><section className="setup-panel" aria-label="TikTok account connection"><h3>Connect your TikTok identity</h3>
  <p>Connect one exact TikTok username. Read permissions: <code>user.info.basic</code> and <code>user.info.profile</code>. These identify your account and public profile; they do not allow uploading or publishing.</p>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  {unresolved?<p role="alert">The previous authorization or refresh has an unresolved outcome. Reconcile it before starting another connection. Studio has not confirmed a connected identity.</p>:connection?.verifiedAt?<div className="callout"><strong>{connection.state==='connected_identity'?'Identity connected':'Verification required'}: @{connection.username}</strong><p>{connection.displayName}</p><p>{connection.state==='connected_identity'?'The OAuth account ID matched an independent TikTok User Info response and the selected username.':'A fresh TikTok identity check is required.'} Email ownership is not verified by this connection. Publishing remains disabled.</p><small>Last verified {connection.verifiedAt} · Access expires {connection.expiresAt}</small></div>:<>
   <p className="muted">{connection?.available?`Connection state: ${connection.state.replaceAll('_',' ')}`:connection?.state==='broker_unavailable'?'The private connection service is unavailable. Restart Studio and check again.':'TikTok developer app configuration is required before sign-in.'}</p>
   {connection?.state==='configuration_required'&&<details><summary>Developer setup</summary><p>Use Login Kit Desktop with callback <code>http://127.0.0.1:4315/callback</code>. Supply the approved client credentials privately to Apple Keychain service <code>James Au Studio TikTok OAuth</code>, accounts <code>client-key</code> and <code>client-secret</code>, then restart Studio. Never paste credentials into chat.</p></details>}
   <form onSubmit={connect}><fieldset className="setup-fields" disabled={busy||!connection?.available}>
    <label className="field">Exact TikTok username<input required pattern="[A-Za-z0-9._]{1,24}" maxLength={24} autoComplete="off" value={username} onChange={e=>{setUsername(e.target.value);setConsent(false);}} placeholder="Username without @"/></label>
    <label className="check-field"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Connect @{username||'this account'} with the two read permissions above. Keep its OAuth credentials encrypted on this Mac. No publishing access.</label>
    <button type="submit" className="button primary" disabled={!consent||!username.trim()}>Continue to TikTok</button>
   </fieldset></form></>}
  <button type="button" className="button" onClick={()=>void (connection?.verifiedAt&&!unresolved?verify():refresh())} disabled={busy}>{busy?'Checking…':'Check connection'}</button>
 </section></details></>;
}
