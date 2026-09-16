import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import http from 'node:http';
import {privateStore} from '../private-store.mjs';
import {createBroker,handleName,metadata} from '../broker.mjs';
import {NodeOAuthClient} from '@atproto/oauth-client-node';

const secret='SYNTHETIC-SECRET-NEVER-LOG';
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
async function fixture(t,{wrongIdentity=false,error=false}={}){
  const root=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'studio-broker-test-')));
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const port=await freePort(),capability='a'.repeat(64);let flow;let callbacks=0;let authCalls=0;
  const broker=await createBroker({root,port,studioPort:4310,capability,
    oauthFactory:()=>({authorize:async(handle,options)=>{authCalls++;flow=options.state;if(error)throw new Error(secret);return new URL('https://bsky.social/oauth/authorize?request_uri=synthetic');},
      callback:async(params)=>{callbacks++;if(params.get('state')!=='fixture-state')throw new Error(secret);return {state:flow,session:{did:'did:plc:fixture',getTokenInfo:async()=>({scope:'atproto',sub:'did:plc:fixture',expiresAt:new Date(Date.now()+3600000)})}};}}),
    fetchPublic:async()=>Response.json({handle:'test.bsky.social',did:wrongIdentity?'did:plc:wrong':'did:plc:fixture'})});
  await new Promise(r=>broker.server.listen(port,'127.0.0.1',r));
  t.after(()=>new Promise(r=>broker.server.close(r)));
  const request=(p,options={})=>fetch(`http://127.0.0.1:${port}${p}`,{...options,redirect:'manual',headers:{'X-Studio-Broker':capability,...options.headers}});
  return {root,port,broker,request,calls:()=>({callbacks,authCalls})};
}

