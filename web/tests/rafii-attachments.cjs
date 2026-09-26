/**
 * Chat attachments in a real browser against the local dev harness (chat-context SPEC §12): the ＋ menu, a PNG upload,
 * the Library's staged "Add 1", the `@` list typed with `keyboard.type` (never `fill`), Enter keeping the literal text,
 * ArrowDown + Enter inserting 「label」, e-mail and pasted handles not opening it, Escape closing only the list, IME through
 * a CDP session, "Used this time" after sending, a handcrafted MP4 through begin → PUT → commit, and on a phone the sheet,
 * the first search result inside the visual viewport, no horizontal overflow and a 16 px textbox.
 *
 * The harness has the three flags on (scripts/postriff_dev_hosted.py). The browser's signed-URL PUT goes to a
 * Supabase-shaped URL, which this scene forwards to the harness's `PUT /dev/upload/{token}` (the real client only uploads
 * to Supabase). Drafting requests with any writer other than `deterministic-preview` are aborted.
 *
 *   RAFII_WEB_URL=http://127.0.0.1:4439 RAFII_API_URL=http://127.0.0.1:4438 node web/tests/rafii-attachments.cjs [--out=dir]
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
const api = process.env.RAFII_API_URL || 'http://127.0.0.1:4438';
for (const url of [base, api])
  if (!['127.0.0.1', 'localhost'].includes(new URL(url).hostname))
    throw new Error('Runs against the local harness only.');
const args = Object.fromEntries(
  process.argv
    .slice(2)
    .map((a) => a.replace(/^--/, '').split('='))
    .map(([k, v]) => [k, v ?? true])
);
const out =
  typeof args.out === 'string'
    ? args.out
    : path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/attachments');
fs.mkdirSync(out, { recursive: true });
const seed = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json'), 'utf8')
);
const TOUR_IDS = [
  ...fs
    .readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8')
    .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
].map((m) => m[1]);
const TOURS = JSON.stringify({
  completed: {},
  dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])),
  nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1]))
});
const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok: Boolean(ok) });
  process.stdout.write(
    `${ok ? 'ok  ' : 'FAIL'} ${name}${!ok && detail !== undefined ? ` — ${JSON.stringify(detail)}` : ''}\n`
  );
};

// --- fixtures ---------------------------------------------------------------------------------------------------------
function crc32(buf) {
  let c = ~0;
  for (const b of buf) {
    c ^= b;
    for (let k = 0; k < 8; k += 1) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}
function png(width, height, rgb) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
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
function box(type, payload = Buffer.alloc(0)) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(8 + payload.length);
  head.write(type, 4, 'latin1');
  return Buffer.concat([head, payload]);
}
/** A tiny MP4 the server accepts (brand, moov with a 3 s mvhd, an mdat) and no browser can decode: no frames here. */
function mp4() {
  const ftyp = box(
    'ftyp',
    Buffer.concat([Buffer.from('isom'), Buffer.from([0, 0, 2, 0]), Buffer.from('isommp41')])
  );
  const mvhd = Buffer.alloc(100);
  mvhd.writeUInt32BE(1000, 12); // timescale
  mvhd.writeUInt32BE(3000, 16); // duration: 3 s
  mvhd.writeUInt32BE(0x00010000, 20);
  mvhd.writeUInt16BE(0x0100, 24);
  for (const [i, v] of [0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000].entries())
    mvhd.writeUInt32BE(v, 36 + i * 4);
  mvhd.writeUInt32BE(2, 96);
  return Buffer.concat([ftyp, box('moov', box('mvhd', mvhd)), box('mdat', Buffer.alloc(256, 7))]);
}

