/**
 * Lane G browser scenes for Rafii Generative UI (rafii-genui/1), run by run.cjs in cloud CI (Chromium + WebKit) against the
 * acceptance stack: the real web build, the real hosted API (tests/agent_ui_acceptance/serve.py), the harness Manager and
 * the fixture provider at the network boundary. Viewports are EMULATION (labelled so in the evidence); they never stand in
 * for the real-iPhone part of G15.
 *
 * Every scene needs a generated view first (lane F mounts it as [data-rafii-generated], lane C renders it). When a lane
 * has not delivered the element a scene needs, the scene is BLOCKED with that exact reason — never passed.
 * Scene ids are the corpus ids in tests/agent_ui_acceptance/corpus.py (E2E_SCENES); the contract test checks they match.
 */
'use strict';

const SCENES = [];
const scene = (id, run) => SCENES.push({ id, run });

class Blocked extends Error {}
const blocked = (why) => { throw new Blocked(why); };

const GENERATED = '[data-rafii-generated]';
const UI_PATH = /\/api\/workspaces\/[0-9a-f-]{36}\/agent\/ui\//;
// A harness Manager flow that reads journey data (campaign specialist → campaign_list, J05) with an explicit UI intent.
const ELIGIBLE = "Chart what's missing in the campaign by status";

async function providerStats(t) {
  if (!t.providerBase) blocked('harness: no fixture provider URL');
  const res = await fetch(`${t.providerBase}/__stats`);
  return (await res.json()).requests;
}

async function arm(t, fault, count = 1) {
  if (!t.providerBase) blocked('harness: no fixture provider URL');
  await fetch(`${t.providerBase}/__fault`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fault, count }) });
}

function track(page) {
  const log = [];
  page.on('request', (r) => log.push({ at: Date.now(), method: r.method(), url: r.url(), kind: 'request' }));
  page.on('requestfailed', (r) => log.push({ at: Date.now(), method: r.method(), url: r.url(), kind: 'failed', error: r.failure()?.errorText }));
  return log;
}

const uiRequests = (log, since = 0, pattern = UI_PATH) => log.filter((e) => e.kind === 'request' && e.at >= since && pattern.test(new URL(e.url).pathname));

async function openPanel(t, page) {
  await page.goto(`${t.base}/app/overview`, { waitUntil: 'domcontentloaded' });
  const launcher = page.locator('#rafii-launcher');
  await launcher.waitFor({ state: 'visible', timeout: 240000 });
  await page.waitForFunction(() => document.querySelector('#rafii-launcher') && !document.querySelector('#rafii-launcher').disabled, null, { timeout: 240000 });
  if (!(await page.locator('#rafii-panel').isVisible().catch(() => false))) await launcher.click();
  const composer = page.locator('#rafii-panel').getByLabel('Ask Rafii', { exact: true });
  await composer.waitFor({ timeout: 60000 });
  return composer;
}

