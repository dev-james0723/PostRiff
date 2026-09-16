import http from 'node:http';
import {randomBytes,timingSafeEqual,createHash} from 'node:crypto';
import {privateStore} from './private-store.mjs';

export const TIKTOK_SCOPE='user.info.basic,user.info.profile';
const TTL=10*60*1000;
const digest=value=>createHash('sha256').update(value).digest('hex');
const eq=(a,b)=>typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const username=value=>typeof value==='string'&&/^[A-Za-z0-9._]{1,24}$/.test(value)&&!value.endsWith('.')?value.toLowerCase():null;
const opaque=value=>typeof value==='string'&&value.length>0&&value.length<=256&&!/[\s\x00-\x1f]/.test(value);
const safeJson=async response=>{
  const chunks=[];let size=0;
  for await(const chunk of response.body){size+=chunk.length;if(size>1024*1024)throw new Error('response_too_large');chunks.push(Buffer.from(chunk));}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
};
const validateToken=token=>{
  const scopes=typeof token.scope==='string'?token.scope.split(','):[];
  const granted=new Set(scopes);
  if(granted.size!==2||scopes.length!==2||TIKTOK_SCOPE.split(',').some(s=>!granted.has(s)))throw new Error('scope_mismatch');
  if(typeof token.access_token!=='string'||!token.access_token||token.access_token.length>16384||/[\s\x00-\x1f]/.test(token.access_token)||
     String(token.token_type).toLowerCase()!=='bearer'||!Number.isInteger(token.expires_in)||token.expires_in<=0||token.expires_in>86400||!opaque(token.open_id))throw new Error('invalid_token');
};

