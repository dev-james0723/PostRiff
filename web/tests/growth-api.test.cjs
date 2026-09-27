const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const file = path.resolve(__dirname, '../src/lib/api/client.ts');
const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText;
const exports_ = {};
new Function('exports', 'require', compiled)(exports_, require);

test('growth routes preserve workspace encoding, request keys and guards', async () => {
  const original = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, ...options });
    return Response.json({ status: 'complete' });
  };
  try {
    const api = exports_.createApi(async () => 'private-session');
    const input = {
      variantId: 'v',
      variantRevision: 7,
      confirmed: true,
      requestKey: 'stable-key-123456'
    };
    await api.postDoctor('w/foreign', input);
    await api.postDoctorRewrite('w', {
      checkId: 'c',
      model: 'chosen/model',
      facts: { real: 'My own fact' },
      confirmed: true,
      requestKey: 'stable-rewrite-key'
    });
    await api.analyzeHistory('w', {
      sourceIds: ['s'],
      ownContent: true,
      retainText: true,
      confirmed: true,
      requestKey: 'stable-history-key'
    });
    await api.performanceFeedback('w', 'job/encoded');
    assert.equal(calls[0].url, '/api/workspaces/w%2Fforeign/growth/check');
    assert.deepEqual(JSON.parse(calls[0].body), input);
    assert.equal(calls[1].url, '/api/workspaces/w/growth/rewrite');
    assert.equal(JSON.parse(calls[1].body).model, 'chosen/model');
    assert.equal(calls[2].url, '/api/workspaces/w/growth/history');
    assert.equal(calls[3].url, '/api/workspaces/w/growth/feedback/job%2Fencoded');
    assert.ok(calls.every((c) => c.headers.Authorization === 'Bearer private-session'));
    assert.ok(calls.every((c) => c.headers['X-PostRiff-Request'] === 'founder-alpha'));
  } finally {
    global.fetch = original;
  }
});

test('public analysis and DNA never attach session credentials', async () => {
  const original = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, ...options });
    return Response.json({ dimensions: [] });
  };
  try {
    const api = exports_.createApi(async () => {
      throw new Error('Public routes must not ask for a session');
    });
    await api.publicPostDoctor({
      text: 'A draft',
      platform: 'Threads',
      language: 'en',
      confirmed: true
    });
    await api.contentDNA('public-token');
    assert.equal(calls[0].url, '/api/post-doctor');
    assert.equal(calls[0].headers['X-PostRiff-Request'], 'founder-alpha');
    assert.equal(calls[1].url, '/api/content-dna/public-token');
    assert.ok(calls.every((c) => !c.headers.Authorization));
  } finally {
    global.fetch = original;
  }
});