/** Ask an eligible question in the panel and wait for the generated view. Resolves {region, startedAt}. */
async function generated(t, page, { prompt = ELIGIBLE, wait = 'ready', timeout = 120000 } = {}) {
  // Proven absent (no scene of this run ever got a region): don't wait again. Once any scene had a region, a miss is that
  // scene's own FAILURE (with diagnostics) and later scenes still try: one miss must never cascade into "blocked".
  if (t.shared.noRegion && !t.shared.regionSeen) blocked(t.shared.noRegion);
  const composer = await openPanel(t, page);
  // One document-level observer installed BEFORE sending: it counts every change inside any generated region, so a region
  // node that is replaced, or a stream that finishes before the region is located, is still measured (no per-node race).
  await page.evaluate((sel) => {
    window.__g = { mutations: 0, firstChildAt: null };
    new MutationObserver((records) => {
      for (const record of records) {
        const el = record.target.nodeType === 1 ? record.target : record.target.parentElement;
        if (el && el.closest && el.closest(sel)) {
          window.__g.mutations += 1;
          if (!window.__g.firstChildAt && document.querySelector(`${sel} [data-genui]`)) window.__g.firstChildAt = performance.now();
        }
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  }, GENERATED);
  const startedAt = await page.evaluate(() => performance.now());
  await composer.fill(prompt);
  await composer.press('Enter');
  const region = page.locator(`#rafii-panel ${GENERATED}`).last();
  const answer = page.locator('#rafii-panel article[aria-label="Rafii\'s answer"]').last();
  await answer.waitFor({ timeout }).catch(() => {});
  try {
    await region.waitFor({ state: 'attached', timeout: 45000 });
  } catch {
    // Lane F: an eligible answer without a view offers an explicit button (passive surfaces never generate on their own).
    const build = page.locator('#rafii-panel').getByRole('button', { name: /build interactive view/i }).last();
    let clicked = false;
    if (await build.count()) {
      await build.click();
      clicked = true;
      await region.waitFor({ state: 'attached', timeout: 45000 }).catch(() => {});
    }
    if (!(await region.count())) {
      const answered = await page.locator('#rafii-panel article[aria-label="Rafii\'s answer"]').count();
      const why = `no ${GENERATED} region within 45 s of the native answer to an eligible turn (native answers: ${answered}; `
        + `'Build interactive view' ${clicked ? 'clicked' : 'absent'})`;
      if (t.shared.regionSeen) throw new Error(`lane F/C (intermittent: earlier scenes rendered views): ${why}`);
      t.shared.noRegion = `lane F/C: ${why}`;
      blocked(t.shared.noRegion);
    }
    t.shared.buildButtonNeeded = (t.shared.buildButtonNeeded || 0) + 1;
  }
  t.shared.regionSeen = true;
  if (wait === 'ready') await waitReady(page, timeout, t);
  return { region, startedAt };
}

/** Ready (mark or frame state) — or a terminal failure, which is proven once per run so later scenes don't wait for it. */
async function waitReady(page, timeout = 90000, t = null) {
  if (t && t.shared.noReady) blocked(t.shared.noReady);
  let outcome;
  try {
    outcome = await page.waitForFunction(() => {
      if (performance.getEntriesByName('rafii-genui:ready').length > 0 || document.querySelector('[data-rafii-generated][data-generation-state="ready"]')) return 'ready';
      return document.querySelector('[data-rafii-generated][data-generation-state="failed"]') ? 'failed' : false;
    }, null, { timeout }).then((h) => h.jsonValue());
  } catch {
    outcome = 'timeout';
  }
  if (outcome === 'ready') return;
  const why = outcome === 'failed'
    ? 'lanes B/C: the fixture view ended data-generation-state="failed" (validator/stream path; see api-corpus.json for the reason)'
    : "lane C/F: neither the 'rafii-genui:ready' mark nor data-generation-state=ready appeared within the timeout";
  if (t) t.shared.noReady = why;
  blocked(why);
}

const marks = (page) => page.evaluate(() => ['rafii-genui:first-component', 'rafii-genui:ready']
  .map((name) => performance.getEntriesByName(name).map((m) => ({ name, at: m.startTime, detail: m.detail || null }))).flat());

async function noRawDsl(region) {
  const text = await region.innerText().catch(() => '');
  return !/^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*[A-Z][A-Za-z0-9_]*\(/m.test(text) && !text.includes('root = ');
}

async function axe(page, selector) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  return page.evaluate(async (sel) => {
    const result = await window.axe.run(sel, { resultTypes: ['violations'] });
    return result.violations.filter((v) => ['serious', 'critical'].includes(v.impact)).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }));
  }, selector);
}

async function firstInput(region) {
  const input = region.locator('input[type="text"], input:not([type]), textarea, [role="textbox"]').first();
  return (await input.count()) ? input : null;
}

// --- scenes ------------------------------------------------------------------------------------------------------------
scene('progressive-render', async (t) => {
  const page = await t.page({ surface: 'panel' });
  await arm(t, 'slow', 1);
  const { region } = await generated(t, page);
  const m = await marks(page);
  const first = m.find((x) => x.name === 'rafii-genui:first-component');
  const ready = m.find((x) => x.name === 'rafii-genui:ready');
  if (!first || !ready) blocked(`lane C: performance marks missing (${m.map((x) => x.name).join(',') || 'none'})`);
  t.assert(first.at < ready.at, 'first component rendered before ready', { first: first.at, ready: ready.at });
  const g = await page.evaluate(() => window.__g);
  t.assert(g.mutations >= 2, 'the region grew in several steps (progressive), not once', g);
  t.assert(await noRawDsl(region), 'no raw DSL is ever shown');
  t.metric('firstComponentToReadyMs', ready.at - first.at);
  return `first component ${Math.round(ready.at - first.at)} ms before ready; ${g.mutations} DOM updates`;
});

