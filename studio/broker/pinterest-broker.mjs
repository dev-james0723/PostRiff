import http from 'node:http';
import {createHash,randomBytes,timingSafeEqual} from 'node:crypto';
import {privateStore} from './private-store.mjs';

export const PINTEREST_SCOPE='user_accounts:read,boards:read,boards:write,boards:read_secret,boards:write_secret,pins:read,pins:write,pins:read_secret,pins:write_secret,ads:read,ads:write,billing:read,billing:write';
const REDIRECT_URI='http://127.0.0.1:4317/callback';
const TTL=10*60*1000;
const digest=value=>createHash('sha256').update(value).digest('hex');
const eq=(a,b)=>typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const username=value=>typeof value==='string'&&/^[a-z0-9_]{1,30}$/i.test(value)?value.toLowerCase():null;
const opaque=value=>typeof value==='string'&&value.length>0&&value.length<=16384&&!/[\s\x00-\x1f]/.test(value);
const scopeSet=value=>typeof value==='string'?value.split(/[ ,]+/).filter(Boolean):[];
const safeJson=async response=>{
  const chunks=[];let size=0;
  for await(const chunk of response.body){size+=chunk.length;if(size>1024*1024)throw new Error('response_too_large');chunks.push(Buffer.from(chunk));}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
};
const json=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
const redirect=(res,to,cookie)=>{res.writeHead(303,{Location:to,'Cache-Control':'no-store',...(cookie?{'Set-Cookie':cookie}:{})});res.end();};
const cookie=(header,name)=>typeof header==='string'?header.split(';').map(v=>v.trim()).find(v=>v.startsWith(name+'='))?.slice(name.length+1)??null:null;
const exactScopes=value=>{const actual=scopeSet(value),expected=scopeSet(PINTEREST_SCOPE),set=new Set(actual);return actual.length===expected.length&&set.size===expected.length&&expected.every(scope=>set.has(scope));};
const validateToken=token=>{
  if(!token||!exactScopes(token.scope)||!opaque(token.access_token)||!opaque(token.refresh_token)||String(token.token_type).toLowerCase()!=='bearer'||!Number.isInteger(token.expires_in)||token.expires_in<=0||token.expires_in>2592000)throw new Error('invalid_token');
};

