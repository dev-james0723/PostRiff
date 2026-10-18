const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(relative) {
  const file = path.resolve(__dirname, relative);
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const exports = {};
  new Function('exports', 'require', compiled)(exports, require);
  return exports;
}

const view = load('../src/lib/substack/presentation.ts');
const { createApi, ApiError } = load('../src/lib/api/client.ts');
const hash = 'a'.repeat(64);
const connection = {
  id: 'feed-a', mode: 'public_feed', status: 'feed_added', publicationUrl: 'https://alice.substack.com',
  ownershipVerified: false, accountAuthenticated: false, analyticsConnected: false, publishingAuthorized: false
};
const draft = { id: 'draft-a', connectionId: 'feed-a', contentHash: hash, approvedHash: hash, status: 'approved' };
const handoff = {
  status: 'manual_action_required', autoPublished: false, contentHash: hash, publicationUrl: connection.publicationUrl,
  title: 'My draft', body: '<script>doNotRun()</script>\nDraft text', format: 'markdown', scheduledFor: null
};

test('a public feed cannot acquire ownership, OAuth, analytics or publishing through inconsistent flags', () => {
  const claims = view.substackConnectionClaims({ ...connection, ownershipVerified: true, accountAuthenticated: true, analyticsConnected: true, publishingAuthorized: true });
  assert.equal(claims[0].label, 'Public Feed Added');
  assert.equal(claims[0].verified, true);
  assert.ok(claims.slice(1).every((claim) => claim.verified === false));
});

test('MCP analytics cannot turn into publishing authorization and revocation removes all positive claims', () => {
  const mcp = { ...connection, mode: 'official_mcp_analytics', status: 'connected', accountAuthenticated: true, analyticsConnected: true, publishingAuthorized: true };
  const claims = view.substackConnectionClaims(mcp);
  assert.equal(claims.find((claim) => claim.label.startsWith('Analytics')).verified, true);
  assert.equal(claims.find((claim) => claim.label === 'Publishing Authorized').verified, false);
  for (const status of ['disconnected', 'revoked', 'permission_missing', 'unknown']) {
    assert.ok(view.substackConnectionClaims({ ...mcp, status }).every((claim) => claim.verified === false));
  }
});

test('unknown or incomplete capability data does not enable an operation', () => {
  for (const status of ['unsupported', 'requires_official_approval', 'requires_account_eligibility', 'permission_missing', 'temporarily_unavailable', 'ready', true, undefined]) {
    assert.equal(view.substackAvailable({ post_publish: { status } }, 'post_publish'), false);
  }
  assert.equal(view.substackAvailable({}, 'post_publish'), false);
  assert.equal(view.substackAvailable({ draft_create: { status: 'available' } }, 'draft_create'), true);
});

test('links reject executable schemes, credentials, alternate ports and lookalike publication hosts', () => {
  // Deliberately fake userinfo assembled as URL fields, never a stored credential.
  const credentialedPublication = new URL('https://alice.substack.com');
  const fakeUserinfo = ['name', 'secret'];
  [credentialedPublication.username, credentialedPublication.password] = fakeUserinfo;
  for (const url of [
    'javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'file:///etc/passwd',
    'http://alice.substack.com', credentialedPublication.href, 'https://alice.substack.com:8443',
    'https://alice.substack.com.evil.example', 'https://substack.com@evil.example', 'https://127.0.0.1',
    'https://alice.local.substack.com', '//alice.substack.com', '', null
  ]) assert.equal(view.safeSubstackHref(url), null, String(url));
  assert.equal(view.safeSubstackHref('https://alice.substack.com/p/one'), 'https://alice.substack.com/p/one');
  assert.equal(view.safeSubstackHref('https://alice.substack.com/p/one', 'https://alice.substack.com'), 'https://alice.substack.com/p/one');
  assert.equal(view.safeSubstackHref('https://another.substack.com/p/one', 'https://alice.substack.com'), null);
});

test('handoff eligibility requires the exact reviewed digest and an active destination', () => {
  assert.equal(view.approvedSubstackDraft(draft, connection), true);
  assert.equal(view.approvedSubstackDraft({ ...draft, status: 'handoff_ready' }, connection), true);
  for (const changed of [{ contentHash: 'b'.repeat(64) }, { approvedHash: null }, { status: 'draft' }, { status: 'canceled' }, { contentHash: 'short', approvedHash: 'short' }]) {
    assert.equal(view.approvedSubstackDraft({ ...draft, ...changed }, connection), false);
  }
  assert.equal(view.approvedSubstackDraft(draft, undefined), false);
  assert.equal(view.approvedSubstackDraft(draft, { ...connection, status: 'disconnected' }), false);
  assert.equal(view.approvedSubstackDraft(draft, { ...connection, id: 'another-publication' }), false);
});

test('handoff export rejects a false publish success and mismatched content instead of downloading', () => {
  assert.equal(view.substackHandoffMarkdown(handoff, hash), '# My draft\n\n<script>doNotRun()</script>\nDraft text\n');
  for (const changed of [
    { contentHash: 'b'.repeat(64) }, { status: 'published' }, { autoPublished: true }, { autoPublished: undefined },
    { publicationUrl: 'javascript:alert(1)' }, { format: 'html' }
  ]) assert.throws(() => view.substackHandoffMarkdown({ ...handoff, ...changed }, hash), /receipt did not match/);
});

