import http from 'node:http';
import {randomBytes,timingSafeEqual,createHash} from 'node:crypto';
import {NodeOAuthClient} from '@atproto/oauth-client-node';
import {privateStore} from './private-store.mjs';

const SCOPE='atproto';
const TTL=10*60*1000;
const digest=value=>createHash('sha256').update(value).digest('hex');
const eq=(a,b)=>typeof a==='string'&&typeof b==='string'&&a.length===b.length&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
export function handleName(value){
  if(typeof value!=='string'||value.length>253)throw new Error('invalid_handle');
  const handle=value.trim().toLowerCase().replace(/^@/,'');
  if(!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*$/.test(handle))throw new Error('invalid_handle');
  return handle;
}
export function metadata(port){
  const redirect=`http://127.0.0.1:${port}/callback`;
  return {client_id:`http://localhost?redirect_uri=${encodeURIComponent(redirect)}&scope=atproto`,
    redirect_uris:[redirect],scope:SCOPE,grant_types:['authorization_code','refresh_token'],
    response_types:['code'],application_type:'native',token_endpoint_auth_method:'none',dpop_bound_access_tokens:true};
}

export async function createBroker({port,studioPort,root,capability,oauthFactory,fetchPublic=fetch,now=Date.now}){
  if(!Number.isInteger(port)||port<1024||port>65535||!Number.isInteger(studioPort)||studioPort<1024||studioPort>65535||typeof capability!=='string'||capability.length<40)throw new Error('invalid_configuration');
  const store=await privateStore(root),control=store('control'),states=store('oauth-state'),sessions=store('oauth-session');
  const locks=new Map();
  const requestLock=async(key,fn)=>{const prev=locks.get(key)||Promise.resolve();let release;const tail=new Promise(r=>{release=r;});locks.set(key,tail);await prev;try{return await fn();}finally{release();if(locks.get(key)===tail)locks.delete(key);}};
  const oauth=(oauthFactory||((options)=>new NodeOAuthClient(options)))({clientMetadata:metadata(port),stateStore:states,sessionStore:sessions,requestLock});
  let pending=await control.get('pending'),record=await control.get('identity');
  // An interrupted PAR request cannot be replayed blindly.
  if(pending&&pending.phase==='preparing'){pending={...pending,phase:'interrupted'};await control.set('pending',pending);}
  const status=()=>({provider:'bluesky',available:true,state:record?(record.expiresAt&&Date.parse(record.expiresAt)<=now()?'needs_reauthentication':'connected_identity'):(pending&&pending.expires>now()?pending.phase:'not_connected'),
    handle:record?.handle||pending?.handle||null,did:record?.did||null,scope:record?.scope||SCOPE,
    verifiedAt:record?.verifiedAt||null,expiresAt:record?.expiresAt||null,
    identitySignals:record?['oauth_subject','public_profile_match']:[],publishReady:false,publishing:false});
  const headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"};
  const json=(res,code,body)=>{res.writeHead(code,{...headers,'Content-Type':'application/json'});res.end(JSON.stringify(body));};
  const redirect=(res,url,cookie)=>{res.writeHead(303,{...headers,Location:url,...(cookie?{'Set-Cookie':cookie}:{})});res.end();};
  async function persistPending(value){pending=value;await control.set('pending',value);}
  const server=http.createServer(async(req,res)=>{
    try{
      if(req.headers.host!==`127.0.0.1:${port}`){json(res,403,{error:'host_not_allowed'});return;}
      const url=new URL(req.url,`http://127.0.0.1:${port}`);
      if(url.pathname==='/callback'&&req.method==='GET'){
        const cookie=(req.headers.cookie||'').split(';').map(v=>v.trim()).find(v=>v.startsWith('studio_broker_nonce='))?.slice(20);
        if(!pending||pending.phase!=='private_handoff'||pending.expires<=now()||!cookie||!eq(digest(cookie),pending.browserHash)){json(res,400,{error:'callback_not_expected'});return;}
        const allowed=new Set(['code','state','iss','error','error_description']);
        if([...url.searchParams.keys()].some(k=>!allowed.has(k)||url.searchParams.getAll(k).length!==1)||url.search.length>16384){json(res,400,{error:'invalid_callback'});return;}
        const selected=pending;
        await persistPending({...selected,phase:'verifying'});
        try{
          const {session,state}=await oauth.callback(url.searchParams);
          if(!eq(state,selected.flow))throw new Error('identity_mismatch');
          const token=await session.getTokenInfo(false);
          if(token.scope!==SCOPE||token.sub!==session.did)throw new Error('scope_mismatch');
          const response=await fetchPublic('https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor='+encodeURIComponent(selected.handle),{redirect:'error',signal:AbortSignal.timeout(15000)});
          if(!response.ok)throw new Error('profile_unavailable');
          const profile=await response.json();
          if(profile.did!==session.did||handleName(profile.handle)!==selected.handle)throw new Error('identity_mismatch');
          const next={handle:selected.handle,did:session.did,scope:token.scope,verifiedAt:new Date(now()).toISOString(),expiresAt:token.expiresAt?.toISOString()||null};
          await control.set('identity',next);record=next;
          await persistPending({...selected,phase:'complete',authUrl:null,browserHash:null});
        }catch{
          // Provider errors may contain credentials. Never forward or log them.
          await persistPending({...selected,phase:'connection_failed',authUrl:null,browserHash:null});
        }
        redirect(res,`http://127.0.0.1:${studioPort}/connection-return`,'studio_broker_nonce=; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=0');return;
      }
      if(url.pathname.startsWith('/begin/')&&req.method==='GET'){
        const ticket=url.pathname.slice(7);
        if(!pending||pending.phase!=='awaiting_private_signin'||pending.expires<=now()||!eq(digest(ticket),pending.ticketHash)){json(res,410,{error:'signin_expired'});return;}
        const nonce=randomBytes(32).toString('hex'),authUrl=pending.authUrl;
        await persistPending({...pending,phase:'private_handoff',ticketHash:null,authUrl:null,browserHash:digest(nonce)});
        redirect(res,authUrl,`studio_broker_nonce=${nonce}; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=600`);return;
      }
      if(!eq(req.headers['x-studio-broker'],capability)){json(res,403,{error:'broker_access_denied'});return;}
      if(url.pathname==='/status'&&req.method==='GET'){json(res,200,status());return;}
      if(url.pathname==='/prepare'&&req.method==='POST'){
        let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>1024){json(res,413,{error:'request_too_large'});return;}}
        let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
        if(!body||typeof body!=='object'||Object.keys(body).sort().join(',')!=='handle,scope'||body.scope!==SCOPE){json(res,422,{error:'invalid_request'});return;}
        let handle;try{handle=handleName(body.handle);}catch{json(res,422,{error:'invalid_handle'});return;}
        if(record&&(record.handle!==handle||!record.expiresAt||Date.parse(record.expiresAt)>now())){json(res,409,{error:'account_already_connected'});return;}
        if(pending&&pending.expires>now()&&!['connection_failed','interrupted','complete'].includes(pending.phase)){json(res,409,{error:'signin_already_pending'});return;}
        const flow=randomBytes(32).toString('hex'),ticket=randomBytes(32).toString('hex');
        await persistPending({handle,flow,expires:now()+TTL,phase:'preparing'});
        try{
          const auth=await oauth.authorize(handle,{scope:SCOPE,state:flow,signal:AbortSignal.timeout(30000)});
          const target=new URL(auth);if(target.protocol!=='https:'||target.username||target.password)throw new Error('unsafe_authorization_url');
          await persistPending({...pending,phase:'awaiting_private_signin',authUrl:target.toString(),ticketHash:digest(ticket)});
          json(res,200,{beginPath:`/begin/${ticket}`});
        }catch{await persistPending({...pending,phase:'connection_failed'});json(res,502,{error:'authorization_unavailable'});}
        return;
      }
      json(res,404,{error:'operation_unavailable'});
    }catch{if(!res.headersSent)json(res,500,{error:'connection_operation_failed'});else res.end();}
  });
  return {server,status};
}
