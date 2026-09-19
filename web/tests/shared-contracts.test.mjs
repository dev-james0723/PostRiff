import assert from 'node:assert/strict';
import * as j from '../src/lib/jobs.ts';
import { createApi, ApiError } from '../src/lib/api/client.ts';
const now = Date.parse('2026-09-19T12:00:00Z');
const job = state => ({id: state,state,manifest:{platform:'Threads',account:'Synthetic fixture',channelId:'test',timing:{utc:'2026-09-19T12:01:00Z'}},events:[]});
const phase = {jobs:['scheduled','published','verified','uncertain','new_state'].map(job), reviews:[{status:'needs_review'}]};
assert.equal(j.countSending(phase),2);
assert.equal(j.readStatus(phase,now).publishing,2);
assert.equal(j.readStatus(phase,now).approvals,1);
assert.equal(j.readWeek(phase,now,'UTC')[0].sending.length,2);
assert.equal(j.jobGroup('published'),'publishing');
assert.equal(j.jobGroup('verified'),'verified');
assert.equal(j.jobGroup('new_state'),'other');
assert.equal(j.DONE.has('published'),false);
assert.equal(j.canCancel(job('held')),true);
assert.equal(j.canCancel(job('published')),false);
assert.equal(j.jobNote({...job('held'),nextAction:'Old instruction',events:[{state:'held',message:'Voice changed'}]}),'Voice changed');
assert.equal(j.workerNote({...job('failed'),nextAction:'Old instruction',events:[{state:'failed',message:'No permission'}]}),null);
console.log('Shared job behavior assertions passed');

const originalFetch = globalThis.fetch;
try {
  for (const body of [{error:'Changed copy',code:'workspace_revision_conflict'},{error:'Legacy reply'},{error:{invalid:true},code:2}]) {
    globalThis.fetch = async () => new Response(JSON.stringify(body), {status:409});
    await assert.rejects(createApi(async () => 'synthetic').workspaces(), error => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status,409);
      assert.equal(error.code,typeof body.code === 'string' ? body.code : undefined);
      assert.equal(typeof error.message,'string');
      return true;
    });
  }
} finally { globalThis.fetch = originalFetch; }
console.log('API error compatibility assertions passed');

const { navGroups } = await import('../src/config/nav-config.ts');
const shortcuts = navGroups.flatMap(group => group.items.flatMap(item => item.shortcut ? [item.shortcut.join(' ')] : []));
assert.equal(new Set(shortcuts).size, shortcuts.length, 'navigation shortcuts must be unique');
