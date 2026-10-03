/** Real production-built Founder form + Supabase SDK + Chromium WebAuthn. Auth/Control servers are local fixtures, not production acceptance. */
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = (process.env.FOUNDER_SIGNIN_WEB_URL || 'http://localhost:4499').replace(/\/$/, '');
if (!['localhost', '127.0.0.1'].includes(new URL(base).hostname)) throw new Error('This fixture must never run against a hosted site.');
const AUTH = 'https://founder-fixture.supabase.co';
const evidence = path.resolve(process.env.FOUNDER_SIGNIN_EVIDENCE_DIR || '.founder-signin-evidence');
const userId = '11111111-1111-4111-8111-111111111111';
const factorId = '22222222-2222-4222-8222-222222222222';
const factor = { id: factorId, factor_type: 'totp', friendly_name: 'Fixture authenticator', status: 'verified', created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' };
function token(aal, email) {
  const now = Math.floor(Date.now() / 1000);
  return [Buffer.from('{"alg":"HS256","typ":"JWT"}').toString('base64url'), Buffer.from(JSON.stringify({ sub: userId, email, aud: 'authenticated', role: 'authenticated', iat: now, exp: now + 3600, aal, amr: [{ method: aal === 'aal2' ? 'totp' : 'passkey', timestamp: now }] })).toString('base64url'), Buffer.from('fixture-signature').toString('base64url')].join('.');
}

async function fixture(browser, options = {}) {
  const context = await browser.newContext({ viewport: { width: options.width || 390, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const state = { paths: [], exchange: 0, registered: 0, logout: 0, signatureVerified: false, enrolled: options.enrolled !== false, pageErrors: [], blocked: [] };
  const email = options.wrongAccount ? 'other@example.test' : 'owner@example.test';
  const user = { id: userId, email, email_confirmed_at: '2026-10-01T00:00:00Z', aud: 'authenticated', role: 'authenticated', app_metadata: { provider: 'email', providers: ['email'] }, user_metadata: {}, created_at: '2026-10-01T00:00:00Z', factors: [factor] };
  const session = (aal) => ({ access_token: token(aal, email), token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: 'synthetic-refresh-token', user });
  const key = crypto.generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  const credentialId = crypto.randomBytes(32);
  const challenge = crypto.randomBytes(32).toString('base64url');
  const registrationChallenge = crypto.randomBytes(32).toString('base64url');
  const cdp = await context.newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', { options: { protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  await cdp.send('WebAuthn.addCredential', { authenticatorId, credential: { credentialId: credentialId.toString('base64'), isResidentCredential: true, rpId: 'localhost', privateKey: key.privateKey.export({ type: 'pkcs8', format: 'der' }).toString('base64'), userHandle: Buffer.from(userId).toString('base64'), signCount: 0 } });
  page.on('pageerror', (error) => state.pageErrors.push(error.message));
  await context.addInitScript(({ cancel, unsupported }) => {
    localStorage.setItem('consumer-fixture', 'untouched');
    if (unsupported) Object.defineProperty(window, 'PublicKeyCredential', { value: undefined, configurable: true });
    if (cancel) navigator.credentials.get = async () => { throw new DOMException('The operation was cancelled.', 'NotAllowedError'); };
  }, { cancel: options.cancel, unsupported: options.unsupported });
  await context.route('**/*', async (route) => {
    const request = route.request(); const url = new URL(request.url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': base, 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Credentials': 'true' }, body: JSON.stringify(body) });
    if (url.origin === AUTH) {
      if (request.method() === 'OPTIONS') return json({});
      state.paths.push(url.pathname);
      const data = request.postDataJSON();
      if (url.pathname.endsWith('/passkeys/authentication/options')) {
        if (options.disabled) return json({ code: 'passkey_disabled', error_code: 'passkey_disabled', msg: 'private provider detail' }, 400);
        return json({ challenge_id: 'fixture-challenge', options: { challenge, rpId: 'localhost', allowCredentials: [], userVerification: 'required', timeout: 10000 } });
      }
      if (url.pathname.endsWith('/passkeys/authentication/verify')) {
        assert.equal(data.challenge_id, 'fixture-challenge');
        const credential = data.credential; const response = credential.response;
        const clientData = Buffer.from(response.clientDataJSON, 'base64url'); const authData = Buffer.from(response.authenticatorData, 'base64url');
        assert.equal(JSON.parse(clientData).challenge, challenge); assert.equal(JSON.parse(clientData).origin, base);
        assert.ok(authData[32] & 4, 'the actual browser assertion requires user verification');
        assert.ok(crypto.verify('sha256', Buffer.concat([authData, crypto.createHash('sha256').update(clientData).digest()]), key.publicKey, Buffer.from(response.signature, 'base64url')));
        state.signatureVerified = true;
        return json(session('aal1'));
      }
      if (url.pathname.endsWith('/authorize')) {
        assert.equal(url.searchParams.get('provider'),'google');assert.equal(url.searchParams.get('code_challenge_method'),'s256');
        state.googleChallenge=url.searchParams.get('code_challenge');
        const target=new URL(url.searchParams.get('redirect_to'));assert.equal(target.origin,base);assert.equal(target.pathname,'/founder/sign-in');
        target.searchParams.set('code','synthetic-google-code');
        if(options.googleStateMismatch)target.searchParams.set('founder_state','wrong-state');
        return route.fulfill({status:302,headers:{location:target.toString()}});
      }
      if (url.pathname.endsWith('/token')) {
        if(url.searchParams.get('grant_type')==='pkce') {
          assert.equal(data.auth_code,'synthetic-google-code');
          assert.equal(crypto.createHash('sha256').update(data.code_verifier).digest('base64url'),state.googleChallenge);
          state.pkceVerified=true;
        }
        return json(session('aal1'));
      }
      if (url.pathname.endsWith('/user')) return json(user);
      if (url.pathname.endsWith('/challenge')) return json({ id: 'fixture-totp-challenge', type: 'totp', expires_at: Math.floor(Date.now() / 1000) + 300 });
      if (url.pathname === `/auth/v1/factors/${factorId}/verify`) {
        assert.equal(data.code, '123456'); assert.equal(data.challenge_id, 'fixture-totp-challenge');
        return json(session('aal2'));
      }
      if (url.pathname.endsWith('/passkeys/registration/options')) {
        assert.ok(state.exchange > 0 && state.enrolled && !options.wrongAccount, 'registration must follow accepted Founder exchange');
        return json({ challenge_id: 'fixture-registration', options: { challenge: registrationChallenge, rp: { id: 'localhost', name: 'Founder local fixture' }, user: { id: Buffer.from(userId).toString('base64url'), name: email, displayName: 'Fixture owner' }, pubKeyCredParams: [{ type: 'public-key', alg: -7 }], authenticatorSelection: { residentKey: 'required', userVerification: 'required' }, timeout: 10000, attestation: 'none' } });
      }
      if (url.pathname.endsWith('/passkeys/registration/verify')) {
        const clientData = JSON.parse(Buffer.from(data.credential.response.clientDataJSON, 'base64url'));
        assert.equal(clientData.type, 'webauthn.create'); assert.equal(clientData.challenge, registrationChallenge); assert.equal(clientData.origin, base);
        state.registered += 1;
        return json({ id: '33333333-3333-4333-8333-333333333333', friendly_name: 'Virtual passkey', created_at: new Date().toISOString() });
      }
      if (url.pathname.endsWith('/logout')) { state.logout += 1; return json({}); }
      throw new Error(`Unexpected fixture Auth request: ${request.method()} ${url.pathname}`);
    }
    if (url.origin !== base) { state.blocked.push(url.origin); return route.abort(); }
    if (url.pathname === '/api/control/v2/session/exchange') {
      state.exchange += 1;
      assert.equal(request.method(), 'POST'); assert.equal(request.headers()['x-control-exchange'], '1');
      const jwt = request.headers().authorization.split(' ')[1];
      assert.equal(JSON.parse(Buffer.from(jwt.split('.')[1], 'base64url')).aal, 'aal2', 'AAL1 must never be sent for Founder exchange');
      if (options.stepUpRefused) return json({ code: 'STEP_UP_REQUIRED', message: 'private provider detail' }, 401);
      if (!state.enrolled || options.wrongAccount) return json({ code: 'FOUNDER_REQUIRED', message: 'private operator data' }, 403);
      return json({ data: { assurance: 'aal2' } });
    }
    if (url.pathname === '/founder' && request.isNavigationRequest()) return route.fulfill({ contentType: 'text/html', body: '<h1>Verified fixture Founder</h1>' });
    return route.continue();
  });
  if (options.enrolled === false) await page.clock.install();
  await page.goto(base + '/founder/sign-in?next=%2Ffounder%3Fmode%3Ddemo');
  await page.getByRole('heading', { name: 'Sign in as the founder' }).waitFor();
  return { context, page, state };
}

async function verifyCode(page) {
  await page.getByRole('heading', { name: 'Enter your authenticator code' }).waitFor();
  await page.getByLabel('Authenticator code', { exact: true }).fill('123456');
  await page.getByRole('button', { name: 'Verify founder session', exact: true }).click();
}

(async () => {
  fs.mkdirSync(evidence, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: process.env.RAFII_CHROMIUM_PATH || undefined });
  const results = [];
  async function check(name, options, work) {
    const f = await fixture(browser, options);
    try { await work(f); assert.deepEqual(f.state.pageErrors, []); assert.deepEqual(f.state.blocked, []); results.push({ name, passed: true }); console.log('PASS', name); }
    catch (error) { await f.page.screenshot({ path: path.join(evidence, 'FAIL-' + name + '.png'), fullPage: true }).catch(() => {}); results.push({ name, passed: false, detail: String(error.message).slice(0, 800) }); console.error('FAIL', name, error); }
    finally { await f.context.close(); }
  }
  try {
    await check('Google-PKCE-primary-fresh-MFA-and-storage-isolation',{width:390},async({page,state})=>{
      await page.getByRole('button',{name:'Continue with Google',exact:true}).click();
      await page.getByRole('heading',{name:'Enter your authenticator code'}).waitFor();
      assert.equal(state.pkceVerified,true);assert.equal(state.exchange,0);
      assert.equal(new URL(page.url()).searchParams.has('code'),false);
      assert.deepEqual(await page.evaluate(()=>Object.keys(sessionStorage)),[]);
      assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage)),['consumer-fixture']);
      await verifyCode(page);await page.getByRole('heading',{name:'Set up faster sign-in'}).waitFor();
      await page.getByRole('button',{name:'Continue to Founder',exact:true}).click();
      await page.getByRole('heading',{name:'Verified fixture Founder'}).waitFor();
      assert.equal(state.exchange,1);assert.equal(state.logout,0);assert.equal(state.registered,0);
    });
    await check('Google-foreign-callback-cannot-reach-MFA-or-exchange',{googleStateMismatch:true},async({page,state})=>{
      await page.getByRole('button',{name:'Continue with Google',exact:true}).click();
      await page.getByText('Sign-in could not be verified. Use your existing Rafii account and try again.').waitFor();
      assert.equal(state.pkceVerified,undefined);assert.equal(state.exchange,0);
      assert.deepEqual(await page.evaluate(()=>Object.keys(sessionStorage)),[]);
      assert.equal(await page.getByLabel('Password',{exact:true}).isEnabled(),true);
    });
    await check('mobile-passkey-MFA-and-storage-isolation', { width: 390 }, async ({ page, state }) => {
      await page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true }).waitFor();
      await page.screenshot({ path: path.join(evidence, 'mobile-sign-in.png'), fullPage: true });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
      await page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true }).click();
      await page.getByRole('heading', { name: 'Enter your authenticator code' }).waitFor();
      assert.equal(state.signatureVerified, true); assert.equal(state.exchange, 0);
      assert.deepEqual(await page.evaluate(() => Object.keys(localStorage)), ['consumer-fixture']);
      assert.equal(await page.evaluate(() => localStorage.getItem('consumer-fixture')), 'untouched');
      await verifyCode(page);
      await page.getByRole('heading', { name: 'Verified fixture Founder' }).waitFor();
      assert.equal(state.exchange, 1); assert.equal(state.logout, 0); assert.equal(state.registered, 0);
    });
    await check('password-enrollment-and-optional-native-registration', { width: 1440, enrolled: false }, async ({ page, state }) => {
      await page.screenshot({ path: path.join(evidence, 'desktop-sign-in.png'), fullPage: true });
      await page.getByLabel('Founder email').fill('owner@example.test'); await page.getByLabel('Password', { exact: true }).fill('fixture-password');
      await page.getByRole('button', { name: 'Continue', exact: true }).click(); await verifyCode(page);
      await page.getByRole('heading', { name: 'Waiting for founder enrollment' }).waitFor();
      assert.equal(state.registered, 0); assert.equal(await page.getByRole('button', { name: 'Set up Face ID / Passkey', exact: true }).count(), 0);
      state.enrolled = true;
      await page.clock.fastForward(16000);
      await page.getByRole('heading', { name: 'Set up faster sign-in' }).waitFor();
      await page.getByRole('button', { name: 'Set up Face ID / Passkey', exact: true }).click();
      await page.getByRole('heading', { name: 'Verified fixture Founder' }).waitFor();
      assert.equal(state.registered, 1); assert.equal(state.logout, 0);
    });
    await check('cancelled-prompt-is-safe-and-retryable', { cancel: true }, async ({ page, state }) => {
      await page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true }).click();
      await page.getByText('The passkey prompt was cancelled. Nothing changed.').waitFor();
      assert.equal(state.exchange, 0); assert.equal(state.paths.filter((p) => p.endsWith('/authentication/options')).length, 1);
      assert.equal(await page.getByLabel('Password', { exact: true }).isEnabled(), true);
    });
    await check('disabled-provider-retains-password-fallback', { disabled: true }, async ({ page, state }) => {
      await page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true }).click();
      await page.getByText('Passkey sign-in is unavailable here. Use your password and authenticator app instead.').waitFor();
      assert.equal(state.exchange, 0); assert.equal(await page.getByLabel('Password', { exact: true }).isEnabled(), true);
      assert.equal((await page.locator('body').innerText()).includes('private provider detail'), false);
    });
    await check('wrong-account-cannot-enroll-or-register', { wrongAccount: true }, async ({ page, state }) => {
      await page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true }).click(); await verifyCode(page);
      await page.getByRole('heading', { name: 'Waiting for founder enrollment' }).waitFor();
      await page.getByText('Account: other@example.test').waitFor();
      assert.equal(state.registered, 0);
      await page.getByRole('button', { name: 'Use a different account' }).click();
      await page.getByRole('heading', { name: 'Sign in as the founder' }).waitFor();
      assert.equal(await page.getByLabel('Password', { exact: true }).inputValue(), '');
    });
    await check('step-up-refusal-surfaces-actionable-error', { stepUpRefused: true }, async ({ page, state }) => {
      await page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true }).click(); await verifyCode(page);
      await page.getByRole('heading', { name: 'Sign in as the founder' }).waitFor();
      await page.getByText('This change needs a fresh second-factor check. Sign in again to continue.').waitFor();
      assert.equal(state.exchange, 1); assert.equal(state.registered, 0);
      assert.equal(await page.getByLabel('Password', { exact: true }).inputValue(), '');
    });
    await check('repeated-click-does-not-start-two-ceremonies', {}, async ({ page, state }) => {
      const button = page.getByRole('button', { name: 'Sign in with Face ID / Passkey', exact: true });
      await button.waitFor(); await button.evaluate((el) => { el.click(); el.click(); });
      await page.getByRole('heading', { name: 'Enter your authenticator code' }).waitFor();
      assert.equal(state.paths.filter((p) => p.endsWith('/authentication/options')).length, 1); assert.equal(state.exchange, 0);
    });
  } finally { await browser.close(); fs.writeFileSync(path.join(evidence, 'results.json'), JSON.stringify({ authority: 'local synthetic Auth/Control servers; real UI, SDK and Chromium virtual authenticator, not iPhone biometric acceptance', results }, null, 2)); }
  if (results.length !== 9 || results.some((r) => !r.passed)) process.exitCode = 1;
})().catch((error) => { console.error(error); process.exitCode = 1; });
