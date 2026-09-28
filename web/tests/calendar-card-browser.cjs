/**
 * Read-only calendar-card browser gate.
 *
 *   node tests/calendar-card-browser.cjs --out=/tmp/calendar-card
 *
 * Run against the local Next development server only. The fixture is synthetic and production-404;
 * the test makes no provider, publishing, approval or scheduling call.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3190';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname))
  throw new Error('Calendar-card browser checks run against localhost only.');
const args = Object.fromEntries(
  process.argv
    .slice(2)
    .map((arg) => arg.replace(/^--/, '').split('='))
    .map(([key, value]) => [key, value ?? true])
);
const out = path.resolve(args.out || '.');
fs.mkdirSync(out, { recursive: true });

const viewports = [
  { name: '320', width: 320, height: 800 },
  { name: '390x844', width: 390, height: 844 },
  { name: '430x932', width: 430, height: 932 },
  { name: '1440x900', width: 1440, height: 900 }
];
const results = [];
const check = (viewport, name, ok, detail) => {
  results.push({ viewport, name, ok: Boolean(ok), detail: ok ? undefined : detail });
  process.stdout.write(
    `${ok ? 'ok  ' : 'FAIL'} ${viewport}: ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail).slice(0, 400)}` : ''}\n`
  );
};

async function axe(page) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async () => {
    const report = await window.axe.run('[data-testid="calendar-card"]', {
      resultTypes: ['violations']
    });
    return report.violations
      .filter((violation) => ['serious', 'critical'].includes(violation.impact))
      .map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.length,
        target: violation.nodes[0]?.target
      }));
  });
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.RAFII_CHROMIUM_PATH || undefined
  });
  try {
    for (const viewport of viewports) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: 1,
        colorScheme: 'dark',
        reducedMotion: 'reduce',
        hasTouch: viewport.width < 768,
        isMobile: viewport.width < 768
      });
      await context.addInitScript(() => {
        localStorage.setItem('rafii.motion', 'reduced');
        document.addEventListener('DOMContentLoaded', () => {
          const style = document.createElement('style');
          style.textContent = 'nextjs-portal,.tsqd-open-btn-container{display:none!important}';
          document.head.appendChild(style);
        });
      });
      const page = await context.newPage();
      await page.goto(`${base}/dev/calendar-card`, { waitUntil: 'networkidle', timeout: 120000 });
      const card = page.getByTestId('calendar-card');
      await card.waitFor({ state: 'visible', timeout: 30000 });

      const labels = await card.locator('dt').allInnerTexts();
      check(
        viewport.name,
        'six lifecycle states stay distinct',
        [
          'Scheduled',
          'Awaiting approval',
          'In flight',
          'Failed / held / uncertain',
          'Published, confirming',
          'Verified live'
        ].every((label) => labels.includes(label)),
        labels
      );
      check(
        viewport.name,
        'card exposes no mutation controls',
        (await card.locator('button,input,textarea,select,[role="button"]').count()) === 0
      );
      const links = card.getByRole('link');
      check(
        viewport.name,
        'only read-only Calendar navigation is interactive',
        (await links.count()) === 1 &&
          (await links.first().getAttribute('href')) === '/app/calendar',
        await links.allInnerTexts()
      );

      const geometry = await page.evaluate(() => {
        const root = document.scrollingElement;
        const card = document.querySelector('[data-testid="calendar-card"]');
        const box = card?.getBoundingClientRect();
        return {
          viewport: window.innerWidth,
          pageScrollWidth: root?.scrollWidth,
          cardClientWidth: card?.clientWidth,
          cardScrollWidth: card?.scrollWidth,
          card: box && { x: box.x, right: box.right, width: box.width }
        };
      });
      check(
        viewport.name,
        'page has no horizontal overflow',
        geometry.pageScrollWidth <= viewport.width + 1,
        geometry
      );
      check(
        viewport.name,
        'card has no internal horizontal overflow',
        geometry.cardScrollWidth <= geometry.cardClientWidth + 1,
        geometry
      );
      check(
        viewport.name,
        'card stays inside the viewport',
        geometry.card && geometry.card.x >= -1 && geometry.card.right <= viewport.width + 1,
        geometry
      );

      const violations = await axe(page);
      check(
        viewport.name,
        'axe has no serious or critical violations',
        violations.length === 0,
        violations
      );
      await page.waitForTimeout(350);
      const animations = await card.evaluate(
        (element) =>
          element
            .getAnimations({ subtree: true })
            .filter((animation) => animation.playState === 'running').length
      );
      check(
        viewport.name,
        'reduced motion leaves no running card animation',
        animations === 0,
        animations
      );

      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => ({
        text: document.activeElement?.textContent?.trim(),
        href: document.activeElement?.getAttribute?.('href')
      }));
      check(
        viewport.name,
        'keyboard focus reaches Open Calendar',
        focused.href === '/app/calendar' && /Open Calendar/.test(focused.text || ''),
        focused
      );
      const focusVisible = await links.first().evaluate((element) => {
        const style = getComputedStyle(element);
        return (
          document.activeElement === element &&
          (style.outlineStyle !== 'none' || style.boxShadow !== 'none')
        );
      });
      check(viewport.name, 'focused link has a visible indicator', focusVisible);

      await page.screenshot({
        path: path.join(out, `calendar-card-${viewport.name}.png`),
        fullPage: true
      });
      await context.close();
    }

    // One keyboard activation proves the sole control navigates with GET only; it cannot mutate calendar state.
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      reducedMotion: 'reduce'
    });
    const page = await context.newPage();
    const mutations = [];
    const calendarNavigations = [];
    page.on('request', (request) => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()))
        mutations.push({ method: request.method(), url: request.url() });
      if (request.method() === 'GET' && new URL(request.url()).pathname === '/app/calendar')
        calendarNavigations.push(request.url());
    });
    await page.goto(`${base}/dev/calendar-card`, { waitUntil: 'networkidle', timeout: 120000 });
    const open = page.getByRole('link', { name: 'Open Calendar' });
    await open.focus();
    await page.keyboard.press('Enter');
    await page.waitForURL(
      (url) =>
        url.pathname === '/app/calendar' ||
        (url.pathname === '/auth/sign-in' && url.searchParams.get('next') === '/app/calendar'),
      { timeout: 30000 }
    );
    check(
      '390x844',
      'keyboard activation only navigates; no mutation request is sent',
      calendarNavigations.length > 0 && mutations.length === 0,
      { calendarNavigations, mutations, finalUrl: page.url() }
    );
    await context.close();
  } finally {
    await browser.close();
  }

  const failed = results.filter((result) => !result.ok);
  fs.writeFileSync(
    path.join(out, 'calendar-card-browser.json'),
    JSON.stringify({ base, fixture: 'synthetic', reducedMotion: true, viewports, results }, null, 2)
  );
  console.log(`${results.length - failed.length}/${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})().catch((error) => {
  console.error(error);
  fs.writeFileSync(
    path.join(out, 'calendar-card-browser.json'),
    JSON.stringify(
      {
        base,
        fixture: 'synthetic',
        viewports,
        results,
        stoppedBy: String(error?.message || error)
      },
      null,
      2
    )
  );
  process.exit(1);
});
