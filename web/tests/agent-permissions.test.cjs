const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { SRC, createLoader } = require('./agent-ui-journeys/_load.cjs');
const model = createLoader().load('src/lib/agent-permissions/model.ts');
const view = { state: { epoch: 4, needsChoice: true }, consentVersion: 'agent-permissions/1', copyDigest: 'a'.repeat(64), categories: [{id:'manage_settings',mode:'ask'}] };

test('permission surfaces remain dark unless explicitly enabled', () => {
  for (const value of [undefined, '', '0', 'true', 'on']) assert.equal(model.permissionsUiEnabled(value), false);
  assert.equal(model.permissionsUiEnabled('1'), true);
});
test('preset selection does not silently claim consent or fresh authentication', () => {
  const body = model.putBody(view, {preset:'full',source:'settings'}, 'key');
  assert.deepEqual(body, {preset:'full',expectedEpoch:4,consentVersion:view.consentVersion,copyDigest:view.copyDigest,source:'settings',idempotencyKey:'key'});
  assert.equal(model.needsFreshSignIn(view, 'full'), true);
  assert.equal(model.needsFreshSignIn(view, 'custom', {'category:manage_settings':'assist'}), true);
  assert.equal(model.needsFreshSignIn(view, 'recommended'), false);
});
test('custom save preserves narrowing and transmits explicit confirmation only', () => {
  const body = model.putBody(view, {preset:'custom',source:'settings',changes:{'domain:screen':false,'category:create_edit':'off','other:unsafe':true},confirmed:true}, 'request');
  assert.deepEqual(body.scopes, {'domain:screen':false,'category:create_edit':'off'});
  assert.equal(body.confirmed, true);
  assert.equal(body.stepUp, undefined);
});
class ApiError extends Error { constructor(message,status,code){super(message);this.status=status;this.code=code;} }
const apiModule = createLoader({stubs:{[path.join(SRC,'lib/api/client')]:{ApiError, APP_GUARD_HEADER:{'X-Rafii-App':'1'}}}}).load('src/lib/api/agent-permissions.ts');
test('reminder transport sends no request key or grant and escapes the workspace', async () => {
  const saved = global.fetch;
  let request;
  global.fetch=async (url,opts)=>{request={url,...opts};return new Response(JSON.stringify({reminder:{due:false,nextAt:42}}));};
  try {
    const api=apiModule.createAgentPermissionsApi(async()=> 'signed-session');
    await api.remindAgentPermissions('workspace/path',{action:'not_now'});
    assert.equal(request.url,'/api/workspaces/workspace%2Fpath/agent/permissions/reminder');
    assert.deepEqual(JSON.parse(request.body),{action:'not_now'});
    assert.equal(request.headers.Authorization,'Bearer signed-session');
    assert.equal(request.headers['X-Rafii-App'],'1');
  } finally {global.fetch=saved;}
});
test('stale epoch and step-up responses remain typed, unsaved failures', async () => {
  const saved=global.fetch;
  try {
    for(const [status,code,extra] of [[409,'agent_permissions_changed',{current:{epoch:5}}],[403,'step_up_required',{stepUp:{required:true}}]]) {
      global.fetch=async()=>new Response(JSON.stringify({error:'Reload or sign in',code,...extra}),{status});
      await assert.rejects(apiModule.createAgentPermissionsApi(async()=> 'session').putAgentPermissions('w',{}), error => {
        assert.equal(error instanceof apiModule.AgentPermissionsError,true);
        assert.equal(error.code,code); assert.deepEqual(error.body,{error:'Reload or sign in',code,...extra}); return true;
      });
    }
  } finally {global.fetch=saved;}
});
test('missing session never dispatches a permission write', async () => {
  const saved=global.fetch;
  global.fetch=()=>{throw new Error('unexpected dispatch');};
  try {await assert.rejects(apiModule.createAgentPermissionsApi(async()=>null).revokeAgentPermissions('w',{all:true}),e=>e.status===401);}
  finally {global.fetch=saved;}
});