scene('typing-during-stream', async (t) => {
  const page = await t.page({ surface: 'panel' });
  await arm(t, 'slow', 1);
  const { region } = await generated(t, page, { wait: 'none' });
  const composer = page.locator('#rafii-panel').getByLabel('Ask Rafii', { exact: true });
  await composer.click();
  const phrase = 'typed while streaming 廣東話 🎹';
  await composer.type(phrase, { delay: 25 });
  await waitReady(page, 90000, t);
  t.assert((await composer.inputValue()) === phrase, 'the composer value survived the stream', await composer.inputValue());
  t.assert(await composer.evaluate((el) => el === document.activeElement), 'focus stayed in the composer');
  const input = await firstInput(region);
  return input ? 'composer value/focus kept; generated input present' : 'composer value/focus kept (the fixture view has no generated input)';
});

scene('typing-during-patch', async (t) => {
  const page = await t.page({ surface: 'panel' });
  const { region } = await generated(t, page);
  const input = await firstInput(region);
  if (!input) blocked('lane C/E: the generated view has no text input to type into (needs a TextField in the generated library/fixture)');
  await input.click();
  await input.type('dirty value 普通话', { delay: 20 });
  const artifactId = await region.getAttribute('data-artifact-id');
  if (!artifactId) blocked('lane F: the generated region has no data-artifact-id to address an edit');
  // Lane F's explicit edit (surfaces/artifact.tsx): "Change this view" → "What should change?" → "Update view".
  const editButton = page.locator('#rafii-panel').getByRole('button', { name: 'Change this view', exact: true }).last();
  if (!(await editButton.count())) blocked('lane F: no "Change this view" affordance on the generated view (edits flag or role)');
  const readyBefore = await page.evaluate(() => performance.getEntriesByName('rafii-genui:ready').length);
  await editButton.click();
  await page.locator('#rafii-panel').getByLabel('What should change?').last().fill('change the period');
  await page.locator('#rafii-panel').getByRole('button', { name: 'Update view', exact: true }).last().click();
  const edited = await page.waitForFunction((n) => performance.getEntriesByName('rafii-genui:ready').length > n
    || document.querySelector('[data-rafii-generated][data-generation-state="failed"]'), readyBefore, { timeout: 90000 }).then(() => true).catch(() => false);
  if (!edited) blocked('lanes B/F: the explicit edit produced no new ready revision within 90 s');
  const value = await input.inputValue().catch(() => null);
  const conflict = await page.locator('[data-rafii-dirty-conflict], [role="alertdialog"]').count();
  t.assert(value === 'dirty value 普通话' || conflict > 0, 'the dirty value survived the patch or a native conflict UI protects it', { value, conflict });
  return conflict ? 'native conflict UI shown for the dirty field' : 'dirty value kept across the patch';
});

