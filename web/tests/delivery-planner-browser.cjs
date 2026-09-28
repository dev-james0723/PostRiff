/**
 * Compact conversation Delivery Summary + Channel × Language planner against the local synthetic
 * harness. Creates its own principal and deterministic-preview conversation; no provider is called.
 *
 *   RAFII_WEB_URL=http://127.0.0.1:4782 node web/tests/delivery-planner-browser.cjs --browser=chromium
 *   RAFII_WEB_URL=http://127.0.0.1:4782 node web/tests/delivery-planner-browser.cjs --browser=webkit
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const { randomUUID } = require('node:crypto');
const { chromium, webkit } = require('playwright');

const args = Object.fromEntries(
  process.argv
    .slice(2)
    .map((arg) => arg.replace(/^--/, '').split('='))
    .map(([key, value]) => [key, value ?? true])
);
const browserName = args.browser === 'webkit' ? 'webkit' : 'chromium';
const engine = browserName === 'webkit' ? webkit : chromium;
const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:4782';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname))
  throw new Error('Delivery Planner browser QA runs against the local harness only.');
const out = path.resolve(
  __dirname,
  `../../docs/design/rafii-composer-delivery-planner/evidence/after/${browserName}`
);
fs.mkdirSync(out, { recursive: true });

const report = {
  browser: browserName,
  execution: 'local synthetic providers, emulated viewports',
  checks: [],
  screenshots: [],
  errors: []
};
function check(name, condition, detail) {
  report.checks.push({
    name,
    passed: Boolean(condition),
    ...(detail === undefined ? {} : { detail })
  });
  assert.ok(condition, `${name}${detail === undefined ? '' : `: ${JSON.stringify(detail)}`}`);
}

function crc32(buffer) {
  let value = ~0;
  for (const byte of buffer) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit += 1) value = (value >>> 1) ^ (0xedb88320 & -(value & 1));
  }
  return ~value >>> 0;
}
function png(width, height, rgb) {
  const chunk = (type, data) => {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const checksum = Buffer.alloc(4);
    checksum.writeUInt32BE(crc32(body));
    return Buffer.concat([length, body, checksum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.concat([
    Buffer.from([0]),
    Buffer.from(Array.from({ length: width }, () => rgb).flat())
  ]);
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0))
  ]);
}

async function seed() {
  const principal = randomUUID();
  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer dev:${principal}`,
    'X-PostRiff-Request': 'founder-alpha'
  };
  const call = async (method, pathname, body) => {
    const response = await fetch(base + pathname, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const text = await response.text();
    if (!response.ok)
      throw new Error(`${method} ${pathname}: ${response.status} ${text.slice(0, 300)}`);
    return JSON.parse(text);
  };
  const boot = await call('POST', '/api/auth/verify', {});
  for (const second of [false, true]) {
    const started = await call(
      'POST',
      `/api/workspaces/${boot.workspaceId}/channels/linkedin/oauth/start`,
      { capability: 'publish' }
    );
    await call('POST', `/api/workspaces/${boot.workspaceId}/channels/linkedin/oauth/complete`, {
      state: new URL(started.authorizeUrl).searchParams.get('state'),
      code: second ? 'good-code-2' : 'good-code'
    });
  }
  const snapshot = await call('GET', `/api/workspaces/${boot.workspaceId}`);
  const linkedIn = snapshot.state.phase2.channels.filter(
    (channel) => channel.platform === 'LinkedIn'
  );
  check(
    'seed has two connected LinkedIn accounts',
    linkedIn.length === 2,
    linkedIn.map((channel) => channel.account)
  );
  const run = await call('POST', `/api/workspaces/${boot.workspaceId}/ideas/quick-start`, {
    expectedRevision: snapshot.revision,
    text: 'A small practice habit makes room for creativity.',
    ownContent: true,
    confirmUse: true,
    destinations: [
      { platform: 'LinkedIn', language: 'en-US', channelId: linkedIn[0].id },
      { platform: 'LinkedIn', language: 'en-US', channelId: linkedIn[1].id },
      { platform: 'Threads', language: 'en-GB' }
    ],
    model: 'deterministic-preview',
    reasoning: 'quick',
    voiceMode: 'neutral',
    timeZone: 'Asia/Hong_Kong'
  });
  return { principal, conversationId: run.conversationId };
}

async function makeContext(browser, viewport, principal, reducedMotion = 'reduce') {
  const phone = viewport.width < 768;
  const context = await browser.newContext({
    viewport,
    colorScheme: 'light',
    reducedMotion,
    hasTouch: phone,
    isMobile: browserName === 'chromium' && phone
  });
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'active_theme', value: 'rafii', url: base },
    { name: 'sidebar_state', value: 'false', url: base }
  ]);
  await context.addInitScript((id) => {
    localStorage.setItem('postriff-dev-principal', id);
    localStorage.setItem(
      'postriff-onboarding:' + id,
      JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} })
    );
    localStorage.setItem('postriff.tour.dismissed', '1');
    localStorage.setItem('theme', 'light');
  }, principal);
  await context.route('**/*', (route) =>
    new URL(route.request().url()).origin === new URL(base).origin
      ? route.continue()
      : route.abort()
  );
  return context;
}

