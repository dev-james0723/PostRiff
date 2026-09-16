import {useEffect,useState} from 'react';
import {connectionsApi,type RedditConnection as State} from './connectionsApi';

export default function RedditConnection(){
 const [connection,setConnection]=useState<State|null>(null),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function refresh(){try{setConnection((await connectionsApi.status()).reddit);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
 useEffect(()=>{void refresh();},[]);
 async function verify(){setBusy(true);setError('');try{setConnection(await connectionsApi.verifyReddit());}catch(cause){setError(cause instanceof Error?cause.message:'Verification unavailable.');}finally{setBusy(false);}}
 async function connectBrowser(){if(!consent)return;setBusy(true);setError('');try{setConnection(await connectionsApi.connectRedditBrowser());}catch(cause){setError(cause instanceof Error?cause.message:'Browser identity connection could not be recorded.');}finally{setBusy(false);}}
 async function enableBrowserPublishing(){setBusy(true);setError('');try{setConnection(await connectionsApi.enableRedditBrowserPublishing());}catch(cause){setError(cause instanceof Error?cause.message:'Browser publishing readiness could not be recorded.');}finally{setBusy(false);}}
 async function connect(event:React.SubmitEvent<HTMLFormElement>){event.preventDefault();if(!consent)return;setBusy(true);setError('');try{window.location.assign(await connectionsApi.prepareReddit('Ok-External401'));}catch(cause){setError(cause instanceof Error?cause.message:'Reddit sign-in could not start.');setBusy(false);}}
 const unresolved=connection?.state==='connection_unresolved',connected=connection?.state==='connected_identity'||connection?.state==='connected_browser_identity';
 return <section className="setup-panel" aria-label="Reddit account connection"><h3>Connect your Reddit account</h3>
  <p>{connection?.route==='controlled_browser'?<>Studio recorded the browser-verified identity <strong>u/Ok-External401</strong>. No Reddit API scope or credential is attached. The controlled browser route can open Reddit’s composer after a route test.</>:<>Studio will verify <strong>u/Ok-External401</strong> with Reddit’s <code>identity</code> scope only.</>} Comments, votes, messages, subscriptions, scheduling, editing, deletion, and autonomous posting remain unavailable.</p>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  {connected?<><p className="success-banner">Verified Reddit identity: <strong>u/{connection?.username}</strong>. {connection?.publishReady?'Browser publishing enabled.':'Publishing route not yet enabled.'}</p>{connection?.route==='controlled_browser'?<div className="callout"><strong>{connection.publishReady?'Publish-ready through controlled browser':'Controlled browser connected'}</strong><p>Future posting preference: Computer or Chrome. Studio must verify the signed-in username and receive approval for the exact community, title, body, media, and timing before each Post click.</p>{connection.publishReady?<small>Route test {connection.routeTestId} · completed {connection.routeTestedAt}</small>:<button type="button" className="button primary" disabled={busy} onClick={()=>void enableBrowserPublishing()}>{busy?'Enabling…':'Enable tested browser publishing'}</button>}</div>:<button type="button" disabled={busy} onClick={()=>void verify()}>{busy?'Verifying…':'Re-verify Reddit identity'}</button>}</>:<form onSubmit={connect}>
   <p>Connection state: <strong>{connection?.state??'loading'}</strong></p>
   {connection?.state==='configuration_required'&&<p className="muted">A Reddit developer app with approval for this identity-only use is required before private authorization can begin.</p>}
   {unresolved&&<p role="alert" className="error-banner">The previous authorization is unresolved. Do not retry until it is reconciled.</p>}
   <label><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)} disabled={busy||unresolved||!connection?.available}/> I confirm the exact account and identity-only OAuth scope. This does not publish or grant future publishing access.</label>
   <button disabled={!consent||busy||unresolved||!connection?.available} type="submit">{busy?'Opening Reddit…':'Continue to Reddit consent'}</button>
   <button className="button" disabled={!consent||busy||unresolved} type="button" onClick={()=>void connectBrowser()}>{busy?'Connecting…':'Connect verified browser identity'}</button>
  </form>}
 </section>;
}