scene('keyboard-only', async (t) => {
  const page = await t.page({ surface: 'panel' });
  await generated(t, page);
  // Deterministic: focus the tabbable just before the view and press Tab once (must land inside), then focus the view's last
  // tabbable and press Tab once (must land outside: no trap). Every step names the element, for lane C.
  const plan = await page.evaluate((sel) => {
    const regions = document.querySelectorAll(sel);
    const region = regions[regions.length - 1];
    const tabbable = [...document.querySelectorAll('a[href], button, input, select, textarea, [tabindex]')]
      .filter((el) => el.tabIndex >= 0 && !el.disabled && el.getClientRects().length > 0 && !el.closest('[inert]') && getComputedStyle(el).visibility !== 'hidden');
    const inside = tabbable.map((el, i) => (region.contains(el) ? i : -1)).filter((i) => i >= 0);
    const tag = (el, mark) => { if (el) el.setAttribute('data-g-kb', mark); };
    if (!inside.length) return { inside: 0 };
    tag(tabbable[inside[0] - 1], 'before');
    tag(tabbable[inside[inside.length - 1]], 'last');
    const describe = (el) => el && `${el.tagName.toLowerCase()}${el.getAttribute('role') ? `[role=${el.getAttribute('role')}]` : ''}`
      + `${el.closest('[data-genui]') ? `@${el.closest('[data-genui]').getAttribute('data-genui')}#${el.closest('[data-statement-id]')?.getAttribute('data-statement-id') || ''}` : ''}`;
    return { inside: inside.length, first: describe(tabbable[inside[0]]), last: describe(tabbable[inside[inside.length - 1]]), hasBefore: inside[0] > 0 };
  }, GENERATED);
  if (!plan.inside) blocked('lane C/E: the generated view has no tabbable control (tabIndex >= 0, visible, enabled)');
  const where = () => page.evaluate((sel) => {
    const el = document.activeElement;
    const inView = !!el?.closest(sel);
    return { inView, el: el ? `${el.tagName.toLowerCase()}${el.closest('[data-genui]') ? `@${el.closest('[data-genui]').getAttribute('data-genui')}` : ''}` : null };
  }, GENERATED);
  // WebKit follows Safari's default keyboard model: plain Tab reaches only text fields and pop-up selects; Alt+Tab reaches
  // buttons, links and checkboxes too. Use the key that visits every control, so the check means the same in both engines.
  const tab = t.browser === 'webkit' ? 'Alt+Tab' : 'Tab';
  if (plan.hasBefore) await page.locator('[data-g-kb="before"]').focus();
  else await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press(tab);
  const entered = await where();
  await page.locator('[data-g-kb="last"]').focus();
  await page.keyboard.press(tab);
  const exited = await where();
  t.metric('tabKey', tab);
  t.assert(entered.inView, `Tab from the control before the view lands inside it (landed on ${entered.el}; first tabbable inside: ${plan.first})`);
  t.assert(!exited.inView, `Tab from the view's last control (${plan.last}) leaves the view (landed on ${exited.el})`);
  const visible = await page.evaluate(() => { const el = document.activeElement; const s = el && getComputedStyle(el); return !!s && (s.outlineStyle !== 'none' || s.boxShadow !== 'none'); });
  return `${plan.inside} tabbable control(s); entered at ${entered.el}, left to ${exited.el}; focus indicator visible=${visible}`;
});

scene('reduced-motion', async (t) => {
  const page = await t.page({ surface: 'panel', reducedMotion: 'reduce' });
  await generated(t, page);
  const running = await page.evaluate((sel) => document.getAnimations().filter((a) => {
    const target = a.effect && a.effect.target;
    const timing = a.effect && a.effect.getComputedTiming();
    return target && target.closest && target.closest(sel) && a.playState === 'running' && timing && (timing.duration || 0) > 0 && timing.iterations === Infinity;
  }).length, GENERATED);
  t.assert(running === 0, 'no looping animation inside the generated view under reduced motion', { running });
  return 'no looping animation under prefers-reduced-motion';
});

scene('axe', async (t) => {
  const page = await t.page({ surface: 'panel' });
  await generated(t, page);
  const violations = await axe(page, `#rafii-panel ${GENERATED}`);
  t.assert(violations.length === 0, 'axe: no serious/critical violations in the generated view', violations);
  return 'axe: 0 serious/critical';
});

scene('locales', async (t) => {
  const done = [];
  for (const locale of ['en-US', 'zh-HK', 'zh-CN']) {
    const page = await t.page({ surface: 'panel', locale });
    const { region } = await generated(t, page);
    t.assert(await noRawDsl(region), `${locale}: no raw DSL`);
    const lang = await page.evaluate(() => document.documentElement.lang);
    done.push(`${locale}→lang=${lang}`);
    await page.context().close();   // free the whole context before the next locale (WebKit lost pages when contexts piled up)
  }
  return done.join(', ');
});

scene('history-reload-zero-attempts', async (t) => {
  const page = await t.page({ surface: 'panel' });
  const log = track(page);
  await generated(t, page);
  const before = await providerStats(t);
  const since = Date.now();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await openPanel(t, page);
  try {
    await page.locator(`#rafii-panel ${GENERATED}`).last().waitFor({ state: 'attached', timeout: 60000 });
  } catch {
    blocked('lane F: the generated view did not come back from history after reload');
  }
  await page.waitForTimeout(3000);
  const after = await providerStats(t);
  const creates = uiRequests(log, since).filter((e) => e.method === 'POST' && /\/presentations$/.test(new URL(e.url).pathname));
  t.assert(after === before, 'reload made zero provider requests', { before, after });
  t.assert(creates.length === 0, 'reload never POSTed a new presentation', creates.map((c) => c.url));
  return 'reload: provider delta 0, no new presentation';
});

