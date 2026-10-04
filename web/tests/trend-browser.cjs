/** Real UI / loopback server. All API calls are intercepted explicit synthetic fixtures. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, webkit } = require('playwright');
const engine = process.env.POSTRIFF_BROWSER_ENGINE || 'chromium';
assert.ok(['chromium','webkit'].includes(engine), 'Supported browser engine required');
const { fixtures } = require('./trend-fixtures.cjs');
const workspaceFixture = require('./fixtures/wp04a-workspace.json');
const base = process.env.TREND_WEB_URL;
assert.ok(
  base && new URL(base).hostname === '127.0.0.1',
  'Explicit loopback-only TREND_WEB_URL required'
);
const out = process.env.TREND_EVIDENCE_DIR;
assert.ok(out, 'Explicit isolated TREND_EVIDENCE_DIR required');
fs.mkdirSync(out, { recursive: true });
const colorScheme = process.env.TREND_COLOR_SCHEME || 'light';
const longContent = process.env.TREND_LONG_CONTENT === '1';
const results = [];
const record = (name, detail) => {
  results.push({ name, pass: true, detail });
  console.log('PASS ' + name);
};
async function axe(page, name) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const issues = await page.evaluate(async () => {
    const result = await window.axe.run(
      document.querySelector('[role="dialog"]') ?? document.querySelector('main') ?? document,
      { resultTypes: ['violations'] }
    );
    return result.violations
      .filter((v) => ['serious', 'critical'].includes(v.impact))
      .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target) }));
  });
  assert.deepEqual(issues, [], name + ' axe');
  record(name + ' axe');
}
async function noOverflow(page, name) {
  assert.ok(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
    name + ' horizontal overflow'
  );
  record(name + ' fits viewport');
}
async function visibleText(page, pattern) {
  await page.getByText(pattern).first().waitFor();
}
async function run() {
  const browser = await ({chromium,webkit})[engine].launch({ headless: true });
  try {
    for (const width of (process.env.TREND_WIDTHS || '1440,390,820').split(',').map(Number)) {
      const context = await browser.newContext({
        viewport: { width, height: 1000 },
        reducedMotion: 'reduce',
        colorScheme
      });
      const f = fixtures({ longContent }),
        snapshot = structuredClone(workspaceFixture.snapshot),
        wid = snapshot.state.workspace.id;
      snapshot.state.phase2.jobs = [];
      snapshot.state.phase2.reviews = [];
      snapshot.state.variants = snapshot.state.variants.slice(0, 1);
      snapshot.state.variants[0].rejected = false;
      snapshot.state.variants[0].blockedByRetraction = false;
      snapshot.state.phase2.channels = [
        {
          id: 'synthetic-channel',
          platform: 'LinkedIn',
          account: 'Synthetic teacher',
          displayState: 'read_verified',
          revoked: false
        }
      ];
      f.opportunity.draft_id = snapshot.state.variants[0].id;
      f.run.draft_id = snapshot.state.variants[0].id;
      let flagsOn = false,
        workspaceAllowed = true,
        scenario = 'fresh',
        revokedReceipt = false,
        watch = null,
        labDelay = false,
        completeLab;
      const calls = [],
        unhandledMutations = [],
        external = [],
        errors = [];
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
        ({ tours, colorScheme }) => {
          localStorage.setItem('theme', colorScheme);
          const id = '00000000-0000-0000-0000-000000000001';
          localStorage.setItem('postriff-dev-principal', id);
          const state = JSON.stringify({
            completed: {},
            dismissed: Object.fromEntries(tours.map((t) => [t, 1])),
            nudged: Object.fromEntries(tours.map((t) => [t, 1]))
          });
          localStorage.setItem('postriff-onboarding', state);
          localStorage.setItem('postriff-onboarding:' + id, state);
        },
        { tours, colorScheme }
      );
      await context.route('**/*', async (route) => {
        const req = route.request(),
          url = new URL(req.url()),
          pathname = url.pathname;
        if (url.origin !== base) {
          external.push(url.origin);
          return route.abort();
        }
        if (!pathname.startsWith('/api/')) return route.continue();
        const body = req.method() === 'POST' ? req.postDataJSON() : null;
        calls.push({ method: req.method(), path: pathname, query: url.search, body });
        const send = (data, status = 200) =>
          route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
        const root = `/api/workspaces/${wid}/coworker/trends`;
        if (pathname.startsWith(root)) {
          assert.match(req.headers().authorization, /^Bearer dev:/);
          assert.equal(req.headers()['x-postriff-request'], 'founder-alpha');
          const endpoint = pathname.slice(root.length);
          if (endpoint === '' && req.method() === 'GET') {
            if (scenario === 'loading') await new Promise((r) => setTimeout(r, 700));
            if (scenario === 'unavailable')
              return send({ code: 'source_unavailable', error: 'No source' }, 503);
            if (scenario === 'error')
              return send({ code: 'invalid_request', error: 'Safe error' }, 400);
            if (scenario === 'invalid') return send({ data: [] });
            const t = structuredClone(f.trend);
            if (scenario === 'expired') t.verification_state = 'inputs_expired';
            if (scenario === 'deleted') t.verification_state = 'inputs_deleted';
            if (scenario === 'low_confidence') {
              t.inferred = { ...t.inferred, confidence: 'unknown', data_state: 'provisional' };
              t.workspace_fit = null;
            }
            if (scenario === 'aggregate') {
              t.coverage.representation = 'aggregate_only';
              t.evidence = [
                { id: 'restricted', display_state: 'restricted', reason: 'No display' }
              ];
            }
            const data = url.searchParams.get('query') === 'nothing' ? [] : [t];
            return send({
              ...f.envelope(
                data,
                scenario === 'partial'
                  ? 'partial'
                  : scenario === 'collecting'
                    ? 'collecting'
                    : 'stored_result'
              ),
              next_cursor:
                scenario === 'pagination' && !url.searchParams.has('cursor')
                  ? 'synthetic-next'
                  : null
            });
          }
          if (endpoint === '/opportunities')
            return send(
              f.envelope(
                scenario === 'low_confidence'
                  ? []
                  : [
                      {
                        ...f.opportunity,
                        ...(scenario === 'opportunity_expired'
                          ? { expires_at: '2000-01-01T00:00:00Z' }
                          : {})
                      }
                    ]
              )
            );
          if (endpoint === '/opportunities/whitespace' && req.method() === 'GET')
            return send(f.envelope([]));
          if (endpoint === '/opportunities/synthetic-opportunity/accept') {
            assert.equal(req.method(), 'POST');
            assert.equal(body.angle_id, 'synthetic-angle');
            assert.equal(body.channel_id, 'synthetic-channel');
            assert.equal(body.revision, 1);
            assert.ok(body.idempotency_key);
            return send(
              f.envelope({
                source_id: 'synthetic-source',
                href: '/app/ideas?source=synthetic-source',
                verified: true,
                existing: false
              })
            );
          }
          if (endpoint === '/watches' && req.method() === 'POST') {
            assert.equal(body.notification_policy, 'in_app');
            assert.deepEqual(body.platforms, ['bluesky']);
            watch = {
              id: 'synthetic-watch',
              revision: 1,
              trend_id: body.trend_id,
              platforms: body.platforms,
              threshold: body.threshold,
              notification_policy: body.notification_policy,
              active: true
            };
            return send(f.envelope(watch));
          }
          if (endpoint === '/watches' && req.method() === 'GET')
            return send(f.envelope(watch ? [watch] : []));
          if (endpoint === '/watches/synthetic-watch' && req.method() === 'DELETE') {
            assert.equal(url.searchParams.get('expected_revision'), '1');
            assert.ok(url.searchParams.get('idempotency_key'));
            watch.active = false;
            watch.revision++;
            return send(f.envelope(watch));
          }
          if (endpoint === '/opportunity-lab/runs' && req.method() === 'POST') {
            assert.deepEqual(
              Object.keys(body).sort(),
              [
                'draft_id',
                'draft_revision',
                'opportunity_id',
                'opportunity_revision',
                'target_platform',
                'idempotency_key'
              ].sort()
            );
            assert.equal(body.draft_id, snapshot.state.variants[0].id);
            if (labDelay)
              await new Promise((r) => {
                completeLab = r;
              });
            return send(f.envelope({ ...f.run, draft_revision: body.draft_revision }));
          }
          if (endpoint.startsWith('/opportunity-lab/runs/')) return send(f.envelope(f.run));
          if (endpoint.endsWith('/receipts/synthetic-receipt'))
            return revokedReceipt
              ? send({ code: 'evidence_unavailable', error: 'Revoked' }, 410)
              : send(
                  f.envelope(
                    scenario === 'aggregate'
                      ? {
                          ...f.receipt,
                          evidence: [],
                          coverage: { ...f.coverage, representation: 'aggregate_only' }
                        }
                      : f.receipt
                  )
                );
          if (endpoint === '/synthetic-trend') return send(f.envelope(f.trend));
          const values = {
            '/methodology': f.methodology,
            '/calibration': f.calibration,
            '/language-patterns': f.languages,
            '/synthetic-trend/genome': f.genome,
            '/synthetic-trend/propagation': f.propagation,
            '/synthetic-trend/saturation': f.saturation
          };
          if (endpoint in values) return send(f.envelope(values[endpoint]));
          throw new Error('Unhandled trend fixture ' + req.method() + ' ' + endpoint);
        }
        if (pathname.endsWith('/actions') && body?.action === 'variant_edit') {
          assert.equal(body.payload.variantRevision, snapshot.state.variants[0].revision);
          snapshot.revision++;
          snapshot.state.variants[0].revision++;
          snapshot.state.variants[0].text = body.payload.text;
          snapshot.state.variants[0].needsReview = true;
          return send(snapshot);
        }
        if (req.method() !== 'GET') {
          if (pathname.endsWith('/active-time') || pathname.endsWith('/time-savings/activity'))
            return send({ verified: true });
          unhandledMutations.push(req.method() + ' ' + pathname);
          return send({ error: 'Unexpected mutation' }, 403);
        }
        if (pathname === '/api/catalog')
          return send({
            authMode: 'dev',
            execution: 'dev-synthetic',
            phase2: true,
            templates: [],
            routes: [],
            profileMetadata: {}
          });
        if (pathname === '/api/workspaces')
          return send({
            workspaces: [
              {
                workspaceId: wid,
                membership: snapshot.membership,
                name: 'Synthetic Trend workspace',
                plan: 'studio',
                memberCounts: { owner: 1 }
              }
            ]
          });
        if (pathname === '/api/me')
          return send({
            userId: '00000000-0000-0000-0000-000000000001',
            displayName: 'Synthetic owner',
            preferences: { timeZone: 'UTC', locale: 'en', alertNewDevice: false },
            mfa: {}
          });
        if (pathname === `/api/workspaces/${wid}`) return send(snapshot);
        if (pathname.endsWith('/coworker/status'))
          return send({
            flags: flagsOn ? f.flags : {},
            trend_beta: { state: !flagsOn ? 'feature_off' : workspaceAllowed ? 'stored_radar' : 'workspace_not_allowlisted',
              radar_available: flagsOn && workspaceAllowed, acquisition: 'none', metric_reads_enabled: false,
              follower_conversion: 'unavailable' },
            weekly: { recipes: 0, weeks: 0 },
            notifications: { enabled: false }
          });
        if (pathname.endsWith('/usage'))
          return send({
            subscription: { plan: 'studio', status: 'active' },
            trial: {},
            balances: []
          });
        if (pathname.endsWith('/phone'))
          return send({ available: false, providerReady: false, flags: {}, number: null,
            preferences: { enabled: false, proactiveCalls: false, scheduledCalls: false,
              quietStart: 22, quietEnd: 8, timeZone: 'UTC', maxCallsPerDay: 0,
              maxMilliCreditsPerCall: 0, eventAllowlist: [], customRules: [],
              fallbackToPush: false, fallbackToEmail: false }, calls: [], schedules: [] });
        if (pathname.endsWith('/memory')) return send(workspaceFixture.memory);
        if (pathname.endsWith('/memory/proposals'))
          return send({ pending: [], recent: [], learning: { items: [] } });
        if (pathname.endsWith('/ideas/conversations')) return send({ conversations: [] });
        if (pathname.endsWith('/channels'))
          return send({ channels: snapshot.state.phase2.channels, providers: [] });
        if (pathname.endsWith('/audit')) return send({ entries: [] });
        if (pathname.endsWith('/time-savings')) return send({});
        return send({ error: 'Unavailable unrelated fixture route' }, 404);
      });
      const page = await context.newPage();
      page.setDefaultTimeout(45000);
      page.on('pageerror', (e) => errors.push(e.message));
      try {
        await page.goto(base + '/app/trends', { waitUntil: 'domcontentloaded', timeout: 180000 });
        await visibleText(page, 'Trend Beta is off');
        assert.equal(calls.filter((c) => c.path.includes('/coworker/trends')).length, 0);
        record(width + ' flags off: zero trend requests');
        flagsOn = true;
        workspaceAllowed = false;
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 120000 });
        await visibleText(page, 'This workspace is outside the Trend Beta');
        assert.equal(calls.filter((c) => c.path.includes('/coworker/trends')).length, 0);
        record(width + ' workspace not allowlisted: zero trend requests');
        workspaceAllowed = true;
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 120000 });
        await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor();
        assert.equal(
          calls.some((c) => c.path.includes('/coworker/trends') && c.method !== 'GET'),
          false
        );
        record(width + ' browse stored data only, authenticated contract');
        await noOverflow(page, width + ' radar');
        await axe(page, width + ' radar');
        if (process.env.TREND_GROWTH_BETA_SMOKE_ONLY === '1') {
          await visibleText(page, 'Source coverage is limited; live discovery is not verified.');
          assert.deepEqual(errors, [], 'browser runtime errors');
          assert.deepEqual(unhandledMutations, [], 'unexpected mutations');
          record(width + ' limited source coverage and no runtime/mutation errors');
          continue;
        }
        assert.equal(
          await page.locator('html').evaluate((el) => el.classList.contains('dark')),
          colorScheme === 'dark'
        );
        assert.ok((await page.getByText('Demo data', { exact: true }).count()) >= 1);
        assert.equal(await page.locator('[data-trend-card] .vi-state').innerText(), 'Still taking shape');
        assert.equal(
          await page
            .locator('.trend-radar svg polyline, .trend-radar svg path[data-sparkline]')
            .count(),
          0
        );
        const evidenceSummary = page
          .locator('summary')
          .filter({ hasText: 'Timeline and original conversations' });
        await evidenceSummary.focus();
        await page.keyboard.press('Space');
        await visibleText(page, f.trend.evidence[0].excerpt);
        await evidenceSummary.click();
        const scope = page.locator('.trend-scope-summary > summary');
        await scope.click();
        await page
          .locator('.trend-scope-summary')
          .getByText('Source details and limits', { exact: true })
          .click();
        for (const value of [
          'synthetic-scope',
          'synthetic-epoch',
          f.coverage.scope,
          'Freshness deadline:'
        ])
          assert.ok(
            (await page.locator('.trend-scope-summary .trend-coverage').innerText()).includes(value)
          );
        await scope.click();
        const creatorText = await page.locator('[data-trend-card]').innerText();
        const primaryText = (await page.locator('.vi-insight, .vi-primary').allInnerTexts()).join('\n');
        for (const term of [
          'evidence only',
          'qualified',
          'calibration',
          'denominator',
          'posts/hour',
          'Coverage unavailable',
          'measurement support'
        ])
          assert.ok(
            !primaryText.toLowerCase().includes(term.toLowerCase()),
            'Primary copy excludes ' + term
          );
        assert.ok(creatorText.includes('Evidence & Coverage'));
        assert.ok(creatorText.includes('Momentum Curve'));
        assert.ok(primaryText.includes('Key Insight') && primaryText.includes('Create original post'));
        record(
          width +
            ' explicit demo, native emoji, exact timeline, coverage axes and keyboard disclosure'
        );
        if (width === 1440) {
          await page.emulateMedia({ reducedMotion: 'no-preference' });
          await page.waitForFunction(
            () =>
              getComputedStyle(document.querySelector('.trend-radar .rafii-lens'))
                .transitionDuration === '0.2s'
          );
          assert.equal(
            await page
              .locator('.trend-disclosure-chevron')
              .first()
              .evaluate((el) => getComputedStyle(el).transitionDuration),
            '0.2s'
          );
          await page.emulateMedia({ reducedMotion: 'reduce' });
          await page.waitForFunction(
            () =>
              getComputedStyle(document.querySelector('.trend-radar .rafii-lens'))
                .transitionDuration === '0s'
          );
          record('meaningful 200ms motion; reduced motion removes it');
        }
        await page.screenshot({ path: path.join(out, `radar-${width}.png`), fullPage: true });
        const trust = page.getByRole('button', { name: 'Why should I trust this?', exact: true });
        await trust.click();
        const drawer = page.getByRole('dialog');
        await drawer.getByRole('heading', { name: '1. What we saw' }).waitFor();
        for (const title of [
          '2. How the conversation is changing',
          '3. How Rafii reads the pattern',
          '4. What it might mean'
        ])
          assert.equal(await drawer.getByRole('heading', { name: title }).count(), 1);
        assert.equal(
          await drawer.getByText(f.trend.evidence[0].excerpt, { exact: true }).count(),
          1
        );
        assert.ok(!(await drawer.innerText()).includes('posts/hour^2')); // raw units live one level deeper
        await drawer.getByText('Measurement details and methodology', { exact: true }).click();
        await visibleText(drawer, /synthetic-method \/ 2/);
        assert.ok((await drawer.innerText()).includes('posts/hour^2'));
        assert.ok((await drawer.innerText()).includes('Insufficient observations'));
        for (const value of [
          'synthetic-baseline',
          'end excluded',
          'synthetic-snapshot-2',
          'synthetic-receipt'
        ])
          assert.ok((await drawer.innerText()).includes(value));
        await drawer.getByText('Workspace fit, timing and risk', { exact: true }).click();
        assert.equal(await drawer.locator('.trend-fit-grid > div').count(), 7);
        await drawer.getByText('Workspace fit, timing and risk', { exact: true }).click();
        record(
          width + ' exact method windows units snapshots and seven independent fit dimensions'
        );

        await drawer.getByRole('tab', { name: 'Timeline', exact: true }).click();
        await visibleText(drawer, 'Gap — Collector unavailable');
        assert.equal(
          await drawer.locator('.trend-timeline-point').count(),
          f.trend.observed.timeline.length
        );
        await drawer.getByRole('tab', { name: 'Graph / list' }).focus();
        await page.keyboard.press('Enter');
        await visibleText(drawer, /Directly observed relation/);
        await visibleText(drawer, /Hypothesized adaptation/);
        await drawer.getByText('First-seen observations', { exact: true }).click();
        assert.equal(
          await drawer.locator('.trend-disclosure[open] li').count(),
          f.propagation.nodes.length
        );
        await drawer.getByText('First-seen observations', { exact: true }).click();
        await drawer.getByRole('tab', { name: 'Genome & narratives' }).click();
        await visibleText(drawer, 'Practice as listening');
        await drawer.getByRole('tab', { name: 'Crowding' }).click();
        await visibleText(drawer, '80 classified / 100 eligible observations');
        assert.equal(
          await drawer.locator('.trend-crowding').count(),
          f.saturation.dimensions.length
        );
        assert.equal(
          await drawer.getByText('Denominator: 80 classified posts', { exact: true }).count(),
          5
        );
        await drawer.getByRole('tab', { name: 'Evidence', exact: true }).click();
        assert.ok((await drawer.innerText()).includes(f.trend.unverified_claims[0]));
        assert.ok(await drawer.evaluate((el) => el.scrollWidth <= el.clientWidth + 1));
        await axe(page, width + ' trust drawer');
        await page.screenshot({ path: path.join(out, `trust-${width}.png`), fullPage: false });
        assert.ok(
          await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
        );
        assert.equal(await drawer.evaluate((el) => getComputedStyle(el).transitionDuration), '0s');
        record(width + ' reduced motion removes drawer transitions');
        for (let i = 0; i < 8; i++) {
          await page.keyboard.press('Tab');
          await page
            .waitForFunction(
              () => document.querySelector('[role="dialog"]')?.contains(document.activeElement),
              {},
              { timeout: 1500 }
            )
            .catch(async (e) => {
              console.log(
                'FOCUS DEBUG',
                await page.evaluate(() => ({
                  active: document.activeElement?.outerHTML,
                  dialogs: [...document.querySelectorAll('[role="dialog"]')].map((d) =>
                    d.outerHTML.slice(0, 400)
                  )
                }))
              );
              throw e;
            });
        }
        await page.keyboard.press('Escape');
        await drawer.waitFor({ state: 'hidden' });
        assert.ok(await trust.evaluate((el) => el === document.activeElement));
        record(
          width + ' trust layers, native language, graph equivalent, focus trap/Escape/restore'
        );
        await page.getByRole('button', { name: 'How this works' }).click();
        await visibleText(page, /Not enough comparable history. Calibration is unknown/);
        assert.equal(await page.getByText('99 percent', { exact: true }).count(), 0);
        record(width + ' insufficient calibration hides percentage');
        await page.getByRole('button', { name: 'How this works' }).click();
        await page.getByRole('tab', { name: 'Language & Slang', exact: true }).click();
        await visibleText(page, f.languages[0].meaning);
        assert.equal(await page.getByText(f.trend.evidence[0].excerpt, { exact: true }).count(), 1);
        await page.getByRole('tab', { name: 'For You', exact: true }).click();
        await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor();
        record(width + ' native language interpretation and evidence retained');
        if (width === 1440) {
          const latestList = () => calls.filter((c) => c.path.endsWith('/coworker/trends')).at(-1);
          const queryHas = async (key, value) => {
            for (let i = 0; i < 100; i++) {
              if (new URLSearchParams(latestList().query).get(key) === value) return;
              await page.waitForTimeout(20);
            }
            assert.equal(new URLSearchParams(latestList().query).get(key), value);
          };
          for (const [label, value] of [
            ['Picking up', 'rising'],
            ['Breaking out', 'breaking'],
            ['Active now', 'hot'],
            ['Platforms', 'platforms'],
            ['Niche', 'niche']
          ]) {
            await page.getByRole('tab', { name: label, exact: true }).click();
            await queryHas('view', value);
          }
          await page.getByRole('textbox', { name: 'Niche', exact: true }).fill('practice');
          await queryHas('niche', 'practice');
          await page.getByRole('combobox', { name: /^Platform/ }).selectOption('bluesky');
          await queryHas('platform', 'bluesky');
          await page.getByRole('combobox', { name: /^Language/ }).selectOption('yue');
          await queryHas('language', 'yue');
          await page.getByRole('combobox', { name: /^Time range/ }).selectOption('1');
          await page.waitForTimeout(150);
          const elapsed =
            Date.now() - Date.parse(new URLSearchParams(latestList().query).get('since'));
          assert.ok(elapsed >= 86400000 && elapsed < 86410000);
          await page.getByRole('tab', { name: 'For You', exact: true }).click();
          await queryHas('view', 'for_you');
          for (const [key, value] of [
            ['niche', 'practice'],
            ['platform', 'bluesky'],
            ['language', 'yue']
          ])
            assert.equal(new URLSearchParams(latestList().query).get(key), value);
          await page.getByRole('button', { name: /^Filters/ }).click();
          record('all section and filter queries preserved across navigation');
          scenario = 'pagination';
          await page.reload({ waitUntil: 'domcontentloaded' });
          await page.getByRole('button', { name: 'Next page', exact: true }).click();
          await queryHas('cursor', 'synthetic-next');
          await page.getByRole('button', { name: 'Back to first page', exact: true }).click();
          await queryHas('cursor', null);
          await page.getByRole('button', { name: 'Next page', exact: true }).click();
          await queryHas('cursor', 'synthetic-next');
          await page.getByRole('button', { name: /^Filters/ }).click();
          await page.getByRole('combobox', { name: /^Platform/ }).selectOption('bluesky');
          await queryHas('platform', 'bluesky');
          await queryHas('cursor', null);
          scenario = 'fresh';
          await page.reload({ waitUntil: 'domcontentloaded' });
          await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor();
          record('pagination and filter cursor reset preserve server contract');

          await page.getByText('Watch this conversation', { exact: true }).click();
          await page.getByRole('checkbox', { name: 'bluesky', exact: true }).check();
          await page.getByRole('button', { name: 'Save watch', exact: true }).click();
          await visibleText(page, /Watching · bluesky/);
          await page.getByRole('tab', { name: 'Watchlist', exact: true }).click();
          await page.getByRole('button', { name: 'Disable watch' }).click();
          await visibleText(page, /Disabled · bluesky/);
          record('watch persisted create + revision-safe disable');
          await page.getByRole('tab', { name: 'For You', exact: true }).click();
          await page.getByText(f.opportunity.angles[0].title, { exact: true }).first().click();
          await visibleText(
            page,
            'Facts you need: ' + f.opportunity.angles[0].factual_requirements.join('; ')
          );
          await visibleText(page, 'Format: ' + f.opportunity.angles[0].format_reason);
          await page.getByText(f.opportunity.angles[0].title, { exact: true }).first().click();
          await page.getByText('Develop this idea', { exact: true }).click();
          await page
            .getByRole('combobox', { name: /^Destination account/ })
            .selectOption('synthetic-channel');
          await page.getByLabel('Your goal').fill('Teach a useful practice habit');
          await page.getByRole('button', { name: 'Save to Ideas' }).click();
          await page
            .getByRole('link', { name: 'Review source and create original post' })
            .waitFor();
          record('accept opportunity into existing Ideas source, no generation');
          await page.getByLabel('Search trends').fill('nothing');
          await page.getByRole('button', { name: 'Search', exact: true }).click();
          await visibleText(page, 'No matches in the available scope');
          record('empty exact filters and interval');
          for (const state of [
            'loading',
            'partial',
            'collecting',
            'unavailable',
            'error',
            'invalid',
            'expired',
            'deleted',
            'aggregate',
            'low_confidence',
            'opportunity_expired'
          ]) {
            scenario = state;
            await page.reload({ waitUntil: 'domcontentloaded', timeout: 120000 });
            if (state === 'loading') {
              await page.getByRole('status', { name: 'Loading evidence…' }).waitFor();
              await page
                .getByRole('heading', { name: f.trend.canonical_topic, exact: true })
                .waitFor();
            }
            if (state === 'partial') await visibleText(page, 'Some coverage is missing');
            if (state === 'collecting') await visibleText(page, 'Collecting evidence');
            if (state === 'unavailable') await visibleText(page, 'Sources are unavailable');
            if (state === 'error' || state === 'invalid')
              await visibleText(page, 'Trends could not load');
            if (state === 'expired' || state === 'deleted') {
              await visibleText(page, 'Evidence revoked or expired');
              assert.equal(
                await page.locator('[data-trend-card] .vi-insight').count(),
                0
              );
              assert.equal(
                await page.getByText(f.trend.evidence[0].excerpt, { exact: true }).count(),
                0
              );
            }
            if (state === 'low_confidence') {
              const main = page.locator('[data-trend-card]');
              await main.getByText('Workspace relevance is Unknown. Your audience and brand context need support.').waitFor();
              await main.getByText('Original angles are not available for this selection').waitFor();
              assert.equal(await main.getByRole('button', { name: 'Create original post' }).isDisabled(), true);
              assert.equal(await page.getByText('Develop this idea', { exact: true }).count(), 0);
            }
            if (state === 'opportunity_expired') {
              await visibleText(page, 'Original angles are not available for this selection');
              assert.equal(await page.getByRole('button', { name: 'Create original post' }).isDisabled(), true);
              assert.equal(await page.getByText('Develop this idea', { exact: true }).count(), 0);
            }
            if (state === 'aggregate') {
              await page.getByRole('button', { name: 'Why should I trust this?' }).click();
              await visibleText(page.getByRole('dialog'), /No display-permitted conversations/);
              assert.equal(
                await page.getByText(f.trend.evidence[0].excerpt, { exact: true }).count(),
                0
              );
              await page.keyboard.press('Escape');
            }
            record('state ' + state);
          }
          scenario = 'fresh';
          revokedReceipt = true;
          await page.reload({ waitUntil: 'domcontentloaded', timeout: 120000 });
          await page.getByRole('button', { name: 'Why should I trust this?' }).click();
          await visibleText(page, 'Evidence revoked or no longer available');
          await page.keyboard.press('Escape');
          await visibleText(page, 'Evidence revoked or expired');
          assert.equal(
            await page.locator('[data-trend-card] .vi-insight').count(),
            0
          );
          record('receipt 410 removes card claims');
          revokedReceipt = false;
          await page.goto(base + '/app/queue?view=drafts');
          await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
          const editor = page.getByRole('dialog');
          await editor.getByRole('heading', { name: 'Opportunity Lab', exact: true }).waitFor();
          assert.equal(
            calls.some((c) => c.path.endsWith('/opportunity-lab/runs')),
            false
          );
          await editor.getByRole('button', { name: 'Review this draft' }).click();
          await visibleText(editor, 'Review ready for saved version 1.');
          assert.equal(await editor.getByRole('button', { name: 'Apply this edit' }).count(), 2);
          assert.equal(
            await editor.getByRole('button', { name: 'Apply this edit' }).nth(1).isDisabled(),
            true
          );
          await editor.getByText('Original wording', { exact: true }).first().click();
          await visibleText(editor, f.run.diagnostics[0].suggested_edit.before);
          await editor.getByText('Demo data', { exact: true }).waitFor();
          await editor.getByText('Evidence and comparison', { exact: true }).first().click();
          await visibleText(editor, 'Comparison: ' + f.run.diagnostics[0].comparison_frame);
          await editor.getByText('Evidence and comparison', { exact: true }).first().click();
          await axe(page, 'Lab populated diagnostics');
          await page.screenshot({
            path: path.join(out, 'lab-diagnostics-1440.png'),
            fullPage: false
          });
          await editor.getByRole('button', { name: 'Apply this edit' }).first().click();
          await visibleText(editor, 'This check is stale');
          assert.match(
            await editor.getByRole('textbox', { name: 'Draft text' }).inputValue(),
            /^Listen to one phrase/
          );
          record('Lab explicit check, user-fact guard, selective existing revision edit');
          await axe(page, 'Lab existing editor');
          await page.screenshot({ path: path.join(out, 'lab-1440.png'), fullPage: true });
          await page.keyboard.press('Escape');
          await page.goto(base + '/app/queue?view=drafts');
          await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
          labDelay = true;
          await page.getByRole('button', { name: 'Review this draft' }).click();
          await page
            .getByRole('textbox', { name: 'Draft text' })
            .fill('Unsaved revision changed during evaluation.');
          for (let tries = 0; tries < 50 && !completeLab; tries++) await page.waitForTimeout(20);
          assert.ok(completeLab);
          completeLab();
          await visibleText(page, 'This check is stale');
          assert.equal(await page.getByRole('button', { name: 'Apply this edit' }).count(), 0);
          record('Lab stale-result race leaves changed draft untouched');
          await page.keyboard.press('Escape');
          f.opportunity.draft_id = null;
          await page.reload({ waitUntil: 'domcontentloaded' });
          await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
          await visibleText(page, 'Opportunity Lab unavailable for this draft');
          assert.equal(await page.getByRole('button', { name: 'Review this draft' }).count(), 0);
          await page.keyboard.press('Escape');
          f.opportunity.draft_id = snapshot.state.variants[0].id;
          record('Lab absent server linkage stays unavailable');
        }
        if (width !== 1440) {
          await page.goto(base + '/app/queue?view=drafts');
          await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
          const editor = page.getByRole('dialog');
          await editor.getByRole('button', { name: 'Review this draft' }).click();
          await visibleText(editor, 'Review ready for saved version 1.');
          await editor.getByText('Demo data', { exact: true }).waitFor();
          await noOverflow(page, width + ' Lab');
          await axe(page, width + ' Lab populated diagnostics');
          await page.screenshot({
            path: path.join(out, `lab-diagnostics-${width}.png`),
            fullPage: false
          });
          await page.keyboard.press('Escape');
          await page.goto(base + '/app/trends');
          await page.getByRole('heading', { name: f.trend.canonical_topic, exact: true }).waitFor();
        }
        if (width === 820) {
          // Browser zoom changes the CSS viewport as well as pixel density; CSS `zoom` alone
          // leaves media queries at 820px and is not an equivalent test of browser zoom.
          await page.setViewportSize({ width: 410, height: 500 });
          if (engine === 'chromium') {
            const cdp = await context.newCDPSession(page);
            await cdp.send('Emulation.setDeviceMetricsOverride', {
              width: 410, height: 500, deviceScaleFactor: 2, mobile: false
            });
          }
          assert.equal(await page.evaluate(() => matchMedia('(max-width: 767px)').matches), true);
          record(engine === 'chromium'
            ? '200% browser-zoom-equivalent reflow: 820 physical pixels / 410 CSS pixels'
            : 'WebKit 200% reflow layout: 410 CSS pixels; browser zoom and pixel density not emulated');
          await noOverflow(page, '820 at 200% zoom');
          await page.getByRole('button', { name: 'Why should I trust this?' }).click();
          await page.getByRole('dialog').getByRole('heading', { name: '1. What we saw' }).waitFor();
          await noOverflow(page, 'drawer at 200% zoom');
          await axe(page, '200% zoom');
          await page.screenshot({ path: path.join(out, 'zoom-200.png'), fullPage: false });
        }
        assert.deepEqual(errors, [], 'browser runtime errors');
        assert.deepEqual(unhandledMutations, [], 'unexpected mutations');
        record(width + ' zero unexpected mutations/runtime errors', {
          externalBlocked: external.length
        });
      } catch (error) {
        fs.writeFileSync(
          path.join(out, `failure-${width}.txt`),
          JSON.stringify({ error: String(error), errors, calls }, null, 2) +
            '\n' +
            (await page
              .locator('body')
              .innerText()
              .catch(() => ''))
        );
        await page
          .screenshot({ path: path.join(out, `failure-${width}.png`), fullPage: true })
          .catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(out, 'results.json'),
      JSON.stringify(
        { execution: 'synthetic_intercepted_browser', engine, colorScheme, longContent, results },
        null,
        2
      )
    );
  }
}
run().catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
