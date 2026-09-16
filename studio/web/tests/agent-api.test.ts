import {test, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {agentApi, isActiveRun, readyForGeneration, runStateLabel, type AgentStatus, type Run, type RunRequest} from '../src/agentApi.ts';

// Isolated transport unit tests, not a model provider or an application backend.
const realFetch=globalThis.fetch;
afterEach(()=>{globalThis.fetch=realFetch;});
const request:RunRequest={expectedRevision:3,inputHash:'reviewed-input',requestId:'7a7b4997-fc26-4f9b-8e76-3e8d24eaebdd',consent:true};

test('readiness is a read-only operation and does not start a model',async()=>{
  let calls=0;
  globalThis.fetch=async(path,options)=>{
    calls++;assert.equal(path,'/api/agent/status');assert.equal(options?.method,undefined);
    assert.equal(options?.credentials,'same-origin');
    return Response.json({available:false,authentication:'unavailable'});
  };
  await agentApi.status();assert.equal(calls,1);
});

test('conversation intake records only an exact saved draft and content type',async()=>{
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/api/agent/conversations');assert.equal(options?.method,'POST');
    assert.equal(new Headers(options?.headers).get('X-Studio-Request'),'1');
    assert.deepEqual(JSON.parse(String(options?.body)),{draftId:'draft-one',expectedDraftRevision:8,contentType:'reflection'});
    return Response.json({conversation:{id:'conversation-one',state:'awaiting_answer'}});
  };
  await agentApi.create('draft-one',8,'reflection');
});

test('one answer is scoped to its current question and conversation revision',async()=>{
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/api/agent/conversations/conversation%2Fone/answer');
    assert.deepEqual(JSON.parse(String(options?.body)),{expectedRevision:2,slot:'objective',value:'Explain the idea clearly, without personal claims.'});
    return Response.json({conversation:{state:'ready'}});
  };
  await agentApi.answer('conversation/one',2,'objective','Explain the idea clearly, without personal claims.');
});

test('input review uses a GET and preserves the exact backend snapshot',async()=>{
  const reviewed={inputHash:'hash',input:{source:'Supplied source text',angle:'Neutral summary',template:{body:'# Structure'}}};
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/api/agent/conversations/conversation-one/review');
    assert.equal(options?.method,undefined);assert.equal(options?.body,undefined);
    return Response.json(reviewed);
  };
  assert.deepEqual(await agentApi.review('conversation-one'),reviewed);
});

test('explicit retries preserve the same consent-bound idempotency request',async()=>{
  const bodies:string[]=[];
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/api/agent/conversations/one/runs');bodies.push(String(options?.body));
    return Response.json({run:{id:'same-run'}});
  };
  await agentApi.generate('one',request);await agentApi.generate('one',request);
  assert.equal(bodies[0],bodies[1]);assert.deepEqual(JSON.parse(bodies[0]),request);
});

test('a failed generation HTTP request is never automatically retried',async()=>{
  let calls=0;
  globalThis.fetch=async()=>{calls++;return Response.json({error:{code:'unavailable',message:'Provider unavailable.'}},{status:503});};
  await assert.rejects(agentApi.generate('one',request),/Provider unavailable/);
  assert.equal(calls,1);
});

test('polling reads a tracked run and cancellation targets only that run',async()=>{
  const requests:{path:unknown;method:string|undefined;body:unknown}[]=[];
  globalThis.fetch=async(path,options)=>{requests.push({path,method:options?.method,body:options?.body});return Response.json({run:{id:'tracked'}});};
  await agentApi.run('tracked');await agentApi.cancel('tracked');
  assert.deepEqual(requests,[{path:'/api/agent/runs/tracked',method:undefined,body:undefined},{path:'/api/agent/runs/tracked/cancel',method:'POST',body:'{}'}]);
});

test('candidate apply contains chosen channels, result hash and optimistic draft revision only',async()=>{
  globalThis.fetch=async(path,options)=>{
    assert.equal(path,'/api/agent/runs/run-one/apply');
    const body=JSON.parse(String(options?.body));
    assert.deepEqual(body,{expectedDraftRevision:8,resultHash:'candidate-hash',channels:['instagram']});
    for(const forbidden of ['publish','approved','account','command','destination','consent'])assert.equal(forbidden in body,false);
    return Response.json({run:{state:'applied'},draft:{revision:9}});
  };
  await agentApi.apply('run-one',8,'candidate-hash',['instagram']);
});

test('history reads encode the draft ID and cannot change the query shape',async()=>{
  globalThis.fetch=async(path)=>{assert.equal(path,'/api/agent/runs?draftId=draft%26other%3Dvalue');return Response.json({runs:[]});};
  await agentApi.runs('draft&other=value');
});

test('CLI availability alone is not generation readiness',()=>{
  assert.equal(readyForGeneration(null),false);
  assert.equal(readyForGeneration({available:true,authentication:'login_required'} as AgentStatus),false);
  assert.equal(readyForGeneration({available:false,authentication:'ready'} as AgentStatus),false);
  assert.equal(readyForGeneration({available:true,authentication:'ready'} as AgentStatus),true);
});

test('interrupted, failed and applied runs are terminal, never publish success',()=>{
  for(const state of ['failed','cancelled','interrupted','needs_review','applied'] as Run['state'][]){
    assert.equal(isActiveRun({state} as Run),false);
    assert.equal(/published|scheduled/i.test(runStateLabel(state)),false);
  }
  assert.equal(isActiveRun({state:'queued'} as Run),true);
  assert.equal(isActiveRun({state:'running'} as Run),true);
});