async function seedLibraryPhoto() {
  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer dev:${seed.principal}`,
    'X-PostRiff-Request': 'founder-alpha'
  };
  const snap = await (
    await fetch(`${base}/api/workspaces/${seed.workspaceId}`, { headers })
  ).json();
  const res = await fetch(`${base}/api/workspaces/${seed.workspaceId}/actions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      expectedRevision: snap.revision,
      action: 'p2_media_upload',
      payload: { data: png(640, 480, [40, 110, 170]).toString('base64') }
    })
  });
  if (!res.ok) throw new Error(`library seed failed: ${res.status} ${await res.text()}`);
  // A saved post for the @ list's Posts group (the free preview writer; the seeded workspace has no drafts).
  const rev = async () =>
    (await (await fetch(`${base}/api/workspaces/${seed.workspaceId}`, { headers })).json())
      .revision;
  const quick = await fetch(`${base}/api/workspaces/${seed.workspaceId}/ideas/quick-start`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      expectedRevision: await rev(),
      text: 'Slow practice builds accuracy.\nOne bar, three times, half speed.',
      ownContent: true,
      confirmUse: true,
      model: 'deterministic-preview',
      destinations: [{ platform: 'Instagram', language: 'en' }]
    })
  });
  if (!quick.ok) throw new Error(`draft seed failed: ${quick.status} ${await quick.text()}`);
  const run = await quick.json();
  const applied = await fetch(
    `${base}/api/workspaces/${seed.workspaceId}/ideas/runs/${run.runId}/apply`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ expectedRevision: await rev(), artifactHash: run.artifactHash })
    }
  );
  if (!applied.ok) throw new Error(`draft apply failed: ${applied.status} ${await applied.text()}`);
}

async function context(browser, viewport) {
  const phone = viewport.width < 768;
  const ctx = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    colorScheme: 'dark',
    hasTouch: phone,
    isMobile: phone
  });
  await ctx.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: seed.principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base },
    { name: 'sidebar_state', value: 'false', url: base }
  ]);
  await ctx.addInitScript(
    ({ id, tours }) => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('postriff-onboarding', tours);
    },
    { id: seed.principal, tours: TOURS }
  );
  // Only the free preview writer may draft here.
  await ctx.route('**/ideas/conversations/*/turns', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}');
    if (body.model && body.model !== 'deterministic-preview') return route.abort();
    return route.continue();
  });
  // The signed-URL PUT (a Supabase-shaped URL from the harness) is forwarded to the harness.
  await ctx.route('https://devharness.supabase.co/**', async (route) => {
    const token = new URL(route.request().url()).searchParams.get('token');
    const res = await fetch(`${api}/dev/upload/${token}`, {
      method: 'PUT',
      headers: { 'Content-Type': route.request().headers()['content-type'] || 'video/mp4' },
      body: route.request().postDataBuffer()
    });
    await route.fulfill({
      status: res.ok ? 200 : 400,
      contentType: 'application/json',
      body: '{"Key":"ok"}'
    });
  });
  return ctx;
}

const message = (page) => page.getByRole('textbox', { name: 'Message', exact: true });
const plus = (page) => page.getByRole('button', { name: 'Add to message' });
const chips = (page) => page.locator('[data-slot="reference-chip"]');
const suggestions = (page) => page.getByRole('listbox', { name: 'Suggestions' });
const focused = (page) => page.evaluate(() => document.activeElement?.getAttribute('aria-label'));
const value = (page) => message(page).inputValue();

async function open(page) {
  await page.goto(`${base}/app/agent/${seed.conversationId}`, {
    waitUntil: 'domcontentloaded',
    timeout: 400000
  });
  await message(page).waitFor({ state: 'visible', timeout: 120000 });
  await plus(page).waitFor({ state: 'visible', timeout: 60000 });
}

async function waitChipWord(page, index, pattern, timeout = 60000) {
  const started = Date.now();
  const seen = new Set();
  while (Date.now() - started < timeout) {
    const label =
      (await chips(page)
        .nth(index)
        .locator('button')
        .first()
        .getAttribute('aria-label')
        .catch(() => null)) || '';
    seen.add(label.split(', ').pop());
    if (pattern.test(label)) return { ok: true, seen: [...seen] };
    await page.waitForTimeout(100);
  }
  return { ok: false, seen: [...seen] };
}

