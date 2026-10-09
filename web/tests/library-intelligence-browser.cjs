/**
 * Rafii Intelligent Library — T09 browser harness (UI spec §6; A059, A061–A065).
 *
 * Real Next app + dev hosted API + disposable PostgreSQL (started by scripts/consumer_ready_browser.py --library or an
 * equivalent cloud job). Identity and storage are synthetic; the files are real bytes. Covers 390×844, 768×1024,
 * 1440×900, phone landscape, reduced motion and 200 % zoom, plus keyboard paths: selection, Escape, focus restore,
 * no autoplay, bottom-bar clearance and URL state on return.
 *
 *   RAFII_WEB_URL=http://127.0.0.1:4439 RAFII_LIBRARY_INTELLIGENCE_EVIDENCE=<dir> node web/tests/library-intelligence-browser.cjs
 *
 * Optional: RAFII_LIBRARY_ENGINES=chromium,webkit (default chromium), PLAYWRIGHT_MODULE=<path to playwright>.
 * Desktop WebKit is labelled as such; it is not an iPhone Safari result (A066 needs a real device).
 */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { mkdirSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const base = (process.env.RAFII_WEB_URL || 'http://127.0.0.1:4439').replace(/\/$/, '');
const out = process.env.RAFII_LIBRARY_INTELLIGENCE_EVIDENCE || process.env.RAFII_LIBRARY_EVIDENCE || resolve(__dirname, '../../docs/design/rafii-intelligent-library-2026-10-08/evidence/ui');
const engines = (process.env.RAFII_LIBRARY_ENGINES || 'chromium').split(',').map((name) => name.trim()).filter(Boolean);
mkdirSync(out, { recursive: true });

const VIEWPORTS = [
  { name: 'phone-390x844', viewport: { width: 390, height: 844 }, mobile: true },
  { name: 'tablet-768x1024', viewport: { width: 768, height: 1024 }, mobile: false },
  { name: 'desktop-1440x900', viewport: { width: 1440, height: 900 }, mobile: false },
  { name: 'phone-landscape-844x390', viewport: { width: 844, height: 390 }, mobile: false },
  // 1280 × 800 at 200 % zoom lays out like a 640 × 400 CSS-pixel viewport.
  { name: 'zoom-200-1280x800', viewport: { width: 640, height: 400 }, deviceScaleFactor: 2, mobile: true }
];

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), ...(detail === undefined ? {} : { detail }) });
  assert.ok(ok, `${name}${detail === undefined ? '' : `: ${JSON.stringify(detail)}`}`);
}

/** The address follows state a moment later (throttled URL updates); wait up to 5 s for it, then report. */
async function addressSettles(page, predicate) {
  return page.waitForFunction(predicate, null, { timeout: 5000 }).then(() => true, () => false);
}

/**
 * Evidence screenshots show settled UI, not a sheet halfway through opening: wait (up to 2 s) until no finite
 * animation or transition is running. Infinite ones (spinners, a playing preview) are ignored.
 */
async function settled(page) {
  await page
    .waitForFunction(() => document.getAnimations().every((animation) => animation.playState !== 'running' || animation.effect?.getComputedTiming().endTime === Infinity), null, { timeout: 2000 })
    .catch(() => {});
}

