/** Actual Queue UI/API/SQL/shared worker; synthetic Mastodon and explicitly advanced test clock. */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { readFileSync, writeFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { deflateSync } = require('node:zlib');
const { chromium, webkit } = require('playwright');
const ENGINE = process.env.MASTODON_BROWSER_ENGINE || 'chromium';
assert.ok(ENGINE === 'chromium' || ENGINE === 'webkit', 'A real Chromium or WebKit engine must be selected');
assert.equal(process.platform, 'linux');
assert.match(process.env.CI || '', /^(true|1)$/);
const base = 'http://127.0.0.1:4448', fixture = 'http://127.0.0.1:4348';
const out = resolve(process.env.MASTODON_BROWSER_EVIDENCE_DIR || resolve(__dirname, '../../.jcb-artifacts/mastodon-browser'));

function crc32(raw) {
  let crc = 0xffffffff;
  for (const byte of raw) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)); }
  const result = Buffer.alloc(4); result.writeUInt32BE((crc ^ 0xffffffff) >>> 0); return result;
}
function png(color) {
  const chunk = (name, data) => { const type = Buffer.from(name), length = Buffer.alloc(4); length.writeUInt32BE(data.length); return Buffer.concat([length, type, data, crc32(Buffer.concat([type, data]))]); };
  const header = Buffer.alloc(13); header.writeUInt32BE(320); header.writeUInt32BE(320, 4); header[8] = 8; header[9] = 2;
  const row = Buffer.from([0, ...Array.from({ length: 320 }, () => color).flat()]);
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', deflateSync(Buffer.concat(Array(320).fill(row)))), chunk('IEND', Buffer.alloc(0))]);
}
function wav() {
  const raw = Buffer.alloc(16044); raw.write('RIFF'); raw.writeUInt32LE(raw.length - 8, 4); raw.write('WAVEfmt ', 8);
  raw.writeUInt32LE(16, 16); raw.writeUInt16LE(1, 20); raw.writeUInt16LE(1, 22); raw.writeUInt32LE(8000, 24);
  raw.writeUInt32LE(16000, 28); raw.writeUInt16LE(2, 32); raw.writeUInt16LE(16, 34); raw.write('data', 36); raw.writeUInt32LE(16000, 40); return raw;
}

