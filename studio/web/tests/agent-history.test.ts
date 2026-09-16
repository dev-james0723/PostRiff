import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readWorkspaceRuns,selectHistory} from '../src/agentHistory.ts';
import type {Conversation,Run} from '../src/agentApi.ts';

const conversation=(id:string)=>({id,draftId:'draft'} as Conversation);
const run=(id:string,conversationId:string,state:Run['state'],extra:Partial<Run>={})=>({id,conversationId,state,draftId:'draft',requestId:id,createdAt:id,...extra} as Run);

test('history resumes the actual run conversation rather than the newest unrelated intake',()=>{
  const result=selectHistory([conversation('new'),conversation('older')],[run('last','older','needs_review')]);
  assert.equal(result.run?.id,'last');assert.equal(result.conversation?.id,'older');
});

test('an active run takes priority over a newer terminal run or requested historic ID',()=>{
  const result=selectHistory([conversation('new'),conversation('active')],[run('newer','new','failed'),run('tracked','active','running')],'newer');
  assert.equal(result.run?.id,'tracked');assert.equal(result.conversation?.id,'active');
});

test('the explicit idempotency request is selected when no active generation exists',()=>{
  const result=selectHistory([conversation('a'),conversation('b')],[run('latest','a','failed'),run('requested','b','needs_review')],'requested');
  assert.equal(result.run?.id,'requested');assert.equal(result.conversation?.id,'b');
});

test('no runs means newest intake; a missing run conversation is never falsely paired',()=>{
  assert.equal(selectHistory([conversation('first')],[]).conversation?.id,'first');
  const orphan=selectHistory([conversation('first')],[run('last','missing','running')]);
  assert.equal(orphan.conversation,null);assert.equal(orphan.run?.id,'last');
});

test('workspace discovery is finite, deduplicated and uses at most three concurrent reads',async()=>{
  let active=0,maxActive=0;const calls:string[]=[];
  const result=await readWorkspaceRuns(['one','two','three','four','one',''],async id=>{
    calls.push(id);active++;maxActive=Math.max(maxActive,active);
    await new Promise(resolve=>setTimeout(resolve,8));
    active--;return{runs:[run(`run-${id}`,'c',id==='two'?'running':'failed',{draftId:id})]};
  },50);
  assert.equal(maxActive,3);assert.deepEqual([...calls].sort(),['four','one','three','two']);
  assert.equal(result.length,4);assert.equal(result.find(item=>item.state==='running')?.draftId,'two');
});

test('workspace discovery never accepts records belonging to a different requested draft',async()=>{
  const result=await readWorkspaceRuns(['one'],async()=>({runs:[run('belongs','c','running',{draftId:'one'}),run('wrong','c','running',{draftId:'unrequested'})]}));
  assert.deepEqual(result.map(item=>item.id),['belongs']);
});

test('empty workspace never performs a transport operation',async()=>{
  let calls=0;assert.deepEqual(await readWorkspaceRuns([],async()=>{calls++;return{runs:[]};}),[]);assert.equal(calls,0);
});
