import {useEffect,useState} from 'react';
import {connectionsApi,type ThreadsConnection as State,type ThreadsPostResult} from './connectionsApi';

const INITIAL_TEXT='Testing a new publishing connection for James Au Studio.\n\nThis post was reviewed and sent through my own local workflow.';
async function sha256(value:string){
 const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));
 return [...new Uint8Array(bytes)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
}
async function receipt(text:string){
 const manifest={account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',text,visibility:'public',replyControl:'provider_default',scheduledAt:null,media:[],derivatives:[]};
 const approvalReceiptHash=await sha256(JSON.stringify(manifest,Object.keys(manifest).sort()));
 return {approvalReceiptHash,idempotencyKey:await sha256('threads.publish\0'+approvalReceiptHash)};
}

export default function ThreadsConnection(){
 const [connection,setConnection]=useState<State|null>(null),[consent,setConsent]=useState(false),[publishConsent,setPublishConsent]=useState(false),[busy,setBusy]=useState(false),[authorizationUrl,setAuthorizationUrl]=useState(''),[error,setError]=useState(''),[text,setText]=useState(INITIAL_TEXT),[result,setResult]=useState<ThreadsPostResult|null>(null);
 async function refresh(){try{setConnection((await connectionsApi.status()).threads);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
 useEffect(()=>{void refresh();},[]);
 async function verify(){setBusy(true);setError('');try{setConnection(await connectionsApi.verifyThreads());}catch(cause){setError(cause instanceof Error?cause.message:'Connection verification unavailable.');}finally{setBusy(false);}}
 async function testRoute(){setBusy(true);setError('');try{setConnection(await connectionsApi.testThreadsRoute());}catch(cause){setError(cause instanceof Error?cause.message:'Threads publishing route test failed.');}finally{setBusy(false);}}
 async function connect(event:React.SubmitEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError('');try{setAuthorizationUrl(await connectionsApi.prepareThreads('jamesaucreates'));}catch(cause){setError(cause instanceof Error?cause.message:'Threads sign-in could not start.');}finally{setBusy(false);}}
 async function publish(event:React.SubmitEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError('');setResult(null);try{const hashes=await receipt(text);setResult(await connectionsApi.publishThreadsText({text,...hashes,publicationConsent:true}));setPublishConsent(false);}catch(cause){setError(cause instanceof Error?cause.message:'Threads could not return verified publication evidence.');}finally{setBusy(false);}}
 return <section className="setup-panel" aria-label="Threads account connection"><h3>Threads publishing</h3>
  <p>Meta verifies <strong>@jamesaucreates</strong>. Studio uses the official Threads API with <code>threads_basic</code> and <code>threads_content_publish</code>. Every public post still requires approval of its exact copy and destination.</p>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  {connection?.verifiedAt?<div className="callout"><strong>{connection.publishReady?'Publish-ready':connection.state==='connected_identity'?'Identity connected':'Verification required'}: @{connection.username}</strong><p>Threads user ID {connection.userId}</p><p>{connection.publishReady?'The authenticated identity and current publishing quota both passed the official API route test.':'The saved identity is connected. Run the read-only route test to verify the publishing path and current quota.'}</p><small>Identity verified {connection.verifiedAt}{connection.routeTestedAt?` · Route tested ${connection.routeTestedAt}`:''} · Access expires {connection.expiresAt}</small></div>:<>
   <p className="muted">{connection?.available?`Connection state: ${connection.state.replaceAll('_',' ')}`:connection?.state==='broker_unavailable'?'The private connection service is unavailable. Restart Studio and check again.':'Threads app credentials and trusted local TLS are required. Add them privately, then restart Studio.'}</p>
   {connection?.state==='configuration_required'&&<p>Meta callback: <code>https://threads-jamesau.meta:4316/callback</code> · Apple Keychain service: <code>James Au Studio Threads OAuth</code>, accounts <code>client-id</code> and <code>client-secret</code>.</p>}
   {authorizationUrl?<div className="callout"><strong>Secure sign-in link ready</strong><p>Open this one-time link in the browser where @jamesaucreates is already signed in. It expires in ten minutes.</p><a className="button primary" href={authorizationUrl}>Open Threads sign-in</a></div>:<form onSubmit={connect}><fieldset className="setup-fields" disabled={busy||!connection?.available}><label className="check-field"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Connect @jamesaucreates for identity verification and approval-gated Threads publishing. Keep its OAuth token encrypted on this Mac.</label><button type="submit" className="button primary" disabled={!consent}>{busy?'Preparing…':'Prepare Threads sign-in'}</button></fieldset></form>}</>}
  {connection?.state==='connected_identity'&&!connection.publishReady&&<button type="button" className="button primary" onClick={()=>void testRoute()} disabled={busy}>{busy?'Testing…':'Run publishing route test'}</button>}
  {connection?.publishReady&&<form onSubmit={publish}><fieldset className="setup-fields" disabled={busy}>
   <label>Exact public post<textarea value={text} maxLength={500} rows={5} onChange={event=>{setText(event.target.value);setPublishConsent(false);setResult(null);}}/></label>
   <small>{text.length}/500 · @jamesaucreates · Main profile feed · Public · Immediate · No media or derivatives</small>
   <label className="check-field"><input type="checkbox" checked={publishConsent} onChange={event=>setPublishConsent(event.target.checked)}/> Publish this exact text now to the public @jamesaucreates Threads profile.</label>
   <button type="submit" className="button primary" disabled={!publishConsent||text.length<1||text.trim()!==text}>{busy?'Publishing and verifying…':'Publish exact post'}</button>
  </fieldset></form>}
  {result&&<div className="callout"><strong>Verified published post</strong><p><a href={result.url} target="_blank" rel="noreferrer">Open on Threads</a></p><small>Post ID {result.threadId} · Verified {result.verifiedAt}</small></div>}
  <button type="button" className="button" onClick={()=>void (connection?.verifiedAt?verify():refresh())} disabled={busy}>{busy?'Checking…':'Check connection'}</button>
 </section>;
}
