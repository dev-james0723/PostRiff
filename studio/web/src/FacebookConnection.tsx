import {useEffect,useState} from 'react';
import {connectionsApi,type FacebookConnection as State,type FacebookPostResult} from './connectionsApi';
async function sha256(value:string){const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value));return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');}
async function receipt(state:State,message:string,link:string|null,scheduledAt:string|null){const manifest={account:state.pageName,pageId:state.pageId,destination:'page_feed',nativeFormat:'facebook.page_post',message,link,visibility:'public',scheduledAt,derivatives:[]};const approvalReceiptHash=await sha256(JSON.stringify(manifest,Object.keys(manifest).sort()));return {approvalReceiptHash,idempotencyKey:await sha256('facebook.publish\0'+approvalReceiptHash)};}
export default function FacebookConnection(){
 const [connection,setConnection]=useState<State|null>(null),[pageName,setPageName]=useState('James Au Studio'),[pageId,setPageId]=useState(''),[consent,setConsent]=useState(false),[publishConsent,setPublishConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[link,setLink]=useState(''),[schedule,setSchedule]=useState(''),[result,setResult]=useState<FacebookPostResult|null>(null);
 async function refresh(){try{setConnection((await connectionsApi.status()).facebook);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Connection status unavailable.');}}
 useEffect(()=>{void refresh();},[]);
 async function verify(){setBusy(true);setError('');try{setConnection(await connectionsApi.verifyFacebook());}catch(cause){setError(cause instanceof Error?cause.message:'Connection verification unavailable.');}finally{setBusy(false);}}
 async function testRoute(){if(!connection)return;setBusy(true);setError('');try{setConnection(await connectionsApi.testFacebookRoute(connection));}catch(cause){setError(cause instanceof Error?cause.message:'Facebook publishing route test failed.');}finally{setBusy(false);}}
 async function connect(e:React.SubmitEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError('');try{window.location.assign(await connectionsApi.prepareFacebook(pageName,pageId));}catch(cause){setError(cause instanceof Error?cause.message:'Facebook sign-in could not start.');setBusy(false);}}
 async function publish(e:React.SubmitEvent<HTMLFormElement>){e.preventDefault();if(!connection)return;setBusy(true);setError('');setResult(null);try{const scheduledAt=schedule?new Date(schedule).toISOString():null,hashes=await receipt(connection,message,link||null,scheduledAt);setResult(await connectionsApi.publishFacebookPost(connection,{message,link:link||null,scheduledAt,...hashes,publicationConsent:true}));setPublishConsent(false);}catch(cause){setError(cause instanceof Error?cause.message:'Facebook could not return verified post evidence.');}finally{setBusy(false);}}
 return <section className="setup-panel" aria-label="Facebook Page publishing connection"><h3>Facebook Page publishing</h3>
  <p>The official Pages API connection requests Page listing, read-back and post publishing scopes.</p>
  {error&&<p role="alert" className="error-banner">{error}</p>}
  {connection?.verifiedAt?<div className="callout"><strong>{connection.publishReady?'Publish-ready':connection.state==='connected_identity'?'Page connected':'Verification required'}: {connection.pageName}</strong><p>Page ID {connection.pageId} · owner {connection.userName}</p><p>{connection.publishReady?'Page identity and feed read-back passed the official API route test.':'Run the read-only route test before posting.'}</p><small>Identity verified {connection.verifiedAt}{connection.routeTestedAt?' · Route tested '+connection.routeTestedAt:''} · Access expires {connection.expiresAt}</small></div>:<>
   <p className="muted">{connection?.available?'Connection state: '+connection.state.replaceAll('_',' '):'Facebook credentials and a working HTTPS callback are required.'}</p>
   {connection?.state==='configuration_required'&&<p>Apple Keychain: <code>James Au Studio Facebook OAuth</code> / <code>client-id</code> and <code>client-secret</code>. Broker callback port: <code>4319</code>.</p>}
   <form onSubmit={connect}><fieldset className="setup-fields" disabled={busy||!connection?.available}>
    <label className="field">Exact Facebook Page name<input required maxLength={160} value={pageName} onChange={e=>{setPageName(e.target.value);setConsent(false);}}/></label>
    <label className="field">Numeric Facebook Page ID<input required pattern="[0-9]{5,30}" inputMode="numeric" value={pageId} onChange={e=>{setPageId(e.target.value);setConsent(false);}}/></label>
    <label className="check-field"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Connect this exact Page for identity verification and approval-gated Page posting. Keep Page tokens encrypted on this Mac.</label>
    <button type="submit" className="button primary" disabled={!consent||!pageName.trim()||!/^\d{5,30}$/.test(pageId)}>{busy?'Preparing…':'Continue to Facebook'}</button>
   </fieldset></form></>}
  {connection?.state==='connected_identity'&&!connection.publishReady&&<button type="button" className="button primary" onClick={()=>void testRoute()} disabled={busy}>{busy?'Testing…':'Run publishing route test'}</button>}
  {connection?.publishReady&&<form onSubmit={publish}><fieldset className="setup-fields" disabled={busy}>
   <label className="field">Exact Page post<textarea required value={message} maxLength={63206} rows={6} onChange={e=>{setMessage(e.target.value);setPublishConsent(false);setResult(null);}}/></label>
   <label className="field">Link (optional)<input type="url" value={link} onChange={e=>{setLink(e.target.value);setPublishConsent(false);setResult(null);}}/></label>
   <label className="field">Schedule (optional; at least 10 minutes ahead)<input type="datetime-local" value={schedule} onChange={e=>{setSchedule(e.target.value);setPublishConsent(false);setResult(null);}}/></label>
   <small>{connection.pageName} · Page feed · Public · {schedule||'Immediate'} · No media or derivatives</small>
   <label className="check-field"><input type="checkbox" checked={publishConsent} onChange={e=>setPublishConsent(e.target.checked)}/> {schedule?'Schedule':'Publish'} this exact text and link on {connection.pageName} at the time shown.</label>
   <button type="submit" className="button primary" disabled={!publishConsent||!message.trim()}>{busy?'Submitting and verifying…':schedule?'Schedule exact Facebook post':'Publish exact Facebook post'}</button>
  </fieldset></form>}
  {result&&<div className="callout"><strong>Verified {result.state} Facebook post</strong>{result.url&&<p><a href={result.url} target="_blank" rel="noreferrer">Open on Facebook</a></p>}<small>Post ID {result.postId} · Verified {result.verifiedAt}</small></div>}
  <button type="button" className="button" onClick={()=>void (connection?.verifiedAt?verify():refresh())} disabled={busy}>{busy?'Checking…':'Check connection'}</button>
 </section>;
}
