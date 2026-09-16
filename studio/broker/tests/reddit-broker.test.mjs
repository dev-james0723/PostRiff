import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import {createRedditBroker,REDDIT_SCOPE,REDDIT_REDIRECT_URI,REDDIT_BROWSER_ROUTE_SIGNALS} from '../reddit-broker.mjs';

const identity={username:'Ok-External401',scope:REDDIT_SCOPE};
const freePort=()=>new Promise((resolve,reject)=>{const server=net.createServer();server.listen(0,'127.0.0.1',()=>{const {port}=server.address();server.close(error=>error?reject(error):resolve(port));});});
async function fixture(t,options={}){
 const root=await fs.mkdtemp(path.join(process.cwd(),'.reddit-broker-')),port=4318,studioPort=await freePort(),capability='a'.repeat(64),calls=[];let clock=Date.now();
 const token={access_token:'reddit-synthetic-access',token_type:'bearer',expires_in:3600,scope:REDDIT_SCOPE,...options.token};
 const user={name:identity.username,id:'t2_2mqzltq1ix',...options.user};
 const fetchApi=async(url,init={})=>{calls.push({url:String(url),method:init.method||'GET',headers:init.headers,body:init.body});if(options.fail)throw new Error('SYNTHETIC_PRIVATE_ERROR');return Response.json(String(url).includes('access_token')?token:user);};
 const config={root,port,studioPort,capability,clientId:options.configured===false?null:'fixture-client',clientSecret:options.configured===false?null:'x'.repeat(20),fetchApi,now:()=>clock};
 const broker=await createRedditBroker(config);await new Promise(resolve=>broker.server.listen(port,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>broker.server.close(resolve)));t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const request=(pathname,options={})=>fetch(`http://127.0.0.1:${port}${pathname}`,{...options,redirect:'manual',headers:{'X-Studio-Broker':capability,...options.headers}});
 return {root,broker,request,calls,advance:ms=>{clock+=ms;}};
}
async function begin(f){const prepared=await f.request('/prepare',{method:'POST',body:JSON.stringify(identity)});assert.equal(prepared.status,200);const beginPath=(await prepared.json()).beginPath;const redirect=await f.request(beginPath);assert.equal(redirect.status,303);const auth=new URL(redirect.headers.get('location'));return {auth,cookie:redirect.headers.get('set-cookie').split(';')[0],callback:`/callback?state=${auth.searchParams.get('state')}&code=SYNTHETIC`};}
async function connect(f){const b=await begin(f);await f.request(b.callback,{headers:{Cookie:b.cookie}});return b;}

test('missing configuration fails closed',async t=>{const f=await fixture(t,{configured:false});assert.equal(f.broker.status().state,'configuration_required');assert.equal((await f.request('/prepare',{method:'POST',body:JSON.stringify(identity)})).status,503);assert.equal(f.calls.length,0);});
test('exact account connects using only identity scope and encrypted token storage',async t=>{
 const f=await fixture(t),b=await connect(f),status=f.broker.status();
 assert.equal(status.state,'connected_identity');assert.equal(status.username,identity.username);assert.equal(status.accountId,'t2_2mqzltq1ix');assert.equal(status.publishReady,false);assert.equal(b.auth.origin,'https://www.reddit.com');assert.equal(b.auth.pathname,'/api/v1/authorize');assert.equal(b.auth.searchParams.get('scope'),REDDIT_SCOPE);assert.equal(b.auth.searchParams.get('duration'),'temporary');assert.equal(b.auth.searchParams.get('redirect_uri'),REDDIT_REDIRECT_URI);assert.equal(f.calls.length,2);
 for(const name of await fs.readdir(f.root)){const bytes=await fs.readFile(path.join(f.root,name));assert.equal(bytes.includes(Buffer.from('reddit-synthetic-access')),false);}
 assert.equal(JSON.stringify(status).includes('synthetic-access'),false);
});
for(const token of [{scope:'identity read'},{scope:'read'},{access_token:undefined},{token_type:'invalid'},{expires_in:3601}])test('invalid or expanded token fails closed '+JSON.stringify(token),async t=>{const f=await fixture(t,{token});await connect(f);assert.equal(f.broker.status().state,'connection_unresolved');assert.equal(f.broker.status().publishReady,false);});
for(const user of [{name:'Different-Account'},{id:undefined}])test('substituted account fails closed '+JSON.stringify(user),async t=>{const f=await fixture(t,{user});await connect(f);assert.equal(f.broker.status().state,'connection_unresolved');assert.equal(f.broker.status().accountId,null);});
test('callback requires nonce and exact state, and no write route exists',async t=>{const f=await fixture(t),b=await begin(f);assert.equal((await f.request(b.callback)).status,400);assert.equal(f.calls.length,0);await f.request(b.callback,{headers:{Cookie:b.cookie}});assert.equal((await f.request(b.callback,{headers:{Cookie:b.cookie}})).status,400);assert.equal((await f.request('/submit',{method:'POST'})).status,404);assert.equal((await f.request('/comment',{method:'POST'})).status,404);assert.equal((await f.request('/messages',{method:'POST'})).status,404);});

