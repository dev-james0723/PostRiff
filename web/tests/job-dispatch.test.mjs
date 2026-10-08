import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from '../node_modules/typescript/lib/typescript.js';

const source = readFileSync(new URL('../src/features/queue/job-dispatch.ts', import.meta.url), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
new Function('exports', output)(exports);
const { canPublishApprovedJob } = exports;
const due = { state:'scheduled', approvalDigest:'a'.repeat(64), nextAt:99, leaseUntil:0, cancelRequested:false,
  attempts:[], events:[], manifest:{workspaceId:'workspace-one',expiresAt:200} };
const preview = {environment:'preview',origin:'https://preview.example.invalid'};

test('publish action is only available for a due already-approved first attempt', () => {
  assert.equal(canPublishApprovedJob(due, 100, true), true);
  assert.equal(canPublishApprovedJob(due, 100, false), false);
  for (const change of [{state:'provider_accepted'},{state:'uncertain'},{state:'submitting'},{state:'held'},
    {providerReference:'urn:li:share:123'}, {container:'123'}, {progress:{stage:'create_attempted'}},
    {nextAt:101}, {nextAt:undefined}, {leaseUntil:101}, {cancelRequested:true},
    {attempts:[{number:1}]}, {approvalDigest:undefined}, {manifest:{expiresAt:99}}]) {
    assert.equal(canPublishApprovedJob({...due,...change}, 100, true), false, JSON.stringify(change));
  }
});

test('preview holds require the current deployment and definitive no-submission evidence', () => {
  const pending = {...due,state:'held',previewDispatchPending:true,manifest:{...due.manifest,workerBinding:preview},
    events:[{state:'held',message:'Approved preview post; choose Publish approved post when due.'}]};
  assert.equal(canPublishApprovedJob(pending,100,true,preview),true);
  assert.equal(canPublishApprovedJob(pending,100,true),false,'Production cannot release preview approval');
  assert.equal(canPublishApprovedJob(pending,100,true,{...preview,origin:'https://another.example.invalid'}),false);
  assert.equal(canPublishApprovedJob({...pending,nextAt:101},100,true,preview),false);
  const legacy = {...due,state:'held',resultSchema:'postriff.result.v1',
    providerConfirmed:'Live provider transport is not configured; nothing was submitted',
    events:[{state:'held',message:'Live provider transport is not configured; nothing was submitted'}],
    attempts:[{number:1,startedAt:90,endedAt:91}]};
  assert.equal(canPublishApprovedJob(legacy,100,true,preview),true);
  for (const change of [{providerReference:'urn:li:share:123'},{providerUpload:{id:'upload'}},
    {state:'uncertain'},{resultSchema:undefined},{attempts:[{number:1,startedAt:90}]},
    {attempts:[{number:1,startedAt:90,endedAt:Infinity}]},{providerConfirmed:'Provider outcome unknown'},
    {events:[{state:'held',message:'Some other cause'}]},{workerBinding:preview}]) {
    assert.equal(canPublishApprovedJob({...legacy,...change},100,true,preview),false,JSON.stringify(change));
  }
  assert.equal(canPublishApprovedJob(due,100,true,preview),false,'Preview cannot consume an unbound scheduled job');
});
