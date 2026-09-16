import https from 'node:https';
import fs from 'node:fs';
import {randomBytes,timingSafeEqual,createHash} from 'node:crypto';
import {privateStore} from './private-store.mjs';

export const THREADS_SCOPE='threads_basic,threads_content_publish';
export const THREADS_HOST='threads-jamesau.meta';
export const THREADS_ROUTE='official_api';
export const THREADS_ROUTE_DRIVER='threads_graph_api';
export const THREADS_PUBLICATION_POLICY='exact_post_approval_required';
const TTL=10*60*1000;
const MAX_TEXT=500;
const ROUTE_SIGNALS=['identity_reverified','publishing_quota_read'];
const digest=value=>createHash('sha256').update(value).digest('hex');
const stable=value=>JSON.stringify(value,Object.keys(value).sort());
const eq=(a,b)=>typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const username=value=>typeof value==='string'&&/^[a-z0-9._]{1,30}$/i.test(value)?value.toLowerCase():null;
const accessTokenOk=token=>typeof token?.access_token==='string'&&token.access_token.length>20&&token.access_token.length<16384&&!/[\s\x00-\x1f]/.test(token.access_token);
export const threadsShortTokenOk=token=>accessTokenOk(token)&&(typeof token.user_id==='string'||typeof token.user_id==='number')&&/^\d{1,30}$/.test(String(token.user_id));
export const threadsLongTokenOk=token=>accessTokenOk(token)&&Number.isFinite(token.expires_in)&&token.expires_in>0&&token.expires_in<=90*24*60*60;
export const threadsPublishManifest=value=>({
  account:value?.account,destination:value?.destination,nativeFormat:value?.nativeFormat,
  mediaType:value?.mediaType,text:value?.text,visibility:value?.visibility,
  replyControl:value?.replyControl,scheduledAt:value?.scheduledAt,
  media:value?.media,derivatives:value?.derivatives,
});
export const threadsPublishHash=value=>digest(stable(threadsPublishManifest(value)));
export const threadsIdempotencyKey=value=>digest('threads.publish\0'+threadsPublishHash(value));

