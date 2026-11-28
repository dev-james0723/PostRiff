// Offline handoff tests. The real Rafii API, permissions, video checks, fingerprint and TUS
// client run against in-memory endpoints. Browser decoding and Supabase sessions are fixtures.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../web/node_modules/typescript');

const workspace = '11111111-1111-4111-8111-111111111111';
const otherWorkspace = '22222222-2222-4222-8222-222222222222';
const owner = '33333333-3333-4333-8333-333333333333';
const otherUser = '44444444-4444-4444-8444-444444444444';
const asset = 'a'.repeat(32);
const endpoint = 'https://oxacvkhpfgytkepxcaqh.storage.supabase.co/storage/v1/upload/resumable';
const videos = `/api/workspaces/${workspace}/media/videos`;
const assetPath = `/api/workspaces/${workspace}/library/assets/${asset}`;

function memoryStorage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key)
  };
}

const compiled = new Map();
function loadModule(file, context, resolve) {
  if (!compiled.has(file)) {
    compiled.set(file, ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, allowJs: true }
    }).outputText);
  }
  const result = {};
  const run = vm.runInContext(`(function(require, exports) {${compiled.get(file)}\n})`, context, { filename: file });
  run(resolve, result);
  return result;
}

function element(tag) {
  const listeners = new Map();
  return {
    tag, children: [], textContent: '', disabled: false,
    addEventListener: (name, fn) => listeners.set(name, fn),
    emit: (name, detail) => listeners.get(name)?.({ detail }),
    append(...nodes) { this.children.push(...nodes); },
    prepend(...nodes) { this.children.unshift(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(key, value) { this[key] = value; }
  };
}

function fixture({ mount = false } = {}) {
  const localStorage = memoryStorage();
  const sessionStorage = memoryStorage();
  localStorage.setItem('postriff-workspace', workspace);
  const panel = element('div');
  const document = {
    ...element('document'), cookie: `postriff_workspace=${workspace}`, createElement: element,
    getElementById: id => mount && id === 'workspace-transfer' ? panel : null
  };
  const context = vm.createContext({
    Blob, File, URL, Response, Request, Headers, AbortController, AbortSignal, crypto: globalThis.crypto,
    TextEncoder, TextDecoder, Uint8Array, Error, console, setTimeout, clearTimeout, btoa, localStorage, sessionStorage,
    document
  });
  const state = { user: owner, role: 'editor', calls: [], storageError: false, lostBegin: false, offset: 0 };
  const blob = new Blob([Buffer.from('000000106674797069736f6d00000000000000086d6f6f76000000096d64617401', 'hex')], { type: 'video/mp4' });
  const cut = { blob, title: 'Fixture cut', aspectRatio: '16:9' };
  const user = () => ({ id: state.user, email: 'editor@example.invalid' });
  const auth = {
    getSession: async () => ({ data: { session: state.user && { user: user(), access_token: `token-${state.user}` } } }),
    getUser: async token => ({ data: { user: token === `token-${state.user}` && state.user ? user() : null } })
  };
  const ticket = {
    assetId: asset, method: 'TUS', expiresAt: Date.now() / 1000 + 600, maxBytes: 1000000,
    resumable: { protocol: 'tus', endpoint, chunkBytes: 6 * 1024 * 1024, headers: { 'x-signature': 'test-grant' },
      metadata: { bucketName: 'test-videos', objectName: `${workspace}/video/${asset}.mp4`, contentType: 'video/mp4', cacheControl: '3600' } }
  };
  context.fetch = async (url, init = {}) => {
    const method = init.method || 'GET';
    const headers = new Headers(init.headers);
    state.calls.push({ method, url, body: init.body });
    if (method === 'GET' && url === '/api/auth/config') {
      return Response.json({ provider: 'supabase', projectUrl: 'https://oxacvkhpfgytkepxcaqh.supabase.co', publishableKey: 'sb_publishable_test' });
    }
    if (url.startsWith(endpoint)) {
      assert.equal(headers.get('authorization'), null);
      assert.equal(headers.get('x-signature'), 'test-grant');
      if (method === 'POST') return new Response(null, { status: 201, headers: { Location: endpoint + '/session' } });
      if (method === 'HEAD') return new Response(null, { headers: { 'Upload-Length': String(blob.size), 'Upload-Offset': String(state.offset) } });
      if (method === 'PATCH') {
        if (state.storageError) return new Response(null, { status: 403 });
        state.offset += init.body.size;
        return new Response(null, { status: 204, headers: { 'Upload-Offset': String(state.offset) } });
      }
    }
    if (url !== '/api/ideas/models') assert.equal(headers.get('authorization'), `Bearer token-${state.user}`);
    if (method === 'GET' && url === '/api/workspaces') return Response.json({ workspaces: [
      { workspaceId: otherWorkspace, name: 'Other', membership: { role: 'owner' } },
      { workspaceId: workspace, name: 'Edit room', membership: { role: state.role } }
    ] });
    if (method === 'GET' && url === '/api/me') return Response.json({ userId: state.user, displayName: 'Test editor', mfa: { enforced: false } });
    if (method === 'GET' && url === '/api/ideas/models') return Response.json({ attachments: { video: { enabled: true, maxSeconds: 180, maxBytes: 1000000 } } });
    if (url === videos && method === 'POST') {
      if (state.lostBegin) throw new TypeError('begin response lost');
      state.afterBegin?.();
      return Response.json({ upload: ticket });
    }
    if (url === `${videos}/${asset}/resume` && method === 'POST') return Response.json({ assetId: asset, objectComplete: false, upload: ticket });
    if (url === `${videos}/${asset}/commit` && method === 'POST') {
      return Response.json({ revision: 2, video: { assetId: asset, duration: 4, bytes: state.offset, verified: { container: true } } });
    }
    if (url === assetPath && method === 'PATCH') return Response.json({ assetId: asset, status: 'updated' });
    throw new Error(`Unexpected request: ${method} ${url}`);
  };
  const shared = name => loadModule(path.join(__dirname, '../web/src/', name + '.ts'), context);
  const modules = {
    'client': shared('lib/api/client'), 'permissions': shared('lib/auth/permissions'),
    'resumable-upload': shared('lib/api/resumable-upload'), 'ssr': { createBrowserClient: () => ({ auth }) },
    'video-file': { ...shared('features/agent/attachments/video-file'),
      readVideoMetadata: async () => ({ width: 640, height: 360, duration: 4 }), extractFrames: async () => [] }
  };
  const studio = loadModule(path.join(__dirname, 'studio-workspace.js'), context, specifier => {
    const key = path.basename(specifier).replace(/\.ts$/, '');
    assert.ok(Object.hasOwn(modules, key), `Unexpected module ${specifier}`);
    return modules[key];
  });
  const options = { auth, signal: new AbortController().signal, status() {} };
  const pending = {};
  const send = (destination, transferState = pending) => studio.transferCut(cut, destination, transferState, options);
  return { context, state, ticket, cut, panel, document, check: () => studio.readDestination(auth), send };
}

test('destination check reads the selected workspace and discloses its account without reserving storage', async () => {
  const f = fixture();
  const destination = await f.check();
  assert.equal(destination.workspaceId, workspace);
  assert.equal(destination.name, 'Edit room');
  assert.equal(destination.userId, owner);
  assert.ok(destination.account);
  assert.ok(f.state.calls.length > 0);
  assert.ok(f.state.calls.every(request => request.method === 'GET'));
});

test('a read-only membership and a signed-out browser cannot reserve an upload', async () => {
  const f = fixture();
  f.state.role = 'viewer';
  await assert.rejects(f.check);
  f.state.user = null;
  await assert.rejects(f.check);
  assert.ok(f.state.calls.every(request => request.method === 'GET'));
});

test('changing the account after destination confirmation prevents all upload writes', async () => {
  const f = fixture();
  const destination = await f.check();
  f.state.user = otherUser;
  await assert.rejects(f.send(destination));
  assert.ok(f.state.calls.every(request => request.method === 'GET'));
});

test('switching the active workspace after confirmation prevents an upload to the old destination', async () => {
  const f = fixture();
  const destination = await f.check();
  f.context.localStorage.setItem('postriff-workspace', otherWorkspace);
  f.context.document.cookie = `postriff_workspace=${otherWorkspace}`;
  await assert.rejects(f.send(destination));
  assert.ok(f.state.calls.every(request => request.method === 'GET'));
});

test('switching accounts while the ticket returns prevents any storage or commit writes', async () => {
  const f = fixture();
  const destination = await f.check();
  f.state.afterBegin = () => { f.state.user = otherUser; };
  await assert.rejects(f.send(destination));
  assert.deepEqual(f.state.calls.filter(request => request.method !== 'GET').map(request => request.url), [videos]);
});

test('losing the begin response leaves one reservation attempt after explicit retry', async () => {
  const f = fixture();
  const destination = await f.check();
  f.state.lostBegin = true;
  await assert.rejects(f.send(destination));
  f.state.lostBegin = false;
  await assert.rejects(f.send(destination));
  await assert.rejects(f.send(destination, {})); // Lost in-memory state (editor reopened in this tab).
  assert.deepEqual(f.state.calls.filter(request => request.method !== 'GET').map(request => request.url), [videos]);
});

test('after a storage refusal, retry resumes the original asset, commits uploaded bytes and names it', async () => {
  const f = fixture();
  const destination = await f.check();
  f.state.storageError = true;
  await assert.rejects(f.send(destination));
  const before = f.state.calls.length;
  f.state.storageError = false;
  const receipt = await f.send(destination);
  assert.equal(receipt.assetId, asset);
  assert.equal(f.state.calls.filter(request => request.url === videos).length, 1);
  const writes = f.state.calls.slice(before).filter(request => request.method !== 'GET');
  assert.deepEqual(writes.map(request => request.url), [
    `${videos}/${asset}/resume`, endpoint + '/session', endpoint + '/session', `${videos}/${asset}/commit`, assetPath
  ]);
  assert.equal(JSON.parse(writes.at(-1).body).title.includes('Fixture cut'), true);
  assert.ok(f.state.offset > 0);
});

test('reopening a completed cut in the tab returns its receipt without a second transfer', async () => {
  const f = fixture();
  const destination = await f.check();
  const first = await f.send(destination);
  const before = f.state.calls.length;
  const reopened = await f.send(destination, {});
  assert.equal(first.assetId, asset);
  assert.equal(reopened.assetId, asset);
  assert.ok(f.state.calls.slice(before).every(request => request.method === 'GET'));
});

test('a mismatched workspace path in a signed ticket receives zero bytes', async () => {
  const f = fixture();
  f.ticket.resumable.metadata.objectName = `${otherWorkspace}/video/${asset}.mp4`;
  const destination = await f.check();
  await assert.rejects(f.send(destination));
  assert.equal(f.state.offset, 0);
  assert.deepEqual(f.state.calls.filter(request => request.method !== 'GET').map(request => request.url), [videos]);
});

test('cut-ready waits for two distinct clicks, sends once and opens Creative Studio with the saved reference', async () => {
  const f = fixture({ mount: true });
  f.document.emit('rafii:cut-ready', f.cut);
  assert.equal(f.state.calls.length, 0);
  const [actions, message] = f.panel.children;
  const [button, workspaceLink] = actions.children;
  assert.equal(workspaceLink.href, '/app/creative?workspace=1');
  assert.equal(button.textContent, 'Check Library destination');

  await button.emit('click');
  assert.ok(f.state.calls.every(request => request.method === 'GET'));
  assert.match(message.textContent, /editor@example\.invalid/);
  assert.match(button.textContent, /Save MP4 to Edit room/);
  await Promise.all([button.emit('click'), button.emit('click')]);
  assert.deepEqual(actions.children.map(link => link.href), [
    `/app/creative?reference=${asset}`, '/app/library'
  ]);
  assert.equal(f.state.calls.filter(request => request.url === videos).length, 1);

  const before = f.state.calls.length;
  f.document.emit('rafii:cut-invalidated');
  assert.equal(f.panel.children.length, 0);
  await button.emit('click');
  assert.equal(f.state.calls.length, before);
});

test('invalidating an approved cut before the save click prevents any write', async () => {
  const f = fixture({ mount: true });
  f.document.emit('rafii:cut-ready', f.cut);
  const [button] = f.panel.children[0].children;
  await button.emit('click');
  f.document.emit('rafii:cut-invalidated');
  await button.emit('click');
  assert.ok(f.state.calls.every(request => request.method === 'GET'));
  assert.equal(f.panel.children.length, 0);
});
