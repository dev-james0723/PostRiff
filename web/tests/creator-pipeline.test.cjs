const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createLoader } = require('./agent-ui-library-loader.cjs');
const { load } = createLoader();
const client = load('src/lib/agent-runtime/creator-pipeline.ts');
const request = { suggestionId: 'suggestion-a', platforms: ['Threads'], budgetCeilingUsdMicro: 0, digest: 'a'.repeat(64), idempotencyKey: 'creator-request-key-original' };
test('Pending descriptor validates and drops content/credentials', () => {
  assert.deepEqual(client.normalizePending({ ...request, summary: 'private', token: 'secret' }), request);
  for (const patch of [{ digest: 'bad' }, { platforms: ['Threads', 'Threads'] }, { budgetCeilingUsdMicro: -1 }, { idempotencyKey: '' }]) assert.equal(client.normalizePending({ ...request, ...patch }), null);
});
test('Uncertain request survives scope remount and stays isolated', () => {
  const old = global.sessionStorage, values = new Map();
  global.sessionStorage = { getItem: (k) => values.get(k), setItem: (k,v) => values.set(k,v), removeItem: (k) => values.delete(k) };
  try { client.savePending('user-a:workspace-a',request); assert.deepEqual(client.readPending('user-a:workspace-a'),request);assert.equal(client.readPending('user-b:workspace-a'),null);assert.equal(client.readPending('user-a:workspace-b'),null);client.clearPending('user-a:workspace-a');assert.equal(client.readPending('user-a:workspace-a'),null); } finally { global.sessionStorage=old; }
});
test('Transport preserves exact original body and session guard on reconciliation', async () => {
  const old=global.fetch,calls=[];
  global.fetch=async (url,init)=>{calls.push({url,...init});return {ok:true,json:async()=>({taskId:'t'})};};
  try { const api=client.createPipelineApi(async()=> 'synthetic-session');await api.create('workspace/a',request);await api.create('workspace/a',request);assert.equal(calls[0].body,calls[1].body);assert.equal(calls[0].url,'/api/workspaces/workspace%2Fa/agent/creator-pipeline/create');assert.equal(calls[0].headers['X-PostRiff-Request'],'founder-alpha');assert.equal(calls[0].cache,'no-store'); } finally {global.fetch=old;}
});
test('Result links cannot escape the intended native task/draft/queue pages',()=>{
  for(const href of ['https://evil.test','//evil.test','/app/../api/admin','/app/tasks?task=x&admin=1','/app/queue?job=<script>'])assert.equal(client.safeHref(href),null);
  for(const href of ['/app/tasks?task=abc','/app/queue?view=drafts&draft=def','/app/queue?job=xyz','/app/analytics'])assert.equal(client.safeHref(href),href);
});
