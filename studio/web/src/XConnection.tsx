import {useEffect,useState} from 'react';
import {connectionsApi,type XBrowserConnection} from './connectionsApi';

export default function XConnection(){
 const [state,setState]=useState<XBrowserConnection|null>(null),[error,setError]=useState('');
 async function refresh(){try{setState(await connectionsApi.xBrowserStatus());setError('');}catch(cause){setError(cause instanceof Error?cause.message:'X status unavailable.');}}
 useEffect(()=>{void refresh();},[]);
 return <section className="setup-panel" aria-label="X account connection"><h3>X posting and scheduling</h3>
  <div className="callout"><strong>Free persistent Codex browser route</strong>
   <p>Uses the signed-in X tab in Codex’s in-app browser. It does not use the paid X API, launch a separate Chrome or Edge profile, or copy cookies.</p>
   {state?.state==='connected_identity'?<><p className="success-banner">Connected and live-tested as <strong>@{state.username}</strong>.</p><p>Ask Codex to make, post, or schedule an X post. Codex reuses the saved browser session and verifies the exact account before every final action.</p><small>Route: {state.routeDriver} · exact post approval required · live test {state.liveTestVerified?'verified':'pending'}</small></>:<p>Open X in the Codex in-app browser and sign in once, then ask Codex to verify the connection.</p>}
  </div>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  <button type="button" className="button" onClick={()=>void refresh()}>Refresh status</button>
 </section>;
}
