import {useEffect,useState} from 'react';
import {connectionsApi,type PinterestConnection as State} from './connectionsApi';

export default function PinterestConnection(){
 const [connection,setConnection]=useState<State|null>(null),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function refresh(){try{setConnection((await connectionsApi.status()).pinterest);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
 useEffect(()=>{void refresh();},[]);
 async function verify(){setBusy(true);setError('');try{setConnection(await connectionsApi.verifyPinterest());}catch(cause){setError(cause instanceof Error?cause.message:'Verification unavailable.');}finally{setBusy(false);}}
 async function connectBrowser(){setBusy(true);setError('');try{setConnection(await connectionsApi.connectPinterestBrowser());}catch(cause){setError(cause instanceof Error?cause.message:'Browser identity connection unavailable.');}finally{setBusy(false);}}
 async function connect(event:React.SubmitEvent<HTMLFormElement>){event.preventDefault();if(!consent)return;setBusy(true);setError('');try{window.location.assign(await connectionsApi.preparePinterest('jamesaucreates'));}catch(cause){setError(cause instanceof Error?cause.message:'Pinterest sign-in could not start.');setBusy(false);}}
 const unresolved=connection?.state==='connection_unresolved';
 return <section className="setup-panel" aria-label="Pinterest account connection"><h3>Connect your Pinterest account</h3>
  <p>Connect <strong>@jamesaucreates</strong>. Studio requests only <code>user_accounts:read</code> to verify this account. Board selection and individually approved Pins belong to the separate Hosted Pinterest integration; no publishing grant is requested here.</p>
  <p>Studio has no board or Pin mutation route, and never receives Ads, Billing, Secret Board or Secret Pin access. Trial Pins are creator-visible only. Any future real Pin, including Sandbox, requires separate exact-post approval.</p>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  {connection?.state==='connected_identity'||connection?.state==='connected_browser_identity'?<><p className="success-banner">Verified Pinterest identity: <strong>@{connection.username}</strong>{connection.accountType?` (${connection.accountType})`:''}. Route: <strong>{connection.routeDriver}</strong>. Publishing remains disabled.</p>{connection.routeDriver==='official_api_oauth'&&<button type="button" disabled={busy} onClick={()=>void verify()}>{busy?'Verifying…':'Re-verify Pinterest identity'}</button>}</>:<form onSubmit={connect}>
   <p>Connection state: <strong>{connection?.state??'loading'}</strong></p>
   {unresolved&&<p role="alert" className="error-banner">The previous authorization is unresolved. Do not retry until it is reconciled.</p>}
   <label><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)} disabled={busy||unresolved}/> I confirm the exact account and identity-read-only scope. This grants no permission to create Pins, manage boards or run advertising.</label>
   <button disabled={!consent||busy||unresolved} type="submit">{busy?'Opening Pinterest…':'Continue to Pinterest consent'}</button>
   {connection?.state==='configuration_required'&&<button type="button" disabled={busy} onClick={()=>void connectBrowser()}>Connect the browser-verified account</button>}
  </form>}
 </section>;
}
