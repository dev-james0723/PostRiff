/**
 * Privacy F6: the children's /play area never touches sign-in. The proxy must not refresh a Supabase session there
 * (no auth call, no Set-Cookie), while /app keeps its gate and the legacy-host redirect keeps running first.
 * proxy.ts is transpiled and its project imports stubbed (same approach as page-outline.test.cjs).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { NextRequest, NextResponse } = require('next/server');

function transpile(relative, stubs) {
  const file = path.join(__dirname, '..', 'src', relative);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  const fakeRequire = (id) => {
    if (id in stubs) return stubs[id];
    throw new Error(`unexpected import ${id}`);
  };
  new Function('require', 'module', 'exports', outputText)(fakeRequire, mod, mod.exports);
  return mod.exports;
}

function loadProxy({ legacyRedirect = null } = {}) {
  const calls = [];
  const playPath = transpile('lib/play-path.ts', {});
  const proxy = transpile('proxy.ts', {
    'next/server': { NextResponse, NextRequest },
    '@/lib/play-path': playPath,
    '@/lib/supabase/env': { hasSupabaseEnv: () => true },
    '@/lib/founder/errors': { CONTROL_COOKIE: '__Host-rafii-control', FOUNDER_SIGN_IN_PATH: '/founder/sign-in' },
    '@/lib/legacy-host': { legacyHostRedirect: () => legacyRedirect },
    '@/lib/supabase/middleware': {
      // Stands in for the real Supabase refresh: it would call getUser() and refresh the auth cookies.
      async updateSession(request) {
        calls.push(request.nextUrl.pathname);
        const response = NextResponse.next();
        response.cookies.set('sb-test-auth-token', 'refreshed');
        return { response, user: null };
      }
    }
  });
  return { proxy: proxy.proxy, calls };
}

const request = (pathname, headers = {}) =>
  new NextRequest(new URL(pathname, 'http://127.0.0.1:3117'), { headers: { cookie: 'sb-test-auth-token=parent', ...headers } });

test('/play routes skip the Supabase session refresh: no auth call and no Set-Cookie, even for a signed-in parent', async () => {
  const { proxy, calls } = loadProxy();
  for (const pathname of ['/play', '/play/', '/play/note-garden']) {
    const response = await proxy(request(pathname, { 'x-postriff-home-render': '1' }));
    assert.equal(response.headers.get('set-cookie'), null, `${pathname}: no cookie set or refreshed`);
    assert.equal(response.headers.get('location'), null, `${pathname}: not redirected`);
    assert.equal(response.headers.get('x-middleware-request-x-postriff-home-render'), '0', `${pathname}: a spoofed route hint is overwritten`);
  }
  assert.deepEqual(calls, [], 'updateSession never ran for /play');
});

test('/app still refreshes the session and sends signed-out visitors to sign-in; other pages still refresh', async () => {
  const { proxy, calls } = loadProxy();
  const app = await proxy(request('/app/drafts'));
  assert.equal(app.status, 307);
  assert.equal(new URL(app.headers.get('location')).pathname, '/auth/sign-in');
  const pricing = await proxy(request('/pricing'));
  assert.match(pricing.headers.get('set-cookie') ?? '', /sb-test-auth-token=refreshed/);
  const player = await proxy(request('/player'));
  assert.match(player.headers.get('set-cookie') ?? '', /sb-test-auth-token=refreshed/, '/player is not the play area');
  assert.deepEqual(calls, ['/app/drafts', '/pricing', '/player']);
});

test('the legacy-host redirect still runs before the /play shortcut', async () => {
  const { proxy, calls } = loadProxy({ legacyRedirect: { location: 'https://rafii.io/play/note-garden', status: 308 } });
  const response = await proxy(request('/play/note-garden'));
  assert.equal(response.status, 308);
  assert.equal(response.headers.get('location'), 'https://rafii.io/play/note-garden');
  assert.deepEqual(calls, []);
});
