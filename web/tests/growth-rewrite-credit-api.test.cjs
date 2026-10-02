const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const compiled = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../src/lib/api/client.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText;
const exports_ = {};
new Function('exports', 'require', compiled)(exports_, require);

test('the exact Growth request and explicit maximum survive estimate, quote and execution', async () => {
  const original = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, ...options });
    return Response.json(url.endsWith('credit-estimates')
      ? { ceilingMilliCredits: 78000, estimateMilliCredits: 78000, stateRevision: 7, estimateKind: 'maximum' }
      : url.endsWith('credit-quotes') ? { quoteId: 'opaque-approved-max', maxMilliCredits: 78000 } : { runId: 'opaque-run' });
  };
  try {
    const api = exports_.createApi(async () => 'synthetic-session');
    const request = { checkId: 'check', model: 'exact/writer', facts: { own: 'My own fact' }, confirmed: true, requestKey: 'stable-rewrite-key' };
    const estimate = await api.creditEstimate('w/encoded', { operation: 'post-doctor-rewrite', request });
    const quote = await api.creditQuote('w/encoded', { operation: 'post-doctor-rewrite', request, expectedRevision: estimate.stateRevision, maxMilliCredits: estimate.ceilingMilliCredits });
    await api.postDoctorRewrite('w/encoded', { ...request, expectedRevision: estimate.stateRevision, creditQuoteId: quote.quoteId });
    assert.deepEqual(JSON.parse(calls[0].body).request, request);
    assert.deepEqual(JSON.parse(calls[1].body).request, request);
    assert.equal(JSON.parse(calls[1].body).maxMilliCredits, 78000);
    assert.deepEqual(JSON.parse(calls[2].body), { ...request, expectedRevision: 7, creditQuoteId: 'opaque-approved-max' });
    assert.equal(calls[2].url, '/api/workspaces/w%2Fencoded/growth/rewrite');
    assert.ok(calls.every(c => c.headers.Authorization === 'Bearer synthetic-session'));
  } finally {
    global.fetch = original;
  }
});
