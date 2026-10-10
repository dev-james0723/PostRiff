/** UI contract acceptance only: real app/session shell, synthetic TaskV1 HTTP responses, no models/providers. */
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:4439';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw Error('Cloud disposable harness only');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')));
const out = path.resolve(args.out || '../artifacts/task-center'); fs.mkdirSync(out, { recursive: true });
const name = args.browser === 'webkit' ? 'webkit' : 'chromium';
const principal = randomUUID();
const headers = { Authorization: `Bearer dev:${principal}`, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Origin: base };
const checks = [];
function check(label, ok) { checks.push({ name: label, ok: Boolean(ok) }); console.log(`${ok ? 'PASS' : 'FAIL'} ${label}`); assert(ok, label); }
const tours = [...fs.readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const tourState = { completed: {}, dismissed: Object.fromEntries(tours.map((id) => [id, 1])), nudged: Object.fromEntries(tours.map((id) => [id, 1])) };
const now = new Date().toISOString(), future = new Date(Date.now() + 3600000).toISOString();
const longBody = 'A complete, reviewable draft. '.repeat(100);
function sample() {
  return { taskId: 'task-a', title: 'Prepare autumn campaign', state: 'awaiting_approval', partial: true, version: 8, href: '/app/agent/conversation-a?task=task-a',
    progress: { total: 2, completed: 1, failed: 0, cancelled: 0 }, can: { cancel: true, retry: false, continue: false }, createdBy: { userId: principal, isMe: true }, updatedAt: now,
    steps: [{ stepKey: 'draft', label: 'Prepare platform copy', state: 'completed', capabilityId: 'draft.create', riskClass: 'R1', attempts: 1, maxAttempts: 2, generation: 1,
      verified: true, reason: null, reasonCode: null, waitingOn: [], nextAttemptAt: null, delegate: null, undo: null, can: { retry: false, undo: false } }],
    approvals: [{ approvalId: 'approval-a', stepKey: 'schedule', kind: 'schedule', riskClass: 'R2', digest: 'exact-review-digest', summary: { platform: 'Threads', body: longBody },
      requiredPermission: 'approve', requiresStepUp: false, state: 'pending', expiresAt: future, can: { decide: true, why: null } }],
    receipts: [{ effectKey: 'effect-a', stepKey: 'schedule', capabilityId: 'schedule.apply', outcome: 'applied', verified: true, checks: [{ name: 'Queue record saved', ok: true }], changedRefs: [],
      providerReceipt: { kind: 'publish', jobId: 'job-a', state: 'queued', verifiedAt: null }, costState: 'none', evidenceRefs: [], cannotRecall: [], at: now }] };
}
(async () => {
  const seed = await fetch(`${base}/api/auth/verify`, { method: 'POST', headers, body: '{}' });
  if (!seed.ok) throw Error(`Harness auth ${seed.status}`);
  const { workspaceId: w } = await seed.json();
  const browser = await (name === 'webkit' ? webkit : chromium).launch({ headless: true });
  try {
    for (const width of [1440, 390]) {
      const ctx = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: 'dark', locale: 'en-US', reducedMotion: 'reduce' });
      await ctx.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }, { name: 'postriff_theme', value: 'rafii', url: base }]);
      await ctx.addInitScript(({ id, tours }) => { localStorage.setItem('postriff-dev-principal', id); localStorage.setItem('postriff-onboarding', JSON.stringify(tours)); }, { id: principal, tours: tourState });
      let task = sample(), deny = false, dropFirst = true; const cancels = [], approvals = [];
      await ctx.route(`**/api/workspaces/${w}/agent/tasks**`, async (route) => {
        const req = route.request(); const url = new URL(req.url());
        if (req.method() === 'POST') {
          cancels.push(req.postDataJSON());
          if (dropFirst) { dropFirst = false; await route.abort('failed'); return; }
          return route.fulfill({ json: { outcome: 'applied', verified: true } });
        }
        if (url.pathname.endsWith('/tasks')) return route.fulfill({ json: { items: [task], nextCursor: null, counts: { open: 1, needsMe: 1 }, engine: 'enabled', asOf: now } });
        return deny ? route.fulfill({ status: 403, json: { error: 'Your access has changed.' } }) : route.fulfill({ json: { engine: task, events: [], cursor: 0 } });
      });
      await ctx.route(`**/api/workspaces/${w}/agent/approvals/*/decide`, async (route) => { approvals.push(route.request().postDataJSON()); return route.fulfill({ json: { outcome: 'applied', verified: true } }); });
      const page = await ctx.newPage();
      await page.goto(`${base}/app/tasks`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('heading', { level: 1, name: 'Tasks', exact: true }).waitFor({ timeout: 180000 });
      await page.getByRole('button', { name: /Prepare autumn campaign/ }).click();
      const heading = page.getByRole('heading', { level: 2, name: 'Prepare autumn campaign', exact: true }); await heading.waitFor();
      check(`${name} ${width}: selected detail receives keyboard focus`, await heading.evaluate((el) => el === document.activeElement));
      check(`${name} ${width}: review body is complete`, await page.locator('dd').filter({ hasText: longBody }).textContent() === longBody);
      check(`${name} ${width}: queued provider receipt is unverified`, await page.getByText('Not verified · applied', { exact: true }).isVisible());
      await page.getByRole('button', { name: 'Approve this action', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.getByRole('region', { name: 'Approve this action', exact: true }).waitFor({ state: 'hidden' });
      check(`${name} ${width}: approval binds original digest and key`, approvals.length === 1 && approvals[0].digest === 'exact-review-digest' && Boolean(approvals[0].idempotencyKey));
      check(`${name} ${width}: accepted request does not invent completed task`, (await heading.locator('..').textContent()).includes('Awaiting approval'));
      await page.getByRole('button', { name: 'Cancel task', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.getByRole('region', { name: 'Cancel task', exact: true }).getByRole('alert').waitFor();
      await page.getByRole('button', { name: 'Confirm', exact: true }).click();
      await page.getByRole('region', { name: 'Cancel task', exact: true }).waitFor({ state: 'hidden' });
      check(`${name} ${width}: uncertain retry retains exact idempotency key`, cancels.length === 2 && cancels[0].idempotencyKey === cancels[1].idempotencyKey && cancels[1].expectedVersion === 8);
      task = { ...task, can: { cancel: false, retry: false, continue: false }, approvals: [{ ...task.approvals[0], summary: { body: 'x'.repeat(50001) } }] };
      await page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await page.getByText('The complete action cannot be shown here.', { exact: false }).waitFor();
      check(`${name} ${width}: incomplete approval is disabled`, await page.getByRole('button', { name: 'Approve this action', exact: true }).isDisabled());
      check(`${name} ${width}: withdrawn cancel action disappears`, await page.getByRole('button', { name: 'Cancel task', exact: true }).count() === 0);
      check(`${name} ${width}: no horizontal scrolling`, await page.evaluate(() => document.scrollingElement.scrollWidth <= innerWidth + 1));
      await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
      const violations = await page.evaluate(async () => (await window.axe.run(document.querySelector('main') || document)).violations.filter((v) => ['critical', 'serious'].includes(v.impact)).map((v) => v.id));
      check(`${name} ${width}: axe serious/critical absent (${violations.join(',')})`, violations.length === 0);
      await page.screenshot({ path: path.join(out, `${name}-${width}-tasks.png`), fullPage: true });
      deny = true;
      await page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await page.getByText('Your access has changed.', { exact: true }).waitFor();
      check(`${name} ${width}: refreshed denial hides stale private detail`, await heading.count() === 0 && await page.locator('dd').count() === 0);
      await ctx.close();
    }
  } finally { await browser.close(); fs.writeFileSync(path.join(out, `${name}-receipt.json`), JSON.stringify({ kind: 'synthetic-ui-contract', checks }, null, 2)); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
