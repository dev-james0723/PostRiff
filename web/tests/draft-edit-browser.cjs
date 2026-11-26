'use strict';
/**
 * One-click tone and polish edits in the draft editor (plan D5, TONE-5) and restore / discard in the draft details
 * sheet (D3), through the real web app and the hosted Python handlers of the local dev harness. Synthetic identity
 * and synthetic text only. No API response is mocked; every request that leaves the harness origin is blocked.
 *
 * Journey at 1440 and 375 px, each in a fresh workspace: open a draft, choose "Warm", see the candidate, use it, undo;
 * select one sentence, polish it, discard. At 1440 also: discard a waiting candidate and restore a version from the
 * details sheet. Checked along the way: the polite live status line, where focus lands after "Use this", "Undo" and
 * "Discard", the draft text staying untouched until "Use this", text outside a selection staying byte-identical,
 * 44 px controls, no horizontal scrolling, and axe (WCAG 2.x A/AA) on the open editor dialog.
 *
 * This script starts nothing. It needs, already running:
 *   API  LC_ALL=C <venv>/bin/python scripts/postriff_dev_hosted.py --port 4331   (draft edits are on by default there,
 *        and its fixture writers follow an edit deterministically; never --no-draft-edits)
 *   web  cd web && npm run dev -- -p 3100
 * Run:   node web/tests/draft-edit-browser.cjs        (Node 24, from the repository root or web/)
 * Env:   RAFII_WEB_URL                  the web app (default http://localhost:3100; loopback only)
 *        RAFII_DRAFT_EDIT_MODEL         a harness writer id to pin in the browser and for the API-made candidate.
 *                                       The script never picks a model itself; unset, the workspace default writes.
 *        RAFII_DRAFT_EDIT_EVIDENCE_DIR  screenshots and result.json (default .token-pilot/reports/draft-edit-browser)
 */
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const base = (process.env.RAFII_WEB_URL || 'http://localhost:3100').replace(/\/+$/, '');
const target = new URL(base);
if (!['localhost', '127.0.0.1'].includes(target.hostname) || target.origin !== base) {
  throw new Error(`RAFII_WEB_URL must be a plain loopback origin such as http://localhost:3100 (got ${base}). This script runs only against the local dev harness.`);
}
const pinnedModel = (process.env.RAFII_DRAFT_EDIT_MODEL || '').trim();
const root = path.resolve(__dirname, '../..');
const out = path.resolve(process.env.RAFII_DRAFT_EDIT_EVIDENCE_DIR || path.join(root, '.token-pilot/reports/draft-edit-browser'));
const WIDTHS = [1440, 375];
/** The editor waits up to 150 s for a writer (lib/api/draft-edits.ts); a little more here. */
const EDIT_TIMEOUT = 170_000;
const DRAFT = 'Our spring piano workshop opens on 12 March at 7 pm. Bring one short passage you are practising this week. Places are limited to 20 people, so reply if you would like one.';
const SENTENCE = 'Bring one short passage you are practising this week.';
const TEXTAREA = 'textarea[aria-label="Draft text"]';
const tours = Object.fromEntries([...fs.readFileSync(path.join(root, 'web/src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((match) => [match[1], 1]));

const checks = [];
const accessibility = [];
const screenshots = [];
const pageErrors = [];
const record = (width, check) => {
  checks.push({ width, check });
  console.log(`draft-edit browser [${width}] ${check}`);
};
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Bearer `dev:<principal>` against the harness, through the web app's /api rewrite (as the browser calls it). */
function client(principal) {
  const headers = { 'Content-Type': 'application/json', 'X-PostRiff-Request': 'founder-alpha', Authorization: `Bearer dev:${principal}`, Origin: base };
  return async function api(method, url, body) {
    const response = await fetch(base + url, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(EDIT_TIMEOUT) });
    const text = await response.text();
    if (!response.ok) throw Object.assign(new Error(`${method} ${url} → ${response.status} ${text.slice(0, 400)}`), { status: response.status, body: text });
    return text ? JSON.parse(text) : null;
  };
}

/** Fails at once, and says what to start, when the harness is not there or is not the synthetic one. */
async function preflight() {
  let config;
  try {
    const response = await fetch(`${base}/api/auth/config`, { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new Error(`HTTP ${response.status} (is the API harness on port 4331 running behind the web app?)`);
    config = await response.json();
  } catch (error) {
    throw new Error(
      [
        `No Rafii dev harness answered at ${base}/api/auth/config: ${error?.cause?.code || error.message}.`,
        'This script starts nothing. Start the harness first, then run it again:',
        '  API  LC_ALL=C <venv>/bin/python scripts/postriff_dev_hosted.py --port 4331   (with draft edits on)',
        '  web  cd web && npm run dev -- -p 3100',
        'or set RAFII_WEB_URL to the running web app.'
      ].join('\n'),
      { cause: error }
    );
  }
  if (config?.execution !== 'dev-synthetic') throw new Error(`${base} is not the synthetic dev harness (execution: ${config?.execution ?? 'unknown'}). This script runs only there.`);
}

/** The editor offers the control only when the writer catalogue says edits are on (`draftEdits.enabled`). */
async function checkCatalog(api) {
  const catalog = await api('GET', '/api/ideas/models');
  if (catalog?.draftEdits?.enabled !== true) {
    throw new Error('One-click draft edits are off on this API: GET /api/ideas/models carries no draftEdits entry. Start the API harness with draft edits on (its default; not --no-draft-edits), or POSTRIFF_DRAFT_EDITS=1 on another host.');
  }
  if (pinnedModel && !(catalog.models ?? []).some((model) => model.id === pinnedModel && model.qualified)) {
    throw new Error(`RAFII_DRAFT_EDIT_MODEL=${pinnedModel} is not a qualified writer on this API. Listed: ${(catalog.models ?? []).map((model) => `${model.id}${model.qualified ? '' : ' (not qualified)'}`).join(', ') || 'none'}.`);
  }
}

/** One saved draft with known synthetic text: the deterministic preview writes it, then the text is set by `variant_edit`. */
async function seedDraft(api, ws) {
  let snapshot = await api('GET', ws);
  const run = await api('POST', `${ws}/ideas/quick-start`, {
    expectedRevision: snapshot.revision,
    text: 'Synthetic workshop note: invite students to bring one short passage they are practising.',
    ownContent: true,
    confirmUse: true,
    destinations: [{ platform: 'LinkedIn', language: 'en' }],
    model: 'deterministic-preview',
    reasoning: 'quick',
    voiceMode: 'neutral',
    timeZone: 'UTC'
  });
  let ready = run;
  const deadline = Date.now() + 60_000;
  while (['queued', 'running'].includes(ready.status) && Date.now() < deadline) {
    await sleep(250);
    ready = await api('GET', `${ws}/ideas/runs/${run.runId}/events`);
  }
  assert.equal(ready.status, 'completed', `The deterministic seed draft did not complete (status ${ready.status}).`);
  snapshot = await api('GET', ws);
  snapshot = await api('POST', `${ws}/ideas/runs/${run.runId}/apply`, { expectedRevision: snapshot.revision, artifactHash: ready.artifactHash });
  snapshot = await api('GET', ws);
  const seeded = (snapshot.state.variants ?? []).find((variant) => variant.platform === 'LinkedIn');
  assert.ok(seeded, 'The applied run left a LinkedIn draft.');
  const saved = await api('POST', `${ws}/actions`, { expectedRevision: snapshot.revision, action: 'variant_edit', payload: { variantId: seeded.id, variantRevision: seeded.revision, text: DRAFT } });
  const variant = saved.state.variants.find((item) => item.id === seeded.id);
  assert.ok(variant.text.includes(SENTENCE), 'The synthetic draft text was stored.');
  return variant;
}

const hydrated = async (locator) => {
  await locator.waitFor();
  const end = Date.now() + 30_000;
  while (Date.now() < end) {
    if (await locator.evaluate((el) => Object.keys(el).some((key) => key.startsWith('__reactProps')), undefined, { timeout: Math.max(1, end - Date.now()) }).catch(() => false)) return;
    await sleep(50);
  }
  throw new Error('Hydration timeout');
};

async function untilText(locator, expected, what, timeout = 15_000) {
  const end = Date.now() + timeout;
  let seen = '';
  while (Date.now() < end) {
    seen = ((await locator.textContent().catch(() => '')) ?? '').replace(/\s+/g, ' ').trim();
    if (typeof expected === 'string' ? seen === expected : expected.test(seen)) return seen;
    await sleep(100);
  }
  throw new Error(`${what}: expected ${expected}, saw "${seen}"`);
}

/** Focus must land on `selector`; on failure, say where it is instead. */
async function focusOn(page, selector, what) {
  try {
    await page.waitForFunction((wanted) => document.activeElement?.matches(wanted) ?? false, selector, { timeout: 10_000 });
  } catch {
    const actual = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return 'the page body (focus was dropped)';
      return `<${el.tagName.toLowerCase()}> ${el.getAttribute('data-tone-control') ?? el.getAttribute('data-tone-focus') ?? (el.textContent ?? '').trim().slice(0, 60)}`;
    });
    throw new Error(`${what}: focus is on ${actual}, expected ${selector}.`);
  }
}

/**
 * Selects `passage` in the editor the way a keyboard user does: caret at its start, then Shift+ArrowRight once per
 * character. Real key events are what React's onSelect listens to; a programmatic setSelectionRange plus a synthetic
 * `selectionchange` never reached it (checked in Chromium: calling the textarea's own onSelect handler directly did
 * update the panel, so the gap was the synthetic event, not the product). One key press per UTF-16 unit, so the
 * passage must be plain text without astral characters.
 */
async function selectPassage(textarea, passage) {
  await textarea.click();
  const length = await textarea.evaluate((el, wanted) => {
    const start = el.value.indexOf(wanted);
    if (start < 0) throw new Error(`"${wanted}" is not in the draft`);
    if (/[\uD800-\uDFFF]/.test(wanted)) throw new Error('selectPassage needs a passage without astral characters');
    el.focus();
    el.setSelectionRange(start, start, 'forward');
    return wanted.length;
  }, passage);
  for (let index = 0; index < length; index += 1) await textarea.press('Shift+ArrowRight');
}

/** Waits for what one click produced: a candidate, a refusal or failure, or "nothing changed". */
async function editOutcome(panel, copy, what) {
  const candidate = panel.getByTestId('tone-candidate');
  const problem = panel.getByRole('alert');
  const unchanged = panel.getByText(copy.noChange, { exact: true });
  try {
    await candidate.or(problem).or(unchanged).first().waitFor({ timeout: EDIT_TIMEOUT });
  } catch {
    throw new Error(`${what}: no candidate, failure or "nothing changed" message within ${EDIT_TIMEOUT / 1000} s.`);
  }
  if (await problem.count()) {
    const message = ((await problem.first().textContent()) ?? '').trim();
    const hint = /AI writer/i.test(message)
      ? ' The writer cannot follow edits (409 draft_edit_writer_unavailable). The harness makes its fixture writers follow edits when draft edits are on; otherwise set RAFII_DRAFT_EDIT_MODEL to a harness writer that supports edits.'
      : '';
    throw new Error(`${what}: the edit was refused or failed: "${message}".${hint}`);
  }
  if (await candidate.count()) return { candidate, unchanged: false };
  return { candidate, unchanged: true };
}

async function shot(page, name) {
  const file = path.join(out, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  screenshots.push(path.relative(root, file));
}

/** No horizontal scrolling on the page or inside the dialog. */
async function noOverflow(page, dialog, width, what) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${what} at ${width}: the page scrolls sideways`);
  assert.equal(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), true, `${what} at ${width}: the dialog scrolls sideways`);
}

/** axe on the open editor dialog. Serious and critical findings fail; each names whether it sits in the tone panel. */
async function axeDialog(page, dialog, width, moment) {
  await dialog.evaluate((el) => el.setAttribute('data-axe-target', 'draft-editor'));
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run('[data-axe-target="draft-editor"]', { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] }, resultTypes: ['violations'] });
    return result.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      nodes: violation.nodes.map((node) => {
        const selector = Array.isArray(node.target) ? node.target[0] : node.target;
        let inTonePanel = false;
        try {
          inTonePanel = Boolean(document.querySelector(selector)?.closest('[data-testid="tone-edit"]'));
        } catch {
          /* a selector axe built for a shadow root: reported as outside */
        }
        return { target: String(selector), inTonePanel };
      })
    }));
  });
  accessibility.push({ width, moment, violations });
  const blocking = violations.filter((violation) => ['serious', 'critical'].includes(violation.impact));
  assert.deepEqual(blocking, [], `axe (${moment}, ${width}): serious or critical violations in the editor dialog: ${JSON.stringify(blocking, null, 2)}`);
}

const variantIn = (snapshot, id) => snapshot.state.variants.find((variant) => variant.id === id);
const lastOrigin = (variant) => (variant.revisions ?? []).toSorted((a, b) => a.revision - b.revision).at(-1)?.origin;

async function journey(browser, width, contract) {
  const { TONE_COPY, PRESET_TONE_IDS, choiceName } = contract;
  const copy = TONE_COPY.en;
  const principal = randomUUID();
  const api = client(principal);
  const boot = await api('POST', '/api/auth/verify', { plan: 'studio' });
  const workspaceId = boot.workspaceId;
  const ws = `/api/workspaces/${workspaceId}`;
  await checkCatalog(api);
  const seeded = await seedDraft(api, ws);
  const original = seeded.text;

  const context = await browser.newContext({ viewport: { width, height: width < 768 ? 844 : 960 }, reducedMotion: 'reduce', locale: 'en-US' });
  await context.route('**/*', (route) => (new URL(route.request().url()).origin === base ? route.continue() : route.abort()));
  await context.addCookies([
    { name: 'postriff_dev', value: '1', url: base },
    { name: 'postriff_dev_principal', value: principal, url: base },
    { name: 'postriff_theme', value: 'rafii', url: base }
  ]);
  await context.addInitScript(
    ({ id, workspace, progress, model }) => {
      localStorage.setItem('postriff-dev-principal', id);
      localStorage.setItem('postriff-workspace', workspace);
      const seen = JSON.stringify({ completed: progress, dismissed: progress, nudged: progress });
      localStorage.setItem('postriff-onboarding', seen);
      localStorage.setItem(`postriff-onboarding:${id}`, seen);
      if (model) localStorage.setItem('postriff-agent-model-v2', model);
      // Development overlays are not part of the product and can sit over controls on a phone.
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style');
        style.textContent = '.tsqd-parent-container,nextjs-portal{display:none!important}';
        document.head.appendChild(style);
      });
    },
    { id: principal, workspace: workspaceId, progress: tours, model: pinnedModel }
  );
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  page.on('pageerror', (error) => pageErrors.push({ width, message: error.message }));
  page.on('console', (message) => {
    if (message.type() === 'error') console.log(`[${width}] browser console error: ${message.text().slice(0, 300)}`);
  });

  try {
    // Open the draft in the editor.
    await page.goto(`${base}/app/queue?view=drafts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const card = page.locator(`[data-card-kind="draft"][data-card-key="draft:${seeded.id}"]`);
    const editButton = card.getByRole('button', { name: 'Edit', exact: true });
    await hydrated(editButton);
    await editButton.click();
    const dialog = page.getByRole('dialog', { name: /^Edit draft/ });
    await dialog.waitFor();
    const textarea = dialog.locator(TEXTAREA);
    assert.equal(await textarea.inputValue(), original);
    const panel = dialog.getByTestId('tone-edit');
    try {
      await panel.waitFor({ timeout: 20_000 });
    } catch {
      throw new Error('The tone panel is not in the editor although the catalogue has draftEdits.enabled: check the edit permission and that this is not the sample workspace.');
    }
    await panel.getByRole('heading', { name: copy.title, exact: true }).waitFor();
    const status = panel.getByTestId('tone-edit-status');
    assert.equal(await status.getAttribute('aria-live'), 'polite', 'the status line is a polite live region');
    for (const control of await panel.locator('[data-tone-control]').all()) {
      const box = await control.boundingBox();
      assert.ok(box && box.height >= 43.5, `${await control.getAttribute('data-tone-control')} is at least 44 px tall (${box?.height})`);
    }
    await noOverflow(page, dialog, width, 'editor');
    record(width, 'Editor opened on a saved draft; tone panel present, polite live status, 44 px controls, no sideways scroll');

    // One click: Warm. A candidate waits beside the draft; the draft keeps its text.
    const warm = choiceName({ mode: 'tone', tone: 'warm' });
    await panel.getByRole('button', { name: copy.tones.warm, exact: true }).click();
    const first = await editOutcome(panel, copy, 'Warm');
    assert.equal(first.unchanged, false, 'Warm: the writer returned the text unchanged, so there is no candidate to review. The journey needs a writer that changes the tone.');
    const candidate = first.candidate;
    await untilText(status, copy.ready(warm), 'live status after the candidate arrived');
    await untilText(candidate.getByRole('heading', { level: 4 }), new RegExp(`${escapeRegExp(warm)} · ${escapeRegExp(copy.scopeDraft)}$`), 'candidate heading');
    await candidate.getByRole('group', { name: copy.current, exact: true }).waitFor();
    await candidate.getByRole('group', { name: copy.suggested, exact: true }).waitFor();
    try {
      await candidate.getByText(copy.voiceNeutral, { exact: true }).waitFor({ timeout: 5_000 });
    } catch {
      throw new Error(`The candidate shows no "${copy.voiceNeutral}" line: the edit response carried no voice {requested, effective} (spec 5.4), or this workspace unexpectedly wrote in a personal voice.`);
    }
    try {
      await candidate.getByText(/^Rewritten from /).waitFor({ timeout: 5_000 });
    } catch {
      throw new Error('The candidate shows no "Rewritten from …" line: neither the edit response (base {kind, revision}, spec 5.4) nor the stored candidate (edit.baseKind) names the text it started from.');
    }
    let snapshot = await api('GET', ws);
    let variant = variantIn(snapshot, seeded.id);
    assert.equal(variant.text, original, 'the draft keeps its text until "Use this"');
    assert.equal(variant.proposedUpdate?.edit?.mode, 'tone');
    assert.equal(variant.proposedUpdate?.edit?.tone, 'warm');
    const warmText = variant.proposedUpdate.text;
    assert.notEqual(warmText, original);
    assert.equal(await textarea.inputValue(), original, 'the editor still shows the draft');
    await candidate.scrollIntoViewIfNeeded();
    await shot(page, `candidate-${width}`);
    await noOverflow(page, dialog, width, 'candidate');
    await axeDialog(page, dialog, width, 'Warm candidate shown');
    record(width, 'One click on Warm gave a candidate (current and suggested wording, voice line, base line); the draft text is unchanged; status announced; axe clean');

    // Use this: the new wording is in the draft, focus moves to the note that holds Undo, a toast offers Undo too.
    const before = variant.revision;
    await candidate.getByRole('button', { name: copy.use, exact: true }).click();
    await page.waitForFunction(({ selector, text }) => document.querySelector(selector)?.value === text, { selector: TEXTAREA, text: warmText });
    snapshot = await api('GET', ws);
    variant = variantIn(snapshot, seeded.id);
    assert.equal(variant.text, warmText);
    assert.equal(variant.revision, before + 1, 'accepting writes one new revision');
    assert.equal(lastOrigin(variant), 'accepted-edit', 'the new revision is recorded as an accepted edit, not as the author\'s writing');
    assert.ok(variant.editBase && variant.editBase.acceptedRevision === variant.revision, `the draft records the base of the accepted edit (editBase: ${JSON.stringify(variant.editBase)})`);
    await focusOn(page, '[data-tone-focus="applied"]', 'After "Use this"');
    const toast = page.locator('[data-sonner-toast]').filter({ hasText: copy.applied(warm) });
    await toast.waitFor();
    await toast.getByRole('button', { name: copy.undo, exact: true }).waitFor();
    await shot(page, `applied-${width}`);
    record(width, '"Use this" put the candidate in the draft as an accepted-edit revision with editBase; focus moved to the applied note; the toast offers Undo');

    // Undo: the earlier wording comes back as a new "restored" revision; focus returns to the tone buttons.
    const applied = panel.locator('[data-tone-focus="applied"]');
    await applied.getByRole('button', { name: copy.undo, exact: true }).click();
    await page.waitForFunction(({ selector, text }) => document.querySelector(selector)?.value === text, { selector: TEXTAREA, text: original });
    await focusOn(page, `[data-tone-control="${PRESET_TONE_IDS[0]}"]`, 'After "Undo"');
    await page.locator('[data-sonner-toast]').filter({ hasText: copy.restored }).waitFor();
    snapshot = await api('GET', ws);
    variant = variantIn(snapshot, seeded.id);
    assert.equal(variant.text, original);
    assert.equal(lastOrigin(variant), 'restored');
    assert.equal(variant.proposedUpdate ?? null, null);
    record(width, 'Undo restored the earlier wording as a restored revision; focus returned to the first tone button');

    // Select one sentence, polish it. Only that passage may change.
    await selectPassage(textarea, SENTENCE);
    await untilText(panel.locator('p', { hasText: copy.scopeLabel }).first(), new RegExp(`${escapeRegExp(copy.scopeSelection)} · ${escapeRegExp(copy.characters(SENTENCE.length))}$`), 'scope after selecting a sentence');
    const at = original.indexOf(SENTENCE);
    const head = original.slice(0, at);
    const tail = original.slice(at + SENTENCE.length);
    let choice = { mode: 'polish' };
    await panel.getByRole('button', { name: copy.polish, exact: true }).click();
    let outcome = await editOutcome(panel, copy, 'Polish wording on a selection');
    if (outcome.unchanged) {
      // "Nothing changed" is a correct answer for a polish; the selection and Discard are then checked with a tone.
      snapshot = await api('GET', ws);
      assert.equal(variantIn(snapshot, seeded.id).proposedUpdate ?? null, null, 'no candidate is kept for a no-change answer');
      record(width, 'Polish on the selected sentence answered "nothing changed" with no candidate; checking the selection with Direct instead');
      choice = { mode: 'tone', tone: 'direct' };
      await panel.getByRole('button', { name: copy.tones.direct, exact: true }).click();
      outcome = await editOutcome(panel, copy, 'Direct on a selection');
      assert.equal(outcome.unchanged, false, 'Direct on the selected sentence also changed nothing, so Discard cannot be checked.');
    }
    const name = choiceName(choice);
    await untilText(outcome.candidate.getByRole('heading', { level: 4 }), new RegExp(`${escapeRegExp(name)} · ${escapeRegExp(copy.scopeSelection)}$`), 'selection candidate heading');
    snapshot = await api('GET', ws);
    variant = variantIn(snapshot, seeded.id);
    const pending = variant.proposedUpdate;
    assert.ok(pending?.edit, 'a selection candidate waits on the draft');
    assert.equal(pending.edit.mode, choice.mode);
    assert.ok(pending.edit.scope === 'selection' || pending.edit.selection, `the candidate records a selection edit (${JSON.stringify(pending.edit)})`);
    assert.ok(pending.text.startsWith(head) && pending.text.endsWith(tail), 'every character outside the selected sentence is unchanged');
    assert.equal(variant.text, original);
    await shot(page, `selection-candidate-${width}`);
    await axeDialog(page, dialog, width, `${name} on a selection`);

    // Discard: the candidate goes, the draft and its revision stay, focus returns to the button that asked for it.
    const revision = variant.revision;
    await outcome.candidate.getByRole('button', { name: copy.discard, exact: true }).click();
    await outcome.candidate.waitFor({ state: 'detached' });
    await focusOn(page, `[data-tone-control="${choice.mode === 'polish' ? 'polish' : choice.tone}"]`, 'After "Discard"');
    snapshot = await api('GET', ws);
    variant = variantIn(snapshot, seeded.id);
    assert.equal(variant.proposedUpdate ?? null, null);
    assert.equal(variant.revision, revision, 'discarding writes no revision');
    assert.equal(await textarea.inputValue(), original);
    await noOverflow(page, dialog, width, 'after discard');
    record(width, `${name} on one selected sentence changed only that passage; Discard removed the candidate without a revision; focus returned to its button`);

    if (width === WIDTHS[0]) {
      // Details sheet (D3): discard a waiting candidate, then restore the accepted Warm version from the history.
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      snapshot = await api('GET', ws);
      variant = variantIn(snapshot, seeded.id);
      const made = await api('POST', `${ws}/drafts/${encodeURIComponent(seeded.id)}/edits`, {
        variantRevision: variant.revision,
        mode: 'tone',
        tone: 'direct',
        base: 'original',
        voiceMode: 'neutral',
        ...(pinnedModel ? { model: pinnedModel } : {}),
        idempotencyKey: randomUUID(),
        expectedRevision: snapshot.revision
      });
      assert.equal(made?.edit?.status, 'candidate', `the route answered a Direct candidate (${JSON.stringify(made?.edit)})`);
      await page.reload({ waitUntil: 'domcontentloaded' });
      const open = card.locator('[data-card-open]');
      await hydrated(open);
      await open.click();
      const sheet = page.getByRole('dialog').filter({ has: page.getByText('Revision history', { exact: true }) });
      await sheet.waitFor();
      const direct = choiceName({ mode: 'tone', tone: 'direct' });
      await sheet.getByText(new RegExp(`^${escapeRegExp(direct)} · ${escapeRegExp(copy.scopeDraft)}\\.`)).waitFor();
      await sheet.getByRole('button', { name: copy.sheet.discard, exact: true }).click();
      await page.locator('[data-sonner-toast]').filter({ hasText: copy.sheet.discardedTitle }).waitFor();
      snapshot = await api('GET', ws);
      assert.equal(variantIn(snapshot, seeded.id).proposedUpdate ?? null, null, 'the sheet discarded the waiting candidate');
      const restore = sheet.getByRole('button', { name: new RegExp(`^${escapeRegExp(copy.sheet.restoreVersionOf('Rewording accepted'))}`) });
      await restore.click();
      await page.locator('[data-sonner-toast]').filter({ hasText: copy.sheet.restoredTitle }).waitFor();
      snapshot = await api('GET', ws);
      variant = variantIn(snapshot, seeded.id);
      assert.equal(variant.text, warmText, 'the accepted Warm wording is the current text again');
      assert.equal(lastOrigin(variant), 'restored');
      await shot(page, `details-sheet-${width}`);
      record(width, 'Details sheet: Discard cleared a waiting Direct candidate; "Restore this version" brought back the accepted Warm wording as a restored revision');
    }
  } catch (error) {
    await page.screenshot({ path: path.join(out, `failure-${width}.png`), fullPage: true }).catch(() => {});
    console.log((await page.locator('body').innerText().catch(() => '')).slice(-3000));
    throw error;
  } finally {
    await context.close();
  }
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  await preflight();
  const contract = await import(pathToFileURL(path.join(__dirname, '../src/features/pipeline/tone-edit-contract.ts')).href);
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of WIDTHS) await journey(browser, width, contract);
  } finally {
    await browser.close();
  }
  assert.deepEqual(pageErrors, [], 'no page errors');
  const report = { status: 'PASS', base, widths: WIDTHS, pinnedModel: pinnedModel || null, execution: 'local dev harness; real web app and hosted handlers; synthetic identity and text; no mocked API responses', checks, accessibility, screenshots, pageErrors };
  fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: 'PASS', checks: checks.length, evidence: path.relative(root, out) }));
})().catch((error) => {
  try {
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ status: 'FAIL', base, error: String(error?.stack || error), checks, accessibility, screenshots, pageErrors }, null, 2));
  } catch {
    /* the report directory is not writable: the console still has the error */
  }
  console.error(error?.stack || error);
  process.exitCode = 1;
});
