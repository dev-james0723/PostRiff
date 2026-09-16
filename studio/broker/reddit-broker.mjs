import http from 'node:http';
import {createHash,randomBytes,timingSafeEqual} from 'node:crypto';
import {privateStore} from './private-store.mjs';

export const REDDIT_SCOPE='identity';
export const REDDIT_REDIRECT_URI='http://127.0.0.1:4318/callback';
export const REDDIT_BROWSER_SCOPE='browser_identity_only';
export const REDDIT_BROWSER_SIGNALS=['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'];
export const REDDIT_BROWSER_ROUTE_SIGNALS=['identity_reverified','composer_loaded','community_selector_present','title_and_body_fields_present','semantic_post_control_present'];
const TTL=10*60*1000;
const USER_AGENT='mac:com.jamesau.studio:v0.5.0 (by /u/Ok-External401)';
const digest=value=>createHash('sha256').update(value).digest('hex');
const eq=(a,b)=>typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const username=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{3,20}$/.test(value)?value:null;
const opaque=value=>typeof value==='string'&&value.length>0&&value.length<=16384&&!/[\s\x00-\x1f]/.test(value);
const safeJson=async response=>{
  const chunks=[];let size=0;
  for await(const chunk of response.body){size+=chunk.length;if(size>1024*1024)throw new Error('response_too_large');chunks.push(Buffer.from(chunk));}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
};
const json=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer'});res.end(JSON.stringify(value));};
const redirect=(res,to,cookie)=>{res.writeHead(303,{Location:to,'Cache-Control':'no-store','Referrer-Policy':'no-referrer',...(cookie?{'Set-Cookie':cookie}:{})});res.end();};
const cookie=(header,name)=>typeof header==='string'?header.split(';').map(value=>value.trim()).find(value=>value.startsWith(name+'='))?.slice(name.length+1)??null:null;
const exactScope=value=>typeof value==='string'&&value.trim().split(/\s+/).filter(Boolean).length===1&&value.trim()===REDDIT_SCOPE;
const validateToken=token=>{
  if(!token||!opaque(token.access_token)||!exactScope(token.scope)||String(token.token_type).toLowerCase()!=='bearer'||!Number.isInteger(token.expires_in)||token.expires_in<=0||token.expires_in>3600)throw new Error('invalid_token');
};

