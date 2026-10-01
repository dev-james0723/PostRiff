/** Real local Next/API/PostgreSQL Inbox; identity, provider and suggestion are synthetic. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { writeFileSync, mkdirSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium, webkit } = require('playwright');

const base = 'http://127.0.0.1:4461';
const evidence = resolve(__dirname, '../../docs/superpowers/handoffs/inbox-v1-browser-evidence.json');
const evidenceDir = resolve(__dirname, '../../docs/superpowers/handoffs/inbox-v1-browser');
const principal = randomUUID();
const headers = { Authorization: `Bearer dev:${principal}`, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
const failures = [];
const results = [];

async function main() {
  const browser = await chromium.launch({ headless: true });
  let safari;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
    await context.addInitScript(id => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
    }, principal);
    await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    const api = async (method, path, data) => {
      const response = await context.request.fetch(base + path, { method, headers, data });
      assert.ok(response.ok(), `${method} ${path} -> ${response.status()} ${(await response.text()).slice(0, 300)}`);
      return response.json();
    };
    const boot = await api('POST', '/api/auth/verify', { plan: 'studio' });
    const wid = boot.workspaceId;
    let connection;
    for (const capability of ['publish', 'analytics', 'comments_read', 'reply']) {
      const started = await api('POST', `/api/workspaces/${wid}/channels/threads/oauth/start`, { capability });
      const done = await api('POST', `/api/workspaces/${wid}/channels/threads/oauth/complete`, { state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'good-code' });
      assert.equal(done.capabilities.publish.level, 'Direct', `publish survived ${capability}`);
      connection = done.connectionId;
    }
    const channels = await api('GET', `/api/workspaces/${wid}/channels`);
    const channel = channels.channels.find(c => c.id === connection);
    assert.equal(channel.capabilities.publish.level, 'Direct');
    assert.equal(channel.capabilities.analytics.level, 'Direct');
    assert.equal(channel.capabilities.comments_read.level, 'Direct');
    assert.equal(channel.capabilities.reply.level, 'Direct');
    results.push({ scenario: 'cumulative OAuth reconnect', passed: true });
    const fixture = async (name, data = {}) => api('POST', `/dev/inbox/${name}`, { workspaceId: wid, ...data });
    await fixture('seed');
    const page = await context.newPage();
    const comment = text => page.getByRole('list', { name: 'Comments' }).getByText(text).first();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => failures.push(`page: ${error.message}`));
    page.on('console', message => { if (message.type() === 'error') failures.push(`console: ${message.text()}`); });
    page.on('response', response => { if (response.url().startsWith(base + '/api/') && response.status() >= 500) failures.push(`network: ${response.status()} ${response.url()}`); });
    await page.goto(base + '/app/inbox');
    await page.getByRole('heading', { name: 'Inbox', level: 1 }).waitFor();
    await page.getByText('Can you reply there?').waitFor();
    await page.getByRole('button', { name: 'Check for new comments' }).click();
    await page.getByText('Where can I read more about the practice method?').waitFor();
    await page.getByText(/Checked .*ago|Checked just now/).first().waitFor();
    const loaded = await api('GET', `/api/workspaces/${wid}/audience/threads`);
    assert.equal(loaded.counts.all, 6);
    assert.ok(loaded.sync[0].lastSyncAt);
    const spam = loaded.threads.find(thread => thread.text.includes('Buy fake followers'));
    assert.equal(spam.triage.category, 'spam');
    assert.equal(spam.triage.priority, 'ignore');
    results.push({ scenario: 'manual sync, server freshness and authoritative attention', passed: true, counts: loaded.counts });
    await page.getByRole('radio', { name: /Needs reply/ }).click();
    await page.getByText('Where can I read more about the practice method?').waitFor();
    await page.getByRole('radio', { name: /Review/ }).click();
    await page.getByRole('radio', { name: /FYI/ }).click();
    await page.getByRole('radio', { name: /^All/ }).click();
    results.push({ scenario: 'Engagement Copilot filters', passed: true });
    await comment('Can you reply there?').click();
    await page.getByRole('link', { name: 'Reply on Instagram' }).waitFor();
    results.push({ scenario: 'unsupported provider click-through', passed: true });
    await comment('Where can I read more about the practice method?').click();
    await page.getByRole('button', { name: 'Suggest a reply' }).click();
    const composer = page.getByRole('textbox', { name: 'Your reply' });
    await composer.waitFor();
    try {
      await page.waitForFunction(() => /practice method/.test(document.querySelector('textarea[aria-label="Your reply"]')?.value ?? ''), null, { timeout: 10000 });
    } catch (error) {
      throw new Error(`Synthetic suggestion was not inserted: ${JSON.stringify({ toasts: await page.locator('[data-sonner-toast]').allTextContents(), failures, inbox: await api('GET', `/api/workspaces/${wid}/audience/threads`) })}`, { cause: error });
    }
    await composer.fill('Thanks for asking. I can share the method tomorrow.');
    await page.getByRole('button', { name: 'Review & approve' }).click();
    const dialog = page.getByRole('dialog', { name: 'Approve reply?' });
    await dialog.waitFor();
    await dialog.getByText('Thanks for asking. I can share the method tomorrow.').waitFor();
    await dialog.getByRole('button', { name: /Approve/ }).click();
    await dialog.waitFor({ state: 'hidden' });
    let current = await api('GET', `/api/workspaces/${wid}/audience/threads`);
    let draft = current.threads.find(t => t.commentId === '77001').replies.at(-1);
    assert.equal(draft.status, 'approved');
    assert.equal(draft.requiresReconfirmation, true);
    results.push({ scenario: 'synthetic suggestion, edit, exact preview, approval while sender off', passed: true });
    await fixture('sender', { enabled: true });
    await page.reload();
    await comment('Where can I read more about the practice method?').click();
    await page.getByRole('button', { name: 'Review this reply again' }).click();
    await page.getByRole('button', { name: 'Review & approve' }).click();
    const reconfirm = page.getByRole('dialog', { name: 'Approve reply?' });
    await reconfirm.waitFor();
    await reconfirm.getByRole('button', { name: /Approve/ }).click();
    await reconfirm.waitFor({ state: 'hidden' });
    const tick = await context.request.get(base + '/api/cron/worker', { headers: { Authorization: 'Bearer ' + 'd'.repeat(24) } });
    assert.ok(tick.ok(), `synthetic worker ${tick.status()}`);
    await page.reload();
    await comment('Where can I read more about the practice method?').click();
    await page.getByRole('list', { name: 'Reply receipt timeline' }).first().waitFor();
    current = await api('GET', `/api/workspaces/${wid}/audience/threads`);
    draft = current.threads.find(t => t.commentId === '77001').replies.at(-1);
    assert.equal(draft.status, 'verified');
    assert.ok(draft.providerReference);
    await page.getByRole('button', { name: 'Copy provider reply ID' }).first().waitFor();
    results.push({ scenario: 'synthetic send and authoritative read-back receipt', passed: true });
    await fixture('reply-error', { enabled: true });
    await page.getByRole('button', { name: 'Write another' }).click();
    await page.getByRole('textbox', { name: 'Your reply' }).fill('A second exact reply for the uncertain case.');
    await page.getByRole('button', { name: 'Review & approve' }).click();
    const secondReview = page.getByRole('dialog', { name: 'Approve reply?' });
    await secondReview.waitFor();
    await secondReview.getByRole('button', { name: /Approve/ }).click();
    await secondReview.waitFor({ state: 'hidden' });
    const uncertainTick = await context.request.get(base + '/api/cron/worker', { headers: { Authorization: 'Bearer ' + 'd'.repeat(24) } });
    assert.ok(uncertainTick.ok());
    current = await api('GET', `/api/workspaces/${wid}/audience/threads`);
    draft = current.threads.find(t => t.commentId === '77001').replies.at(-1);
    assert.equal(draft.status, 'uncertain');
    const uncertainId = draft.draftId;
    const repeatTick = await context.request.get(base + '/api/cron/worker', { headers: { Authorization: 'Bearer ' + 'd'.repeat(24) } });
    assert.ok(repeatTick.ok());
    current = await api('GET', `/api/workspaces/${wid}/audience/threads`);
    assert.equal(current.threads.find(t => t.commentId === '77001').replies.find(r => r.draftId === uncertainId).status, 'uncertain');
    await fixture('reply-error', { enabled: false });
    results.push({ scenario: 'inconclusive synthetic publish, durable uncertain receipt and no resend', passed: true });
    await fixture('cooldown-clear');
    await fixture('error', { enabled: true });
    await page.getByRole('button', { name: 'Check for new comments' }).click();
    await page.getByText(/Provider refresh unavailable/).first().waitFor();
    await fixture('error', { enabled: false });
    results.push({ scenario: 'provider sync error without lost comments', passed: true });
    for (const [width, height] of [[1440, 900], [768, 1024], [430, 932], [390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + '/app/inbox');
      await page.getByText('Where can I read more about the practice method?').waitFor();
      if (width === 1440) {
        mkdirSync(evidenceDir, { recursive: true });
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(500);
        const badgesInsideRows = await page.evaluate(() => [...document.querySelectorAll('ul[aria-label="Comments"] button')].every(button =>
          [...button.querySelectorAll('[title]')].every(badge => {
            const row = button.getBoundingClientRect();
            const box = badge.getBoundingClientRect();
            return box.top >= row.top - 1 && box.bottom <= row.bottom + 1;
          })));
        assert.equal(badgesInsideRows, true, 'category badges stay inside their comment rows');
        await page.screenshot({ path: resolve(evidenceDir, 'chromium-1440x900.png') });
      }
      if (width < 1024) {
        await comment('Where can I read more about the practice method?').click();
        if (width === 430) {
          await page.getByText('New to Inbox?').waitFor({ state: 'hidden' });
          await page.screenshot({ path: resolve(evidenceDir, 'chromium-sheet-430x932.png') });
        }
        await page.getByRole('button', { name: 'Back to comments' }).click();
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width}px overflow`);
      results.push({ scenario: 'responsive Inbox', browser: 'Chromium emulation', width, height, reducedMotion: true, passed: true });
    }
    safari = await webkit.launch({ headless: true });
    const mobile = await safari.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    await mobile.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
    await mobile.addInitScript(id => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} }));
    }, principal);
    await mobile.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    const mobilePage = await mobile.newPage();
    mobilePage.on('pageerror', error => failures.push(`WebKit page: ${error.message}`));
    await mobilePage.goto(base + '/app/inbox');
    await mobilePage.getByText('Where can I read more about the practice method?').waitFor();
    await mobilePage.getByText('Where can I read more about the practice method?').click();
    await mobilePage.getByText('New to Inbox?').waitFor({ state: 'hidden' });
    await mobilePage.screenshot({ path: resolve(evidenceDir, 'webkit-sheet-390x844.png') });
    await mobilePage.getByRole('button', { name: 'Back to comments' }).click();
    assert.equal(await mobilePage.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    results.push({ scenario: 'mobile sheet and back', browser: 'WebKit emulation', width: 390, height: 844, reducedMotion: true, passed: true });
    await mobile.close();
    await fixture('viewer', { enabled: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(base + '/app/inbox');
    await comment('Where can I read more about the practice method?').click();
    await page.getByText(/Replying needs the edit and reply permissions/).waitFor();
    results.push({ scenario: 'viewer permission variant', passed: true });
    await context.close();
    assert.deepEqual(failures, []);
    mkdirSync(resolve(evidence, '..'), { recursive: true });
    writeFileSync(evidence, JSON.stringify({ status: 'PASS', execution: 'local disposable PostgreSQL; synthetic identity, Threads transport and reply writer; no external provider/model calls', physicalDevice: false, results, failures }, null, 2) + '\n');
    console.log(JSON.stringify({ status: 'PASS', results: results.length, failures }));
  } finally {
    if (safari) await safari.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
