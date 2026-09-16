import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import {createLinkedInBroker,LINKEDIN_SCOPE} from '../linkedin-broker.mjs';

test('LinkedIn OAuth binds the exact callback, scopes, identity and keeps publishing disabled',async()=>{
 const root=await mkdtemp(path.join(process.cwd(),'.linkedin-broker-')),capability='c'.repeat(64);let postCalls=0;
 const fetchApi=async(url,init={})=>{
  if(String(url).includes('/accessToken'))return new Response(JSON.stringify({access_token:'access-token',token_type:'Bearer',expires_in:3600,scope:LINKEDIN_SCOPE}),{status:200});
  if(String(url).includes('/userinfo'))return new Response(JSON.stringify({sub:'linkedin-subject',name:'James Au',email:'jamesaucreates@gmail.com',email_verified:true}),{status:200});
  if(String(url).includes('/rest/posts')){postCalls++;return new Response('',{status:201,headers:{'x-restli-id':'urn:li:share:123456789'}});}
  throw new Error('unexpected_request');
 };
 const {server}=await createLinkedInBroker({port:0,studioPort:4310,root,capability,clientId:'86761m831bhyiu',clientSecret:'test-secret',fetchApi,allowEphemeralPort:true});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const address=server.address(),port=typeof address==='object'&&address?address.port:0;
 try{
  const api=(url,init={})=>fetch(`http://127.0.0.1:${port}${url}`,{...init,headers:{'X-Studio-Broker':capability,...init.headers}});
  const prepared=await api('/prepare',{method:'POST',body:JSON.stringify({email:'jamesaucreates@gmail.com',scope:LINKEDIN_SCOPE})});assert.equal(prepared.status,200);
  const {beginPath}=await prepared.json(),begin=await fetch(`http://127.0.0.1:${port}${beginPath}`,{redirect:'manual'});assert.equal(begin.status,303);
  const auth=new URL(begin.headers.get('location'));assert.equal(auth.origin,'https://www.linkedin.com');assert.equal(auth.pathname,'/oauth/v2/authorization');assert.equal(auth.searchParams.get('redirect_uri'),'http://127.0.0.1:4321/callback');assert.equal(auth.searchParams.get('scope'),LINKEDIN_SCOPE);
  const callback=await fetch(`http://127.0.0.1:${port}/callback?state=${auth.searchParams.get('state')}&code=test-code`,{redirect:'manual'});assert.equal(callback.status,303);
  const status=await (await api('/status')).json();assert.equal(status.state,'connected_identity');assert.equal(status.email,'jamesaucreates@gmail.com');assert.equal(status.publishReady,false);assert.equal(status.publishing,false);
  const publication=await api('/publish-text',{method:'POST',body:JSON.stringify({text:'Testing the LinkedIn connection for James Au Studio. This post was reviewed and sent through my local approval workflow.',approvalReceiptHash:'sha256:8a311cb35fe270fc880e24b3fa6319c48f338b39711e3a12e5b0c436cbbc67df',idempotencyKey:'test-publication-1',publicationConsent:true})});assert.equal(publication.status,200);const published=await publication.json();assert.equal(published.url,'https://www.linkedin.com/feed/update/urn:li:share:123456789/');assert.equal(published.replayed,false);
  const ready=await (await api('/status')).json();assert.equal(ready.publishReady,true);
  assert.equal(ready.schedulingAvailable,true);
  const scheduledAt=new Date(Date.now()+2*60*1000).toISOString(),text='A local scheduling test that must not call the LinkedIn Posts API.';
  const preview=await api('/schedule-preview',{method:'POST',body:JSON.stringify({text,scheduledAt})});assert.equal(preview.status,200);const candidate=await preview.json();assert.equal(candidate.manifest.text,text);assert.match(candidate.approvalReceiptHash,/^sha256:[a-f0-9]{64}$/);
  const scheduled=await api('/schedule-text',{method:'POST',body:JSON.stringify({text,scheduledAt,approvalReceiptHash:candidate.approvalReceiptHash,idempotencyKey:'test-schedule-1',publicationConsent:true})});assert.equal(scheduled.status,200);const job=await scheduled.json();assert.equal(job.state,'scheduled');assert.equal(job.replayed,false);assert.equal(job.text,text);
  const queued=await api('/scheduled');assert.equal(queued.status,200);assert.deepEqual((await queued.json()).jobs.map(value=>value.idempotencyKey),['test-schedule-1']);assert.equal(postCalls,1);
 }finally{await new Promise(resolve=>server.close(resolve));await rm(root,{recursive:true,force:true});}
});
