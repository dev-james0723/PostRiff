/** Local synthetic identity/media browser journey. Run with the disposable hosted harness and Next dev server. */
const { chromium } = require('playwright');
const { randomUUID } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const apiBase = process.env.RAFII_API_URL || 'http://127.0.0.1:4399';
const webBase = process.env.RAFII_WEB_URL || 'http://localhost:3199';
const pgPort = process.env.RAFII_PG_PORT || '55442';
const videoPath = process.env.RAFII_VIDEO_FIXTURE || '/tmp/rafii-context-fixture.mp4';
const out = process.env.RAFII_QA_OUT || '/tmp/rafii-context-qa';
for (const origin of [apiBase, webBase]) assert.match(new URL(origin).hostname, /^(localhost|127\.0\.0\.1)$/);
assert.ok(fs.existsSync(videoPath), `Generate the synthetic MP4 fixture at ${videoPath}`);
fs.mkdirSync(out, { recursive: true });
const principal = randomUUID();
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer dev:${principal}`, 'X-PostRiff-Request': 'founder-alpha' };
const checks = [];
function check(name, condition) { assert.ok(condition, name); checks.push(name); process.stdout.write(`ok ${name}\n`); }
async function call(method, route, body) {
  const response = await fetch(apiBase + route, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const result = await response.text();
  if (!response.ok) throw Error(`${method} ${route}: ${response.status} ${result.slice(0, 400)}`);
  return result ? JSON.parse(result) : null;
}
function sql(query) {
  const command = spawnSync('/opt/homebrew/opt/postgresql@17/bin/psql',
    [`host=127.0.0.1 port=${pgPort} dbname=postgres`, '-v', 'ON_ERROR_STOP=1', '-Atc', query], { encoding: 'utf8' });
  if (command.status !== 0) throw Error(`Synthetic seed failed: ${command.stderr}`);
  return command.stdout.trim();
}
async function context(browser, viewport, reducedMotion = 'no-preference') {
  const mobile = viewport.width < 768;
  const browserContext = await browser.newContext({ viewport, deviceScaleFactor: mobile ? 3 : 1, isMobile: mobile, hasTouch: mobile, reducedMotion, colorScheme: 'dark' });
  await browserContext.addCookies([
    { name: 'postriff_dev', value: '1', url: webBase },
    { name: 'postriff_dev_principal', value: principal, url: webBase },
    { name: 'postriff_theme', value: 'rafii', url: webBase }
  ]);
  await browserContext.addInitScript((id) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem('postriff-onboarding', JSON.stringify({ completed: {}, dismissed: {}, nudged: {} }));
    window.__scrollBehaviors = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function(options) {
      window.__scrollBehaviors.push(typeof options === 'object' ? options.behavior : String(options));
      return original.call(this, options);
    };
  }, principal);
  const video = fs.readFileSync(videoPath);
  await browserContext.route('https://dev.invalid/**', (route) => route.fulfill({ status: 200, body: video, contentType: 'video/mp4', headers: { 'Access-Control-Allow-Origin': '*' } }));
  return browserContext;
}
async function ready(page, conversationId) {
  await page.goto(`${webBase}/app/agent/${conversationId}`, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.getByRole('heading', { name: 'Navigation research' }).waitFor({ timeout: 120000 });
  const width = page.viewportSize()?.width ?? 1440;
  if (width >= 1024) await page.getByRole('navigation', { name: 'Thread map' }).locator('button').first().waitFor({ timeout: 120000 });
  else await page.getByRole('button', { name: /Open thread map/ }).waitFor({ timeout: 120000 });
}
function noOverflow(page) { return page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1); }

(async () => {
  const { workspaceId } = await call('POST', '/api/auth/verify', {});
  const conversation = await call('POST', `/api/workspaces/${workspaceId}/ideas/conversations`, { title: 'Navigation research' });
  const conversationId = conversation.conversationId;
  const assetId = randomUUID().replaceAll('-', '');
  sql(`INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body)
       SELECT '${conversationId}'::uuid,'${workspaceId}'::uuid,n,
              CASE WHEN n % 2 = 0 THEN 'assistant' ELSE 'user' END,
              jsonb_build_object('text',CASE WHEN n=973 THEN 'Unique research context at turn 973，導航片段' ELSE 'Turn ' || n || ' about navigation' END)
       FROM generate_series(1,1101) n;
       UPDATE public.pr_conversations SET updated_at=now() WHERE id='${conversationId}'::uuid;
       UPDATE public.pr_workspaces SET state=state || jsonb_build_object('phase2',
         coalesce(state->'phase2','{}'::jsonb) || jsonb_build_object('assets',
         coalesce(state->'phase2'->'assets','[]'::jsonb) || jsonb_build_array(jsonb_build_object(
           'id','${assetId}','mime','video/mp4','processing','ready','duration',4,'objectName','browser-fixture.mp4'))))
       WHERE id='${workspaceId}'::uuid;`);
  const target = sql(`SELECT id::text FROM public.pr_messages WHERE conversation_id='${conversationId}'::uuid AND seq=973`);
  await call('POST', `/api/workspaces/${workspaceId}/ideas/conversations/${conversationId}/moments`, { assetId, title: 'Practice clip', seconds: 1.25 });
  const browser = await chromium.launch({ headless: true });
  try {
    const desktop = await context(browser, { width: 1440, height: 900 });
    const page = await desktop.newPage();
    await ready(page, conversationId);
    await page.waitForFunction(() => document.querySelector('[aria-label*="of 1102"]'), null, { timeout: 30000 });
    const rail = page.getByRole('navigation', { name: 'Thread map' });
    check('desktop thread map is visible and bounded', await rail.isVisible() && await rail.locator('button').count() <= 36);
    const marker = rail.locator('button').first();
    await marker.focus();
    check('desktop marker has focus preview', await rail.getByText(/Your request|Rafii response/).first().isVisible());
    await marker.click();
    await rail.getByRole('button', { name: /Turn 1 about navigation/ }).last().click();
    await page.waitForURL((url) => url.searchParams.has('turn'), { timeout: 10000 });
    check('desktop marker changes deep-link URL', new URL(page.url()).searchParams.has('turn'));
    const preview = page.getByRole('link', { name: /Navigation research/ }).first();
    await preview.focus();
    check('conversation preview exposes real excerpt on focus', await preview.getByText(/Turn 1101 about navigation/).isVisible());
    check('desktop has no horizontal overflow', await noOverflow(page));
    await page.screenshot({ path: path.join(out, 'desktop-thread-map.png') });

    await page.getByRole('button', { name: /Search\.\.\./ }).first().click();
    const search = page.getByPlaceholder('Jump to a conversation or turn…');
    await search.waitFor({ timeout: 10000 });
    await search.fill('Unique research context');
    await page.getByText(/Unique research context at turn 973/).first().waitFor({ timeout: 10000 });
    await page.getByText(/Unique research context at turn 973/).first().click();
    await page.waitForURL((url) => url.searchParams.get('turn') === target, { timeout: 30000 });
    await page.locator(`#turn-${target}`).waitFor({ timeout: 30000 });
    check('search jumps to exact turn outside initial message window', await page.locator(`#turn-${target}`).isVisible() && await page.locator('ol > li[id^="turn-"]').count() <= 102);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator(`#turn-${target}`).waitFor({ timeout: 30000 });
    check('exact turn deep link survives reload', new URL(page.url()).searchParams.get('turn') === target);
    await page.getByRole('button', { name: 'Jump to latest' }).click();
    await page.getByText('Saved moment · Practice clip').waitFor({ timeout: 30000 });
    await page.getByRole('button', { name: 'Play from 00:01' }).click();
    await page.getByLabel('Now Playing').waitFor({ timeout: 10000 });
    check('Rafii-owned media opens persistent Now Playing', await page.getByLabel('Now Playing').getByText('Practice clip').isVisible());
    await page.getByLabel('Now Playing').getByRole('button', { name: 'Save moment' }).click();
    await page.getByText(/Moment saved to this conversation/).waitFor({ timeout: 10000 });
    await page.getByRole('button', { name: 'Make content' }).first().click();
    check('Moment uses existing composer as context', /Make content inspired by this moment/.test(await page.getByRole('textbox', { name: 'Message' }).inputValue()));
    await page.getByRole('link', { name: 'Library', exact: true }).first().click();
    await page.waitForURL(/\/app\/library(?:[/?#]|$)/, { timeout: 90000, waitUntil: 'domcontentloaded' });
    check('Now Playing persists across client-side app navigation', await page.getByLabel('Now Playing').isVisible());
    await page.screenshot({ path: path.join(out, 'desktop-now-playing.png') });
    await desktop.close();

    const phone = await context(browser, { width: 390, height: 844 }, 'reduce');
    const mobile = await phone.newPage();
    await ready(mobile, conversationId);
    check('phone uses compact control instead of desktop rail', !await mobile.getByRole('navigation', { name: 'Thread map' }).isVisible() && await mobile.getByRole('button', { name: /Open thread map/ }).isVisible());
    await mobile.getByRole('button', { name: /Open thread map/ }).click();
    await mobile.getByRole('dialog', { name: 'Thread map' }).waitFor({ timeout: 10000 });
    check('phone sheet lists navigable groups', await mobile.getByRole('dialog', { name: 'Thread map' }).getByRole('button').count() > 0);
    await mobile.screenshot({ path: path.join(out, 'phone-thread-sheet.png') });
    const group = mobile.getByRole('dialog', { name: 'Thread map' }).getByRole('button').first();
    await group.click();
    await mobile.evaluate(() => { window.__scrollBehaviors = []; });
    await mobile.getByRole('dialog', { name: 'Thread map' }).getByRole('button').filter({ hasText: /Turn 1 about navigation/ }).first().click();
    await mobile.waitForURL((url) => url.searchParams.has('turn'), { timeout: 15000 });
    check('phone sheet jumps to an exact turn', new URL(mobile.url()).searchParams.has('turn'));
    await mobile.waitForFunction(() => window.__scrollBehaviors.includes('auto'), null, { timeout: 10000 });
    check('reduced motion uses a non-animated jump', (await mobile.evaluate(() => window.__scrollBehaviors)).includes('auto'));
    check('phone has no horizontal overflow', await noOverflow(mobile));
    check('phone composer remains usable', await mobile.getByRole('textbox', { name: 'Message' }).isVisible());
    await mobile.screenshot({ path: path.join(out, 'phone-conversation.png') });
    await phone.close();
    process.stdout.write(JSON.stringify({ status: 'passed', execution: 'local synthetic', checks, screenshots: out }) + '\n');
  } finally { await browser.close(); }
})().catch((error) => { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1; });
