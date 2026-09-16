import http from 'node:http';
import {createHash,randomBytes,timingSafeEqual} from 'node:crypto';
import {privateStore} from './private-store.mjs';

export const X_SCOPE='tweet.read users.read tweet.write offline.access';
export const X_REDIRECT_URI='http://127.0.0.1:4320/callback';
const TTL=10*60*1000;
const digest=value=>createHash('sha256').update(value).digest('hex');
const eq=(a,b)=>typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const base64url=value=>Buffer.from(value).toString('base64url');
const opaque=value=>typeof value==='string'&&value.length>0&&value.length<=16384&&!/[\s\x00-\x1f]/.test(value);
const username=value=>typeof value==='string'&&/^[A-Za-z0-9_]{1,15}$/.test(value)?value:null;
const exactScope=value=>{
  if(typeof value!=='string')return false;
  const expected=X_SCOPE.split(' '),actual=value.trim().split(/\s+/).filter(Boolean);
  return actual.length===expected.length&&expected.every(scope=>actual.includes(scope));
};
const safeJson=async response=>{
  const chunks=[];let size=0;
  for await(const chunk of response.body){size+=chunk.length;if(size>1024*1024)throw new Error('response_too_large');chunks.push(Buffer.from(chunk));}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
};
const json=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer'});res.end(JSON.stringify(value));};
const redirect=(res,to,cookie)=>{res.writeHead(303,{Location:to,'Cache-Control':'no-store','Referrer-Policy':'no-referrer',...(cookie?{'Set-Cookie':cookie}:{})});res.end();};
const cookie=(header,name)=>typeof header==='string'?header.split(';').map(value=>value.trim()).find(value=>value.startsWith(name+'='))?.slice(name.length+1)??null:null;
const validClientId=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{8,256}$/.test(value);
const validateToken=token=>{
  if(!token||!opaque(token.access_token)||!opaque(token.refresh_token)||!exactScope(token.scope)||String(token.token_type).toLowerCase()!=='bearer'||!Number.isInteger(token.expires_in)||token.expires_in<=0||token.expires_in>7200)throw new Error('invalid_token');
};

