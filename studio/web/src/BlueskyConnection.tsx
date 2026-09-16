import {useEffect,useState} from 'react';
import {connectionsApi,type Connection} from './connectionsApi';

export default function BlueskyConnection(){
  const [connection,setConnection]=useState<Connection|null>(null),[handle,setHandle]=useState('');
  const [consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function refresh(){try{setConnection((await connectionsApi.status()).bluesky);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
  useEffect(()=>{void refresh();},[]);
  async function connect(event:React.SubmitEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('');
    try{const path=await connectionsApi.prepare(handle);window.location.assign(path);}
    catch(cause){setError(cause instanceof Error?cause.message:'Sign-in could not start.');setBusy(false);}
  }
  return <section className="setup-panel" aria-label="Bluesky account connection"><h3>Connect your Bluesky account</h3>
    <p>Sign in privately with Bluesky. Studio requests identity access only, with no permission to post or read messages.</p>
    {error&&<p role="alert" className="error-banner">{error}</p>}
    {connection?.state==='connected_identity'?<div className="callout"><strong>Identity connected: @{connection.handle}</strong><p>OAuth identity and public profile matched. Publishing is not enabled.</p><small>Verified {connection.verifiedAt}</small></div>:<>
      <p className="muted">{connection?.available?`Connection state: ${connection.state.replaceAll('_',' ')}`:'Private connection service is unavailable. Restart Studio after installing the broker.'}</p>
      <p>New to Bluesky? <a href="https://bsky.app" target="_blank" rel="noreferrer">Create your account privately</a>, then return with your chosen handle.</p>
      <form onSubmit={connect}><fieldset className="setup-fields" disabled={busy||!connection?.available}>
        <label className="field">Bluesky handle<input required maxLength={253} autoComplete="off" placeholder="name.bsky.social" value={handle} onChange={e=>{setHandle(e.target.value);setConsent(false);}}/></label>
        <label className="check-field"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Connect this exact account with identity-only access. Keep the session privately on this Mac. No paid service or publication is included.</label>
        <button type="submit" className="button primary" disabled={!consent||!handle.trim()}>{busy?'Opening private sign-in…':'Continue to Bluesky'}</button>
      </fieldset></form>
    </>}
    <button type="button" className="button" onClick={()=>void refresh()} disabled={busy}>Check connection</button>
  </section>;
}