(async () => {
  await seedLibraryPhoto();
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.RAFII_CHROMIUM_PATH || undefined
  });
  try {
    // === desktop ======================================================================================================
    const desk = await context(browser, { width: 1440, height: 1000 });
    const page = await desk.newPage();
    // Slow the photo upload a little so its "Uploading" state is observable.
    await page.route('**/actions', async (route) => {
      if ((route.request().postData() || '').includes('"p2_media_upload"'))
        await new Promise((r) => setTimeout(r, 900));
      return route.continue();
    });
    await open(page);

    await plus(page).click();
    const menu = page.getByRole('menu');
    await menu.waitFor({ state: 'visible', timeout: 10000 });
    check(
      '＋ opens the menu',
      await menu.getByRole('menuitem', { name: /Photo or video/ }).isVisible()
    );

    // Library: staged multi-select, then "Add 1".
    await menu.getByRole('menuitem', { name: /From Library/ }).click();
    const library = page.getByRole('dialog', { name: 'Library' });
    await library.waitFor({ state: 'visible', timeout: 15000 });
    await library.locator('button[aria-pressed]').first().click();
    const addOne = library.getByRole('button', { name: 'Add 1' });
    check('Library stages "Add 1"', await addOne.isVisible());
    await addOne.click();
    await library.waitFor({ state: 'hidden', timeout: 15000 });
    check('the Library photo becomes a chip', (await chips(page).count()) === 1);

    // A PNG from this device: Uploading → ready.
    await page
      .locator('input[type=file][aria-label="Photo or video"]')
      .setInputFiles({
        name: 'studio.png',
        mimeType: 'image/png',
        buffer: png(800, 600, [200, 120, 60])
      });
    const upload = await waitChipWord(page, 1, /In post$/);
    check(
      'PNG upload → Uploading → ready',
      upload.ok && upload.seen.some((w) => w.startsWith('Uploading')),
      upload.seen
    );

    // Photo B becomes a reference (the free preview writer won't read it).
    await chips(page).nth(1).locator('button').first().click();
    await page.getByRole('radio', { name: 'Reference' }).click();
    await page.keyboard.press('Escape');
    check(
      'Photo B is a reference',
      (
        (await chips(page).nth(1).locator('button').first().getAttribute('aria-label')) || ''
      ).endsWith('Reference')
    );

    // `@` typed (never filled): the Posts group opens and focus stays on the textarea.
    await message(page).click();
    await page.keyboard.type('改@帖');
    await suggestions(page).waitFor({ state: 'visible', timeout: 10000 });
    check(
      'typing 改@帖 opens Posts with focus kept on the textarea',
      (await focused(page)) === 'Message'
    );
    await page.keyboard.press('Enter');
    check(
      'Enter keeps the literal text',
      !(await suggestions(page).isVisible()) && (await value(page)).includes('改@帖')
    );

    await page.keyboard.type('改@帖');
    await suggestions(page).waitFor({ state: 'visible', timeout: 10000 });
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);
    const picked = await value(page);
    check(
      'ArrowDown + Enter picks and inserts 「label」',
      /改「[^」]+」/.test(picked) && (await chips(page).count()) === 3,
      picked
    );

    await page.keyboard.type(' name@mail');
    check('name@mail does not open the list', !(await suggestions(page).isVisible()));
    await message(page).evaluate((el) => {
      el.setRangeText(' threads.com/@x', el.selectionStart, el.selectionEnd, 'end');
      el.dispatchEvent(
        new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste', data: null })
      );
    });
    check('a pasted threads.com/@x does not open the list', !(await suggestions(page).isVisible()));

    await page.keyboard.type(' @帖');
    await suggestions(page).waitFor({ state: 'visible', timeout: 10000 });
    await page.keyboard.press('Escape');
    check(
      'Escape closes only the list',
      !(await suggestions(page).isVisible()) &&
        (await focused(page)) === 'Message' &&
        page.url().includes(seed.conversationId)
    );

    // IME through CDP: the list follows the composition; Enter and ⌘/Ctrl+Enter do nothing mid-composition.
    const cdp = await desk.newCDPSession(page);
    const before = { chips: await chips(page).count(), messages: await page.locator('li').count() };
    await page.keyboard.type(' @');
    await suggestions(page).waitFor({ state: 'visible', timeout: 10000 });
    await cdp.send('Input.imeSetComposition', { text: '帖', selectionStart: 1, selectionEnd: 1 });
    await page.waitForTimeout(300);
    const composing = await suggestions(page).isVisible();
    await page.keyboard.press('Enter');
    await page.keyboard.press('Control+Enter');
    await page.waitForTimeout(400);
    const after = { chips: await chips(page).count(), messages: await page.locator('li').count() };
    await cdp.send('Input.insertText', { text: '帖' });
    check('IME: the list stays open while composing', composing);
    check(
      'IME: Enter and Ctrl+Enter mid-composition neither pick nor send',
      after.chips === before.chips && after.messages === before.messages,
      { before, after }
    );
    await page.keyboard.press('Escape');

    // Send: the reply's "Used this time" is the server's report.
    await page.getByRole('button', { name: 'Send' }).click();
    const used = page
      .getByRole('region', { name: 'Used this time' })
      .or(page.locator('section[aria-label="Used this time"]'))
      .last();
    await used.waitFor({ state: 'visible', timeout: 120000 });
    const report = await used.innerText();
    check('Used this time lists the post', /Post · .+ · (reworked|for ideas)/.test(report), report);
    check(
      'Used this time lists Photo A · in the post',
      report.includes('Photo A · in the post'),
      report
    );
    check(
      'Photo B is under Not used with the free-writer reason',
      /Not used[\s\S]*Photo B[\s\S]*free preview writer/i.test(report),
      report
    );
    check('only the chips that went out are cleared', (await chips(page).count()) === 0);
    await page.screenshot({ path: path.join(out, 'attachments-desktop-used.png') });

    // A handcrafted MP4: begin → PUT → commit; this browser can't take frames from it.
    await page
      .locator('input[type=file][aria-label="Photo or video"]')
      .setInputFiles({ name: 'clip.mp4', mimeType: 'video/mp4', buffer: mp4() });
    const video = await waitChipWord(page, 0, /No preview in this browser$/, 90000);
    check(
      'the MP4 goes through begin → PUT → commit and says "No preview in this browser"',
      video.ok,
      video.seen
    );
    await page.screenshot({ path: path.join(out, 'attachments-desktop-video.png') });
    await desk.close();

    // === phone ========================================================================================================
    const phone = await context(browser, { width: 390, height: 844 });
    const small = await phone.newPage();
    await open(small);
    await plus(small).tap();
    const sheet = small.getByRole('dialog', { name: 'Add to this message' });
    await sheet.waitFor({ state: 'visible', timeout: 15000 });
    check('phone: ＋ opens the sheet', await sheet.isVisible());
    await sheet.getByRole('button', { name: /^Post/ }).tap();
    const search = small.getByPlaceholder('Search posts');
    await search.waitFor({ state: 'visible', timeout: 10000 });
    const first = small.getByRole('dialog').locator('ul li button').first();
    await first.waitFor({ state: 'visible', timeout: 15000 });
    const inside = await first.evaluate((el) => {
      const r = el.getBoundingClientRect();
      const vv = window.visualViewport;
      return (
        r.top >= (vv ? vv.offsetTop : 0) &&
        r.bottom <= (vv ? vv.offsetTop + vv.height : window.innerHeight)
      );
    });
    check('phone: the first search result is inside the visual viewport', inside);
    await small.keyboard.press('Escape');
    const layout = await small.evaluate(() => {
      const box = document.querySelector('textarea[aria-label="Message"]');
      return {
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        font: box ? parseFloat(getComputedStyle(box).fontSize) : 0
      };
    });
    check('phone: no horizontal overflow', layout.overflow <= 0, layout);
    check('phone: the textbox is at least 16 px', layout.font >= 16, layout);
    await small.screenshot({ path: path.join(out, 'attachments-phone.png') });
    await phone.close();
  } finally {
    await browser.close();
  }
  const failed = results.filter((r) => !r.ok).length;
  fs.writeFileSync(
    path.join(out, 'rafii-attachments.json'),
    JSON.stringify({ at: new Date().toISOString(), results }, null, 1)
  );
  process.stdout.write(`\n${results.length} checks, ${failed} failed\n`);
  if (failed) process.exitCode = 1;
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
