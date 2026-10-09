/**
 * The agent runtime status query (lib/agent-runtime/use-agent.ts): one failed status request must not switch the agent
 * runtime (and generated views) off for the page. Bounded retries for failures that may pass, none for refusals; the panel
 * shows a visible native note when the status truly can't be read.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');

function load() {
  const file = path.join(WEB, 'src/lib/agent-runtime/use-agent.ts');
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const seen = {};
  const stubs = {
    react: { useMemo: (fn) => fn() },
    '@tanstack/react-query': { useQuery: (options) => { seen.options = options; return { data: undefined, error: new Error('x'), refetch: () => 'refetched' }; } },
    '@/lib/auth/session': { useAuth: () => ({ getToken: async () => 't' }) },
    '@/lib/workspace/provider': { useWorkspaceApi: () => ({ workspaceId: 'w1' }) },
    './client': { createAgentApi: () => ({ status: (w) => `status:${w}` }) }
  };
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((id) => { if (id in stubs) return stubs[id]; throw new Error(`unexpected import ${id}`); }, mod, mod.exports);
  return { ...mod.exports, seen };
}

const M = load();

test('status: failures that may pass retry twice with backoff; refusals never retry', () => {
  for (const error of [new TypeError('network'), { status: 503 }, { status: 502 }, { status: 429 }, { status: 408 }]) {
    assert.equal(M.statusRetry(0, error), true, JSON.stringify(error));
    assert.equal(M.statusRetry(1, error), true);
    assert.equal(M.statusRetry(2, error), false, 'bounded: at most two retries');
  }
  for (const status of [400, 401, 403, 404]) assert.equal(M.statusRetry(0, { status }), false, `${status} is an answer, not a blip`);
  assert.deepEqual([0, 1, 2, 5].map(M.statusRetryDelay), [500, 1500, 4000, 4000]);
});

test('status: the hook and a turn sent early share one query definition (key, staleness, retry)', () => {
  const agent = M.useAgent();
  const options = M.seen.options;
  assert.deepEqual(options.queryKey, ['agent-runtime', 'status', 'w1']);
  assert.equal(options.retry, M.statusRetry);
  assert.equal(options.retryDelay, M.statusRetryDelay);
  assert.equal(options.staleTime, 60000);
  assert.equal(options.enabled, true);
  assert.equal(options.queryFn(), 'status:w1');
  assert.equal(agent.refetchStatus(), 'refetched');
  const chat = fs.readFileSync(path.join(WEB, 'src/features/site-agent/chat.tsx'), 'utf8');
  assert.ok(chat.includes('client.fetchQuery(query)') && chat.includes('agentStatusQuery(api, workspaceId)'), 'the early-turn wait uses the same query');
  assert.ok(chat.includes("data-rafii-agent-status='unavailable'") && chat.includes('agent.refetchStatus()'), 'a visible native note with "Check again" when it truly fails');
});
