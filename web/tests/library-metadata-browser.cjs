/** Native metadata workflow: real Next/API/disposable PostgreSQL, synthetic identity/assets. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { chromium, webkit } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = 'http://127.0.0.1:4439';
const out = process.env.RAFII_LIBRARY_EVIDENCE || resolve('.jcb-artifacts/library-metadata');
mkdirSync(out, { recursive: true });
// Fixed disposable address; this fixture never consumes an application DSN or credential.
execFileSync('python', ['-c', "from pathlib import Path; import psycopg; db=psycopg.connect('host=127.0.0.1 port=55479 dbname=postgres'); db.execute(Path('migrations/postriff/112_library_metadata_changes.sql').read_text()); db.close()"], { stdio: 'inherit' });

(async () => {
  const checks = [];
  for (const [engine, browserType] of Object.entries({ chromium, webkit })) {
    const browser = await browserType.launch({ headless: true });
    try {
      for (const width of [1440, 390]) {
        const principal = randomUUID();
        const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
        const headers = { Authorization: 'Bearer dev:' + principal, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Origin: base };
        await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
        await context.addInitScript(id => localStorage.setItem('postriff-dev-principal', id), principal);
        const boot = await context.request.post(base + '/api/auth/verify', { headers, data: { plan: 'studio' } });
        assert.equal(boot.status(), 201, await boot.text());
        const w = (await boot.json()).workspaceId;
        const path = base + '/api/workspaces/' + w + '/library';
        const ids = [];
        for (const name of ['First lesson', 'Second lesson', 'Unselected lesson']) {
          const response = await context.request.post(path + '/files', { headers, data: { filename: name + '.txt', mime: 'text/plain', bytes: 8 } });
          assert.equal(response.status(), 201, await response.text());
          ids.push((await response.json()).upload.assetId);
        }
        const group = await context.request.post(path + '/collections', { headers, data: { name: 'Rehearsal' } });
        assert.equal(group.status(), 200, await group.text());
        const groupId = (await group.json()).collections[0].id;
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(base + '/app/library', { waitUntil: 'domcontentloaded' });
        const batch = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Organize selected assets' }) });
        async function chooseBatch() {
        await page.getByText('Organize selected assets', { exact: true }).click();
        await batch.getByRole('checkbox', { name: 'Select First lesson', exact: true }).check();
        await batch.getByRole('checkbox', { name: 'Select Second lesson', exact: true }).check();
        await batch.getByRole('checkbox', { name: 'Replace tags for selected assets', exact: true }).check();
        await batch.getByRole('textbox', { name: 'Replacement tags' }).fill('rehearsal, reviewed');
        await batch.getByRole('checkbox', { name: 'Replace collections for selected assets', exact: true }).check();
        await batch.getByRole('checkbox', { name: 'Rehearsal', exact: true }).check();
        }
        await chooseBatch();
        const previewResponse = page.waitForResponse(r => r.url() === path + '/metadata/preview');
        await batch.getByRole('button', { name: 'Preview changes', exact: true }).click();
        const previewResult = await previewResponse;
        assert.equal(previewResult.status(), 200, await previewResult.text());
        const preview = await previewResult.json();
        assert.deepEqual(preview.affectedResources.filter(r => r.kind === 'library_asset').map(r => r.id).sort(), ids.slice(0, 2).sort());
        assert(preview.entries.every(e => e.current.tags.length === 0 && e.proposed.tags.join(',') === 'rehearsal,reviewed'));
        const panel = batch.getByRole('region', { name: 'Metadata change preview' });
        await panel.getByRole('button', { name: 'Apply changes', exact: true }).waitFor({ state: 'visible' });
        assert.equal(await panel.getByText('Current', { exact: true }).count(), 4);
        assert.equal(await panel.getByText('Proposed', { exact: true }).count(), 4);
        const before = await context.request.get(path + '?limit=10', { headers });
        assert((await before.json()).assets.every(a => (a.tags || []).length === 0));
        await panel.scrollIntoViewIfNeeded();
        await page.screenshot({ path: resolve(out, `${engine}-${width}-preview.png`), fullPage: true });
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No horizontal overflow');
        await panel.getByRole('button', { name: 'Apply changes', exact: true }).click();
        await panel.getByText('Changes applied and verified', { exact: true }).waitFor({ state: 'visible' });
        const applied = await context.request.get(path + '?limit=10', { headers });
        const assets = (await applied.json()).assets;
        assert(assets.filter(a => ids.slice(0, 2).includes(a.id)).every(a => a.tags.join(',') === 'rehearsal,reviewed' && a.collections.includes(groupId)));
        assert.equal(assets.find(a => a.id === ids[2]).tags.length, 0, 'Unselected asset unchanged');
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByText('Recent metadata changes', { exact: true }).click();
        const history = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Recent metadata changes' }) });
        await history.getByRole('button', { name: 'Open change', exact: true }).first().click();
        await history.getByRole('button', { name: 'Undo changes', exact: true }).click();
        await history.getByText('Changes undone and verified', { exact: true }).waitFor({ state: 'visible' });
        const undone = await context.request.get(path + '?limit=10', { headers });
        assert((await undone.json()).assets.every(a => a.tags.length === 0 && a.collections.length === 0));
        checks.push({ engine, width, check: 'two selected assets preview/apply/reload/reopen/conditional undo; unselected untouched' });

        // The actual server sees a concurrent native edit between Preview and Apply.
        await chooseBatch();
        await batch.getByRole('button', { name: 'Preview changes', exact: true }).click();
        await panel.getByRole('button', { name: 'Apply changes', exact: true }).waitFor({ state: 'visible' });
        const changed = await context.request.patch(path + '/assets/' + ids[0], { headers, data: { title: 'Later title' } });
        assert.equal(changed.status(), 200, await changed.text());
        await panel.getByRole('button', { name: 'Apply changes', exact: true }).click();
        await batch.getByRole('alert').filter({ hasText: 'changed' }).waitFor({ state: 'visible' });
        const refused = await context.request.get(path + '?limit=10', { headers });
        assert((await refused.json()).assets.every(a => a.tags.length === 0), 'Conflict leaves whole batch unapplied');
        checks.push({ engine, width, check: 'stale Apply shows conflict and does not partially change batch' });

        await batch.getByRole('button', { name: 'Preview changes', exact: true }).click();
        await panel.getByRole('button', { name: 'Apply changes', exact: true }).click();
        await panel.getByText('Changes applied and verified', { exact: true }).waitFor({ state: 'visible' });
        const drift = await context.request.patch(path + '/assets/' + ids[1], { headers, data: { tags: ['later'] } });
        assert.equal(drift.status(), 200, await drift.text());
        await panel.getByRole('button', { name: 'Undo changes', exact: true }).click();
        await batch.getByRole('alert').filter({ hasText: 'changed' }).waitFor({ state: 'visible' });
        assert(await panel.getByRole('button', { name: 'Undo changes', exact: true }).isDisabled());
        const preserved = await context.request.get(path + '?limit=10', { headers });
        assert.deepEqual((await preserved.json()).assets.find(a => a.id === ids[1]).tags, ['later']);
        await page.screenshot({ path: resolve(out, `${engine}-${width}-undo-conflict.png`), fullPage: true });
        checks.push({ engine, width, check: 'Undo drift refuses overwrite and explains disabled Undo' });
        assert.deepEqual(errors, [], 'No page errors');
        await context.close();
      }
    } finally { await browser.close(); }
  }
  const receipt = { execution: 'real cloud Next/API/disposable PostgreSQL; synthetic identities and pending assets; no file/provider calls', status: 'PASS', checks };
  writeFileSync(resolve(out, 'browser-receipt.json'), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
})().catch(error => { console.error(error); process.exitCode = 1; });
