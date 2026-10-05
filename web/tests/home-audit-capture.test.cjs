const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

const root = path.resolve(__dirname, '../src/features/agent');
function compile(file, imports = {}) {
  const m = new Module(file);
  m.require = (id) => id in imports ? imports[id] : require(id);
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, file);
  return m.exports;
}
const credit = compile(path.join(root, 'credit-turn.ts'));
function harness() {
  const cells = []; let index = 0;
  const calls = [];
  const api = {
    captureCredits: async () => { calls.push(['credits']); return { balanceUsd: '8.60', totalUsedUsd: '0', source: 'mounted key', modelCalls: 0 }; },
    createCaptureGrant: async (workspace, body) => { calls.push(['grant', body]); return { id: 'grant-a', server_nonce: 'nonce-a', expires_at: '2099-01-01T00:00:00Z' }; },
    creditQuote: async (workspace, body) => { calls.push(['quote', structuredClone(body)]); return { quoteId: 'quote-a' }; },
    quickStart: async (workspace, revision, body) => { calls.push(['dispatch', structuredClone(body)]); return { runId: 'run-a', conversationId: 'conversation-a', status: 'completed' }; },
    revokeCaptureGrant: async (...args) => { calls.push(['revoke', ...args]); return { revoked: true }; }
  };
  const react = {
    useState: initial => { const i = index++; if (!(i in cells)) cells[i] = typeof initial === 'function' ? initial() : initial; return [cells[i], value => { cells[i] = typeof value === 'function' ? value(cells[i]) : value; }]; },
    useRef: initial => { const i = index++; if (!(i in cells)) cells[i] = { current: initial }; return cells[i]; },
    useCallback: fn => fn, useMemo: fn => fn(), useEffect: fn => { fn(); }
  };
  const module = compile(path.join(root, 'home/use-home-generation.ts'), {
    react,
    '@tanstack/react-query': { useQueryClient: () => ({ setQueryData() {}, invalidateQueries: async () => {} }) },
    '@/lib/api/client': { ApiError: class ApiError extends Error {} },
    '@/lib/api/hooks': { keys: { conversations: () => [], snapshot: () => [], usage: () => [] }, useSnapshot: () => ({ data: { state: { variants: [] } } }) },
    '../submission-gate': { createSubmissionGate: () => { let locked = false; return { activate() {}, dispose() {}, enter: () => locked ? false : (locked = true), leave: () => { locked = false; }, alive: () => true }; } },
    '../credit-turn': credit,
    './draft-edit-guard': { checkEditBase() {} },
    './generation-items': { buildItems: () => [] },
    '@/lib/locales': { locales: { canonical: value => value, same: (a, b) => a === b } },
    '@/lib/workspace/provider': { useWorkspaceApi: () => ({ api, workspaceId: 'workspace-a' }) },
    '../use-run': { useRun: () => null }
  });
  return { api, calls, render: () => { index = 0; return module.useHomeGeneration(); }, payload: module.quickStartPayload, verify: module.verifyPrivateCapture };
}
const base = { text: 'A short reflection.', ownContent: false, destinations: [{ platform: 'LinkedIn', language: 'en' }], voiceMode: 'neutral', voiceSourceIds: [], timeZone: 'UTC', maxMilliCredits: 1000 };
const consent = { consentVersion: 'capture-v1', model: 'openai/gpt-4.1-mini' };

test('Auto payload omits model and reasoning; consent metadata alone cannot pin or enable capture', () => {
  const h = harness();
  const payload = h.payload({ ...base, auditCaptureConsent: consent });
  assert.equal(Object.hasOwn(payload, 'model'), false);
  assert.equal(Object.hasOwn(payload, 'reasoning'), false);
  assert.equal(Object.hasOwn(payload, 'auditCaptureConsent'), false);
  assert.equal(Object.hasOwn(payload, 'auditCapture'), false);
  assert.equal(h.payload({ ...base, model: consent.model }).model, consent.model);
});

test('one-run consent creates a grant before the identical quote and dispatch body', async () => {
  const h = harness();
  await h.render().start({ ...base, auditCaptureConsent: consent }, 7);
  assert.deepEqual(h.calls.map(call => call[0]), ['credits', 'grant', 'quote', 'dispatch']);
  assert.deepEqual(h.calls[1][1], { confirmed: true, ...consent });
  const quoted = h.calls[2][1].request;
  const dispatched = h.calls[3][1];
  assert.deepEqual(quoted.auditCapture, { grantId: 'grant-a', serverNonce: 'nonce-a' });
  assert.equal(quoted.research, false);
  assert.equal(quoted.model, consent.model);
  assert.equal(quoted.auditCaptureConsent, undefined);
  const { creditQuoteId, ...same } = dispatched;
  assert.equal(creditQuoteId, 'quote-a');
  assert.deepEqual(same, quoted);
  assert.equal(h.render().captureActive, true);
});

test('ordinary submission never creates or silently opts into retention', async () => {
  const h = harness();
  await h.render().start({ ...base, maxMilliCredits: null }, 7);
  assert.deepEqual(h.calls.map(call => call[0]), ['dispatch']);
  assert.equal(h.calls[0][1].auditCapture, undefined);
  assert.equal(h.calls[0][1].research, undefined);
});

test('failed consent persistence prevents quote and generation', async () => {
  const h = harness();
  h.api.createCaptureGrant = async () => { throw Error('Consent could not be saved'); };
  assert.equal(await h.render().start({ ...base, auditCaptureConsent: consent }, 7), null);
  assert.deepEqual(h.calls.map(call => call[0]), ['credits']);
  assert.match(h.render().error, /Consent could not be saved/);
});

