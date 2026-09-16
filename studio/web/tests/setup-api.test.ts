import {test,afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {isSetupCandidate,routeLabel,setupApi,type SetupCandidate} from '../src/setupApi.ts';

const originalFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=originalFetch;});
const input={channel:'bluesky',nativeFormat:'bluesky.post',accountLabel:'Synthetic account',destinationLabel:'Synthetic profile'};
const candidate={state:'candidate_only',scope:'setup_assessment_only',target:{...input,identityState:'unverified_labels'},setupAuthorized:false,publicationAuthorized:false,remoteScheduling:false,connected:false,publishReady:false,routeDriver:null,routeTestId:null,externalActions:[]} as unknown as SetupCandidate;

test('readiness does not request account discovery or external routes',async()=>{
  globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/setup/readiness');assert.equal(options?.method,undefined);assert.equal(options?.body,undefined);return Response.json({channels:[]});};
  await setupApi.readiness();
});
test('candidate preparation sends exact target fields through the owner boundary',async()=>{
  globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/setup/candidates');assert.equal(options?.method,'POST');assert.equal(options?.credentials,'same-origin');assert.equal(new Headers(options?.headers).get('X-Studio-Request'),'1');assert.deepEqual(JSON.parse(String(options?.body)),input);return Response.json({candidate});};
  assert.deepEqual(await setupApi.prepare(input),candidate);
});
test('candidate guard rejects promoted identity, route or authority',()=>{
  assert.equal(isSetupCandidate(candidate),true);
  for(const change of [{connected:true},{publishReady:true},{setupAuthorized:true},{publicationAuthorized:true},{remoteScheduling:true},{routeDriver:'unqualified'},{routeTestId:'fake'},{externalActions:['connect']},{target:{...candidate.target,identityState:'verified'}}])assert.equal(isSetupCandidate({...candidate,...change} as SetupCandidate),false);
});
test('unsafe candidate responses never become downloadable previews',async()=>{
  globalThis.fetch=async()=>Response.json({candidate:{...candidate,setupAuthorized:true}});
  await assert.rejects(setupApi.prepare(input),/not a safe candidate/);
});
test('setup errors preserve useful server guidance',async()=>{
  globalThis.fetch=async()=>Response.json({error:{code:'invalid_setup_target',message:'Choose a format for this channel.'}},{status:422});
  await assert.rejects(setupApi.prepare(input),/Choose a format/);
});
test('route labels distinguish candidates from qualified integrations',()=>{
  assert.equal(routeLabel('official_api'),'Official API candidate');
  assert.equal(routeLabel('controlled_browser'),'Browser candidate');
  assert.equal(routeLabel(null),'Route review needed');
});