export async function createTikTokBroker({port,studioPort,root,capability,clientKey,clientSecret,fetchApi=fetch,now=Date.now}){
  if(!Number.isInteger(studioPort)||studioPort<1024||studioPort>65535||studioPort===port||!Number.isInteger(port)||port<1024||port>65535||typeof capability!=='string'||capability.length<40)throw new Error('invalid_configuration');
  const configured=typeof clientKey==='string'&&/^[A-Za-z0-9_-]{4,256}$/.test(clientKey)&&typeof clientSecret==='string'&&clientSecret.length>=16;
  const store=await privateStore(root),control=store('tiktok-control'),tokens=store('tiktok-tokens');
  let pending=await control.get('pending'),record=await control.get('identity');
  if(pending&&['preparing','verifying'].includes(pending.phase)){pending={...pending,phase:'connection_unresolved'};await control.set('pending',pending);}
  let verifiedThisRun=false,verificationInProgress=false,preparing=false;
  const isCurrent=()=>configured&&pending?.phase!=='connection_unresolved'&&verifiedThisRun&&record&&Date.parse(record.expiresAt)>now();
  const status=()=>({provider:'tiktok',available:configured,state:pending?.phase==='connection_unresolved'?'connection_unresolved':record?(isCurrent()?'connected_identity':'verification_required'):(configured&&pending&&pending.expires>now()?pending.phase:(configured?'not_connected':'configuration_required')),
    username:record?.username||pending?.username||null,openId:record?.openId||null,displayName:record?.displayName||null,
    scope:TIKTOK_SCOPE,verifiedAt:record?.verifiedAt||null,expiresAt:record?.expiresAt||null,
    identitySignals:isCurrent()?['oauth_subject','independent_user_info_username']:[],publishReady:false,publishing:false});
  const headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"};
  const json=(res,code,body)=>{res.writeHead(code,{...headers,'Content-Type':'application/json'});res.end(JSON.stringify(body));};
  const redirect=(res,url,cookie)=>{res.writeHead(303,{...headers,Location:url,...(cookie?{'Set-Cookie':cookie}:{})});res.end();};
  const persist=async value=>{pending=value;await control.set('pending',value);};
  const verifyIdentity=async(token,expected)=>{
    const response=await fetchApi('https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,username',{
      headers:{Authorization:`Bearer ${token.access_token}`},redirect:'error',signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw new Error('identity_unavailable');
    const body=await safeJson(response),user=body.data?.user;
    if(body.error?.code!=='ok'||!user||user.open_id!==token.open_id||username(user.username)!==expected.username||
       (expected.openId&&user.open_id!==expected.openId))throw new Error('identity_mismatch');
    return {username:expected.username,openId:user.open_id,displayName:typeof user.display_name==='string'?user.display_name.slice(0,200):null,
      scope:TIKTOK_SCOPE,verifiedAt:new Date(now()).toISOString(),expiresAt:new Date(now()+token.expires_in*1000).toISOString()};
  };
  const server=http.createServer(async(req,res)=>{try{
    if(req.headers.host!==`127.0.0.1:${port}`){json(res,403,{error:'host_not_allowed'});return;}
    const url=new URL(req.url,`http://127.0.0.1:${port}`);
    if(url.pathname==='/callback'&&req.method==='GET'){
      const cookie=(req.headers.cookie||'').split(';').map(v=>v.trim()).find(v=>v.startsWith('studio_tiktok_nonce='))?.slice('studio_tiktok_nonce='.length);
      if(!pending||pending.phase!=='private_handoff'||pending.expires<=now()||!cookie||!eq(digest(cookie),pending.browserHash)){json(res,400,{error:'callback_not_expected'});return;}
      if([...url.searchParams.keys()].some(k=>!['code','state','error','error_description','scopes'].includes(k)||url.searchParams.getAll(k).length!==1)||url.search.length>16384){json(res,400,{error:'invalid_callback'});return;}
      const selected=pending;let exchangeStarted=false;await persist({...selected,phase:'verifying',browserHash:null});
      try{
        if(!opaque(url.searchParams.get('code'))||url.searchParams.get('error')||!eq(url.searchParams.get('state'),selected.flow))throw new Error('authorization_failed');
        exchangeStarted=true;const tokenResponse=await fetchApi('https://open.tiktokapis.com/v2/oauth/token/',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({code:url.searchParams.get('code')||'',client_key:clientKey,client_secret:clientSecret,redirect_uri:`http://127.0.0.1:${port}/callback`,grant_type:'authorization_code',code_verifier:selected.verifier}),redirect:'error',signal:AbortSignal.timeout(30000)});
        if(!tokenResponse.ok)throw new Error('token_exchange_failed');const token=await safeJson(tokenResponse);
        validateToken(token);
        const next=await verifyIdentity(token,selected);
        await tokens.set('refresh',{refreshToken:token.refresh_token||null,accessToken:token.access_token,expiresAt:next.expiresAt,scope:TIKTOK_SCOPE,openId:token.open_id});
        await control.set('identity',next);record=next;verifiedThisRun=true;
        await persist({...selected,phase:'complete',browserHash:null,verifier:null});
      }catch{verifiedThisRun=false;await persist({...selected,phase:exchangeStarted?'connection_unresolved':'connection_failed',browserHash:null,verifier:null});}
      redirect(res,`http://127.0.0.1:${studioPort}/connection-return`,'studio_tiktok_nonce=; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=0');return;
    }
    if(url.pathname.startsWith('/begin/')&&req.method==='GET'){
      const ticket=url.pathname.slice(7);if(!pending||pending.phase!=='awaiting_private_signin'||pending.expires<=now()||!eq(digest(ticket),pending.ticketHash)){json(res,410,{error:'signin_expired'});return;}
      const nonce=randomBytes(32).toString('hex');await persist({...pending,phase:'private_handoff',ticketHash:null,browserHash:digest(nonce)});
      const auth=new URL('https://www.tiktok.com/v2/auth/authorize/');
      for(const [k,v] of Object.entries({client_key:clientKey,redirect_uri:`http://127.0.0.1:${port}/callback`,response_type:'code',scope:TIKTOK_SCOPE,state:pending.flow,
        code_challenge:digest(pending.verifier),code_challenge_method:'S256',disable_auto_auth:'1'}))auth.searchParams.set(k,v);
      redirect(res,auth.toString(),`studio_tiktok_nonce=${nonce}; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=600`);return;
    }
    if(!eq(req.headers['x-studio-broker'],capability)){json(res,403,{error:'broker_access_denied'});return;}
    if(url.pathname==='/status'&&req.method==='GET'){json(res,200,status());return;}
    if(url.pathname==='/verify'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!configured){json(res,503,{error:'configuration_required'});return;}
      if(!record){json(res,409,{error:'identity_not_connected'});return;}
      if(verificationInProgress){json(res,409,{error:'verification_in_progress'});return;}
      verificationInProgress=true;verifiedThisRun=false;
      try{
        const saved=await tokens.get('refresh');
        if(!saved?.accessToken)throw new Error('authorization_missing');
        let token={access_token:saved.accessToken,token_type:'Bearer',scope:saved.scope||record.scope,open_id:saved.openId,expires_in:Math.floor((Date.parse(saved.expiresAt)-now())/1000)};
        if(token.expires_in<=60){
          if(!saved.refreshToken)throw new Error('reauthorization_required');
          await persist({...pending,phase:'verifying'});
          const response=await fetchApi('https://open.tiktokapis.com/v2/oauth/token/',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
            body:new URLSearchParams({client_key:clientKey,client_secret:clientSecret,refresh_token:saved.refreshToken,grant_type:'refresh_token'}),redirect:'error',signal:AbortSignal.timeout(30000)});
          if(!response.ok)throw new Error('refresh_failed');
          token=await safeJson(response);
          // RFC 6749 permits scope omission when the refresh grant is unchanged.
          if(token.scope===undefined)token.scope=saved.scope||record.scope;
        }
        validateToken(token);
        const next=await verifyIdentity(token,record);
        await tokens.set('refresh',{refreshToken:token.refresh_token||saved.refreshToken,accessToken:token.access_token,expiresAt:next.expiresAt,scope:TIKTOK_SCOPE,openId:token.open_id});
        await control.set('identity',next);record=next;verifiedThisRun=true;
        await persist({...pending,phase:'complete',verifier:null});
      }catch{verifiedThisRun=false;if(pending?.phase==='verifying')await persist({...pending,phase:'connection_unresolved'});}
      finally{verificationInProgress=false;}
      json(res,200,status());return;
    }
    if(url.pathname==='/prepare'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!configured){json(res,503,{error:'configuration_required'});return;}let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>2048){json(res,413,{error:'request_too_large'});return;}}
      let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
      if(!body||Object.keys(body).sort().join(',')!=='scope,username'||body.scope!==TIKTOK_SCOPE){json(res,422,{error:'invalid_request'});return;}
      const expectedUsername=username(body.username);if(!expectedUsername){json(res,422,{error:'invalid_identity'});return;}
      if(record){json(res,409,{error:'account_already_connected'});return;}if(pending&&pending.expires>now()&&!['connection_failed','interrupted','complete'].includes(pending.phase)){json(res,409,{error:'signin_already_pending'});return;}
      if(preparing){json(res,409,{error:'signin_already_pending'});return;}preparing=true;
      try { const flow=randomBytes(32).toString('hex'),ticket=randomBytes(32).toString('hex');await persist({username:expectedUsername,verifier:randomBytes(48).toString('hex'),flow,expires:now()+TTL,phase:'awaiting_private_signin',ticketHash:digest(ticket)});json(res,200,{beginPath:`/begin/${ticket}`}); } finally { preparing=false; } return;
    }
    json(res,404,{error:'operation_unavailable'});
  }catch{if(!res.headersSent)json(res,500,{error:'connection_operation_failed'});else res.end();}});
  return {server,status};
}
