/** Actual screens + disposable PG + deterministic AI fixtures. No external host, model or publishing. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:3297';
assert.equal(new URL(base).hostname, '127.0.0.1');
const principal = randomUUID();
const root = path.resolve(__dirname, '../..');
const out = path.join(root, 'docs/design/postdoctor-v2/evidence');
fs.mkdirSync(out, { recursive: true });
const headers = {
  'Content-Type': 'application/json',
  'X-PostRiff-Request': 'founder-alpha',
  Authorization: 'Bearer dev:' + principal,
  Origin: base
};
async function api(method, url, body) {
  const response = await fetch(base + url, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) })
  });
  assert.ok(response.ok, `${url}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}
async function screenshot(page, name) {
  await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true });
}
async function mobile(page, selector) {
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    'No horizontal overflow'
  );
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(
    async (selector) =>
      (await window.axe.run(selector, { resultTypes: ['violations'] })).violations
        .filter((v) => ['serious', 'critical'].includes(v.impact))
        .map((v) => ({ id: v.id, nodes: v.nodes.map((n) => n.target) })),
    selector
  );
  assert.deepEqual(violations, []);
}
(async () => {
  assert.equal((await api('GET', '/api/auth/config')).execution, 'dev-synthetic');
  const { workspaceId: wid } = await api('POST', '/api/auth/verify', { plan: 'studio' });
  assert.equal(
    (await api('GET', `/api/workspaces/${wid}/growth/catalog`)).writer,
    'fixture/writer'
  );
  function fixture(kind) {
    return JSON.parse(
      execFileSync(
        '/tmp/rafii-phase1-env/bin/python',
        ['tests/phase2/postdoctor_v2_browser_fixture.py', kind, '55797', principal, wid],
        { cwd: root, encoding: 'utf8' }
      ).trim()
    );
  }
  fixture('draft');
  const tours = Object.fromEntries(
    [
      ...fs
        .readFileSync(path.join(root, 'web/src/features/onboarding/tours.ts'), 'utf8')
        .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
    ].map((m) => [m[1], 1])
  );
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion: 'reduce'
  });
  await context.route('**/*', (route) =>
    new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort()
  );
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await context.addInitScript(
    ({ principal, wid, tours }) => {
      localStorage.setItem('postriff-dev-principal', principal);
      localStorage.setItem('postriff-workspace', wid);
      localStorage.setItem(
        'postriff-onboarding',
        JSON.stringify({ completed: tours, dismissed: tours, nudged: tours })
      );
    },
    { principal, wid, tours }
  );
  const page = await context.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('Browser error:', msg.text().slice(0, 800));
  });
  page.on('requestfailed', (request) =>
    console.log('Request failed:', new URL(request.url()).pathname, request.failure()?.errorText)
  );
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  const checks = [];
  try {
    await page.goto(base + '/app/queue?view=drafts', {
      waitUntil: 'domcontentloaded',
      timeout: 120000
    });
    console.log('Queue loaded');
    await page.getByRole('button', { name: 'Edit', exact: true }).first().click({ timeout: 60000 });
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('checkbox', { name: 'Allow growth AI models' }).check();
    await dialog.getByRole('button', { name: 'Allow growth AI', exact: true }).click();
    await dialog.getByRole('checkbox', { name: 'Allow AI analysis of this draft' }).check();

    await dialog.getByLabel('Advice goal').selectOption('conversation',{timeout:8000});
    await dialog.getByRole('button',{name:'Check draft',exact:true}).click();
    await dialog.getByText('Your next changes',{exact:true}).waitFor();
    assert.equal(await dialog.locator('dl > div').count(),9);
    assert.ok(await dialog.locator('[aria-label="Priority actions"] li').count()<=3);
    await dialog.getByText('Audience context is missing; this dimension is unassessed.').waitFor();
    await dialog.getByRole('button',{name:'Rewrite and recheck',exact:true}).click();
    await dialog.getByText('The proposed version better supports your goal.',{exact:true}).waitFor({timeout:60000});
    for(const [width,height] of [[1440,900],[390,844],[430,932]]) {
      await page.setViewportSize({width,height});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
      const issues=await page.evaluate(async()=> (await window.axe.run('[aria-label="Post Doctor"]')).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id));
      assert.deepEqual(issues,[]);
      await dialog.getByLabel('Advice goal').scrollIntoViewIfNeeded();
      await screenshot(page,'goal-'+width);
      await dialog.getByText('The proposed version better supports your goal.',{exact:true}).scrollIntoViewIfNeeded();
      await screenshot(page,'comparison-'+width);
    }
    await dialog.getByRole('checkbox',{name:'Use change 2',exact:true}).uncheck();
    await dialog.getByRole('button',{name:'Use selected changes',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[aria-label="Draft text"]')?.value==='A clearer opening. Another idea!');
    let saved=await api('GET',`/api/workspaces/${wid}`);
    assert.equal(saved.state.variants[0].postDoctor,undefined);
    assert.equal(saved.state.phase2.jobs.length,0);
    await dialog.getByRole('checkbox',{name:'Allow AI analysis of this draft'}).check();
    await dialog.getByRole('button',{name:'Check draft',exact:true}).click();
    await dialog.getByText('Your next changes',{exact:true}).waitFor();
    saved=await api('GET',`/api/workspaces/${wid}`);
    assert.equal(saved.state.variants[0].postDoctor.goal,'conversation');
    assert.deepEqual(saved.state.variants[0].postDoctor.acceptedChangeIds,['0']);
    const {jobId}=fixture('feedback');
    const feedback=await api('GET',`/api/workspaces/${wid}/growth/feedback/${jobId}`);
    assert.equal(feedback.prediction.goal,'conversation');
    assert.deepEqual(feedback.prediction.acceptedChangeIds,['0']);
    await dialog.getByLabel('Advice goal').selectOption('authority');
    assert.equal(await dialog.getByRole('button',{name:'Rewrite and recheck',exact:true}).count(),0);
    await dialog.getByLabel('Advice goal').focus();
    assert.ok(await dialog.getByLabel('Advice goal').evaluate(el=>el===document.activeElement));
    assert.deepEqual(errors,[]);
    checks.push('1440/390/430 composer, goal, missing audience, three actions, both-order comparison, selective acceptance, recheck and frozen synthetic outcome');
    fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({status:'PASS',execution:'local deterministic providers, synthetic observations, desktop/mobile emulation',checks,realModelCalls:0,pageErrors:errors},null,2));
    console.log(JSON.stringify({status:'PASS',checks}));
  } catch(error) {await screenshot(page,'failure');console.log((await page.locator('body').innerText()).slice(-4000));throw error;}
  finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