async function safeJson(response){
  const chunks=[];let size=0;
  for await(const chunk of response.body){size+=chunk.length;if(size>1024*1024)throw new Error('response_too_large');chunks.push(Buffer.from(chunk));}
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
async function readBody(req,limit=8192){
  let raw='';
  for await(const chunk of req){raw+=chunk;if(Buffer.byteLength(raw)>limit)throw new Error('request_too_large');}
  return JSON.parse(raw||'{}');
}
function validManifest(body){
  const expected=['account','approvalReceiptHash','derivatives','destination','idempotencyKey','media','mediaType','nativeFormat','replyControl','scheduledAt','text','visibility'];
  return body&&typeof body==='object'&&!Array.isArray(body)
    &&Object.keys(body).sort().join(',')===expected.join(',')
    &&body.account==='@jamesaucreates'&&body.destination==='main_profile_feed'
    &&body.nativeFormat==='threads.post'&&body.mediaType==='TEXT'
    &&typeof body.text==='string'&&body.text.length>0&&body.text.length<=MAX_TEXT
    &&body.text.trim()===body.text&&!/[\x00]/.test(body.text)
    &&body.visibility==='public'&&body.replyControl==='provider_default'
    &&body.scheduledAt===null&&Array.isArray(body.media)&&body.media.length===0
    &&Array.isArray(body.derivatives)&&body.derivatives.length===0
    &&/^[a-f0-9]{64}$/.test(body.approvalReceiptHash||'')
    &&/^[a-f0-9]{64}$/.test(body.idempotencyKey||'')
    &&eq(body.approvalReceiptHash,threadsPublishHash(body))
    &&eq(body.idempotencyKey,threadsIdempotencyKey(body));
}

export async function createThreadsBroker({port,studioPort,root,capability,clientId,clientSecret,certificatePath,privateKeyPath,fetchApi=fetch,now=Date.now}){
  if(!Number.isInteger(port)||port<1024||port>65535||!Number.isInteger(studioPort)||studioPort<1024||studioPort>65535||port===studioPort||typeof capability!=='string'||capability.length<40)throw new Error('invalid_configuration');
  const origin=`https://${THREADS_HOST}:${port}`;
  const configured=typeof clientId==='string'&&/^\d{5,30}$/.test(clientId)&&typeof clientSecret==='string'&&clientSecret.length>=16;
  let tls=null;try{if(typeof certificatePath==='string'&&typeof privateKeyPath==='string')tls={cert:fs.readFileSync(certificatePath),key:fs.readFileSync(privateKeyPath)};}catch{tls=null;}
  const available=configured&&!!tls;
  const store=await privateStore(root),control=store('threads-control'),tokens=store('threads-tokens'),attempts=store('threads-publish-attempts');
  let pending=await control.get('pending'),record=await control.get('identity'),routeRecord=await control.get('route');
  if(pending?.phase==='verifying'){pending={...pending,phase:'connection_unresolved'};await control.set('pending',pending);}
  let verifiedThisRun=false,verificationInProgress=false,publishing=false;
  const generation=()=>record?digest(stable({expiresAt:record.expiresAt,scope:record.scope,userId:record.userId,username:record.username})):null;
  const identityCurrent=()=>available&&pending?.phase!=='connection_unresolved'&&verifiedThisRun&&record&&Date.parse(record.expiresAt)>now();
  const routeCurrent=()=>identityCurrent()&&routeRecord?.authGeneration===generation()&&routeRecord?.state==='publish_ready';
  const status=()=>({
    provider:'threads',available,
    state:pending?.phase==='connection_unresolved'?'connection_unresolved':record?(identityCurrent()?'connected_identity':'verification_required'):(available&&pending&&pending.expires>now()?pending.phase:(available?'not_connected':'configuration_required')),
    username:record?.username||pending?.username||null,userId:record?.userId||null,scope:THREADS_SCOPE,
    route:THREADS_ROUTE,routeDriver:THREADS_ROUTE_DRIVER,verifiedAt:record?.verifiedAt||null,expiresAt:record?.expiresAt||null,
    identitySignals:identityCurrent()?['threads_authenticated_user_id','threads_authenticated_username']:[],
    routeState:routeCurrent()?'publish_ready':'not_tested',routeTestId:routeCurrent()?routeRecord.routeTestId:null,
    routeTestedAt:routeCurrent()?routeRecord.testedAt:null,routeTestSignals:routeCurrent()?ROUTE_SIGNALS:[],
    publicationPolicy:THREADS_PUBLICATION_POLICY,publishReady:routeCurrent(),publishing,
  });
  const headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'"};
  const json=(res,code,body)=>{res.writeHead(code,{...headers,'Content-Type':'application/json'});res.end(JSON.stringify(body));};
  const redirect=(res,url,cookie)=>{res.writeHead(303,{...headers,Location:url,...(cookie?{'Set-Cookie':cookie}:{})});res.end();};
  const persist=async value=>{pending=value;await control.set('pending',value);};
  const api=async(url,options={})=>{
    const response=await fetchApi(url,{redirect:'error',signal:AbortSignal.timeout(30000),...options});
    const value=await safeJson(response);
    if(!response.ok)throw new Error('threads_api_failed');
    return value;
  };
  const identity=async(accessToken,expected)=>{
    const url=new URL('https://graph.threads.com/me');url.searchParams.set('fields','id,username');url.searchParams.set('access_token',accessToken);
    const value=await api(url),actual=username(value?.username),userId=typeof value?.id==='string'||typeof value?.id==='number'?String(value.id):null;
    if(actual!==expected.username||!userId||(expected.userId&&userId!==expected.userId))throw new Error('identity_mismatch');
    return {username:actual,userId,scope:THREADS_SCOPE,verifiedAt:new Date(now()).toISOString()};
  };
  const exchange=async code=>{
    const form=new URLSearchParams({client_id:clientId,client_secret:clientSecret,grant_type:'authorization_code',redirect_uri:origin+'/callback',code});
    const token=await api('https://graph.threads.com/oauth/access_token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:form});
    if(!threadsShortTokenOk(token))throw new Error('invalid_short_token');return token;
  };
  const extend=async accessToken=>{
    const url=new URL('https://graph.threads.com/access_token');url.searchParams.set('grant_type','th_exchange_token');url.searchParams.set('client_secret',clientSecret);url.searchParams.set('access_token',accessToken);
    const token=await api(url);if(!threadsLongTokenOk(token))throw new Error('invalid_long_token');return token;
  };
  const savedToken=async()=>{
    const saved=await tokens.get('identity');
    if(!saved?.accessToken||Date.parse(saved.expiresAt)<=now())throw new Error('reauthorization_required');
    return saved;
  };
  const verifySaved=async()=>{
    if(!record)throw new Error('identity_not_connected');
    let saved=await savedToken();
    if(Date.parse(saved.expiresAt)-now()<=7*24*60*60*1000){
      const url=new URL('https://graph.threads.com/refresh_access_token');url.searchParams.set('grant_type','th_refresh_token');url.searchParams.set('access_token',saved.accessToken);
      const refreshed=await api(url);
      if(!threadsLongTokenOk(refreshed))throw new Error('invalid_refreshed_token');
      saved={accessToken:refreshed.access_token,expiresAt:new Date(now()+refreshed.expires_in*1000).toISOString(),scope:THREADS_SCOPE};
      await tokens.set('identity',saved);
    }
    const next=await identity(saved.accessToken,record);next.expiresAt=saved.expiresAt;
    await control.set('identity',next);record=next;verifiedThisRun=true;return saved;
  };
  const publishingQuota=async accessToken=>{
    const url=new URL('https://graph.threads.com/me/threads_publishing_limit');url.searchParams.set('fields','quota_usage,config');url.searchParams.set('access_token',accessToken);
    const value=await api(url),row=value?.data?.[0],usage=row?.quota_usage,total=row?.config?.quota_total,duration=row?.config?.quota_duration;
    if(!Number.isInteger(usage)||usage<0||!Number.isInteger(total)||total<1||usage>total||!Number.isInteger(duration)||duration<1)throw new Error('publishing_quota_unavailable');
    return {usage,total,duration};
  };
  const postEvidence=async(accessToken,postId)=>{
    const url=new URL(`https://graph.threads.com/${postId}`);
    url.searchParams.set('fields','id,text,media_product_type,media_type,permalink,owner,username,timestamp');
    url.searchParams.set('access_token',accessToken);return api(url);
  };
  const verifiedPost=(value,manifest)=>{
    const postId=typeof value?.id==='string'?value.id:null,permalink=typeof value?.permalink==='string'?value.permalink:null;
    const timestamp=typeof value?.timestamp==='string'&&!Number.isNaN(Date.parse(value.timestamp))?value.timestamp:null;
    if(!postId||value.text!==manifest.text||username(value.username)!==record.username||String(value?.owner?.id)!==record.userId
      ||value.media_product_type!=='THREADS'||value.media_type!=='TEXT_POST'||!timestamp
      ||!/^https:\/\/(www\.)?threads\.(com|net)\//.test(permalink||''))throw new Error('publication_unverified');
    return {threadId:postId,url:permalink,username:record.username,text:value.text,mediaType:value.media_type,timestamp};
  };
  const reconcile=async(accessToken,attempt,manifest)=>{
    if(attempt.threadId){
      try{return verifiedPost(await postEvidence(accessToken,attempt.threadId),manifest);}catch{}
    }
    const url=new URL('https://graph.threads.com/me/threads');
    url.searchParams.set('fields','id,text,media_product_type,media_type,permalink,owner,username,timestamp');
    url.searchParams.set('limit','10');url.searchParams.set('access_token',accessToken);
    const value=await api(url);
    const candidates=(Array.isArray(value?.data)?value.data:[]).filter(item=>item?.text===manifest.text&&username(item?.username)===record.username&&String(item?.owner?.id)===record.userId&&Date.parse(item?.timestamp)>=attempt.startedAtMs-120000);
    if(candidates.length!==1)throw new Error('publication_unresolved');
    return verifiedPost(candidates[0],manifest);
  };
  const server=https.createServer(tls||{},async(req,res)=>{try{
    if(req.headers.host!==`${THREADS_HOST}:${port}`){json(res,403,{error:'host_not_allowed'});return;}
    const url=new URL(req.url,origin);
    if(url.pathname==='/callback'&&req.method==='GET'){
      const cookie=(req.headers.cookie||'').split(';').map(v=>v.trim()).find(v=>v.startsWith('studio_threads_nonce='))?.slice(21),allowed=new Set(['code','state','error','error_reason','error_description']);
      if(!pending||pending.phase!=='private_handoff'||pending.expires<=now()||!cookie||!eq(digest(cookie),pending.browserHash)||[...url.searchParams.keys()].some(k=>!allowed.has(k)||url.searchParams.getAll(k).length!==1)||url.search.length>16384){json(res,400,{error:'callback_not_expected'});return;}
      const selected=pending;await persist({...selected,phase:'verifying',ticketHash:null,browserHash:null});let exchangeStarted=false;
      try{
        if(url.searchParams.get('error')||!eq(url.searchParams.get('state'),selected.flow))throw new Error('authorization_failed');
        exchangeStarted=true;const short=await exchange(url.searchParams.get('code')||''),long=await extend(short.access_token);
        const next=await identity(long.access_token,{...selected,userId:String(short.user_id)});next.expiresAt=new Date(now()+long.expires_in*1000).toISOString();
        await tokens.set('identity',{accessToken:long.access_token,expiresAt:next.expiresAt,scope:THREADS_SCOPE});await control.set('identity',next);
        record=next;routeRecord=null;await control.del('route');verifiedThisRun=true;await persist({...selected,phase:'complete',ticketHash:null,browserHash:null});
      }catch{verifiedThisRun=false;await persist({...selected,phase:exchangeStarted?'connection_unresolved':'connection_failed',ticketHash:null,browserHash:null});}
      redirect(res,`http://127.0.0.1:${studioPort}/connection-return`,'studio_threads_nonce=; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=0');return;
    }
    if(url.pathname.startsWith('/begin/')&&req.method==='GET'){
      const ticket=url.pathname.slice(7);
      if(!pending||pending.phase!=='awaiting_private_signin'||pending.expires<=now()||!eq(digest(ticket),pending.ticketHash)){json(res,410,{error:'signin_expired'});return;}
      const nonce=randomBytes(32).toString('hex'),authorize=new URL('https://www.threads.com/oauth/authorize');
      for(const [key,value] of Object.entries({client_id:clientId,redirect_uri:origin+'/callback',response_type:'code',scope:THREADS_SCOPE,state:pending.flow}))authorize.searchParams.set(key,value);
      await persist({...pending,phase:'private_handoff',ticketHash:null,browserHash:digest(nonce)});
      redirect(res,authorize.toString(),`studio_threads_nonce=${nonce}; HttpOnly; SameSite=Lax; Path=/callback; Max-Age=600`);return;
    }
    if(!eq(req.headers['x-studio-broker'],capability)){json(res,403,{error:'broker_access_denied'});return;}
    if(url.pathname==='/status'&&req.method==='GET'){json(res,200,status());return;}
    if(url.pathname==='/verify'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}
      if(!available){json(res,503,{error:'configuration_required'});return;}if(!record){json(res,409,{error:'identity_not_connected'});return;}
      if(verificationInProgress){json(res,409,{error:'verification_in_progress'});return;}
      verificationInProgress=true;verifiedThisRun=false;try{await verifySaved();}catch{verifiedThisRun=false;}finally{verificationInProgress=false;}
      json(res,200,status());return;
    }
    if(url.pathname==='/route-test'&&req.method==='POST'){
      const body=await readBody(req);
      if(Object.keys(body).sort().join(',')!=='account,destination,mediaType,nativeFormat,route,routeDriver'
        ||body.account!=='@jamesaucreates'||body.destination!=='main_profile_feed'||body.nativeFormat!=='threads.post'
        ||body.mediaType!=='TEXT'||body.route!==THREADS_ROUTE||body.routeDriver!==THREADS_ROUTE_DRIVER){json(res,422,{error:'invalid_route_test_manifest'});return;}
      verifiedThisRun=false;const saved=await verifySaved(),quota=await publishingQuota(saved.accessToken);
      routeRecord={state:'publish_ready',routeTestId:'threads-'+randomBytes(20).toString('hex'),testedAt:new Date(now()).toISOString(),signals:ROUTE_SIGNALS,authGeneration:generation(),quota};
      await control.set('route',routeRecord);json(res,200,status());return;
    }
    if(url.pathname==='/publish-text'&&req.method==='POST'){
      const body=await readBody(req,16384);if(!validManifest(body)){json(res,422,{error:'invalid_publish_manifest'});return;}
      if(!routeCurrent()){json(res,409,{error:'publish_route_not_ready'});return;}
      const manifest=threadsPublishManifest(body),key=body.idempotencyKey;let attempt=await attempts.get(key);
      const saved=await savedToken();
      if(attempt){
        if(attempt.payloadHash!==body.approvalReceiptHash){json(res,409,{error:'idempotency_conflict'});return;}
        if(attempt.state==='verified'){json(res,200,{...attempt.result,replayed:true});return;}
        try{
          const result=await reconcile(saved.accessToken,attempt,manifest);
          attempt={...attempt,state:'verified',result,verifiedAt:new Date(now()).toISOString()};await attempts.set(key,attempt);
          json(res,200,{...result,verifiedAt:attempt.verifiedAt,replayed:true});return;
        }catch{json(res,409,{error:'threads_publish_unresolved'});return;}
      }
      publishing=true;
      attempt={state:'reserved',payloadHash:body.approvalReceiptHash,startedAtMs:now(),startedAt:new Date(now()).toISOString(),threadId:null};
      await attempts.set(key,attempt);
      try{
        const form=new URLSearchParams({media_type:'TEXT',text:manifest.text,auto_publish_text:'true',access_token:saved.accessToken});
        const created=await api('https://graph.threads.com/me/threads',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:form});
        const threadId=typeof created?.id==='string'?created.id:null;if(!threadId)throw new Error('publication_unresolved');
        attempt={...attempt,state:'submitted',threadId};await attempts.set(key,attempt);
        const result=verifiedPost(await postEvidence(saved.accessToken,threadId),manifest);
        const verifiedAt=new Date(now()).toISOString();attempt={...attempt,state:'verified',result,verifiedAt};await attempts.set(key,attempt);
        json(res,200,{...result,verifiedAt,replayed:false});
      }catch{
        attempt={...attempt,state:attempt.threadId?'submitted':'uncertain'};await attempts.set(key,attempt);
        json(res,409,{error:'threads_publish_unresolved'});
      }finally{publishing=false;}
      return;
    }
    if(url.pathname==='/prepare'&&req.method==='POST'){
      if(pending?.phase==='connection_unresolved'){json(res,409,{error:'reconciliation_required'});return;}if(!available){json(res,503,{error:'configuration_required'});return;}
      const body=await readBody(req,2048);
      if(!body||Object.keys(body).sort().join(',')!=='scope,username'||body.scope!==THREADS_SCOPE){json(res,422,{error:'invalid_request'});return;}
      const expected=username(body.username);if(!expected){json(res,422,{error:'invalid_identity'});return;}if(record){json(res,409,{error:'account_already_connected'});return;}
      if(pending&&pending.expires>now()&&!['connection_failed','interrupted','complete'].includes(pending.phase)){json(res,409,{error:'signin_already_pending'});return;}
      const flow=randomBytes(32).toString('hex'),ticket=randomBytes(32).toString('hex');
      await persist({username:expected,flow,expires:now()+TTL,phase:'awaiting_private_signin',ticketHash:digest(ticket)});
      json(res,200,{beginPath:`/begin/${ticket}`});return;
    }
    json(res,404,{error:'operation_unavailable'});
  }catch(error){
    const code=error?.message==='request_too_large'?413:500;
    if(!res.headersSent)json(res,code,{error:code===413?'request_too_large':'connection_operation_failed'});else res.end();
  }});
  return {server,status};
}