scene('scope-switch-aborts', async (t) => {
  // A real in-app switch: this principal also belongs to a second workspace (real invitation), the generation of the first
  // is slowed, and the sidebar's workspace menu (components/layout/workspace-switcher.tsx) switches mid-stream.
  let second;
  try {
    second = await t.joinSecondWorkspace('editor');
  } catch (error) {
    blocked(`harness: could not give the principal a second workspace through invitations (${String(error.message).slice(0, 120)})`);
  }
  const page = await t.page({ surface: 'panel' });
  const log = track(page);
  await arm(t, 'slow', 1);
  await generated(t, page, { wait: 'none' });
  const first = t.workspaceId;
  const trigger = page.locator('[data-sidebar="menu-button"]').filter({ hasText: /owner/i }).first();
  if (!(await trigger.count())) blocked('app: the sidebar workspace menu is not reachable on this page/viewport');
  await trigger.click();
  const target = page.getByRole('menuitem').filter({ hasText: /editor/i }).first();
  await target.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {});   // the menu renders its items after opening
  if (!(await target.count())) blocked('app: the second workspace is not listed in the workspace menu');
  const since = Date.now();
  await target.click();
  await page.waitForTimeout(4000);
  const previous = (e) => new URL(e.url).pathname.includes(`/api/workspaces/${first}/agent/ui/`);
  const stale = log.filter((e) => e.kind === 'request' && e.at >= since + 300 && previous(e));
  const aborted = log.filter((e) => e.kind === 'failed' && e.at >= since - 100 && previous(e));
  const shown = await page.locator(`[data-rafii-generated][data-artifact-id]`).count();
  t.assert(stale.length === 0, 'no request to the previous workspace after the switch', stale.map((e) => new URL(e.url).pathname));
  t.metric('abortedPreviousScopeRequests', aborted.length);
  return `switched to ${second.workspaceId.slice(0, 8)}; ${aborted.length} in-flight UI request(s) aborted; 0 later requests to the old scope; views shown after switch: ${shown}`;
});

scene('hidden-no-polling', async (t) => {
  const page = await t.page({ surface: 'panel' });
  const log = track(page);
  await generated(t, page);
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const since = Date.now();
  await page.waitForTimeout(35000);   // longer than the 30 s minimum refresh
  const polled = uiRequests(log, since).filter((e) => /\/(queries|events)/.test(new URL(e.url).pathname));
  t.assert(polled.length === 0, 'a hidden view makes no query/replay requests', polled.map((e) => e.url));
  return '35 s hidden: 0 UI requests';
});

scene('native-fallback', async (t) => {
  const page = await t.page({ surface: 'panel' });
  await arm(t, 'unknown_component', 3);
  const composer = await openPanel(t, page);
  await composer.fill(ELIGIBLE);
  await composer.press('Enter');
  const answer = page.locator('#rafii-panel article[aria-label="Rafii\'s answer"]').last();
  await answer.waitFor({ timeout: 120000 });
  await page.waitForTimeout(8000);
  await arm(t, null);
  const host = page.locator('#rafii-panel [data-rafii-generated-host]').last();
  const region = page.locator(`#rafii-panel ${GENERATED}`).last();
  if (!(await host.count()) && !(await region.count())) blocked('lane F: no generated host/region mounted (failure path cannot be told apart from not mounted)');
  t.assert(await answer.isVisible(), 'the native answer stays visible after a failed generation');
  t.assert(await noRawDsl((await region.count()) ? region : host), 'no raw DSL or error dump in the fallback');
  if (await region.count()) {
    const state = await region.getAttribute('data-generation-state');
    t.assert(state === 'failed', 'the region reports data-generation-state="failed" (lane C frame contract)', { state });
    t.assert((await region.locator('[data-genui]').count()) === 0, 'no generated component is rendered from rejected source');
  }
  const errorOverlay = await page.locator('nextjs-portal, [data-nextjs-dialog]').count();
  t.assert(errorOverlay === 0, 'no framework error overlay');
  return 'native answer kept; fallback without DSL';
});

