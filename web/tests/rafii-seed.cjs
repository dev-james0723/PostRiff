/**
 * Seeds the LOCAL dev harness for the Rafii v9 evidence run: one synthetic principal on the trial plan
 * (two connected-account slots), two distinct LinkedIn accounts (the harness's "second account"
 * consent), two overlapping folders, and one conversation drafted with the deterministic preview model
 * for both accounts plus one platform drafted without an account. Writes evidence/seed.json.
 *
 *   node web/tests/rafii-seed.cjs            (RAFII_WEB_URL defaults to http://127.0.0.1:3100)
 *
 * Identity, providers and the database are the harness's own. The quick start triggers the harness's
 * web research unless it runs with POSTRIFF_RESEARCH=0 (launch entry `postriff-api-offline`).
 */
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Seed runs against the local harness only.');
const principal = process.env.RAFII_DEV_PRINCIPAL || randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };

async function call(method, url, body) {
  const res = await fetch(base + url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* not json */ }
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${text.slice(0, 200)}`);
  return json;
}

async function connect(workspaceId, provider, second) {
  const start = await call('POST', `/api/workspaces/${workspaceId}/channels/${provider}/oauth/start`, { capability: 'publish' });
  const state = new URL(start.authorizeUrl).searchParams.get('state');
  const done = await call('POST', `/api/workspaces/${workspaceId}/channels/${provider}/oauth/complete`, { state, code: second ? 'good-code-2' : 'good-code' });
  if (!done.connected) throw new Error(`${provider} did not connect: ${JSON.stringify(done)}`);
  return done;
}

(async () => {
  const boot = await call('POST', '/api/auth/verify', {});
  const workspaceId = boot.workspaceId;
  // The trial plan has two connected-account slots: both go to LinkedIn, so one platform holds two accounts.
  const connections = [await connect(workspaceId, 'linkedin', false), await connect(workspaceId, 'linkedin', true)];
  let snapshot = await call('GET', `/api/workspaces/${workspaceId}`);
  const channels = snapshot.state.phase2.channels;
  const linkedin = channels.filter((c) => c.platform === 'LinkedIn');
  if (linkedin.length < 2) throw new Error('Expected two LinkedIn accounts; restart the API harness to load the second-account consent.');
  // Two folders that overlap on the first account: selecting both must still give one draft per account.
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, { expectedRevision: snapshot.revision, action: 'p2_folder_save', payload: { name: 'Festival', symbol: 'music', pinned: true, accountIds: [linkedin[0].id, linkedin[1].id] } });
  snapshot = await call('POST', `/api/workspaces/${workspaceId}/actions`, { expectedRevision: snapshot.revision, action: 'p2_folder_save', payload: { name: 'Personal', symbol: 'heart', pinned: true, accountIds: [linkedin[0].id] } });
  // One conversation with account-keyed destinations on the deterministic preview route.
  const run = await call('POST', `/api/workspaces/${workspaceId}/ideas/quick-start`, {
    expectedRevision: snapshot.revision,
    text: 'One thing piano practice taught me about creating: consistency matters more than waiting for inspiration.',
    ownContent: true,
    confirmUse: true,
    destinations: [
      { platform: 'LinkedIn', language: 'en-US', channelId: linkedin[0].id },
      { platform: 'LinkedIn', language: 'en-US', channelId: linkedin[1].id },
      { platform: 'Threads', language: 'en-GB' }
    ],
    model: 'deterministic-preview',
    reasoning: 'quick',
    voiceMode: 'neutral',
    timeZone: 'Asia/Hong_Kong'
  });
  const seed = { base, principal, workspaceId, connections: connections.length, channels: channels.map((c) => ({ id: c.id, platform: c.platform, account: c.account })), folders: snapshot.state.phase2.channelFolders, conversationId: run.conversationId, runId: run.runId, runStatus: run.status, variants: (run.artifact?.variants ?? []).map((v) => ({ platform: v.platform, language: v.language, channelId: v.channelId, account: v.account })) };
  const out = path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json');
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(seed, null, 2));
  console.log(JSON.stringify(seed, null, 2));
})().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