export async function createPinterestBroker({port,studioPort,root,capability,clientId,clientSecret,fetchApi=fetch,now=Date.now}){
  if(port!==4317||studioPort===port||!Number.isInteger(studioPort)||studioPort<1024||studioPort>65535||typeof capability!=='string'||capability.length<40)throw new Error('invalid_configuration');
  const configured=typeof clientId==='string'&&/^[A-Za-z0-9_-]{4,256}$/.test(clientId)&&typeof clientSecret==='string'&&clientSecret.length>=16;
  const store=await privateStore(root),control=store('pinterest-control'),tokens=store('pinterest-tokens');
  let record=await control.get('identity'),browserRecord=await control.get('browser_identity'),pending=await control.get('pending'),verifiedThisRun=false,verificationInProgress=false;
  const persist=async value=>{pending=value;await control.set('pending',value);};
  const status=()=>{
    const base={provider:'pinterest',available:configured,state:'configuration_required',username:null,accountId:null,accountType:null,scope:PINTEREST_SCOPE,routeDriver:'official_api_oauth',verifiedAt:null,expiresAt:null,identitySignals:[],publishReady:false,publishing:false};
    if(browserRecord)return {...base,...browserRecord,available:true,state:'connected_browser_identity'};
    if(!configured)return base;
    if(pending?.phase==='connection_unresolved')return {...base,state:'connection_unresolved'};
    if(pending?.phase&&pending.phase!=='complete')return {...base,state:pending.phase};
    if(!record)return base;
    if(!verifiedThisRun||Date.parse(record.expiresAt)<=now())return {...base,...record,state:'verification_required'};
    return {...base,...record,state:'connected_identity'};
  };
  const requestToken=async body=>{
    const basic=Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
    const response=await fetchApi('https://api.pinterest.com/v5/oauth/token',{method:'POST',headers:{Authorization:`Basic ${basic}`,'Content-Type':'application/x-www-form-urlencoded','Cache-Control':'no-store'},body:new URLSearchParams(body)});
    if(!response.ok)throw new Error('token_exchange_failed');
    const token=await safeJson(response);validateToken(token);return token;
  };
  const identity=async(token,expected)=>{
    const response=await fetchApi('https://api.pinterest.com/v5/user_account',{headers:{Authorization:`Bearer ${token}`,'Cache-Control':'no-store'}});
    if(!response.ok)throw new Error('identity_failed');
    const user=await safeJson(response),actual=username(user?.username),id=typeof user?.id==='string'&&user.id.length<=256?user.id:null;
    if(!actual||actual!==expected||!id)throw new Error('identity_mismatch');
    return {username:actual,accountId:id,accountType:typeof user.account_type==='string'&&user.account_type.length<=64?user.account_type:null,scope:PINTEREST_SCOPE,verifiedAt:new Date(now()).toISOString(),expiresAt:null,identitySignals:['oauth_token','independent_user_account_username'],publishReady:false,publishing:false};
  };
  const saveVerified=async(token,expected)=>{
    const next=await identity(token.access_token,expected);
    next.expiresAt=new Date(now()+token.expires_in*1000).toISOString();
    await tokens.set('identity',{accessToken:token.access_token,refreshToken:token.refresh_token,expiresAt:next.expiresAt,scope:PINTEREST_SCOPE});
    await control.set('identity',next);record=next;verifiedThisRun=true;
  };
  const verifySaved=async()=>{
    if(!record)throw new Error('identity_not_connected');
    let saved=await tokens.get('identity');if(!saved||!opaque(saved.accessToken)||!opaque(saved.refreshToken)||!exactScopes(saved.scope))throw new Error('token_missing');
    if(Date.parse(saved.expiresAt)<=now())saved=await requestToken({grant_type:'refresh_token',refresh_token:saved.refreshToken,scope:PINTEREST_SCOPE});
    await saveVerified(saved,record.username);
  };
  const server=http.createServer(async(req,res)=>{try{
    const host=req.headers.host;if(host!==`127.0.0.1:${port}`&&host!==`localhost:${port}`){json(res,403,{error:'invalid_host'});return;}
    const url=new URL(req.url,`http://127.0.0.1:${port}`);
    if(url.pathname==='/callback'&&req.method==='GET'){
      const nonce=cookie(req.headers.cookie,'studio_pinterest_nonce'),allowed=new Set(['state','code','error','error_description']);
      if(!pending||pending.phase!=='private_handoff'||pending.expires<=now()||!nonce||!eq(digest(nonce),pending.browserHash)||[...url.searchParams.keys()].some(k=>!allowed.has(k)||url.searchParams.getAll(k).length!==1)||url.search.length>16384){json(res,400,{error:'callback_not_expected'});return;}
      const selected=pending;await persist({...selected,phase:'verifying',ticketHash:null,browserHash:null});let exchangeStarted=false;
      try{
        if(url.searchParams.get('error')||!eq(url.searchParams.get('state'),selected.flow)||!opaque(url.searchParams.get('code')))throw new Error('authorization_failed');
        exchangeStarted=true;const token=await requestToken({grant_type:'authorization_code',code:url.searchParams.get('code'),redirect_uri:REDIRECT_URI});await saveVerified(token,selected.username);await persist({...selected,phase:'complete',ticketHash:null,browserHash:null});
      }catch{verifiedThisRun=false;await persist({...selected,phase:exchangeStarted?'connection_unresolved':'connection_failed',ticketHash:null,browserHash:null});}
      redirect(res,`http://127.0.0.1:${studioPort}/connection-return`,'studio_pinterest_nonce=; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=0');return;
    }
    if(url.pathname.startsWith('/begin/')&&req.method==='GET'){
      const ticket=url.pathname.slice(7);if(!pending||pending.phase!=='awaiting_private_signin'||pending.expires<=now()||!eq(digest(ticket),pending.ticketHash)){json(res,410,{error:'signin_expired'});return;}
      const nonce=randomBytes(32).toString('hex'),authorize=new URL('https://www.pinterest.com/oauth/');
      for(const [key,value] of Object.entries({client_id:clientId,redirect_uri:REDIRECT_URI,response_type:'code',scope:PINTEREST_SCOPE,state:pending.flow}))authorize.searchParams.set(key,value);
      await persist({...pending,phase:'private_handoff',ticketHash:null,browserHash:digest(nonce)});redirect(res,authorize.toString(),`studio_pinterest_nonce=${nonce}; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=600`);return;
    }
    if(!eq(req.headers['x-studio-broker'],capability)){json(res,403,{error:'broker_access_denied'});return;}
    if(url.pathname==='/status'&&req.method==='GET'){json(res,200,status());return;}
    if(url.pathname==='/browser-connect'&&req.method==='POST'){
      let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>2048){json(res,413,{error:'request_too_large'});return;}}let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
      const signals=['business_hub_name_and_handle','public_profile_name_and_handle'];
      if(!body||Object.keys(body).sort().join(',')!=='identitySignals,username'||body.username!=='jamesaucreates'||!Array.isArray(body.identitySignals)||body.identitySignals.length!==signals.length||signals.some((signal,index)=>body.identitySignals[index]!==signal)){json(res,422,{error:'invalid_browser_identity'});return;}
      if(record||browserRecord){json(res,409,{error:'account_already_connected'});return;}
      browserRecord={username:'jamesaucreates',accountId:null,accountType:'BUSINESS_BROWSER_VERIFIED',scope:'controlled_browser_session',routeDriver:'controlled_browser',verifiedAt:new Date(now()).toISOString(),expiresAt:null,identitySignals:signals,publishReady:false,publishing:false};await control.set('browser_identity',browserRecord);json(res,200,status());return;
    }
    if(url.pathname==='/verify'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!configured){json(res,503,{error:'configuration_required'});return;}
      if(!record){json(res,409,{error:'identity_not_connected'});return;}
      if(verificationInProgress){json(res,409,{error:'verification_in_progress'});return;}
      verificationInProgress=true;verifiedThisRun=false;try{await verifySaved();}catch{verifiedThisRun=false;}finally{verificationInProgress=false;}json(res,200,status());return;
    }
    if(url.pathname==='/prepare'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!configured){json(res,503,{error:'configuration_required'});return;}
      let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>2048){json(res,413,{error:'request_too_large'});return;}}let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
      if(!body||Object.keys(body).sort().join(',')!=='scope,username'||body.scope!==PINTEREST_SCOPE){json(res,422,{error:'invalid_request'});return;}
      const expected=username(body.username);if(!expected){json(res,422,{error:'invalid_identity'});return;}
      if(record){json(res,409,{error:'account_already_connected'});return;}
      if(pending&&pending.expires>now()&&!['connection_failed','interrupted','complete'].includes(pending.phase)){json(res,409,{error:'signin_already_pending'});return;}
      const flow=randomBytes(32).toString('hex'),ticket=randomBytes(32).toString('hex');await persist({username:expected,flow,expires:now()+TTL,phase:'awaiting_private_signin',ticketHash:digest(ticket)});json(res,200,{beginPath:`/begin/${ticket}`});return;
    }
    json(res,404,{error:'operation_unavailable'});
  }catch{if(!res.headersSent)json(res,500,{error:'connection_operation_failed'});else res.end();}});
  return {server,status};
}