scene('no-auto-writes', async (t) => {
  const page = await t.page({ surface: 'panel' });
  const log = track(page);
  await generated(t, page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await openPanel(t, page);
  await page.waitForTimeout(4000);
  const writes = uiRequests(log).filter((e) => e.method === 'POST' && /\/actions(\/activate)?$/.test(new URL(e.url).pathname));
  t.assert(writes.length === 0, 'mount, render, replay and reload issue no action/activation request', writes.map((w) => w.url));
  return 'mount/replay/reload: 0 action requests';
});

scene('xss', async (t) => {
  const page = await t.page({ surface: 'panel' });
  let dialogs = 0;
  page.on('dialog', async (d) => { dialogs += 1; await d.dismiss(); });
  await arm(t, 'xss', 1);
  const { region } = await generated(t, page);
  const injected = await region.locator('img[src="x"], script, iframe').count();
  const jsLinks = await region.locator('a[href^="javascript:"]').count();
  t.assert(dialogs === 0, 'no script ran from generated props');
  t.assert(injected === 0 && jsLinks === 0, 'markup in props renders as inert text, no javascript: link', { injected, jsLinks });
  return 'markup inert; no dialog; no javascript: link';
});

scene('viewports', async (t) => {
  const out = [];
  for (const vp of t.viewports) {
    const page = await t.page({ surface: vp.surface, viewport: { width: vp.width, height: vp.height }, mobile: vp.width < 768 });
    const { region } = await generated(t, page);
    const fits = await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1);
    const box = await region.boundingBox();
    t.assert(fits, `${vp.id}: no sideways page scroll`);
    t.assert(!box || box.width <= vp.width + 1, `${vp.id}: generated view fits the viewport width`, box);
    out.push(`${vp.id}✓`);
    await page.context().close();   // one live context at a time (WebKit lost pages when five contexts piled up)
  }
  return `${out.join(' ')} (emulation)`;
});

scene('local-interaction-p95', async (t) => {
  const page = await t.page({ surface: 'panel' });
  const { region } = await generated(t, page);
  const input = await firstInput(region);
  const tab = region.getByRole('tab').first();
  const target = input || ((await tab.count()) ? tab : null);
  if (!target) blocked('lane C/E: no local control (input or tab) in the generated view to time');
  await target.click();
  const samples = [];
  for (let i = 0; i < 110; i += 1) {
    const t0 = await page.evaluate(() => performance.now());
    if (input) await page.keyboard.type(String(i % 10));
    else await target.click();
    const t1 = await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now())))));
    if (i >= 10) samples.push(t1 - t0);   // first 10 are warm-up
  }
  samples.sort((a, b) => a - b);
  const p95 = samples[Math.floor(samples.length * 0.95) - 1];
  t.metric('localInteractionP95Ms', p95);
  t.assert(p95 <= 200, 'local interaction p95 ≤ 200 ms over 100 warm actions', { p95 });
  return `p95 ${p95.toFixed(1)} ms over ${samples.length} warm actions (same runner)`;
});

scene('devtools-not-shipped', async (t) => {
  const page = await t.page({ surface: 'panel' });
  const scripts = [];
  page.on('response', async (r) => {
    if (/\.js(\?|$)/.test(r.url()) && r.ok()) scripts.push(r);
  });
  const log = track(page);
  await openPanel(t, page);
  await page.waitForTimeout(2000);
  let hits = 0;
  for (const r of scripts) {
    const body = await r.text().catch(() => '');
    if (body.includes('cdn.jsdelivr.net/npm/@openuidev/devtools')) hits += 1;
  }
  const cdn = log.filter((e) => e.url.includes('cdn.jsdelivr.net'));
  t.assert(hits === 0, 'no shipped chunk references the OpenUI devtools CDN', { hits });
  t.assert(cdn.length === 0, 'no request to cdn.jsdelivr.net', cdn.map((c) => c.url));
  return `${scripts.length} chunks scanned; devtools URL absent`;
});

module.exports = { SCENES, Blocked };
