import {test,afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {download} from '../src/api.ts';
import {deliveryApi,handoffLabel,heartbeatLabel,isHttpsPermalink,isManualManifest,localAssetPath,packageEligible,type HandoffJob,type HandoffManifest,type HandoffReview,type PrepareHandoff} from '../src/deliveryApi.ts';

// Isolated API boundary tests. These stubs do not run a delivery worker.
const originalFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=originalFetch;});
const prepare:PrepareHandoff={draftId:'draft-one',expectedRevision:4,channel:'instagram',accountLabel:'Personal account label',destinationLabel:'Named profile',audience:'Public',scheduledLocal:'2026-11-01T01:30',timezone:'America/New_York',fold:1,windowMinutes:60,deliveryMethod:'assisted_handoff',derivatives:'none'};
const review={id:'frozen-review',draftId:'draft-one',draftRevision:4,manifestHash:'exact-frozen-hash'} as HandoffReview;

test('delivery queue/worker inspection is a read without promotion or approval',async()=>{
  let calls=0;
  globalThis.fetch=async(path,options)=>{calls++;assert.equal(path,'/api/delivery');assert.equal(options?.method,undefined);assert.equal(options?.body,undefined);return Response.json({jobs:[],worker:{paused:true}});};
  await deliveryApi.state();assert.equal(calls,1);
});

test('prepare sends exact manual-only target/time/derivative fields and no publication authority',async()=>{
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/api/delivery/reviews');assert.equal(options?.method,'POST');
    assert.equal(options?.credentials,'same-origin');assert.equal(new Headers(options?.headers).get('X-Studio-Request'),'1');
    assert.deepEqual(JSON.parse(String(options?.body)),prepare);
    return Response.json({review});
  };
  await deliveryApi.prepare(prepare);
});

test('owner local-task acknowledgement sends only exact manifest hash and draft revision',async()=>{
  const bodies:string[]=[];
  globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/delivery/reviews/frozen-review/approve');bodies.push(String(options?.body));return Response.json({job:{id:'same-job'}});};
  await deliveryApi.approve(review);await deliveryApi.approve(review);
  assert.deepEqual(JSON.parse(bodies[0]),{manifestHash:'exact-frozen-hash',expectedRevision:4});
  assert.equal(bodies[0],bodies[1]);
  assert.equal('approvedBy' in JSON.parse(bodies[0]),false);
});

test('local worker control contains only the requested pause setting',async()=>{
  globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/delivery/control');assert.deepEqual(JSON.parse(String(options?.body)),{paused:false});return Response.json({worker:{paused:false}});};
  await deliveryApi.control(false);
});

test('cancellation targets an encoded job ID and sends no external deletion instruction',async()=>{
  globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/delivery/jobs/job%2Fone/cancel');assert.equal(options?.body,'{}');return Response.json({job:{state:'cancelled'}});};
  await deliveryApi.cancel('job/one');
});

test('recording a permalink calls only the local report endpoint, never the supplied URL',async()=>{
  const url='https://example.com/a-manually-posted-item';let calls=0;
  globalThis.fetch=async(path,options)=>{calls++;assert.equal(path,'/api/delivery/jobs/job-one/report');assert.deepEqual(JSON.parse(String(options?.body)),{permalink:url});return Response.json({job:{state:'user_reported',verificationState:'unverified'}});};
  await deliveryApi.report('job-one',url);assert.equal(calls,1);
});

test('job package and asset paths stay same-origin and encode untrusted identifier separators',()=>{
  assert.equal(deliveryApi.packagePath('job?extra=one'),'/api/delivery/jobs/job%3Fextra%3Done/package');
  assert.equal(localAssetPath('asset/../one'),'/api/assets/asset%2F..%2Fone/content');
});

test('only current handoff/user-reported states offer the package control',()=>{
  for(const state of ['queued_local','needs_review','cancelled'] as const)assert.equal(packageEligible({state} as HandoffJob),false);
  for(const state of ['human_action_needed','user_reported'] as const)assert.equal(packageEligible({state} as HandoffJob),true);
});

test('reported HTTPS metadata rejects non-HTTPS and embedded login credentials',()=>{
  assert.equal(isHttpsPermalink('https://example.com/post/one'),true);
  for(const value of ['http://example.com','javascript:alert(1)','file:///tmp/post','https://user:password@example.com/post','not a link'])assert.equal(isHttpsPermalink(value),false);
});

test('heartbeat text never turns a pause setting or missing evidence into worker liveness',()=>{
  assert.equal(heartbeatLabel(null),'No worker heartbeat observed');
  assert.equal(heartbeatLabel('invalid'),'Heartbeat timestamp unavailable');
  assert.equal(heartbeatLabel('2026-09-13T12:00:00Z',Date.parse('2026-09-13T12:00:12Z')),'Heartbeat observed 12s ago');
  assert.match(heartbeatLabel('2026-09-13T12:00:00Z',Date.parse('2026-09-13T11:59:59Z')),/ahead/);
});

test('manual review guard rejects external authority, automatic routes and implicit derivatives',()=>{
  const manual={scope:'local_handoff_only',deliveryMethod:'assisted_handoff',publicationAuthority:false,remoteScheduling:false,identityState:'unverified',derivatives:'none',copy:'Owner-supplied copy',nativeFormat:'instagram.feed',scheduledUtc:'2026-01-01T00:00:00Z',deadlineUtc:'2026-01-01T01:00:00Z'} as HandoffManifest;
  assert.equal(isManualManifest(manual),true);
  for(const patch of [{publicationAuthority:true},{remoteScheduling:true},{identityState:'connected'},{deliveryMethod:'provider_schedule'},{deliveryMethod:'local_dispatch'},{derivatives:'all'}])assert.equal(isManualManifest({...manual,...patch} as HandoffManifest),false);
});

test('queue labels never claim publication or independent verification',()=>{
  assert.equal(handoffLabel('user_reported'),'User reported · unverified');
  for(const state of ['queued_local','human_action_needed','needs_review','cancelled','user_reported'] as const)assert.equal(/published|verified live|scheduled on platform/i.test(handoffLabel(state)),false);
});

test('invalidated package errors retain the actionable server message',async()=>{
  globalThis.fetch=async()=>Response.json({error:{code:'review_invalidated',message:'Draft changed. Prepare a fresh review.'}},{status:409});
  await assert.rejects(download('/api/delivery/jobs/job/package','package.md'),/Draft changed. Prepare a fresh review/);
});