test('identity-only localhost metadata is accepted by real pinned SDK without network',()=>{
  const store={set:async()=>{},get:async()=>undefined,del:async()=>{}};
  const client=new NodeOAuthClient({clientMetadata:metadata(4312),stateStore:store,sessionStore:store,requestLock:async(_key,fn)=>fn()});
  assert.equal(client.clientMetadata.scope,'atproto');
  assert.equal(client.clientMetadata.token_endpoint_auth_method,'none');
});
test('handle input rejects URLs, email, control characters and arbitrary endpoints',()=>{
  assert.equal(handleName('@Test.bsky.social'),'test.bsky.social');
  for(const value of ['https://bsky.social','jamescreates@gmail.com','127.0.0.1','test.bsky.social\nattack',null,{},'a'.repeat(254)])assert.throws(()=>handleName(value));
});
test('vault encrypts records, survives reopening, and isolates namespaces',async t=>{
  const root=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'studio-vault-test-')));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const bucket=(await privateStore(root))('session');await bucket.set('a',{token:secret});
  for(const file of await fs.readdir(root)){assert.equal((await fs.readFile(path.join(root,file))).includes(Buffer.from(secret)),false);assert.equal((await fs.stat(path.join(root,file))).mode&0o077,0);}
  assert.deepEqual(await (await privateStore(root))('session').get('a'),{token:secret});
  assert.equal(await (await privateStore(root))('other').get('a'),undefined);
});
test('vault rejects symlink and hardlinked key',async t=>{
  const root=await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(),'studio-vault-link-')));t.after(()=>fs.rm(root,{recursive:true,force:true}));
  await fs.symlink(root,path.join(root,'link'));await assert.rejects(privateStore(path.join(root,'link')),/unsafe_private_path/);
  await privateStore(root);await fs.link(path.join(root,'broker.key'),path.join(root,'key-copy'));
  await assert.rejects(privateStore(root),/unsafe_private_key/);
});
test('broker has no credential or generic publishing endpoint',async t=>{
  const f=await fixture(t);
  assert.equal((await f.request('/status',{headers:{'X-Studio-Broker':'wrong'}})).status,403);
  const wrongHost=await new Promise((resolve,reject)=>{const req=http.get({hostname:'127.0.0.1',port:f.port,path:'/status',headers:{Host:'external.invalid','X-Studio-Broker':'a'.repeat(64)}},res=>{res.resume();resolve(res.statusCode);});req.on('error',reject);});
  assert.equal(wrongHost,403);
  for(const p of ['/tokens','/credentials','/publish','/proxy'])assert.equal((await f.request(p)).status,404);
  assert.deepEqual(f.calls(),{callbacks:0,authCalls:0});
});
test('bad fields/scopes fail before provider calls',async t=>{
  const f=await fixture(t);
  for(const data of [{handle:'test.bsky.social',scope:'atproto transition:generic'},{handle:'test.bsky.social',scope:'atproto',token:secret},{handle:'https://evil.invalid',scope:'atproto'}]){
    const r=await f.request('/prepare',{method:'POST',body:JSON.stringify(data)});assert.equal(r.status,422);assert.equal((await r.text()).includes(secret),false);
  }
  assert.equal(f.calls().authCalls,0);
});
async function begin(f){
  const r=await f.request('/prepare',{method:'POST',body:JSON.stringify({handle:'test.bsky.social',scope:'atproto'})});assert.equal(r.status,200);
  const body=await r.json();assert.deepEqual(Object.keys(body),['beginPath']);
  const b=await f.request(body.beginPath);assert.equal(b.status,303);
  return {cookie:b.headers.get('set-cookie').split(';')[0],beginPath:body.beginPath};
}
test('successful callback binds browser, OAuth subject and independent profile, then rejects replay',async t=>{
  const f=await fixture(t);const {cookie,beginPath}=await begin(f);
  assert.equal((await f.request(beginPath)).status,410);
  assert.equal((await f.request('/callback?state=fixture-state&code='+secret)).status,400);
  const r=await f.request('/callback?state=fixture-state&code='+secret,{headers:{Cookie:cookie}});
  assert.equal(r.status,303);assert.equal(r.headers.get('location'),'http://127.0.0.1:4310/connection-return');
  const state=await (await f.request('/status')).json();assert.equal(state.state,'connected_identity');assert.equal(state.publishReady,false);assert.equal(state.scope,'atproto');assert.equal(state.identitySignals.length,2);
  assert.equal(JSON.stringify(state).includes(secret),false);
  assert.equal((await f.request('/callback?state=fixture-state&code='+secret,{headers:{Cookie:cookie}})).status,400);
  assert.equal(f.calls().callbacks,1);
});
test('wrong profile never becomes connected; callback errors remain private',async t=>{
  const f=await fixture(t,{wrongIdentity:true}),{cookie}=await begin(f);
  const r=await f.request('/callback?state=fixture-state&code='+secret,{headers:{Cookie:cookie}});
  assert.equal(r.status,303);assert.equal(f.broker.status().state,'connection_failed');assert.equal(f.broker.status().did,null);
});
test('duplicate prepare does not start another auth request and raw provider error is hidden',async t=>{
  const f=await fixture(t);await begin(f);
  assert.equal((await f.request('/prepare',{method:'POST',body:JSON.stringify({handle:'test.bsky.social',scope:'atproto'})})).status,409);
  assert.equal(f.calls().authCalls,1);
  const bad=await fixture(t,{error:true});const r=await bad.request('/prepare',{method:'POST',body:JSON.stringify({handle:'test.bsky.social',scope:'atproto'})});
  assert.equal(r.status,502);assert.equal((await r.text()).includes(secret),false);
});
test('encrypted verified identity survives a broker restart without new auth calls',async t=>{
  const f=await fixture(t),{cookie}=await begin(f);
  await f.request('/callback?state=fixture-state&code='+secret,{headers:{Cookie:cookie}});
  const reloaded=await createBroker({root:f.root,port:f.port,studioPort:4310,capability:'b'.repeat(64),oauthFactory:()=>({})});
  assert.equal(reloaded.status().state,'connected_identity');assert.equal(reloaded.status().did,'did:plc:fixture');
  const expired=await createBroker({root:f.root,port:f.port,studioPort:4310,capability:'b'.repeat(64),oauthFactory:()=>({}),now:()=>Date.now()+7200000});
  assert.equal(expired.status().state,'needs_reauthentication');assert.equal(expired.status().publishReady,false);
});
