const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function actionHook(error) {
  const calls = [];
  const invalidations = [];
  const api = { act: async (...args) => { calls.push(args); throw error; } };
  const queryClient = { invalidateQueries: (input) => { invalidations.push(input.queryKey); return Promise.resolve(); } };
  const stubs = {
    '@tanstack/react-query': { useMutation: (options) => options, useQueryClient: () => queryClient },
    '@/lib/auth/access': {},
    '@/lib/workspace/provider': { useWorkspace: () => ({ api, workspaceId: 'workspace' }) },
    './client': { ApiError }
  };
  const file = path.resolve(__dirname, '../src/lib/api/hooks.ts');
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((name) => {
    if (!(name in stubs)) throw new Error(`Unexpected hook dependency: ${name}`);
    return stubs[name];
  }, mod, mod.exports);
  return { options: mod.exports.useAct(), calls, invalidations };
}

test('freshness 409 refetches authority and revision without retrying approval', async () => {
  for (const code of ['youtube_connection_refreshed', 'youtube_connection_changed']) {
    const error = new ApiError('Reload and review this post.', 409, code);
    const { options, calls, invalidations } = actionHook(error);
    const payload = { confirmed: true, reviewId: 'review', digest: 'exact-manifest' };
    await assert.rejects(options.mutationFn({ revision: 12, action: 'p2_approve', payload }), (actual) => actual === error);
    options.onError(error);
    assert.deepEqual(calls, [['workspace', 12, 'p2_approve', payload]]);
    assert.deepEqual(invalidations, [['snapshot', 'workspace'], ['channels', 'workspace']]);
  }
});

test('unrelated conflicts and provider failures do not trigger this recovery handler', () => {
  for (const error of [
    new ApiError('Workspace changed.', 409, 'workspace_revision_conflict'),
    new ApiError('Verification unavailable.', 503, 'youtube_verification_unavailable'),
    new ApiError('Synthetic invalid response.', 500, 'youtube_connection_refreshed')
  ]) {
    const { options, calls, invalidations } = actionHook(error);
    options.onError(error);
    assert.deepEqual(calls, []);
    assert.deepEqual(invalidations, []);
  }
});