(async () => {
  const browser = await (ENGINE === 'webkit' ? webkit : chromium).launch({ headless: true }); const checks = [];
  let activePage;
  try {
    for (const width of [1440, 390, 320]) {
      const principal = randomUUID();
      const context = await browser.newContext({ viewport: { width, height: 1000 }, timezoneId: 'UTC', reducedMotion: 'reduce' });
      await context.addCookies([{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }]);
      await context.addInitScript(id => { localStorage.setItem('postriff-dev-principal', id); localStorage.setItem('postriff-onboarding:' + id, JSON.stringify({ completed: {}, dismissed: { welcome: 1 }, nudged: {} })); }, principal);
      await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
      const headers = { Authorization: 'Bearer dev:' + principal, Origin: base, 'X-PostRiff-Request': 'founder-alpha' };
      const request = async (method, path, data) => {
        const response = await context.request.fetch(base + path, { method, headers, data });
        assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${(await response.text()).slice(0, 1000)}`); return response.json();
      };
      const tick = async (seconds = 0) => {
        const response = await context.request.post(fixture + '/dev/mastodon/tick', { data: { seconds } }); assert.ok(response.ok(), `Fixture tick ${response.status()}: ${(await response.text()).slice(0, 1000)}`); return response.json();
      };
      const reset = await context.request.post(fixture + '/dev/mastodon/tick', { data: { resetClock: true } }); assert.ok(reset.ok());
      const boot = await request('POST', '/api/auth/verify', { plan: 'studio' }); const wid = boot.workspaceId;
      const started = await request('POST', `/api/workspaces/${wid}/channels/mastodon/oauth/start`, { capability: 'management', input: { instance: 'mastodon.social' } });
      const connected = await request('POST', `/api/workspaces/${wid}/channels/mastodon/oauth/complete`, { state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'synthetic-code' });
      const snapshot = () => request('GET', `/api/workspaces/${wid}`);
      const act = async (action, payload) => { const saved = await snapshot(); return request('POST', `/api/workspaces/${wid}/actions`, { expectedRevision: saved.revision, action, payload }); };
      const images = [];
      for (const color of [[100, 160, 90], [160, 90, 100]]) {
        const saved = await act('p2_media_upload', { data: png(color).toString('base64'), mime: 'image/png', filename: 'SYNTHETIC-queue-image.png' });
        images.push(saved.state.phase2.assets.at(-1));
      }
      const audio = wav();
      const ticket = await request('POST', `/api/workspaces/${wid}/library/files`, { filename: 'SYNTHETIC-queue-audio.wav', mime: 'audio/wav', bytes: audio.length });
      const token = new URL(ticket.upload.url).searchParams.get('token'); assert.ok(token);
      const uploaded = await context.request.put(fixture + '/dev/upload/' + token, { data: audio, headers: { 'Content-Type': 'audio/wav' } }); assert.ok(uploaded.ok());
      await request('POST', `/api/workspaces/${wid}/library/files/${ticket.upload.assetId}/commit`, {});
      const processed = await context.request.post(fixture + '/dev/library/tick?workspace=' + wid + '&assetId=' + ticket.upload.assetId, { data: {} }); assert.ok(processed.ok());
      const normalized = await request('GET', `/api/workspaces/${wid}/library/files/${ticket.upload.assetId}`);
      assert.equal(normalized.asset.hash.length, 64); assert.equal(normalized.asset.mime, 'audio/wav');
      const page = await context.newPage(), errors = [];
      activePage = page;
      page.on('pageerror', error => errors.push(error.message));
      async function prepare(kind) {
        await page.goto(base + '/app/queue');
        await page.getByRole('button', { name: 'Schedule a draft', exact: true }).click();
        const dialog = page.getByRole('dialog');
        await dialog.getByLabel('Draft', { exact: true }).click();
        await page.getByRole('option', { name: /Mastodon.*SYNTHETIC Queue root/ }).click();
        await dialog.getByLabel('Account', { exact: true }).click();
        await page.getByRole('option', { name: /mastodon.social/ }).click();
        const at = (await tick()).now * 1000 + (kind === 'native' ? 9 : 2) * 60000;
        await dialog.getByLabel('Publish at', { exact: true }).fill(new Date(at).toISOString().slice(0, 16));
        if (kind === 'thread') {
          await dialog.getByRole('button', { name: 'Add next thread post', exact: true }).click();
          await dialog.getByLabel('Thread post 2', { exact: true }).fill('SYNTHETIC child two ' + width);
          await dialog.getByRole('button', { name: 'Add next thread post', exact: true }).click();
          await dialog.getByLabel('Thread post 3', { exact: true }).fill('SYNTHETIC child three ' + width);
          assert.equal(await dialog.getByRole('checkbox', { name: /Schedule on the Mastodon server after approval/ }).isDisabled(), true);
        } else {
          await dialog.getByLabel('Image, video or audio (optional)', { exact: true }).click();
          await page.getByRole('button', { name: kind === 'images' ? new RegExp('Image.*hash starts with ' + images[0].hash.slice(0, 8)) : new RegExp('Audio .*hash starts with ' + normalized.asset.hash.slice(0, 8)) }).click();
          await dialog.getByLabel(kind === 'images' ? 'Alt text' : 'Media description (optional)', { exact: true }).fill('SYNTHETIC accessible description');
          if (kind === 'images') {
            await dialog.getByRole('button', { name: 'Add another image', exact: true }).click();
            await dialog.getByLabel('Image 2', { exact: true }).click();
            await page.getByRole('button', { name: new RegExp('Image.*hash starts with ' + images[1].hash.slice(0, 8)) }).click();
            await dialog.getByLabel('Image 2 description', { exact: true }).fill('SYNTHETIC second accessible description');
          }
          if (kind === 'native') await dialog.getByRole('checkbox', { name: /Schedule on the Mastodon server after approval/ }).check();
        }
        await dialog.getByLabel('Content warning', { exact: true }).fill('SYNTHETIC Queue validation');
        await dialog.getByRole('checkbox', { name: /I have the rights to publish this text/ }).check();
        assert.equal(await dialog.evaluate(element => element.getBoundingClientRect().height <= innerHeight * 0.91), true, 'Long schedule form must stay within the viewport.');
        await page.screenshot({ path: resolve(out, `CLOUD-SYNTHETIC-queue-${kind}-${width}.png`), fullPage: false });
        const responsePromise = page.waitForResponse(response => {
          try { return response.request().postDataJSON()?.action === 'p2_review'; } catch { return false; }
        });
        const writesBefore = (await tick()).writes;
        await dialog.getByRole('button', { name: 'Prepare review', exact: true }).click();
        const response = await responsePromise; assert.ok(response.ok(), (await response.text()).slice(0, 1000));
        const saved = await response.json(), review = saved.state.phase2.reviews.at(-1);
        assert.equal(review.manifest.channelId, connected.connectionId); assert.equal(review.manifest.providerAccountId, '100@mastodon.social');
        assert.equal((await tick()).writes, writesBefore, 'Preparing must not publish.');
        if (kind === 'thread') assert.equal(review.manifest.payload.threadParts.length, 2);
        if (kind === 'images') assert.equal(review.manifest.media.length, 2);
        if (kind === 'audio' || kind === 'native') assert.equal(review.manifest.media[0].id, ticket.upload.assetId);
        const approvalPromise = page.waitForResponse(response => {
          try { return response.request().postDataJSON()?.action === 'p2_approve'; } catch { return false; }
        });
        await page.getByRole('button', { name: 'Approve & schedule', exact: true }).click();
        const approval = await approvalPromise; assert.ok(approval.ok(), (await approval.text()).slice(0, 1000));
        const after = await approval.json(); const job = after.state.phase2.jobs.find(item => item.approvalDigest === review.digest);
        assert.ok(job, 'Approval must persist one Queue job.'); return job.id;
      }
      async function finish(id, native = false) {
        let job;
        for (let index = 0; index < 12; index++) {
          await tick(native ? 10 : 70); job = (await snapshot()).state.phase2.jobs.find(item => item.id === id);
          assert.ok(!['failed', 'held', 'uncertain', 'canceled'].includes(job.state), JSON.stringify({ state: job.state, events: job.events?.slice(-3) }));
          if (native && job.progress?.stage === 'native_scheduled') {
            assert.notEqual(job.state, 'verified'); assert.ok(job.providerReference);
            const originalWrites = (await tick()).writes;
            await tick(600); assert.equal((await tick()).writes, originalWrites, 'Accepted native schedule must not be resubmitted.'); native = false;
          }
          if (job.state === 'verified') break;
        }
        assert.equal(job.state, 'verified', JSON.stringify({ state: job.state, progress: job.progress, events: job.events?.slice(-3) }));
        assert.match(job.url, /^https:\/\/mastodon\.social\/@SYNTHETIC\/\d+$/);
        await page.goto(base + '/app/queue?job=' + id);
        await page.getByText(/verified/i).first().waitFor();
        return job;
      }
      const thread = await finish(await prepare('thread')); assert.equal(thread.progress.threadReferences.length, 3); assert.equal(thread.progress.threadVerified, 3);
      const imagesJob = await finish(await prepare('images')); assert.equal(imagesJob.manifest.media.length, 2);
      const audioJob = await finish(await prepare('audio')); assert.equal(audioJob.manifest.media[0].normalizedLibrary, true);
      const nativeJob = await finish(await prepare('native'), true); assert.equal(nativeJob.manifest.timing.nativeProvider, 'Mastodon');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2); assert.equal(overflow, true); assert.deepEqual(errors, []);
      checks.push({ width, checks: ['exact UI thread approval and three verified saved IDs', 'two decoded immutable images with separate alt text', 'validated Library WAV through immutable custody and media upload', 'native accepted pending then unique media-bound publication without resubmission', 'actual shared Queue worker and SQL', 'responsive final receipt and no runtime error'], execution: 'synthetic provider; explicitly advanced fixture clock', browserEngine: ENGINE, realMastodonAcceptance: false });
      console.log(JSON.stringify({ status: 'PASS', execution: 'CLOUD SYNTHETIC QUEUE WIDTH', width, checks: checks.at(-1) }));
      await context.close();
    }
    const proof = JSON.parse(readFileSync(resolve(out, 'CLOUD-SYNTHETIC-browser.json'), 'utf8')); proof.queueChecks = checks;
    writeFileSync(resolve(out, 'CLOUD-SYNTHETIC-browser.json'), JSON.stringify(proof, null, 2));
    console.log(JSON.stringify({ status: 'PASS', execution: 'CLOUD SYNTHETIC QUEUE BROWSER', checks }));
  } catch (error) {
    if (activePage && !activePage.isClosed()) await activePage.screenshot({ path: resolve(out, 'CLOUD-SYNTHETIC-failure.png'), fullPage: false }).catch(() => {});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