function watch(page, label) {
  const errors = [];
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400 && new URL(response.url()).origin === new URL(base).origin)
      errors.push(`http ${response.status()} ${new URL(response.url()).pathname}`);
  });
  return () => {
    report.errors.push(...errors.map((error) => `${label}: ${error}`));
    check(`${label}: no console, page or same-origin network errors`, errors.length === 0, errors);
  };
}

const summaryOf = (page) => page.locator('button[aria-label^="Delivery."]');
async function openConversation(page, seedValue, expectedDestinations = 3) {
  await page.goto(`${base}/app/agent/${seedValue.conversationId}`, {
    waitUntil: 'domcontentloaded',
    timeout: 60000
  });
  // Keep development-only Next.js and TanStack Query badges out of product screenshots.
  await page.addStyleTag({
    content: 'nextjs-portal, .tsqd-open-btn-container { display: none !important; }'
  });
  const composer = page.locator('[data-tour="composer"]');
  await composer.waitFor({ state: 'visible', timeout: 60000 });
  const summary = summaryOf(page);
  await summary.waitFor({ state: 'visible' });
  await page.waitForFunction(
    (count) =>
      document
        .querySelector('button[aria-label^="Delivery."]')
        ?.getAttribute('aria-label')
        ?.includes(`${count} destinations`),
    expectedDestinations
  );
  return { composer, summary };
}
async function openPlanner(page, summary) {
  await summary.click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('heading', { name: 'Publish to' }).waitFor();
  return dialog;
}
async function addChannel(dialog, name) {
  await dialog.getByRole('button', { name: 'Add channel', exact: true }).click();
  await dialog.getByRole('button', { name, exact: typeof name === 'string' }).click();
}
async function shot(locator, name) {
  const file = path.join(out, name);
  await locator.screenshot({ path: file });
  report.screenshots.push(path.relative(path.resolve(__dirname, '../..'), file));
}
async function audit(page, selector, label) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(
    async ({ selector }) => {
      const root = document.querySelector(selector);
      const result = await window.axe.run(root, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
        resultTypes: ['violations']
      });
      return result.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        targets: violation.nodes.map((node) => node.target)
      }));
    },
    { selector }
  );
  check(
    `${label}: axe has no serious or critical findings`,
    violations.filter((violation) => ['serious', 'critical'].includes(violation.impact)).length ===
      0,
    violations
  );
}