/** A short real PCM WAV (440 Hz), so the audio path runs on genuine bytes. */
function wav(seconds = 2, rate = 8000) {
  const samples = seconds * rate;
  const buffer = Buffer.alloc(44 + samples * 2);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(36 + samples * 2, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24);
  buffer.writeUInt32LE(rate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(samples * 2, 40);
  for (let index = 0; index < samples; index += 1) buffer.writeInt16LE(Math.round(Math.sin((2 * Math.PI * 440 * index) / rate) * 12000), 44 + index * 2);
  return buffer;
}

async function noOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

async function dismissWelcome(page) {
  const welcome = page.getByRole('button', { name: 'Not now', exact: true });
  try {
    await welcome.waitFor({ state: 'visible', timeout: 5000 });
    await welcome.click();
    await welcome.waitFor({ state: 'hidden', timeout: 5000 });
  } catch (error) {
    if (await welcome.isVisible().catch(() => false)) throw error;
  }
}

async function openLibrary(page, query = '') {
  await page.goto(`${base}/app/library${query}`);
  await dismissWelcome(page);
  await page.getByRole('searchbox', { name: 'Search Library' }).waitFor({ timeout: 30000 });
  await page.locator('[data-tour="library-card"]').first().waitFor({ timeout: 30000 });
}

(async () => {
  for (const engine of engines) {
    const browserType = playwright[engine];
    assert.ok(browserType, `unknown engine ${engine}`);
    const browser = await browserType.launch({ headless: true });
    try {
      const principal = randomUUID();
      const headers = { Authorization: `Bearer dev:${principal}`, 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Origin: base };
      const contextFor = async (options = {}) => {
        const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...options });
        await context.addCookies([
          { name: 'postriff_dev', value: '1', url: base },
          { name: 'postriff_dev_principal', value: principal, url: base }
        ]);
        await context.addInitScript((id) => localStorage.setItem('postriff-dev-principal', id), principal);
        // Signed private reads in the dev harness point at dev.invalid; serve them from the dev storage route.
        await context.route('https://dev.invalid/**', async (route) => {
          const url = new URL(route.request().url());
          const response = await context.request.get(`${base}/dev/storage${url.pathname}`);
          return route.fulfill({ status: response.status(), body: await response.body(), headers: { 'Content-Type': response.headers()['content-type'] || 'application/octet-stream', 'Access-Control-Allow-Origin': '*' } });
        });
        return context;
      };

      /* --- seed one workspace with real files ------------------------------------------------------------------ */
      const seed = await contextFor();
      const boot = await seed.request.post(`${base}/api/auth/verify`, { headers, data: { plan: 'studio' } });
      assert.equal(boot.status(), 201, await boot.text());
      const ws = (await boot.json()).workspaceId;
      const library = `${base}/api/workspaces/${ws}/library`;
      async function addFile(filename, mime, bytes) {
        const ticketResponse = await seed.request.post(`${library}/files`, { headers, data: { filename, mime, bytes: bytes.length } });
        assert.equal(ticketResponse.status(), 201, await ticketResponse.text());
        const ticket = (await ticketResponse.json()).upload;
        const put = await seed.request.put(`${base}/dev/upload/${new URL(ticket.url).searchParams.get('token')}`, { data: bytes, headers: { 'Content-Type': mime } });
        assert.equal(put.status(), 200, await put.text());
        const committed = await seed.request.post(`${library}/files/${ticket.assetId}/commit`, { headers, data: {} });
        assert.ok(committed.ok(), await committed.text());
        await seed.request.post(`${base}/dev/library/tick?workspace=${ws}&assetId=${ticket.assetId}`);
        return ticket.assetId;
      }
      const seeded = [];
      // More than one page (the Library loads 200 at a time): the server total and Load more must stay honest.
      for (let index = 0; index < 200; index += 1) {
        await addFile(`bulk-reference-${String(index).padStart(3, '0')}.txt`, 'text/plain', Buffer.from(`Reference item ${index}`));
      }
      for (let index = 0; index < 14; index += 1) {
        seeded.push(await addFile(`rehearsal-note-${String(index).padStart(2, '0')}.md`, 'text/markdown', Buffer.from(`Rehearsal note ${index}\nBrahms intermezzo phrasing, pedalling and tempo for week ${index}.`)));
      }
      seeded.push(await addFile('recital-budget.csv', 'text/csv', Buffer.from('item,cost\nhall,1200\npiano tuning,180\n')));
      // Real names: long English, Cantonese and Traditional Chinese, so truncation and layout are exercised.
      const LONG_NAME = '2026年10月 香港大會堂 獨奏會 節目單 Brahms Op. 118 Intermezzi and Ballades final revised programme notes for the printer (v12).md';
      seeded.push(await addFile(LONG_NAME, 'text/markdown', Buffer.from('節目單 programme notes for the recital')));
      seeded.push(await addFile('練琴筆記 左手踏板同埋 rubato.md', 'text/markdown', Buffer.from('練琴筆記 left-hand pedalling and rubato')));
      const audioId = await addFile('practice-take.wav', 'audio/wav', wav());
      const collectionResponse = await seed.request.post(`${library}/collections`, { headers, data: { name: 'Recital' } });
      assert.ok(collectionResponse.ok(), await collectionResponse.text());
      await seed.close();

      for (const spec of VIEWPORTS) {
        const context = await contextFor({ viewport: spec.viewport, deviceScaleFactor: spec.deviceScaleFactor || 1, reducedMotion: 'reduce', hasTouch: spec.mobile });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await openLibrary(page);
        const label = `${engine} ${spec.name}`;
        // The first-view screenshot comes before any check, so a failing viewport still returns its picture.
        await settled(page);
        await page.screenshot({ path: resolve(out, `library-${engine}-${spec.name}.png`) });

        // Redesign §4: exactly one filled primary on the page (Add); everything else is secondary, ghost or danger.
        const primaries = await page.evaluate(() => [...document.querySelectorAll('[data-library-page] .rafii-action')].filter((node) => node.getClientRects().length > 0).length);
        check(`${label}: exactly one filled primary`, primaries === 1, primaries);
        // Long and Chinese names truncate inside their card instead of widening it.
        const named = await page.evaluate(() => {
          const card = [...document.querySelectorAll('[data-library-item]')].find((node) => (node.textContent || '').includes('香港大會堂'));
          if (!card) return null;
          const box = card.getBoundingClientRect();
          return { right: box.right, width: box.width, viewport: window.innerWidth };
        });
        check(`${label}: long Chinese name stays inside its card`, named !== null && named.right <= named.viewport + 1, named);

        // A059: one Add control, scope in plain words, compact chrome.
        check(`${label}: one Add control`, (await page.getByRole('button', { name: /^Add to Library|^Add ·/ }).count()) === 1);
        check(`${label}: no competing upload button`, (await page.getByText('Upload images', { exact: false }).count()) === 0);
        const scope = page.locator('[data-library-scope]');
        check(`${label}: scope visible beside search`, (await scope.isVisible()) && /Entire permitted Library/.test(await scope.innerText()));
        check(`${label}: no horizontal overflow`, await noOverflow(page));

        // A016: a document cover is the real rendered page or says it is preparing/unavailable; only a raster says "PAGE 1".
        const covers = await page.evaluate(() => {
          const nodes = [...document.querySelectorAll('[data-library-item] [data-thumbnail-preview]')];
          return {
            kinds: nodes.map((node) => node.getAttribute('data-thumbnail-preview')),
            pageLabels: nodes.filter((node) => (node.textContent || '').includes('· PAGE 1')).map((node) => node.getAttribute('data-thumbnail-preview')),
            faux: /SHEET PREVIEW|SLIDE PREVIEW|Extracted text preview/.test(document.body.textContent || '')
          };
        });
        // 'audio-player' is the inline preview's own player (its waveform is decoded from the file after a press).
        const honest = ['first-page-raster', 'preparing', 'unavailable', 'audio-waveform', 'audio-file', 'audio-player', 'image', 'video-poster'];
        check(`${label}: every cover is a real rendition or says it is not`, covers.kinds.length > 0 && covers.kinds.every((kind) => honest.includes(kind)), covers.kinds);
        check(`${label}: only a real page raster carries a page label`, covers.pageLabels.every((kind) => kind === 'first-page-raster'), covers.pageLabels);
        check(`${label}: no faux sheet, slide or text-cover labels`, !covers.faux);

        // A065: animated digits never add a second accessible name.
        const digitsHidden = await page.evaluate(() => [...document.querySelectorAll('[data-slot="digit-swap"]')].every((node) => node.closest('[aria-hidden="true"]')));
        check(`${label}: animated digits are hidden from assistive tech`, digitsHidden);

        // A059: the first meaningful item is on screen without scrolling (phone portrait target). Measure the card's
        // preview itself: audio and video cards put their inline player above the open button.
        const first = await page.locator('[data-tour="library-card"]').first().locator('[data-library-thumbnail]').first().boundingBox();
        const tabBar = spec.mobile && spec.viewport.width < 768 ? await page.locator('nav[aria-label="Mobile navigation"]').boundingBox() : null;
        const limit = tabBar ? tabBar.y : spec.viewport.height;
        const firstVisible = Boolean(first) && first.y >= 0 && first.y + Math.min(first.width, first.height) <= limit;
        if (spec.name === 'phone-390x844') check(`${label}: first item preview visible without scrolling`, firstVisible, { first, limit });
        else checks.push({ name: `${label}: first item preview position (recorded)`, ok: true, detail: { first, limit, firstVisible } });

        if (spec.name === 'phone-390x844' || spec.name === 'desktop-1440x900') {
          // Keyboard selection: Space selects, the batch bar appears only then, Escape clears.
          check(`${label}: no batch bar before selection`, (await page.getByRole('region', { name: 'Selected items' }).count()) === 0);
          const toggle = page.getByRole('checkbox', { name: /^Select / }).first();
          await toggle.focus();
          await page.keyboard.press('Space');
          const bar = page.getByRole('region', { name: 'Selected items' });
          await bar.waitFor({ timeout: 10000 });
          check(`${label}: keyboard selection shows batch actions`, /1 item selected/.test(await bar.innerText()));
          check(`${label}: selection is in the address`, await addressSettles(page, () => new URL(location.href).searchParams.has('sel')));
          await settled(page);
          await page.screenshot({ path: resolve(out, `library-${engine}-${spec.name}-selected.png`) });
          await page.keyboard.press('Escape');
          await bar.waitFor({ state: 'detached', timeout: 10000 });
          check(`${label}: Escape clears the selection`, await addressSettles(page, () => !new URL(location.href).searchParams.has('sel')));

          // Focus moves into the detail panel and returns to the opener on Escape.
          const opener = page.locator('button[data-library-open]').first();
          const openerId = await opener.getAttribute('data-library-open');
          await opener.focus();
          await page.keyboard.press('Enter');
          await page.getByRole('button', { name: 'Close asset details' }).waitFor({ timeout: 10000 });
          // A sheet/drawer below 1280 px, the docked inspector from 1280 px (redesign §6): focus moves into either.
          check(`${label}: focus moves into the detail panel`, await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"], [data-library-inspector]'))));
          check(`${label}: open item is in the address`, await addressSettles(page, () => Boolean(new URL(location.href).searchParams.get('asset'))));
          await settled(page);
          await page.screenshot({ path: resolve(out, `library-${engine}-${spec.name}-detail.png`) });
          await page.keyboard.press('Escape');
          await page.getByRole('button', { name: 'Close asset details' }).waitFor({ state: 'detached', timeout: 10000 });
          check(`${label}: focus returns to the opener`, (await page.evaluate(() => document.activeElement?.getAttribute('data-library-open'))) === openerId);

          // A021: opening audio never plays; playing is a press; the last result clears Now Playing.
          await page.getByRole('searchbox', { name: 'Search Library' }).fill('practice-take');
          const audioCard = page.locator(`button[data-library-open="${audioId}"]`).first();
          await audioCard.waitFor({ timeout: 15000 });
          await audioCard.click();
          await page.getByRole('button', { name: 'Close asset details' }).waitFor({ timeout: 10000 });
          await page.waitForTimeout(1500);
          // Non-vacuous: the bar is always mounted (hidden without a track), and nothing on the page is audibly playing.
          check(`${label}: no autoplay on detail open`, await page.evaluate(() => {
            const bar = document.querySelector('[aria-label="Now Playing"]');
            const audible = [...document.querySelectorAll('audio,video')].filter((media) => !media.paused && !media.muted && media.volume > 0);
            return Boolean(bar) && bar.classList.contains('hidden') && audible.length === 0;
          }));
          await page.getByRole('button', { name: 'Play audio in Now Playing' }).click();
          await page.waitForFunction(() => document.querySelector('[aria-label="Now Playing"]')?.classList.contains('hidden') === false, null, { timeout: 10000 });
          await page.getByRole('button', { name: 'Close asset details' }).click();
          await page.getByRole('searchbox', { name: 'Search Library' }).fill('');
          await page.locator('[data-tour="library-card"]').first().waitFor({ timeout: 15000 });
          await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
          await page.waitForTimeout(400);
          const clearance = await page.evaluate(() => {
            const items = [...document.querySelectorAll('[data-library-item]')];
            const last = items[items.length - 1]?.getBoundingClientRect();
            const player = document.querySelector('[aria-label="Now Playing"]')?.getBoundingClientRect();
            const tabs = document.querySelector('nav[aria-label="Mobile navigation"]')?.getBoundingClientRect();
            const coveredTop = Math.min(player && player.height ? player.top : Infinity, tabs && tabs.height ? tabs.top : Infinity);
            return { lastBottom: last?.bottom ?? null, coveredTop: Number.isFinite(coveredTop) ? coveredTop : null, playerLeft: player?.left ?? null, lastRight: last?.right ?? null };
          });
          const overlaps = clearance.lastBottom !== null && clearance.coveredTop !== null && clearance.lastBottom > clearance.coveredTop + 1 && (clearance.playerLeft === null || clearance.lastRight === null || clearance.lastRight > clearance.playerLeft);
          check(`${label}: last result clears Now Playing and the tab bar`, !overlaps, clearance);
          await settled(page);
          await page.screenshot({ path: resolve(out, `library-${engine}-${spec.name}-player.png`) });
          await page.getByRole('button', { name: 'Close player', exact: true }).click();

          // A051: view, density and query survive leaving for a draft and coming back.
          await page.getByRole('radiogroup', { name: 'Library view' }).getByRole('radio', { name: 'List' }).click();
          await page.getByRole('radiogroup', { name: 'Density' }).getByRole('radio', { name: 'Compact' }).click();
          await page.getByRole('searchbox', { name: 'Search Library' }).fill('Brahms');
          await page.waitForFunction(() => new URL(location.href).searchParams.get('q') === 'Brahms', null, { timeout: 10000 });
          const listed = page.getByRole('checkbox', { name: /^Select / });
          await listed.nth(0).check();
          await listed.nth(1).check();
          await page.waitForFunction(() => (new URL(location.href).searchParams.get('sel') || '').split(',').filter(Boolean).length === 2, null, { timeout: 10000 });
          const before = page.url();
          await page.goto(`${base}/app/ideas`);
          await page.goBack();
          await page.getByRole('searchbox', { name: 'Search Library' }).waitFor({ timeout: 30000 });
          const after = new URL(page.url());
          check(`${label}: address state restored on return`, after.searchParams.get('q') === 'Brahms' && after.searchParams.get('mode') === 'list' && after.searchParams.get('density') === 'compact' && (after.searchParams.get('sel') || '').split(',').length === 2, { before, after: page.url() });
          check(`${label}: search field restored`, (await page.getByRole('searchbox', { name: 'Search Library' }).inputValue()) === 'Brahms');
          check(`${label}: selection restored`, (await page.getByRole('region', { name: 'Selected items' }).innerText()).includes('2 items selected'));
          check(`${label}: no signed URL in the address`, !/token=|signature|x-amz-|https?%3A/i.test(page.url()));
          // A selection that no longer exists leaves with a generic notice.
          await page.goto(`${base}/app/library?sel=${seeded[0]},ffffffffffffffffffffffffffffffff`);
          await page.getByRole('searchbox', { name: 'Search Library' }).waitFor({ timeout: 30000 });
          await page.waitForFunction(() => (new URL(location.href).searchParams.get('sel') || '').split(',').filter(Boolean).length === 1, null, { timeout: 15000 });
          check(`${label}: inaccessible ids dropped from the selection`, !page.url().includes('ffffffffffffffffffffffffffffffff'));
          await page.getByRole('button', { name: 'Clear selection' }).click();
        }

        if (spec.name === 'tablet-768x1024') {
          const rail = page.getByRole('navigation', { name: 'Collections' });
          check(`${label}: collection switcher is one row on tablets`, await rail.isVisible() && ((await rail.boundingBox())?.height ?? 999) < 120);
        }
        if (spec.name === 'desktop-1440x900') {
          // More than 200 items: the count is the server's total, and the rest loads on request.
          const stats = (await page.locator('[data-tour="library-stats"]').first().innerText()).replace(/,/g, '');
          check(`${label}: server total over 200 shown`, /\b2[0-9]{2} items\b/.test(stats), stats);
          const loadMore = page.getByRole('button', { name: 'Load more assets' });
          await loadMore.scrollIntoViewIfNeeded();
          check(`${label}: Load more offered past the first 200`, await loadMore.isVisible());
          await page.evaluate(() => window.scrollTo(0, 0));
          const rail = page.getByRole('navigation', { name: 'Collections' });
          check(`${label}: collection rail beside the results`, ((await rail.boundingBox())?.width ?? 999) < 260);
          await page.getByRole('button', { name: 'Hide collections' }).click();
          await page.getByRole('button', { name: 'Show collections' }).waitFor();
          await page.getByRole('button', { name: 'Show collections' }).click();
          check(`${label}: rail collapses and reopens`, await page.getByRole('button', { name: 'Hide collections' }).isVisible());
        }
        if (spec.name === 'zoom-200-1280x800') {
          check(`${label}: reflows at 200% without horizontal scrolling`, await noOverflow(page));
          check(`${label}: Add stays reachable`, await page.getByRole('button', { name: /^Add to Library/ }).isVisible());
        }
        check(`${label}: reduced motion honoured`, await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches));
        check(`${label}: no runtime errors`, errors.length === 0, errors);
        await context.close();
      }
    } finally {
      await browser.close();
    }
  }
  const report = { status: 'pass', base, engines, note: 'Synthetic identity and storage, real files and app. Desktop WebKit is not iPhone Safari.', checks };
  writeFileSync(resolve(out, 'library-intelligence-browser.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: 'pass', checks: checks.length }));
})().catch((error) => {
  writeFileSync(resolve(out, 'library-intelligence-browser-failure.json'), JSON.stringify({ status: 'fail', error: String(error && error.stack ? error.stack : error), checks }, null, 2));
  console.error(error);
  process.exitCode = 1;
});
