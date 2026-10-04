/** Founder notice bell against the local Control fixture; the test notice is in-app only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3397';
if (!['localhost', '127.0.0.1'].includes(new URL(base).hostname)) throw Error('Loopback harness only');
const out = process.env.RAFII_FOUNDER_NOTIFICATION_EVIDENCE_DIR || path.resolve(__dirname, '../../docs/design/founder-admin/rafii-notification-system-2026-10-03/evidence/founder-notification-browser');
fs.mkdirSync(out, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
  const exchange = await context.request.post(base + '/api/control/v2/session/exchange', {
    headers: { Origin: base, Authorization: 'Bearer synthetic-founder-mobile-aal2', 'X-Control-Exchange': '1' }, data: {}
  });
  assert.equal(exchange.status(), 200);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(base + '/founder/settings?tab=notifications', { waitUntil: 'domcontentloaded' });
    const send = page.getByRole('button', { name: 'Send a test notice' });
    await send.waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Send a test notice'));
      return button && !button.disabled;
    }, null, { timeout: 30000 });
    assert.ok(await send.isEnabled());
    await send.click();
    await page.getByText('Test notice added', { exact: true }).waitFor();
    const bell = page.locator('header button[data-slot="popover-trigger"][aria-label^="Founder notifications,"]');
    await bell.waitFor();
    await page.waitForFunction(() => /[1-9]\d* unread/.test(document.querySelector('header button[aria-label^="Founder notifications,"]')?.getAttribute('aria-label') || ''));
    await bell.click();
    const center = page.locator('section[aria-label="Notification center"]');
    await center.waitFor();
    const stack = center.getByRole('button', { name: /Expand notification stack/ });
    await stack.tap();
    await center.getByRole('button', { name: /Collapse notification stack/ }).waitFor();
    const mark = center.getByRole('button', { name: /Mark .* as read/ }).first();
    await mark.waitFor();
    await page.waitForTimeout(400);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: path.join(out, 'founder.mobile.live.expanded.png') });
    const response = page.waitForResponse((value) => /\/api\/control\/v2\/notifications\/[^/]+\/read\?mode=live/.test(value.url()) && value.status() === 200);
    await mark.click();
    await response;
    await page.getByText('Marked as read', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'founder.mobile.read-confirmed.png') });
    let demoNoticeRequests = 0;
    const countDemoNotice = (request) => {
      if (request.method() === 'GET' && request.url().includes('/api/control/v2/notifications?mode=demo')) demoNoticeRequests += 1;
    };
    page.on('request', countDemoNotice);
    await page.goto(base + '/founder?mode=demo', { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { level: 1 }).first().waitFor();
    await page.waitForTimeout(500);
    assert.equal(demoNoticeRequests, 0, 'The Demo header does not fetch a nonexistent notice stream');
    page.off('request', countDemoNotice);
    await page.goto(base + '/founder/settings?mode=demo&tab=notifications', { waitUntil: 'domcontentloaded' });
    await page.locator('header button[aria-label^="Founder notifications,"]').click();
    await page.getByText('Demo has no founder notices.', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'founder.mobile.demo.png') });
    await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
    const violations = await page.evaluate(async () => (await axe.run('header',{runOnly:{type:'tag',values:['wcag2a','wcag2aa']}})).violations.map((item) => item.id));
    assert.deepEqual(violations, []);
    assert.deepEqual(errors, []);
    const result = { status: 'PASS', execution: 'local Founder Control session and durable in-app test notice; email/push not sent', viewport: 390, checks: ['unread bell', 'touch expanded stack', 'confirmed read', 'Demo header skips notice fetch', 'Demo separation', 'axe'] };
    fs.writeFileSync(path.join(out, 'browser.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'founder.failure.png'), fullPage: true }).catch(() => undefined);
    throw error;
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