export async function createXBroker({port,studioPort,root,capability,clientId,fetchApi=fetch,now=Date.now}){
  if(port!==4320||studioPort===port||!Number.isInteger(studioPort)||studioPort<1024||studioPort>65535||typeof capability!=='string'||capability.length<40)throw new Error('invalid_configuration');
  const configured=validClientId(clientId);
  const store=await privateStore(root),control=store('x-control'),tokens=store('x-tokens');
  let record=await control.get('identity'),pending=await control.get('pending'),verificationInProgress=false;
  const persist=async value=>{pending=value;await control.set('pending',value);};
  const expired=()=>!record||Date.parse(record.expiresAt)<=now();
  const status=()=>{
    const base={provider:'x',available:configured,state:'configuration_required',username:null,accountId:null,profileUrl:null,scope:X_SCOPE,route:'official_api',routeDriver:'x_oauth2_pkce',sessionState:'not_established',verifiedAt:null,expiresAt:null,identitySignals:[],routeState:'not_tested',routeTestId:null,routeTestedAt:null,routeTestSignals:[],publicationPolicy:'exact_post_approval_required',publishReady:false,publishing:false};
    if(!configured)return base;
    if(pending?.phase==='connection_unresolved')return {...base,state:'connection_unresolved'};
    if(pending?.phase&&pending.phase!=='complete')return {...base,state:pending.phase};
    if(!record)return base;
    return {...base,...record,state:expired()?'needs_reauthorization':'connected_identity'};
  };
  const requestToken=async body=>{
    const response=await fetchApi('https://api.x.com/2/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Cache-Control':'no-store'},body:new URLSearchParams(body)});
    if(!response.ok)throw new Error('token_exchange_failed');
    const token=await safeJson(response);validateToken(token);return token;
  };
  const verifyIdentity=async(token,expected)=>{
    const response=await fetchApi('https://api.x.com/2/users/me',{headers:{Authorization:`Bearer ${token}`,'Cache-Control':'no-store'}});
    if(!response.ok)throw new Error('identity_failed');
    const current=await safeJson(response),actual=username(current?.data?.username),accountId=typeof current?.data?.id==='string'&&/^[0-9]{1,32}$/.test(current.data.id)?current.data.id:null;
    if(!actual||!accountId||actual.toLowerCase()!==expected.toLowerCase())throw new Error('identity_mismatch');
    return {username:actual,accountId,profileUrl:`https://x.com/${actual}`,scope:X_SCOPE,route:'official_api',routeDriver:'x_oauth2_pkce',sessionState:'oauth_token_active',verifiedAt:new Date(now()).toISOString(),expiresAt:null,identitySignals:['oauth2_users_me','expected_handle_and_stable_account_id_match'],routeState:'not_tested',routeTestId:null,routeTestedAt:null,routeTestSignals:[],publicationPolicy:'exact_post_approval_required',publishReady:false,publishing:false};
  };
  const saveVerified=async(token,expected)=>{
    const next=await verifyIdentity(token.access_token,expected);
    next.expiresAt=new Date(now()+token.expires_in*1000).toISOString();
    await tokens.set('identity',{accessToken:token.access_token,refreshToken:token.refresh_token,expiresAt:next.expiresAt,scope:X_SCOPE});
    await control.set('identity',next);record=next;
  };
  const verifySaved=async()=>{
    if(!record)throw new Error('identity_missing');
    const saved=await tokens.get('identity');
    if(!saved||!opaque(saved.accessToken)||!opaque(saved.refreshToken)||!exactScope(saved.scope))throw new Error('token_missing');
    let token={access_token:saved.accessToken,refresh_token:saved.refreshToken,expires_in:Math.max(1,Math.floor((Date.parse(saved.expiresAt)-now())/1000)),scope:X_SCOPE,token_type:'bearer'};
    if(Date.parse(saved.expiresAt)<=now())token=await requestToken({grant_type:'refresh_token',refresh_token:saved.refreshToken,client_id:clientId});
    await saveVerified(token,record.username);
  };
  const server=http.createServer(async(req,res)=>{try{
    const host=req.headers.host;if(host!==`127.0.0.1:${port}`&&host!==`localhost:${port}`){json(res,403,{error:'invalid_host'});return;}
    const url=new URL(req.url,`http://127.0.0.1:${port}`);
    if(url.pathname==='/callback'&&req.method==='GET'){
      const nonce=cookie(req.headers.cookie,'studio_x_nonce'),allowed=new Set(['state','code','error','error_description']);
      if(!pending||pending.phase!=='private_handoff'||pending.expires<=now()||!nonce||!eq(digest(nonce),pending.browserHash)||[...url.searchParams.keys()].some(key=>!allowed.has(key)||url.searchParams.getAll(key).length!==1)||url.search.length>16384){json(res,400,{error:'callback_not_expected'});return;}
      const selected=pending;await persist({...selected,phase:'verifying',ticketHash:null,browserHash:null});let exchangeStarted=false;
      try{const code=url.searchParams.get('code');if(url.searchParams.get('error')||!eq(url.searchParams.get('state'),selected.flow)||!opaque(code))throw new Error('authorization_failed');exchangeStarted=true;const token=await requestToken({grant_type:'authorization_code',code,redirect_uri:X_REDIRECT_URI,client_id:clientId,code_verifier:selected.verifier});await saveVerified(token,selected.username);await persist({...selected,phase:'complete',ticketHash:null,browserHash:null,verifier:null});}
      catch{await persist({...selected,phase:exchangeStarted?'connection_unresolved':'connection_failed',ticketHash:null,browserHash:null,verifier:null});}
      redirect(res,`http://127.0.0.1:${studioPort}/connection-return`,'studio_x_nonce=; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=0');return;
    }
    if(url.pathname.startsWith('/begin/')&&req.method==='GET'){
      const ticket=url.pathname.slice(7);if(!pending||pending.phase!=='awaiting_private_signin'||pending.expires<=now()||!eq(digest(ticket),pending.ticketHash)){json(res,410,{error:'signin_expired'});return;}
      const nonce=randomBytes(32).toString('hex'),challenge=base64url(createHash('sha256').update(pending.verifier).digest()),authorize=new URL('https://x.com/i/oauth2/authorize');
      for(const [key,value] of Object.entries({response_type:'code',client_id:clientId,redirect_uri:X_REDIRECT_URI,scope:X_SCOPE,state:pending.flow,code_challenge:challenge,code_challenge_method:'S256'}))authorize.searchParams.set(key,value);
      await persist({...pending,phase:'private_handoff',ticketHash:null,browserHash:digest(nonce)});redirect(res,authorize.toString(),`studio_x_nonce=${nonce}; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=600`);return;
    }
    if(!eq(req.headers['x-studio-broker'],capability)){json(res,403,{error:'broker_access_denied'});return;}
    if(url.pathname==='/status'&&req.method==='GET'){json(res,200,status());return;}
    if(url.pathname==='/verify'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!configured){json(res,503,{error:'configuration_required'});return;}
      if(!record){json(res,409,{error:'identity_not_connected'});return;}
      if(verificationInProgress){json(res,409,{error:'verification_in_progress'});return;}
      verificationInProgress=true;try{await verifySaved();}catch{}finally{verificationInProgress=false;}json(res,200,status());return;
    }
    if(url.pathname==='/prepare'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!configured){json(res,503,{error:'configuration_required'});return;}
      let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>2048){json(res,413,{error:'request_too_large'});return;}}let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
      if(!body||Object.keys(body).sort().join(',')!=='scope,username'||body.scope!==X_SCOPE){json(res,422,{error:'invalid_request'});return;}
      const expected=username(body.username);if(!expected){json(res,422,{error:'invalid_identity'});return;}
      if(record&&!expired()){json(res,409,{error:'account_already_connected'});return;}
      if(pending&&pending.expires>now()&&!['connection_failed','complete'].includes(pending.phase)){json(res,409,{error:'signin_already_pending'});return;}
      const flow=randomBytes(32).toString('hex'),ticket=randomBytes(32).toString('hex'),verifier=base64url(randomBytes(48));await persist({username:expected,flow,verifier,expires:now()+TTL,phase:'awaiting_private_signin',ticketHash:digest(ticket)});json(res,200,{beginPath:`/begin/${ticket}`});return;
    }
    json(res,404,{error:'operation_unavailable'});
  }catch{if(!res.headersSent)json(res,500,{error:'connection_operation_failed'});else res.end();}});
  return {server,status};
}