test('a retained capture blocks another grant until the owner ends retention', async () => {
  const h = harness();
  await h.render().start({ ...base, auditCaptureConsent: consent }, 7);
  const previous = h.calls.length;
  assert.equal(await h.render().start({ ...base, auditCaptureConsent: consent }, 7), null);
  assert.equal(h.calls.length, previous);
  await h.render().revokeCapture();
  assert.deepEqual(h.calls.at(-1), ['revoke', 'workspace-a', 'grant-a', 'nonce-a']);
  assert.equal(h.render().captureActive, false);
});

test('UI starts unchecked, gates unsupported routes, and clears consent after an attempt', () => {
  const view = fs.readFileSync(path.join(root, 'home-view.tsx'), 'utf8');
  assert.match(view, /\[captureConsent, setCaptureConsent\] = useState\(false\)/);
  assert.match(view, /choice\.option\?\.provider === 'vercel-ai-gateway' && !imageRequested && !slash/);
  assert.match(view, /if \(captureConsent && !captureEligible\)/);
  assert.match(view, /Keep a private audit record for this generation only/);
  assert.match(view, /finally \{\s*submission.leave\(\);\s*setCaptureConsent\(false\)/);
  assert.doesNotMatch(view, /(?:sessionStorage|localStorage).*capture(?:Consent|Grant)/i);
});

const nodeCrypto = require('node:crypto');
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
function signedAttempt() {
  const { publicKey, privateKey } = nodeCrypto.generateKeyPairSync('ed25519');
  const pinnedKey = publicKey.export({ format: 'der', type: 'spki' }).subarray(-32).toString('base64');
  function signed(manifest) {
    // Preserve a Python-style float in the actual signed bytes while JS metadata normalizes it to an integer.
    const payload = Buffer.from('rafii-model-request-capture-v1\0' + canonical(manifest).replace('"timeout_seconds":20', '"timeout_seconds":20.0'));
    return { schema: 'rafii-request-capture-v1', public_key: pinnedKey, key_id: 'test-only', manifest,
      signed_payload_base64: payload.toString('base64'), signature: nodeCrypto.sign(null, payload, privateKey).toString('base64') };
  }
  const digest = value => nodeCrypto.createHash('sha256').update(value).digest('hex');
  const request = Buffer.from(JSON.stringify({ model: 'openai/test', messages: [{ role: 'system', content: 'PRIVATE-REQUEST-SENTINEL' }, { role: 'user', content: 'A reflection.' }] }));
  const response = Buffer.from(JSON.stringify({ text: 'PRIVATE-RESPONSE-SENTINEL' }));
  const prepared = signed({ physical_attempt_id: 'physical-a', model: 'openai/test', body_sha256: digest(request), body_bytes: request.length, timeout_seconds: 20 });
  const preparedHash = digest(Buffer.concat([Buffer.from(prepared.signed_payload_base64, 'base64'), Buffer.from(prepared.signature, 'base64')]));
  return { pinnedKey, attempt: { capture_id: 'physical-a', state: 'response_observed', prepared,
    network_started: signed({ physical_attempt_id: 'physical-a', prepared_sha256: preparedHash }),
    outcome: signed({ physical_attempt_id: 'physical-a', prepared_sha256: preparedHash, response_complete: true,
      response_sha256: digest(response), response_bytes: response.length, usage: { prompt_tokens: 24, completion_tokens: 12, cost: '0.0003' }, upstream_provider: 'test-provider' }),
    request_base64: request.toString('base64'), response_base64: response.toString('base64'),
    request: { ciphertext: 'encrypted-request', nonce: 'nonce', key_id: 'test-only', kind: 'request', unwanted: 'PRIVATE-REQUEST-SENTINEL' },
    response: { ciphertext: 'encrypted-response', nonce: 'nonce', key_id: 'test-only', kind: 'response' } } };
}

test('browser verifies exact signed bytes and produces an encrypted-only export with safe summaries', async () => {
  const h = harness(); const { attempt, pinnedKey } = signedAttempt();
  const verified = await h.verify(attempt, pinnedKey);
  assert.equal(verified.summary.roleOrder, 'system → user');
  assert.equal(verified.summary.inputTokens, 24);
  assert.equal(verified.summary.outputTokens, 12);
  assert.equal(verified.summary.costUsd, '0.0003');
  const exported = JSON.stringify(verified);
  assert.doesNotMatch(exported, /PRIVATE-REQUEST-SENTINEL|PRIVATE-RESPONSE-SENTINEL|request_base64|response_base64|unwanted/);
  assert.equal(verified.encrypted.request.ciphertext, 'encrypted-request');
});

test('untrusted key, changed manifest, changed plaintext, or mixed attempts cannot be exported', async () => {
  const h = harness();
  for (const variant of ['key', 'manifest', 'body', 'attempt']) {
    const { attempt, pinnedKey } = signedAttempt();
    let key = pinnedKey;
    if (variant === 'key') key = signedAttempt().pinnedKey;
    if (variant === 'manifest') attempt.prepared.manifest.model = 'different';
    if (variant === 'body') attempt.request_base64 = Buffer.from('changed').toString('base64');
    if (variant === 'attempt') attempt.capture_id = 'different';
    await assert.rejects(h.verify(attempt, key), /Private capture verification failed; nothing was downloaded/);
  }
});

test('a zero or unavailable mounted balance stops capture grant and dispatch', async () => {
  for (const balanceUsd of ['0', '-1', 'NaN']) {
    const h = harness();
    h.api.captureCredits = async () => ({ balanceUsd, totalUsedUsd: '0', modelCalls: 0, source: 'mounted key' });
    assert.equal(await h.render().start({ ...base, auditCaptureConsent: consent }, 7), null);
    assert.equal(h.calls.length, 0);
    assert.match(h.render().error, /Existing Gateway credit is unavailable/);
  }
});
