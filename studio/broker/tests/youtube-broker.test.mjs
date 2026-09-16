import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {createYouTubeBroker,YOUTUBE_SCOPE} from '../youtube-broker.mjs';
const identity={email:'jamesaucreates@gmail.com',channelId:'UCzwNcXaG4EdjR27Tm9JH_zA',scope:YOUTUBE_SCOPE};
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
async function fixture(t,options={}){
 const root=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'youtube-broker-')));
 t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const port=await freePort(),capability='a'.repeat(64),calls=[];
 let clock=Date.now();
 const token={access_token:'SYNTHETIC-ACCESS',refresh_token:'SYNTHETIC-REFRESH',token_type:'Bearer',expires_in:3600,scope:YOUTUBE_SCOPE,...options.token};
 const user={sub:'synthetic-subject',email:identity.email,email_verified:true,...options.user};
 const channels={items:[{id:identity.channelId,snippet:{title:'James Au',customUrl:'@jamesaucreates'}}],...options.channels};
 const fetchApi=async(url,init)=>{
  calls.push({url:String(url),method:init.method||'GET',body:init.body});
  if(options.fail)throw new Error('SYNTHETIC-PRIVATE-ERROR');
  if(String(url).includes('/token'))return Response.json(token);
  if(String(url).includes('userinfo'))return Response.json(user);
  return Response.json(channels);
 };
 const config={root,port,studioPort:4310,capability,clientId:options.configured===false?null:'fixture.apps.googleusercontent.com',clientSecret:options.configured===false?null:'x'.repeat(20),fetchApi,now:()=>clock};
 const broker=await createYouTubeBroker(config);
 await new Promise(r=>broker.server.listen(port,'127.0.0.1',r));
 t.after(()=>new Promise(r=>broker.server.close(r)));
 const request=(p,o={})=>fetch(`http://127.0.0.1:${port}${p}`,{...o,redirect:'manual',headers:{'X-Studio-Broker':capability,...o.headers}});
 return {root,broker,request,calls,token,user,channels,config,advance:ms=>{clock+=ms;}};
}
async function begin(f){
 const prepared=await f.request('/prepare',{method:'POST',body:JSON.stringify(identity)});
 assert.equal(prepared.status,200);
 const p=await prepared.json(),b=await f.request(p.beginPath),auth=new URL(b.headers.get('location'));
 assert.equal(auth.searchParams.get('scope'),YOUTUBE_SCOPE);
 assert.equal(auth.searchParams.get('include_granted_scopes'),'false');
 return {callback:'/callback?state='+auth.searchParams.get('state')+'&code=SYNTHETIC',cookie:b.headers.get('set-cookie').split(';')[0],auth};
}
async function connect(f){const b=await begin(f);await f.request(b.callback,{headers:{Cookie:b.cookie}});return b;}
test('missing configuration fails closed',async t=>{const f=await fixture(t,{configured:false});assert.equal(f.broker.status().state,'configuration_required');assert.equal((await f.request('/prepare',{method:'POST',body:'{}'})).status,503);});
test('exact identity connects and encrypts tokens',async t=>{
 const f=await fixture(t);await connect(f);assert.equal(f.broker.status().state,'connected_identity');assert.equal(f.broker.status().channelId,identity.channelId);assert.equal(f.broker.status().publishReady,true);
 for(const name of await fs.readdir(f.root))assert.equal((await fs.readFile(path.join(f.root,name))).includes(Buffer.from('SYNTHETIC-REFRESH')),false);
 assert.equal(JSON.stringify(f.broker.status()).includes('SYNTHETIC-ACCESS'),false);
});
test('canonical Google email scope is accepted',async t=>{const f=await fixture(t,{token:{scope:YOUTUBE_SCOPE.replace(' email ',' https://www.googleapis.com/auth/userinfo.email ')}});await connect(f);assert.equal(f.broker.status().state,'connected_identity');});
for(const scope of [YOUTUBE_SCOPE+' https://www.googleapis.com/auth/youtube.force-ssl','openid email'])test('unapproved or missing scope fails closed: '+scope,async t=>{const f=await fixture(t,{token:{scope}});await connect(f);assert.equal(f.broker.status().state,'connection_failed');assert.equal(f.calls.length,1);});
test('matching but unverified Google email fails closed',async t=>{const f=await fixture(t,{user:{email_verified:false}});await connect(f);assert.equal(f.broker.status().state,'connection_failed');});
test('Brand Account subject connects only when its exact YouTube channel matches',async t=>{const f=await fixture(t,{user:{email:'brand-account@example.com',email_verified:false}});await connect(f);assert.equal(f.broker.status().state,'connected_identity');assert.deepEqual(f.broker.status().identitySignals,['google_oauth_subject','youtube_channels_mine','youtube_upload_scope']);});
test('wrong channel fails closed',async t=>{const f=await fixture(t,{channels:{items:[{id:'UCaaaaaaaaaaaaaaaaaaaaaa'}]}});await connect(f);assert.equal(f.broker.status().state,'connection_failed');});
test('callback requires browser cookie and correct state; replay makes no request',async t=>{const f=await fixture(t),b=await begin(f);assert.equal((await f.request(b.callback)).status,400);assert.equal(f.calls.length,0);await f.request(b.callback,{headers:{Cookie:b.cookie}});const count=f.calls.length;assert.equal((await f.request(b.callback,{headers:{Cookie:b.cookie}})).status,400);assert.equal(f.calls.length,count);});
test('wrong state and denied consent never exchange code',async t=>{const f=await fixture(t),b=await begin(f);await f.request('/callback?state=wrong&error=access_denied',{headers:{Cookie:b.cookie}});assert.equal(f.calls.length,0);assert.equal(f.broker.status().state,'connection_failed');});
test('expired callback makes no provider request',async t=>{const f=await fixture(t),b=await begin(f);f.advance(600001);assert.equal((await f.request(b.callback,{headers:{Cookie:b.cookie}})).status,400);assert.equal(f.calls.length,0);});
for(const token of [{access_token:undefined},{expires_in:-1},{expires_in:'NaN'},{token_type:'Invalid'}])test('malformed token rejected '+JSON.stringify(token),async t=>{const f=await fixture(t,{token});await connect(f);assert.equal(f.broker.status().state,'connection_failed');});
test('expired or restarted connection requires a fresh independent verification',async t=>{
 const f=await fixture(t);await connect(f);f.advance(3600001);assert.equal(f.broker.status().state,'verification_required');
 const r=await f.request('/verify',{method:'POST',body:'{}'});assert.equal(r.status,200);assert.equal((await r.json()).state,'connected_identity');
 assert.equal(f.calls.filter(c=>c.url.includes('/token')).length,2);
 assert.equal(f.calls.at(-3).body.get('grant_type'),'refresh_token');
 const restarted=await createYouTubeBroker(f.config);assert.equal(restarted.status().state,'verification_required');
});
test('refresh channel mismatch clears connected status',async t=>{const f=await fixture(t);await connect(f);f.channels.items=[{id:'UCaaaaaaaaaaaaaaaaaaaaaa'}];const r=await f.request('/verify',{method:'POST',body:'{}'});assert.equal(r.status,200);assert.equal((await r.json()).state,'verification_required');assert.equal(f.broker.status().publishReady,false);});
test('unauthorized controls and write surfaces are absent',async t=>{const f=await fixture(t);assert.equal((await f.request('/verify',{method:'POST',headers:{'X-Studio-Broker':''}})).status,403);assert.equal((await f.request('/publish',{method:'POST'})).status,404);assert.equal((await f.request('/tokens')).status,404);assert.equal(f.calls.length,0);});