test('exact browser evidence connects identity while publishing stays disabled',async t=>{
 const f=await fixture(t,{configured:false});
 const signals=['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'];
 const response=await f.request('/browser-connect',{method:'POST',body:JSON.stringify({username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals:signals,route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome']})});
 assert.equal(response.status,200);
 const status=await response.json();
 assert.equal(status.state,'connected_browser_identity');
 assert.equal(status.username,'Ok-External401');
 assert.equal(status.profileUrl,'https://www.reddit.com/user/Ok-External401/');
 assert.equal(status.scope,'browser_identity_only');
 assert.equal(status.route,'controlled_browser');
 assert.equal(status.routeDriver,'in_app_browser');
 assert.deepEqual(status.preferredPublishDrivers,['computer_use','chrome']);
 assert.deepEqual(status.identitySignals,signals);
 assert.equal(status.sessionState,'verify_before_each_action');
 assert.equal(status.publishReady,false);
 assert.equal(status.publishing,false);
 assert.equal((await f.request('/submit',{method:'POST'})).status,404);
});

test('browser identity connection rejects substituted account or evidence',async t=>{
 const f=await fixture(t,{configured:false});
 const valid={username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals:['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'],route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome']};
 for(const body of [{...valid,username:'Different-Account'},{...valid,identitySignals:['public_profile_url']},{...valid,routeDriver:'chrome'}]){
  assert.equal((await f.request('/browser-connect',{method:'POST',body:JSON.stringify(body)})).status,422);
 }
});

test('exact non-mutating composer evidence enables the browser publishing route without submitting',async t=>{
 const f=await fixture(t,{configured:false});
 const identitySignals=['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'];
 await f.request('/browser-connect',{method:'POST',body:JSON.stringify({username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals,route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome']})});
 const response=await f.request('/enable-browser-publishing',{method:'POST',body:JSON.stringify({username:'Ok-External401',identitySignals,route:'controlled_browser',routeDriver:'in_app_browser',routeTestSignals:REDDIT_BROWSER_ROUTE_SIGNALS,publicationPolicy:'exact_post_approval_required',userAuthorization:true})});
 assert.equal(response.status,200);
 const status=await response.json();
 assert.equal(status.state,'connected_browser_identity');
 assert.equal(status.routeState,'browser_publish_ready');
 assert.equal(status.publishReady,true);
 assert.equal(status.publishing,false);
 assert.equal(status.publicationPolicy,'exact_post_approval_required');
 assert.deepEqual(status.routeTestSignals,REDDIT_BROWSER_ROUTE_SIGNALS);
 assert.match(status.routeTestId,/^reddit-browser-[a-f0-9]{32}$/);
 assert.ok(Date.parse(status.routeTestedAt));
 assert.equal((await f.request('/submit',{method:'POST'})).status,404);
});

test('browser publishing readiness rejects missing identity and substituted route evidence',async t=>{
 const f=await fixture(t,{configured:false});
 const identitySignals=['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'];
 const valid={username:'Ok-External401',identitySignals,route:'controlled_browser',routeDriver:'in_app_browser',routeTestSignals:REDDIT_BROWSER_ROUTE_SIGNALS,publicationPolicy:'exact_post_approval_required',userAuthorization:true};
 assert.equal((await f.request('/enable-browser-publishing',{method:'POST',body:JSON.stringify(valid)})).status,409);
 await f.request('/browser-connect',{method:'POST',body:JSON.stringify({username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals,route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome']})});
 for(const body of [{...valid,routeTestSignals:['composer_loaded']},{...valid,routeDriver:'chrome'},{...valid,userAuthorization:false}]){
  assert.equal((await f.request('/enable-browser-publishing',{method:'POST',body:JSON.stringify(body)})).status,422);
 }
});
