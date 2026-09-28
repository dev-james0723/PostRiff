/** Explicit synthetic API + document visibility fixtures. Real DOM IntersectionObserver.
 * These focused timing/UI checks are separate from trend-live-api-browser Tier C.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { chromium } = require('playwright');
const { fixtures } = require('./trend-fixtures.cjs');
const workspaceFixture = require('./fixtures/wp04a-workspace.json');
const t = require('./trend-contract.cjs').loadTypes();
const base = process.env.TREND_WEB_URL,
  out = process.env.TREND_EVIDENCE_DIR;
assert.ok(base && new URL(base).hostname === '127.0.0.1' && out);
fs.mkdirSync(out, { recursive: true });
const results = [];
const pass = (width, name) => {
  results.push({ width, name, pass: true });
  process.stdout.write(`PASS ${width} ${name}\n`);
};
async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({
        viewport: { width, height: 1000 },
        reducedMotion: 'reduce'
      });
      const f = fixtures(),
        snapshot = structuredClone(workspaceFixture.snapshot),
        wid = snapshot.state.workspace.id;
      f.trend.id = randomUUID();
      f.trend.trust_receipt_id = randomUUID();
      f.opportunity.id = randomUUID();
      f.opportunity.trend_id = f.trend.id;
      f.opportunity.trust_receipt_id = f.trend.trust_receipt_id;
      f.receipt = { ...f.receipt, id: f.trend.id, trust_receipt_id: f.trend.trust_receipt_id, receipt_id: f.trend.trust_receipt_id };
      f.opportunity.state = 'ready';
      f.opportunity.source_id = null;
      const second = {
        ...structuredClone(f.opportunity),
        id: randomUUID(),
        trend_id: randomUUID()
      };
      const root = `/api/workspaces/${wid}/coworker/trends`;
      const candidates = [f.opportunity, second].map((op) => ({
        opportunity_id: op.id,
        revision: op.revision
      }));
      const exposureId = randomUUID();
      let flags = {},
        token = 'explicit-synthetic-page-token',
        dismissed = false,
        exposureFailures = 0,
        dismissConflict = false;
      const calls = [],
        errors = [],
        external = [];
      await context.addCookies([
        { name: 'postriff_dev', value: '1', url: base },
        { name: 'postriff_theme', value: 'rafii', url: base }
      ]);
      const tours = [
        ...fs
          .readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8')
          .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
      ].map((m) => m[1]);
      await context.addInitScript(
        ({ tours }) => {
          const principal = '00000000-0000-0000-0000-000000000001';
          localStorage.setItem('postriff-dev-principal', principal);
          const state = JSON.stringify({
            completed: {},
            dismissed: Object.fromEntries(tours.map((id) => [id, 1])),
            nudged: Object.fromEntries(tours.map((id) => [id, 1]))
          });
          localStorage.setItem('postriff-onboarding', state);
          localStorage.setItem('postriff-onboarding:' + principal, state);
          window.exposureObservations = [];
          const NativeObserver = window.IntersectionObserver;
          window.IntersectionObserver = class extends NativeObserver {
            constructor(callback, options) {
              super((entries, observer) => {
                for (const e of entries)
                  if (e.target.hasAttribute('data-trend-opportunity'))
                    window.exposureObservations.push({
                      ratio: e.intersectionRatio,
                      intersects: e.isIntersecting,
                      visible: e.isVisible,
                      rect: e.intersectionRect.toJSON()
                    });
                callback(entries, observer);
              }, options);
            }
          };
          window.syntheticVisibility = 'hidden';
          Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            get: () => window.syntheticVisibility
          });
        },
        { tours }
      );
      await context.route('**/*', async (route) => {
        const req = route.request(),
          url = new URL(req.url()),
          p = url.pathname;
        if (url.origin !== base) {
          external.push(url.origin);
          return route.abort();
        }
        if (!p.startsWith('/api/')) return route.continue();
        const body = req.method() === 'POST' ? req.postDataJSON() : null;
        calls.push({ path: p, method: req.method(), body });
        const send = (data, status = 200) =>
          route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
        if (p === root) return send(f.envelope([f.trend]));
        if (p === `${root}/${f.trend.id}/receipts/${f.trend.trust_receipt_id}`) return send(f.envelope(f.receipt));
        if (p === root + '/opportunities')
          return send({
            ...f.envelope([{ ...f.opportunity, state: dismissed ? 'dismissed' : 'ready' }, second]),
            exposure_token: token
          });
        if (p === root + '/exposures') {
          t.exposureInputSchema.parse(body);
          assert.deepEqual(body.eligible_candidates, candidates);
          assert.equal(body.opportunity_id, f.opportunity.id);
          if (exposureFailures-- > 0)
            return send(
              { code: 'source_unavailable', error: 'Explicit synthetic transient failure' },
              503
            );
          return send(
            f.envelope({
              exposure_id: exposureId,
              event_id: body.event_id,
              opportunity_id: body.opportunity_id,
              opportunity_revision: body.opportunity_revision,
              trust_receipt_id: body.trust_receipt_id,
              context_digest: body.context_digest,
              measurement: 'client_reported_view',
              eligible_candidate_count: candidates.length,
              recorded_at: new Date().toISOString(),
              expires_at: new Date(Date.now() + 120000).toISOString(),
              existing: false
            })
          );
        }
        if (p.endsWith('/dismiss')) {
          t.dismissOpportunityInputSchema.parse(body);
          if (dismissConflict)
            return send(
              { code: 'revision_conflict', error: 'Explicit synthetic changed revision' },
              409
            );
          dismissed = true;
          return send(
            f.envelope({
              opportunity_id: f.opportunity.id,
              revision: body.revision,
              state: 'dismissed',
              exposure_id: body.exposure_id ?? null,
              existing: false
            })
          );
        }
        if (p.endsWith('/accept')) {
          t.acceptOpportunitySchema.parse(body);
          return send(
            f.envelope({
              source_id: 'explicit-synthetic-source',
              href: '/app/ideas?source=explicit-synthetic-source',
              verified: true,
              existing: false
            })
          );
        }
        if (p === '/api/auth/config')
          return send({ provider: 'dev', execution: 'dev-synthetic', flow: 'dev' });
        if (p === '/api/bootstrap') return send({ workspaceId: wid });
        if (p === '/api/catalog')
          return send({
            authMode: 'dev',
            execution: 'dev-synthetic',
            platforms: ['Bluesky'],
            languages: ['en'],
            presets: [],
            voices: [],
            phase2: true,
            templates: [],
            routes: [],
            profileMetadata: {}
          });
        if (p === '/api/workspaces')
          return send({
            workspaces: [
              {
                workspaceId: wid,
                membership: snapshot.membership,
                name: 'Synthetic exposure fixture',
                plan: 'studio',
                memberCounts: { owner: 1 }
              }
            ]
          });
        if (p === '/api/me')
          return send({
            userId: '00000000-0000-0000-0000-000000000001',
            displayName: 'Synthetic owner',
            preferences: { timeZone: 'UTC', locale: 'en', alertNewDevice: false },
            mfa: {}
          });
        if (p === `/api/workspaces/${wid}`) return send(snapshot);
        if (p.endsWith('/coworker/status'))
          return send({
            flags,
            trend_beta: { state: flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED ? 'stored_radar' : 'feature_off',
              radar_available: flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED === true, acquisition: 'none',
              metric_reads_enabled: false, follower_conversion: 'unavailable' },
            weekly: { recipes: 0, weeks: 0 },
            notifications: { enabled: false }
          });
        if (p.endsWith('/usage'))
          return send({
            subscription: { plan: 'studio', status: 'active' },
            trial: {},
            balances: []
          });
        if (p.endsWith('/memory')) return send(workspaceFixture.memory);
        if (p.endsWith('/memory/proposals'))
          return send({ pending: [], recent: [], learning: { items: [] } });
        if (p.endsWith('/ideas/conversations')) return send({ conversations: [] });
        if (p.endsWith('/channels'))
          return send({ channels: snapshot.state.phase2.channels, providers: [] });
        if (p.endsWith('/audit')) return send({ entries: [] });
        if (p.endsWith('/time-savings')) return send({});
        return send({ error: 'Unavailable unrelated synthetic route' }, 404);
      });
      const page = await context.newPage();
      page.setDefaultTimeout(20000);
      page.on('pageerror', (e) => errors.push(e.message));
      const exposures = () => calls.filter((c) => c.path.endsWith('/exposures'));
      const visibility = (state) =>
        page.evaluate((state) => {
          window.syntheticVisibility = state;
          document.dispatchEvent(new Event('visibilitychange'));
        }, state);
      const card = page.getByRole('region', { name: 'Original contribution' });
      const load = async () => {
        await page.goto(base + '/app/trends', { timeout: 180000 });
        await card.waitFor();
        await card.scrollIntoViewIfNeeded();
      };
      const wait = (ms) => page.waitForTimeout(ms); // Explicit 500ms product dwell boundary, not network readiness.
      try {
        await page.goto(base + '/app/trends', { timeout: 180000 });
        await page
          .getByText('Conversations aren’t available in this workspace yet', { exact: true })
          .waitFor();
        await visibility('visible');
        await wait(650);
        assert.equal(exposures().length, 0);
        pass(width, 'default flags OFF sends no view');
        flags = f.flags;
        await load();
        await wait(650);
        assert.equal(exposures().length, 0);
        pass(width, 'GET delivery and hidden document send no view');
        await page.evaluate(() => {
          const cover = document.createElement('div');
          cover.id = 'synthetic-exposure-cover';
          cover.style.cssText = 'position:fixed;inset:0;z-index:99999;background:white';
          document.body.append(cover);
        });
        await visibility('visible');
        await wait(650);
        assert.equal(exposures().length, 0);
        await visibility('hidden');
        await page.evaluate(() => document.getElementById('synthetic-exposure-cover').remove());
        pass(width, 'occluding overlay cannot satisfy the visible card dwell');

        await visibility('visible');
        await wait(180);
        await visibility('hidden');
        await wait(550);
        assert.equal(exposures().length, 0);
        pass(width, 'sub-500ms visit resets on hidden document');
        await visibility('visible');
        await wait(180);
        await page.getByRole('tab', { name: 'Picking up', exact: true }).click();
        await wait(600);
        assert.equal(exposures().length, 0);
        pass(width, 'unmounted candidate cancels pending dwell');
        await load();
        await page.getByRole('button', { name: 'Why should I trust this?' }).click();
        const drawer = page.getByRole('dialog'); await drawer.waitFor();
        await visibility('visible'); await wait(650);
        assert.equal(exposures().length, 0, 'Covered cards are not reported while the trust drawer is open');
        const resumed = page.waitForRequest((r) => r.url().endsWith('/exposures'));
        await page.keyboard.press('Escape'); await drawer.waitFor({ state: 'hidden' });
        await card.scrollIntoViewIfNeeded();
        await resumed;
        pass(width, 'closing the trust drawer resumes a new visible dwell after focus restoration');
        await wait(650);
        assert.equal(exposures().length, 1);
        const observed = exposures()[0].body;
        assert.deepEqual(observed.eligible_candidates, candidates);
        assert.deepEqual(Object.keys(observed).toSorted(), [
          'context_digest',
          'eligible_candidates',
          'event_id',
          'exposure_token',
          'opportunity_id',
          'opportunity_revision',
          'trust_receipt_id'
        ]);
        pass(
          width,
          'continuous visible card reports exactly one bounded private event with exact eligible page order'
        );
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const violations = await page.evaluate(async () =>
          (
            await window.axe.run(document.querySelector('main'), { resultTypes: ['violations'] })
          ).violations
            .filter((v) => ['serious', 'critical'].includes(v.impact))
            .map((v) => ({ id: v.id, impact: v.impact }))
        );
        assert.deepEqual(violations, []);
        assert.ok(
          await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)
        );
        await card
          .getByRole('button', { name: 'Not relevant', exact: true })
          .scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(out, `opportunity-actions-${width}.png`) });
        pass(width, 'additive opportunity actions pass axe and fit the viewport');

        await card.getByRole('button', { name: 'Not relevant', exact: true }).focus();
        await page.keyboard.press('Enter');
        const status = page.getByText(
          'Marked not relevant. The conversation and its evidence remain available.',
          { exact: true }
        );
        await status.waitFor();
        assert.equal(calls.find((c) => c.path.endsWith('/dismiss')).body.exposure_id, exposureId);
        assert.ok(await status.evaluate((el) => el === document.activeElement));
        await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor();
        await page.getByRole('button', { name: 'Why should I trust this?' }).waitFor();
        await page.screenshot({ path: path.join(out, `dismissed-${width}.png`) });
        pass(
          width,
          'keyboard dismiss uses recorded ID, restores focus and preserves conversation evidence'
        );
        dismissed = false;
        token = null;
        await load();
        await visibility('visible');
        await wait(650);
        assert.equal(exposures().length, 1);
        const before = calls.filter((c) => c.path.endsWith('/dismiss')).length;
        await card.getByRole('button', { name: 'Not relevant', exact: true }).click();
        await status.waitFor();
        assert.equal(calls.filter((c) => c.path.endsWith('/dismiss')).length, before + 1);
        assert.equal(
          'exposure_id' in calls.filter((c) => c.path.endsWith('/dismiss')).at(-1).body,
          false
        );
        pass(width, 'legacy missing token omits exposure ID without fabricating a view');
        dismissed = false;
        token = 'explicit-synthetic-page-token';
        exposureFailures = 1;
        await load();
        await visibility('visible');
        await page.waitForResponse((r) => r.url().endsWith('/exposures') && r.status() === 503);
        await card.getByRole('button', { name: 'Not relevant', exact: true }).click();
        await status.waitFor();
        const retry = exposures()
          .slice(-2)
          .map((c) => c.body);
        assert.deepEqual(retry[0], retry[1]);
        pass(width, 'failed exposure retries once with the same event UUID and exact body');
        dismissed = false;
        exposureFailures = 5;
        await load();
        await visibility('visible');
        await page.waitForResponse((r) => r.url().endsWith('/exposures') && r.status() === 503);
        await card.getByRole('button', { name: 'Not relevant', exact: true }).click();
        await status.waitFor();
        assert.equal(
          'exposure_id' in calls.filter((c) => c.path.endsWith('/dismiss')).at(-1).body,
          false
        );
        pass(width, 'failed bounded exposure never synthesizes an ID for dismissal');
        dismissed = false;
        exposureFailures = 0;
        dismissConflict = true;
        await load();
        await visibility('visible');
        await page.waitForResponse((r) => r.url().endsWith('/exposures') && r.status() === 200);
        await card.getByRole('button', { name: 'Not relevant', exact: true }).click();
        await card
          .getByText('This revision changed. Reload before continuing.', { exact: true })
          .waitFor();
        assert.equal(await status.count(), 0);
        pass(width, 'dismiss conflict keeps candidate and displays failure');
        flags = { ...f.flags, RAFII_TREND_TRUST_RECEIPTS_ENABLED: false };
        const count = exposures().length;
        await load();
        await visibility('visible');
        await wait(650);
        assert.equal(exposures().length, count);
        assert.ok(
          await card.getByRole('button', { name: 'Not relevant', exact: true }).isDisabled()
        );
        pass(width, 'receipt flag OFF disables both exposure and dismissal');
        assert.deepEqual(errors, []);
        assert.deepEqual(external, []);
        pass(width, 'no browser runtime errors or external requests');
      } catch (e) {
        fs.writeFileSync(
          path.join(out, `failure-${width}.json`),
          JSON.stringify(
            {
              error: String(e),
              calls,
              errors,
              observations: await page.evaluate(() => window.exposureObservations)
            },
            null,
            2
          )
        );
        fs.writeFileSync(
          path.join(out, `failure-${width}.txt`),
          await page.locator('body').innerText()
        );
        await page.screenshot({ path: path.join(out, `failure-${width}.png`) });
        throw e;
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(out, 'results.json'),
      JSON.stringify(
        {
          execution: 'explicit_synthetic_api_and_visibility_fixture',
          real_dom_intersection_observer: true,
          results
        },
        null,
        2
      )
    );
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