export async function createRedditBroker({port,studioPort,root,capability,clientId,clientSecret,fetchApi=fetch,now=Date.now}){
  if(port!==4318||studioPort===port||!Number.isInteger(studioPort)||studioPort<1024||studioPort>65535||typeof capability!=='string'||capability.length<40)throw new Error('invalid_configuration');
  const configured=typeof clientId==='string'&&/^[A-Za-z0-9_-]{4,256}$/.test(clientId)&&typeof clientSecret==='string'&&clientSecret.length>=16;
  const store=await privateStore(root),control=store('reddit-control'),tokens=store('reddit-tokens');
  let record=await control.get('identity'),browserRecord=await control.get('browser_identity'),pending=await control.get('pending'),verificationInProgress=false;
  const persist=async value=>{pending=value;await control.set('pending',value);};
  const expired=()=>!record||Date.parse(record.expiresAt)<=now();
  const status=()=>{
    const base={provider:'reddit',available:configured,state:'configuration_required',username:null,accountId:null,profileUrl:null,scope:REDDIT_SCOPE,route:'official_api',routeDriver:'reddit_oauth',preferredPublishDrivers:['computer_use','chrome'],sessionState:'not_established',verifiedAt:null,expiresAt:null,identitySignals:[],routeState:'not_tested',routeTestId:null,routeTestedAt:null,routeTestSignals:[],publicationPolicy:'exact_post_approval_required',publishReady:false,publishing:false};
    if(browserRecord)return {...base,...browserRecord,available:true,state:'connected_browser_identity'};
    if(!configured)return base;
    if(pending?.phase==='connection_unresolved')return {...base,state:'connection_unresolved'};
    if(pending?.phase&&pending.phase!=='complete')return {...base,state:pending.phase};
    if(!record)return base;
    return {...base,...record,state:expired()?'needs_reauthorization':'connected_identity'};
  };
  const requestToken=async code=>{
    const basic=Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
    const response=await fetchApi('https://www.reddit.com/api/v1/access_token',{method:'POST',headers:{Authorization:`Basic ${basic}`,'Content-Type':'application/x-www-form-urlencoded','User-Agent':USER_AGENT,'Cache-Control':'no-store'},body:new URLSearchParams({grant_type:'authorization_code',code,redirect_uri:REDDIT_REDIRECT_URI})});
    if(!response.ok)throw new Error('token_exchange_failed');
    const token=await safeJson(response);validateToken(token);return token;
  };
  const verifyIdentity=async(token,expected)=>{
    const response=await fetchApi('https://oauth.reddit.com/api/v1/me',{headers:{Authorization:`Bearer ${token}`,'User-Agent':USER_AGENT,'Cache-Control':'no-store'}});
    if(!response.ok)throw new Error('identity_failed');
    const current=await safeJson(response),actual=username(current?.name),accountId=typeof current?.id==='string'&&/^t2_[A-Za-z0-9]+$/.test(current.id)?current.id:null;
    if(!actual||!accountId||actual.toLowerCase()!==expected.toLowerCase())throw new Error('identity_mismatch');
    return {username:actual,accountId,profileUrl:`https://www.reddit.com/user/${actual}/`,scope:REDDIT_SCOPE,route:'official_api',routeDriver:'reddit_oauth',preferredPublishDrivers:['computer_use','chrome'],sessionState:'oauth_token_active',verifiedAt:new Date(now()).toISOString(),expiresAt:null,identitySignals:['oauth_identity','stable_account_id_and_public_profile_match'],routeState:'not_tested',routeTestId:null,routeTestedAt:null,routeTestSignals:[],publicationPolicy:'exact_post_approval_required',publishReady:false,publishing:false};
  };
  const saveVerified=async(token,expected)=>{
    const next=await verifyIdentity(token.access_token,expected);
    next.expiresAt=new Date(now()+token.expires_in*1000).toISOString();
    await tokens.set('identity',{accessToken:token.access_token,expiresAt:next.expiresAt,scope:REDDIT_SCOPE});
    await control.set('identity',next);record=next;
  };
  const verifySaved=async()=>{
    if(!record||expired())throw new Error('identity_expired');
    const saved=await tokens.get('identity');
    if(!saved||!opaque(saved.accessToken)||!exactScope(saved.scope)||Date.parse(saved.expiresAt)<=now())throw new Error('token_missing');
    await saveVerified({access_token:saved.accessToken,expires_in:Math.max(1,Math.floor((Date.parse(saved.expiresAt)-now())/1000)),scope:REDDIT_SCOPE,token_type:'bearer'},record.username);
  };
  const server=http.createServer(async(req,res)=>{try{
    const host=req.headers.host;if(host!==`127.0.0.1:${port}`&&host!==`localhost:${port}`){json(res,403,{error:'invalid_host'});return;}
    const url=new URL(req.url,`http://127.0.0.1:${port}`);
    if(url.pathname==='/callback'&&req.method==='GET'){
      const nonce=cookie(req.headers.cookie,'studio_reddit_nonce'),allowed=new Set(['state','code','error','error_description']);
      if(!pending||pending.phase!=='private_handoff'||pending.expires<=now()||!nonce||!eq(digest(nonce),pending.browserHash)||[...url.searchParams.keys()].some(key=>!allowed.has(key)||url.searchParams.getAll(key).length!==1)||url.search.length>16384){json(res,400,{error:'callback_not_expected'});return;}
      const selected=pending;await persist({...selected,phase:'verifying',ticketHash:null,browserHash:null});let exchangeStarted=false;
      try{
        const code=url.searchParams.get('code');
        if(url.searchParams.get('error')||!eq(url.searchParams.get('state'),selected.flow)||!opaque(code))throw new Error('authorization_failed');
        exchangeStarted=true;const token=await requestToken(code);await saveVerified(token,selected.username);await persist({...selected,phase:'complete',ticketHash:null,browserHash:null});
      }catch{await persist({...selected,phase:exchangeStarted?'connection_unresolved':'connection_failed',ticketHash:null,browserHash:null});}
      redirect(res,`http://127.0.0.1:${studioPort}/connection-return`,'studio_reddit_nonce=; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=0');return;
    }
    if(url.pathname.startsWith('/begin/')&&req.method==='GET'){
      const ticket=url.pathname.slice(7);if(!pending||pending.phase!=='awaiting_private_signin'||pending.expires<=now()||!eq(digest(ticket),pending.ticketHash)){json(res,410,{error:'signin_expired'});return;}
      const nonce=randomBytes(32).toString('hex'),authorize=new URL('https://www.reddit.com/api/v1/authorize');
      for(const [key,value] of Object.entries({client_id:clientId,response_type:'code',state:pending.flow,redirect_uri:REDDIT_REDIRECT_URI,duration:'temporary',scope:REDDIT_SCOPE}))authorize.searchParams.set(key,value);
      await persist({...pending,phase:'private_handoff',ticketHash:null,browserHash:digest(nonce)});redirect(res,authorize.toString(),`studio_reddit_nonce=${nonce}; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=600`);return;
    }
    if(!eq(req.headers['x-studio-broker'],capability)){json(res,403,{error:'broker_access_denied'});return;}
    if(url.pathname==='/status'&&req.method==='GET'){json(res,200,status());return;}
    if(url.pathname==='/browser-connect'&&req.method==='POST'){
      let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>4096){json(res,413,{error:'request_too_large'});return;}}let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
      const expected={username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals:REDDIT_BROWSER_SIGNALS,route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome']};
      if(!body||Object.keys(body).sort().join(',')!==Object.keys(expected).sort().join(',')||Object.entries(expected).some(([key,value])=>Array.isArray(value)?!Array.isArray(body[key])||body[key].length!==value.length||value.some((item,index)=>body[key][index]!==item):body[key]!==value)){json(res,422,{error:'invalid_browser_identity'});return;}
      if(record||browserRecord){json(res,409,{error:'account_already_connected'});return;}
      browserRecord={username:expected.username,accountId:null,profileUrl:expected.profileUrl,scope:REDDIT_BROWSER_SCOPE,route:expected.route,routeDriver:expected.routeDriver,preferredPublishDrivers:expected.preferredPublishDrivers,sessionState:'verify_before_each_action',verifiedAt:new Date(now()).toISOString(),expiresAt:null,identitySignals:expected.identitySignals,routeState:'not_tested',routeTestId:null,routeTestedAt:null,routeTestSignals:[],publicationPolicy:'exact_post_approval_required',publishReady:false,publishing:false};
      await control.set('browser_identity',browserRecord);json(res,200,status());return;
    }
    if(url.pathname==='/enable-browser-publishing'&&req.method==='POST'){
      let raw='';for await(const chunk of req){raw+=chunk;if(raw.length>4096){json(res,413,{error:'request_too_large'});return;}}let body;try{body=JSON.parse(raw);}catch{json(res,422,{error:'invalid_request'});return;}
      const expected={username:'Ok-External401',identitySignals:REDDIT_BROWSER_SIGNALS,route:'controlled_browser',routeDriver:'in_app_browser',routeTestSignals:REDDIT_BROWSER_ROUTE_SIGNALS,publicationPolicy:'exact_post_approval_required',userAuthorization:true};
      if(!body||Object.keys(body).sort().join(',')!==Object.keys(expected).sort().join(',')||Object.entries(expected).some(([key,value])=>Array.isArray(value)?!Array.isArray(body[key])||body[key].length!==value.length||value.some((item,index)=>body[key][index]!==item):body[key]!==value)){json(res,422,{error:'invalid_route_test'});return;}
      if(!browserRecord||browserRecord.username!==expected.username||browserRecord.route!==expected.route||browserRecord.routeDriver!==expected.routeDriver||browserRecord.identitySignals?.join('\n')!==expected.identitySignals.join('\n')){json(res,409,{error:'browser_identity_required'});return;}
      browserRecord={...browserRecord,verifiedAt:new Date(now()).toISOString(),routeState:'browser_publish_ready',routeTestId:`reddit-browser-${randomBytes(16).toString('hex')}`,routeTestedAt:new Date(now()).toISOString(),routeTestSignals:expected.routeTestSignals,publicationPolicy:expected.publicationPolicy,publishReady:true,publishing:false};
      await control.set('browser_identity',browserRecord);json(res,200,status());return;
    }
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
      if(!body||Object.keys(body).sort().join(',')!=='scope,username'||body.scope!==REDDIT_SCOPE){json(res,422,{error:'invalid_request'});return;}
      const expected=username(body.username);if(!expected){json(res,422,{error:'invalid_identity'});return;}
      if(record&&!expired()){json(res,409,{error:'account_already_connected'});return;}
      if(pending&&pending.expires>now()&&!['connection_failed','complete'].includes(pending.phase)){json(res,409,{error:'signin_already_pending'});return;}
      const flow=randomBytes(32).toString('hex'),ticket=randomBytes(32).toString('hex');await persist({username:expected,flow,expires:now()+TTL,phase:'awaiting_private_signin',ticketHash:digest(ticket)});json(res,200,{beginPath:`/begin/${ticket}`});return;
    }
    json(res,404,{error:'operation_unavailable'});
  }catch{if(!res.headersSent)json(res,500,{error:'connection_operation_failed'});else res.end();}});
  return {server,status};
}