test('an untitled Note exports its exact body without inventing a heading', () => {
  const body = '  A Note without a title.\n\nKeep the author’s spacing.  ';
  assert.equal(view.substackHandoffMarkdown({ ...handoff, contentType: 'note', title: '', body }, hash), body + '\n');
  assert.equal(view.substackHandoffMarkdown({ ...handoff, contentType: 'note', title: '  ', body }, hash), body + '\n');
});

test('empty editorial target stays optional and invalid dates do not become an epoch schedule', () => {
  assert.equal(view.fromSubstackLocalDateTime(''), null);
  assert.equal(view.toSubstackLocalDateTime(null), '');
  assert.equal(view.toSubstackLocalDateTime('not a date'), '');
  assert.throws(() => view.fromSubstackLocalDateTime('not a date'), /valid target handoff/);
  assert.equal(new Date(view.fromSubstackLocalDateTime('2026-10-20T12:30')).getMinutes(), 30);
});

test('the Substack flow is recognized independently of ordinary OAuth provider names', () => {
  assert.equal(view.isSubstackProvider({ id: 'substack', platform: 'Substack' }), true);
  assert.equal(view.isSubstackProvider({ id: 'partner', platform: 'SUBSTACK' }), true);
  assert.equal(view.isSubstackProvider({ id: 'mastodon', platform: 'Mastodon' }), false);
});

test('all Substack requests carry the existing authenticated workspace boundary and exact revision', async () => {
  const previousFetch = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, ...options }); return Response.json({ revision: 5 }); };
  try {
    const api = createApi(async () => 'synthetic-substack-session');
    const workspace = 'workspace/other';
    const id = 'item/other';
    const revision = { expectedRevision: 4 };
    const content = { ...revision, contentHash: hash };
    await api.substackCapabilities(workspace);
    await api.substackWorkspace(workspace);
    await api.substackAddFeed(workspace, { ...revision, publicationUrl: connection.publicationUrl, mode: 'public_feed', confirmed: true });
    await api.substackDisconnect(workspace, id, revision);
    await api.substackRefreshFeed(workspace, id, revision);
    const input = { ...revision, connectionId: 'feed-a', title: 'Draft', body: 'Text', scheduledFor: null, contentType: 'article', audience: 'everyone' };
    await api.substackCreateDraft(workspace, input);
    await api.substackUpdateDraft(workspace, id, input);
    await api.substackApproveDraft(workspace, id, { ...content, confirmed: true });
    await api.substackHandoff(workspace, id, content);
    await api.substackCancelDraft(workspace, id, content);
    await api.substackDeleteDraft(workspace, id, content);
    const prefix = '/api/workspaces/workspace%2Fother/substack/';
    assert.deepEqual(calls.map((call) => call.url), [
      'capabilities', 'workspace', 'connections', 'connections/item%2Fother/disconnect', 'connections/item%2Fother/refresh',
      'drafts', 'drafts/item%2Fother', 'drafts/item%2Fother/approve', 'drafts/item%2Fother/handoff',
      'drafts/item%2Fother/cancel', 'drafts/item%2Fother'
    ].map((suffix) => prefix + suffix));
    assert.ok(calls.every((call) => call.headers.Authorization === 'Bearer synthetic-substack-session'));
    assert.ok(calls.every((call) => call.headers['X-PostRiff-Request'] === 'founder-alpha'));
    assert.ok(calls.slice(2).every((call) => JSON.parse(call.body).expectedRevision === 4));
    assert.equal(calls[0].cache, 'no-store');
    assert.equal(calls[1].cache, 'no-store');
    assert.equal(calls[6].method, 'PATCH');
    assert.equal(calls.at(-1).method, 'DELETE');
    assert.deepEqual(JSON.parse(calls[7].body), { expectedRevision: 4, contentHash: hash, confirmed: true });
    assert.deepEqual(JSON.parse(calls[8].body), content);
  } finally { global.fetch = previousFetch; }
});

test('a missing Rafii session stops a Substack action before any network request', async () => {
  const previousFetch = global.fetch;
  let calls = 0;
  global.fetch = async () => { calls += 1; return Response.json({}); };
  try {
    const api = createApi(async () => null);
    await assert.rejects(() => api.substackHandoff('w', 'draft', { expectedRevision: 1, contentHash: hash }), (error) => error instanceof ApiError && error.status === 401);
    assert.equal(calls, 0);
  } finally { global.fetch = previousFetch; }
});

test('a stale approval or missing grant propagates an error instead of a successful handoff', async () => {
  const previousFetch = global.fetch;
  try {
    for (const [status, code] of [[409, 'substack_approval_stale'], [403, 'token_scope_denied'], [503, 'provider_unavailable']]) {
      global.fetch = async () => Response.json({ error: 'Action refused', code }, { status });
      const api = createApi(async () => 'synthetic-session');
      await assert.rejects(() => api.substackHandoff('w', 'draft', { expectedRevision: 1, contentHash: hash }), (error) => error instanceof ApiError && error.status === status && error.code === code);
    }
  } finally { global.fetch = previousFetch; }
});
