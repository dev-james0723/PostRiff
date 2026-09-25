const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const LIB = path.join(__dirname, '..', 'src', 'lib', 'site-agent');

function load(name) {
  const file = path.join(LIB, name);
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}

const R = load('routes.ts');
const P = load('panel-logic.ts');
const manifest = JSON.parse(fs.readFileSync(path.join(LIB, 'route-manifest.json'), 'utf8'));
const apiTwin = path.join(__dirname, '..', '..', 'src', 'postriff_phase2', 'site_agent', 'route_manifest.json');

test('the manifest twin matches the API copy byte for byte', () => {
  assert.equal(fs.readFileSync(path.join(LIB, 'route-manifest.json'), 'utf8'), fs.readFileSync(apiTwin, 'utf8'));
});

test('routes match app paths with their parameters', () => {
  assert.equal(R.matchRoute(manifest, '/app/queue').route.id, 'queue');
  assert.deepEqual(R.matchRoute(manifest, '/app/agent/abc-123').params, { conversationId: 'abc-123' });
  assert.equal(R.matchRoute(manifest, '/app/nowhere'), null);
  assert.equal(R.matchRoute(manifest, 'https://evil.example/app'), null);
  assert.equal(R.familyOf(manifest, '/app/workspace/memory'), 'memory');
});

test('only manifest links survive', () => {
  assert.equal(R.safeHref(manifest, '/app/queue?view=drafts'), '/app/queue?view=drafts');
  assert.equal(R.safeHref(manifest, '/app/queue?job=job-1'), '/app/queue?job=job-1');
  assert.equal(R.safeHref(manifest, '/app/help/help_approvals#exact-approvals'), '/app/help/help_approvals#exact-approvals');
  for (const bad of ['https://evil.example', '//evil.example/app', 'javascript:alert(1)', '/app/queue?view=everything', '/app/queue?evil=1',
                     '/app/queue#x', '/app/nowhere', '/app/help/help_approvals#<script>', '/app/automations?edit=../../x']) {
    assert.equal(R.safeHref(manifest, bad), null, bad);
  }
});

test('suggestions fit the page and the role', () => {
  assert.ok(P.suggestionsFor('queue', false).includes('What is waiting for my approval?'));
  assert.ok(P.suggestionsFor('home', true)[0].startsWith('Write'));
  assert.ok(!P.suggestionsFor('home', false).some((s) => s.startsWith('Write')));
  assert.equal(P.suggestionsFor('unknown-family', false).length, 2);
  for (const family of ['home', 'queue', 'automations']) assert.ok(P.suggestionsFor(family, true).length <= 3);
});

test('activity rows are only the steps that really ran', () => {
  const events = [
    { type: 'run.started' },
    { type: 'progress.updated', stage: 'classified', intent: 'diagnose' },
    { type: 'progress.updated', stage: 'tool', tool: 'job.get', label: "Read the post's publishing record", status: 'verified' },
    { type: 'progress.updated', stage: 'tool', tool: 'help.search', label: 'Searched Rafii help', status: 'failed' },
    { type: 'progress.updated', stage: 'tool', tool: 'x', label: 'Blocked thing', status: 'blocked' }
  ];
  const rows = P.activityRows(events, true);
  assert.deepEqual(rows.map((r) => [r.label, r.status]), [
    ["Read the post's publishing record", 'done'],
    ['Searched Rafii help', 'failed'],
    ['Blocked thing', 'blocked'],
    ['Writing the answer', 'running']
  ]);
  assert.deepEqual(P.activityRows([], false), []);
});

test('panel answers are recognised by their body', () => {
  assert.equal(P.isSiteAgentBody({ siteAgent: { blocks: [] } }), true);
  assert.equal(P.isSiteAgentBody({ text: 'Drafted 2 candidates' }), false);
  assert.equal(P.isSiteAgentBody(null), false);
  assert.equal(P.shortTitle('  a  b  '), 'a b');
  assert.equal(P.shortTitle('x'.repeat(60), 10), 'xxxxxxxxx…');
});