(async () => {
  const seedValue = await seed();
  const browser = await engine.launch({
    headless: true,
    executablePath:
      (browserName === 'webkit'
        ? process.env.RAFII_WEBKIT_PATH
        : process.env.RAFII_CHROMIUM_PATH) || undefined
  });
  try {
    const context = await makeContext(browser, { width: 390, height: 844 }, seedValue.principal);
    const page = await context.newPage();
    const finishWatch = watch(page, '390x844 functional flow');
    const { composer, summary } = await openConversation(page, seedValue);
    check(
      'initial summary counts two accounts plus Threads as 3 destinations and 2 languages',
      /3 destinations; 2 languages/.test(await summary.getAttribute('aria-label'))
    );
    check(
      '390 composer has no horizontal overflow',
      await composer.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
    );
    check(
      '390 compact tools do not require horizontal scrolling',
      await composer
        .locator('[data-slot="composer-tools"]')
        .evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
    );
    check(
      '390 page has no horizontal overflow',
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)
    );
    check(
      'reduced-motion preference is active',
      await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
    );
    const compactMetrics = await composer.evaluate((element) => {
      const textarea = element.querySelector('textarea');
      const composerHeight = element.getBoundingClientRect().height;
      return {
        composerHeight,
        textareaHeight: textarea?.getBoundingClientRect().height ?? 0,
        chromeHeight: composerHeight - (textarea?.getBoundingClientRect().height ?? 0)
      };
    });
    check(
      '390 compact composer is materially shorter than the 238px baseline',
      compactMetrics.composerHeight <= 218,
      compactMetrics
    );
    check(
      '390 non-textarea chrome stays inside the 104–136px target',
      compactMetrics.chromeHeight >= 104 && compactMetrics.chromeHeight <= 136,
      compactMetrics
    );
    await shot(composer, 'composer-390x844.png');

    // Capture a like-for-like 430px compact baseline before the functional flow mutates delivery.
    await page.setViewportSize({ width: 430, height: 932 });
    check(
      '430 default composer has no horizontal overflow',
      await composer.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
    );
    await shot(composer, 'composer-430x932.png');
    let dialog = await openPlanner(page, summary);
    const default430Box = await dialog.boundingBox();
    check(
      '430 default planner stays in the visual viewport',
      default430Box &&
        default430Box.x >= 0 &&
        default430Box.y >= 0 &&
        default430Box.x + default430Box.width <= 431 &&
        default430Box.y + default430Box.height <= 933,
      default430Box
    );
    await page.screenshot({ path: path.join(out, 'planner-430x932.png'), fullPage: false });
    report.screenshots.push(
      path.relative(path.resolve(__dirname, '../..'), path.join(out, 'planner-430x932.png'))
    );
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    await page.setViewportSize({ width: 390, height: 844 });

    // Keyboard opens the planner; Escape closes the language catalogue before it closes the dialog.
    await summary.focus();
    await page.keyboard.press('Enter');
    dialog = page.getByRole('dialog');
    await dialog.getByRole('heading', { name: 'Publish to' }).waitFor();
    check(
      'planner has one vertical row per selected destination',
      (await dialog.locator('ul > li').count()) === 3
    );
    check(
      'planner exposes the live staged channel/language count',
      await dialog.getByText(/3 channels · 2 languages/).isVisible()
    );
    const firstLanguage = dialog
      .locator('ul > li')
      .first()
      .getByRole('button', { name: /^Output language for/ })
      .first();
    await firstLanguage.focus();
    await page.keyboard.press('Enter');
    await dialog.getByRole('combobox', { name: 'Search languages or regions' }).waitFor();
    await page.keyboard.press('Escape');
    check('first Escape closes only the language catalogue', await dialog.isVisible());
    await page.keyboard.press('Escape');
    await dialog.waitFor({ state: 'hidden' });
    check(
      'dialog close restores focus to Delivery Summary',
      await summary.evaluate((element) => element === document.activeElement)
    );

    // Cancel discards a staged destination addition.
    dialog = await openPlanner(page, summary);
    await addChannel(dialog, 'Instagram Draft only');
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    check(
      'Cancel leaves the applied destination count untouched',
      /3 destinations/.test(await summary.getAttribute('aria-label'))
    );

    // Shared language is a reversible overlay over the individual staged values.
    dialog = await openPlanner(page, summary);
    const beforeShared = await dialog.locator('ul > li').allTextContents();
    const shared = dialog.getByRole('switch', { name: 'All channels use the same language' });
    await shared.click();
    await dialog.getByRole('button', { name: /Choose a shared language/ }).click();
    await dialog.getByRole('option').filter({ hasText: '日本語' }).first().click();
    check(
      'shared-language ON previews Japanese on every destination',
      (await dialog.locator('ul > li').allTextContents()).every((text) => text.includes('日本語'))
    );
    await shared.click();
    check(
      'shared-language ON then OFF restores every staged individual value',
      JSON.stringify(await dialog.locator('ul > li').allTextContents()) ===
        JSON.stringify(beforeShared)
    );
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();

    // One destination can still hold several languages, and Apply commits through the existing API.
    dialog = await openPlanner(page, summary);
    await dialog
      .getByRole('button', { name: 'Add another language for LinkedIn · Dev Member', exact: true })
      .click();
    await dialog.getByRole('option').filter({ hasText: 'Español (España)' }).first().click();
    await dialog
      .getByRole('button', { name: /^Output language for LinkedIn · Dev Member 1 of 2:/ })
      .click();
    await dialog.getByRole('option').filter({ hasText: '繁體中文（香港）' }).first().click();
    check(
      'long locale name stays inside its destination row',
      await dialog
        .locator('ul > li')
        .first()
        .evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
    );
    await dialog.getByRole('button', { name: 'Apply delivery', exact: true }).click();
    await dialog.waitFor({ state: 'hidden', timeout: 15000 });
    check(
      'multi-language Apply changes the effective unique-language count',
      /4 languages/.test(await summary.getAttribute('aria-label'))
    );

    // Collapse to one destination, then expand past five without creating a chip wall.
    dialog = await openPlanner(page, summary);
    await dialog
      .getByRole('button', { name: 'Remove LinkedIn · Dev Member Two from delivery' })
      .click();
    await dialog.getByRole('button', { name: 'Remove Threads from delivery' }).click();
    await dialog.getByRole('button', { name: 'Apply delivery', exact: true }).click();
    await dialog.waitFor({ state: 'hidden', timeout: 15000 });
    check(
      'one-channel Apply produces the human-readable single-destination summary',
      /1 destination/.test(await summary.getAttribute('aria-label')) &&
        /LinkedIn, Dev Member/.test(await summary.getAttribute('aria-label'))
    );
    check(
      'single-destination summary keeps its visible multi-language count',
      (await summary.textContent()).includes('+1')
    );

    dialog = await openPlanner(page, summary);
    for (const option of [
      /^LinkedIn · Dev Member Two/,
      /^Threads/,
      /^Instagram/,
      /^Xiaohongshu/,
      /^X Draft only$/
    ])
      await addChannel(dialog, option);
    check(
      '5+ destinations stay as vertical planner rows',
      (await dialog.locator('ul > li').count()) === 6
    );
    await dialog.getByRole('button', { name: 'Apply delivery', exact: true }).click();
    await dialog.waitFor({ state: 'hidden', timeout: 15000 });
    check(
      '5+ applied destinations reduce to one compact summary',
      /6 destinations/.test(await summary.getAttribute('aria-label')) &&
        (await summary.textContent()).includes('+3')
    );

    // Message language wins for the current draft and is textual, not color-only.
    await page
      .getByRole('textbox', { name: 'Message', exact: true })
      .fill('Write this in Japanese.');
    await page.waitForFunction(() =>
      document
        .querySelector('button[aria-label^="Delivery."]')
        ?.getAttribute('aria-label')
        ?.includes('1 language')
    );
    check(
      'message-provided language replaces the effective count without rewriting destinations',
      /6 destinations; 1 language/.test(await summary.getAttribute('aria-label')) &&
        /from the message/.test(await summary.getAttribute('aria-label'))
    );
    dialog = await openPlanner(page, summary);
    check(
      'every affected destination exposes a textual From message indicator',
      (await dialog.getByText('From message', { exact: true }).count()) === 6
    );
    const box = await dialog.boundingBox();
    check(
      '390 planner stays inside the visual viewport',
      box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 391 && box.y + box.height <= 845,
      box
    );
    const undersized = await dialog
      .locator('button:not([disabled]), [role="switch"]:not([aria-disabled="true"])')
      .evaluateAll((nodes) =>
        nodes.flatMap((node) => {
          const rect = node.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44)
            ? [
                {
                  name: node.getAttribute('aria-label') || node.textContent?.trim(),
                  width: rect.width,
                  height: rect.height
                }
              ]
            : [];
        })
      );
    check(
      'planner controls retain practical 44px touch targets',
      undersized.length === 0,
      undersized
    );
    await audit(page, '[role="dialog"]', 'open planner');
    await page.screenshot({ path: path.join(out, 'planner-message-390x844.png'), fullPage: false });
    report.screenshots.push(
      path.relative(path.resolve(__dirname, '../..'), path.join(out, 'planner-message-390x844.png'))
    );
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();

    // Empty text keeps Send disabled; an in-flight local fixture turn keeps it disabled while busy.
    const send = page.getByRole('button', { name: 'Send', exact: true });
    await page.getByRole('textbox', { name: 'Message', exact: true }).fill('');
    check('empty message keeps Send disabled', await send.isDisabled());
    await page.route('**/ideas/conversations/*/turns', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 700));
      await route.continue();
    });
    await page
      .getByRole('textbox', { name: 'Message', exact: true })
      .fill('Write a short note in Japanese.');
    await send.waitFor({ state: 'visible' });
    check('valid local-fixture turn enables Send', !(await send.isDisabled()));
    const sent = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        /\/ideas\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname)
    );
    await send.click();
    await page.waitForTimeout(100);
    check('busy turn disables Send', await send.isDisabled());
    check('local deterministic turn returns successfully', (await sent).ok());

    // An actual uploaded attachment remains between the textarea and the compact summary.
    await page.locator('input[type=file][aria-label="Photo or video"]').setInputFiles({
      name: 'delivery.png',
      mimeType: 'image/png',
      buffer: png(800, 600, [86, 122, 164])
    });
    const attachment = page.locator('[data-slot="reference-chip"]').first();
    await attachment.waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForFunction(
      () =>
        !document.querySelector('[data-slot="reference-chip"]')?.textContent?.includes('Uploading')
    );
    check('attachment is visible without hiding Delivery Summary', await summary.isVisible());
    check(
      'attachment state preserves phone-width overflow safety',
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)
    );
    await shot(composer, 'composer-attachment-390x844.png');
    await audit(page, '[data-tour="composer"]', 'compact composer with attachment');
    finishWatch();
    await context.close();

    // Required responsive viewports, all emulated. The conversation restores its authoritative last-turn destinations.
    for (const viewport of [
      { width: 430, height: 932 },
      { width: 768, height: 1024 },
      { width: 1440, height: 900 }
    ]) {
      const responsive = await makeContext(browser, viewport, seedValue.principal);
      const visual = await responsive.newPage();
      const finish = watch(visual, `${viewport.width}x${viewport.height} visual`);
      const opened = await openConversation(visual, seedValue, 6);
      await opened.composer.scrollIntoViewIfNeeded();
      check(
        `${viewport.width}: composer has no horizontal overflow`,
        await opened.composer.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)
      );
      check(
        `${viewport.width}: page has no horizontal overflow`,
        await visual.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)
      );
      const restoredPrefix = viewport.width === 430 ? 'restored-' : '';
      await shot(
        opened.composer,
        `composer-${restoredPrefix}${viewport.width}x${viewport.height}.png`
      );
      const planner = await openPlanner(visual, opened.summary);
      const plannerBox = await planner.boundingBox();
      check(
        `${viewport.width}: planner stays in viewport`,
        plannerBox &&
          plannerBox.x >= 0 &&
          plannerBox.y >= 0 &&
          plannerBox.x + plannerBox.width <= viewport.width + 1 &&
          plannerBox.y + plannerBox.height <= viewport.height + 1,
        plannerBox
      );
      await visual.screenshot({
        path: path.join(out, `planner-${restoredPrefix}${viewport.width}x${viewport.height}.png`),
        fullPage: false
      });
      report.screenshots.push(
        path.relative(
          path.resolve(__dirname, '../..'),
          path.join(out, `planner-${restoredPrefix}${viewport.width}x${viewport.height}.png`)
        )
      );
      await visual.keyboard.press('Escape');
      await planner.waitFor({ state: 'hidden' });
      check(
        `${viewport.width}: planner restores focus to summary`,
        await opened.summary.evaluate((element) => element === document.activeElement)
      );
      finish();
      await responsive.close();
    }
  } catch (error) {
    report.failure = String(error?.stack ?? error);
    throw error;
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(out, 'delivery-planner-browser.json'),
      JSON.stringify(report, null, 2)
    );
  }
  console.log(
    JSON.stringify(
      {
        status: 'PASS',
        browser: browserName,
        checks: report.checks.length,
        screenshots: report.screenshots.length,
        physicalDevice: false
      },
      null,
      2
    )
  );
})().catch((error) => {
  console.error(error?.stack ?? error);
  process.exitCode = 1;
});
