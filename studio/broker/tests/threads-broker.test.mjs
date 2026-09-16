import {test} from 'node:test';
import assert from 'node:assert/strict';
import https from 'node:https';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {createThreadsBroker,threadsIdempotencyKey,threadsLongTokenOk,threadsPublishHash,threadsShortTokenOk} from '../threads-broker.mjs';
import {privateStore} from '../private-store.mjs';

const accessToken='T'.repeat(64);

test('accepts the documented Threads short-lived token response without expires_in',()=>{
  assert.equal(threadsShortTokenOk({access_token:accessToken,user_id:'12345678901234567'}),true);
  assert.equal(threadsShortTokenOk({access_token:accessToken,user_id:123456789}),true);
});

test('rejects malformed Threads short-lived token responses',()=>{
  assert.equal(threadsShortTokenOk({access_token:accessToken}),false);
  assert.equal(threadsShortTokenOk({access_token:accessToken,user_id:'not-a-user'}),false);
  assert.equal(threadsShortTokenOk({access_token:'too-short',user_id:'123'}),false);
});

test('requires a bounded expiry only for the long-lived Threads token',()=>{
  assert.equal(threadsLongTokenOk({access_token:accessToken,expires_in:60*24*60*60}),true);
  assert.equal(threadsLongTokenOk({access_token:accessToken}),false);
  assert.equal(threadsLongTokenOk({access_token:accessToken,expires_in:91*24*60*60}),false);
});

const freePort=()=>new Promise((resolve,reject)=>{
  const server=net.createServer();server.once('error',reject);server.listen(0,'127.0.0.1',()=>{
    const address=server.address();server.close(error=>error?reject(error):resolve(address.port));
  });
});
const request=(port,capability,method,pathname,body)=>new Promise((resolve,reject)=>{
  const payload=body===undefined?null:JSON.stringify(body);
  const req=https.request({hostname:'127.0.0.1',port,path:pathname,method,rejectUnauthorized:false,
    headers:{Host:`threads-jamesau.meta:${port}`,'X-Studio-Broker':capability,...(payload?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(payload)}:{})}},res=>{
    let raw='';res.setEncoding('utf8');res.on('data',chunk=>raw+=chunk);res.on('end',()=>resolve({status:res.statusCode,body:JSON.parse(raw)}));
  });req.once('error',reject);if(payload)req.write(payload);req.end();
});

test('route test enables exact text publishing and idempotent verified replay',async t=>{
  const temporaryRoot=await fs.realpath(os.tmpdir()),root=await fs.mkdtemp(path.join(temporaryRoot,'threads-broker-')),port=await freePort(),certificatePath=path.join(root,'cert.pem'),privateKeyPath=path.join(root,'key.pem');
  t.after(()=>fs.rm(root,{recursive:true,force:true}));
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',privateKeyPath,'-out',certificatePath,'-days','1','-subj','/CN=threads-jamesau.meta'],{stdio:'ignore'});
  const now=Date.parse('2026-09-14T04:00:00Z'),store=await privateStore(root);
  await store('threads-control').set('identity',{username:'jamesaucreates',userId:'38506513508995335',scope:'threads_basic,threads_content_publish',verifiedAt:'2026-09-14T03:00:00Z',expiresAt:'2026-11-13T03:03:03Z'});
  await store('threads-tokens').set('identity',{accessToken:'T'.repeat(64),expiresAt:'2026-11-13T03:03:03Z',scope:'threads_basic,threads_content_publish'});
  let postCalls=0;
  const fetchApi=async(input,options={})=>{
    const url=new URL(input);
    if(url.pathname==='/me'&&options.method!=='POST')return Response.json({id:'38506513508995335',username:'jamesaucreates'});
    if(url.pathname==='/me/threads_publishing_limit')return Response.json({data:[{quota_usage:1,config:{quota_total:250,quota_duration:86400}}]});
    if(url.pathname==='/me/threads'&&options.method==='POST'){postCalls++;return Response.json({id:'thread-1'});}
    if(url.pathname==='/thread-1')return Response.json({id:'thread-1',text:'Adapter route test',media_product_type:'THREADS',media_type:'TEXT_POST',permalink:'https://www.threads.com/@jamesaucreates/post/thread-1',owner:{id:'38506513508995335'},username:'jamesaucreates',timestamp:'2026-09-14T04:00:00Z',is_reply:false});
    return Response.json({error:'unexpected'}, {status:404});
  };
  const capability='c'.repeat(64),broker=await createThreadsBroker({port,studioPort:4310,root,capability,clientId:'1431031092226762',clientSecret:'s'.repeat(32),certificatePath,privateKeyPath,fetchApi,now:()=>now});
  await new Promise((resolve,reject)=>{broker.server.once('error',reject);broker.server.listen(port,'127.0.0.1',resolve);});
  t.after(()=>new Promise(resolve=>broker.server.close(resolve)));
  const route=await request(port,capability,'POST','/route-test',{account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',route:'official_api',routeDriver:'threads_graph_api'});
  assert.equal(route.status,200);assert.equal(route.body.publishReady,true);assert.deepEqual(route.body.routeTestSignals,['identity_reverified','publishing_quota_read']);
  const manifest={account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',text:'Adapter route test',visibility:'public',replyControl:'provider_default',scheduledAt:null,media:[],derivatives:[]};
  const approved={...manifest,approvalReceiptHash:threadsPublishHash(manifest),idempotencyKey:threadsIdempotencyKey(manifest)};
  const published=await request(port,capability,'POST','/publish-text',approved);
  assert.equal(published.status,200);assert.equal(published.body.threadId,'thread-1');assert.equal(published.body.replayed,false);assert.equal(postCalls,1);
  const replay=await request(port,capability,'POST','/publish-text',approved);
  assert.equal(replay.status,200);assert.equal(replay.body.replayed,true);assert.equal(postCalls,1);
  const altered=await request(port,capability,'POST','/publish-text',{...approved,text:'Changed after approval'});
  assert.equal(altered.status,422);assert.equal(postCalls,1);
});
