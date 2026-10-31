/**
 * Note Garden browser journey (local server only; no accounts, no providers, no network beyond the local origin).
 * Run against `next start` or `next dev`: RAFII_NOTE_GARDEN_URL=http://127.0.0.1:3117 node tests/music-game-browser.cjs
 * Optional NOTE_GARDEN_SHOTS=<dir> saves phone, tablet and desktop screenshots.
 */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_NOTE_GARDEN_URL || 'http://127.0.0.1:3117';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local server only');
const origin = new URL(base).origin;
const route = `${base}/play/note-garden`;
const shots = process.env.NOTE_GARDEN_SHOTS;
if (shots) fs.mkdirSync(shots, { recursive: true });
const axeSource = fs.readFileSync(path.join(__dirname, '../node_modules/axe-core/axe.min.js'), 'utf8');
const KEY = 'rafii.noteGarden.v1';
const report = { requests: 0, offOrigin: [], consoleErrors: [], axe: [], checks: [] };
const pass = (name) => { report.checks.push(name); console.log(`ok - ${name}`); };

async function newPage(browser, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ...options });
  // Count AudioContext construction so we can prove it only happens after a gesture.
  await context.addInitScript(() => {
    window.__audioContexts = 0;
    const Real = window.AudioContext;
    if (Real) window.AudioContext = class extends Real { constructor(...args) { super(...args); window.__audioContexts++; window.__ctx = this; } };
    // Loudness probe (DESIGN §9, -6 dBFS): an AnalyserNode on whatever feeds the speakers, i.e. after the limiter.
    window.__peak = 0;
    const connect = AudioNode.prototype.connect;
    AudioNode.prototype.connect = function (target, ...rest) {
      if (target instanceof AudioDestinationNode && !this.__tapped) {
        this.__tapped = true;
        const analyser = this.context.createAnalyser();
        analyser.fftSize = 2048;
        connect.call(this, analyser);
        const buffer = new Float32Array(2048);
        setInterval(() => {
          analyser.getFloatTimeDomainData(buffer);
          for (const v of buffer) if (Math.abs(v) > window.__peak) window.__peak = Math.abs(v);
        }, 10);
      }
      return connect.call(this, target, ...rest);
    };
    // Log every oscillator on the audio clock: when it was started, the stop first asked for, and the latest stop.
    window.__oscLog = [];
    const proto = window.AudioScheduledSourceNode?.prototype;
    if (proto) {
      const start = proto.start;
      const stop = proto.stop;
      proto.start = function (when = 0, ...rest) {
        this.__rec = { calledAt: this.context.currentTime, startAt: when, firstStop: Infinity, stopAt: Infinity };
        window.__oscLog.push(this.__rec);
        return start.call(this, when, ...rest);
      };
      proto.stop = function (when = 0) {
        if (this.__rec) {
          if (this.__rec.firstStop === Infinity) this.__rec.firstStop = when;
          this.__rec.stopAt = Math.min(this.__rec.stopAt, when || this.context.currentTime);
        }
        return stop.call(this, when);
      };
    }
  });
  const page = await context.newPage();
  page.on('request', (request) => {
    const url = request.url();
    report.requests++;
    if (!url.startsWith('data:') && !url.startsWith('blob:') && new URL(url).origin !== origin) report.offOrigin.push(url);
  });
  page.on('console', (message) => { if (message.type() === 'error') report.consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => report.consoleErrors.push(error.message));
  return { context, page };
}

/** Let short entrance fades and pops finish, or axe and screenshots catch half-transparent frames. */
async function settle(page) {
  await page.evaluate(() => Promise.all(document.getAnimations().filter((a) => a.effect.getComputedTiming().duration <= 1000).map((a) => a.finished.catch(() => {}))));
}

async function shoot(page, name, fullPage = false) {
  if (!shots) return;
  await settle(page);
  await page.screenshot({ path: path.join(shots, name), fullPage });
}

async function axe(page, label) {
  await settle(page);
  await page.addScriptTag({ content: axeSource });
  const result = await page.evaluate(async () => {
    const { violations } = await window.axe.run(document, { resultTypes: ['violations'] });
    return violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => n.target.join(' ')).slice(0, 3) }));
  });
  const blocking = result.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  report.axe.push({ screen: label, violations: result });
  assert.deepEqual(blocking, [], `axe serious/critical on ${label}: ${JSON.stringify(blocking)}`);
}

/** Press Tab until the focused element's accessible text matches, then return. Keyboard only. */
async function tabTo(page, pattern, max = 40, key = 'Tab') {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press(key);
    const text = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return '';
      if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
      const copy = el.cloneNode(true);
      for (const hidden of copy.querySelectorAll('[aria-hidden="true"]')) hidden.remove();
      return (copy.textContent || '').trim();
    });
    if (pattern.test(text)) return text;
  }
  throw new Error(`Could not Tab to ${pattern}`);
}

/** Mark the audio clock, run `action`, then check every oscillator started before the mark was cut short. */
async function supersedes(page, action, label) {
  const mark = await page.evaluate(() => window.__ctx.currentTime);
  const before = await page.evaluate(() => window.__oscLog.length);
  await action();
  await page.waitForTimeout(100);
  const result = await page.evaluate(({ mark, before }) => {
    const old = window.__oscLog.slice(0, before);
    return {
      old: old.length,
      wouldHaveRungOn: old.filter((r) => r.firstStop > mark + 0.2).length,
      stillRinging: old.filter((r) => r.stopAt > mark + 0.25).map((r) => [r.calledAt, r.stopAt]),
      started: window.__oscLog.length - before
    };
  }, { mark, before });
  assert.ok(result.wouldHaveRungOn > 0, `${label}: earlier sound was still due to play (test is meaningful)`);
  assert.deepEqual(result.stillRinging, [], `${label}: earlier oscillators stopped within the fade`);
  return result;
}

const answers = (page) => page.getByRole('group', { name: 'Answers' }).getByRole('button');
const nextButton = (page) => page.getByRole('button', { name: 'Next', exact: true });
const heading = (page) => page.locator('h1');
const counterText = (page) => page.evaluate(() => [...document.querySelectorAll('nav p')].map((p) => p.textContent).join());

/** After Next: wait until the question counter changes or the round is over. */
async function afterNext(page, before) {
  await page.waitForFunction((prev) => [...document.querySelectorAll('nav p')].map((p) => p.textContent).join() !== prev, before);
}

async function waitForOpenAnswer(page) {
  await page.waitForFunction(
    () => {
      const group = document.querySelector('[aria-label="Answers"]');
      return group?.getAttribute('aria-busy') !== 'true' && [...group.querySelectorAll('button')].some((b) => !b.disabled);
    },
    null,
    { timeout: 15000 }
  );
}

const dbfs = (v) => (v > 0 ? 20 * Math.log10(v) : -Infinity);
async function peakSince(page, reset) {
  if (reset) return page.evaluate(() => (window.__peak = 0));
  return dbfs(await page.evaluate(() => window.__peak));
}

/** Keyboard: Tab from the focused prompt to the first open answer, Enter; keep going until Next, then Enter. */
async function answerByKeyboard(page, { fromPrompt = true } = {}) {
  await waitForOpenAnswer(page);
  if (fromPrompt) {
    assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'H2', 'focus starts on the question prompt');
    await page.keyboard.press('Tab');
  }
  for (let tries = 0; tries < 4; tries++) {
    await page.keyboard.press('Enter');
    // Either the question is settled (Next has focus) or it was "try again" (focus is back on an open option).
    const outcome = await page
      .waitForFunction(() => {
        const el = document.activeElement;
        if (el?.textContent?.trim() === 'Next') return 'next';
        if (el?.closest('[aria-label="Answers"]') && !el.disabled) return 'try-again';
        return false;
      }, null, { timeout: 8000 })
      .catch(async (error) => {
        const state = await page.evaluate(() => ({
          active: `${document.activeElement?.tagName}:${document.activeElement?.textContent?.trim().slice(0, 40)}`,
          answers: [...document.querySelectorAll('[aria-label="Answers"] button')].map((x) => x.textContent.trim() + (x.disabled ? ' (disabled)' : ''))
        }));
        throw new Error(`no answer outcome after Enter: ${JSON.stringify(state)} (${error.message})`);
      });
    if ((await outcome.jsonValue()) === 'next') break;
  }
  await nextButton(page).waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.textContent?.trim()), 'Next', 'focus moves to Next');
  // Screen readers that only speak the focused button still hear the feedback: Next is described by it.
  const described = await page.evaluate(() => {
    const id = document.activeElement?.getAttribute('aria-describedby');
    return id ? document.getElementById(id)?.textContent?.trim() : '';
  });
  assert.ok(described && described.length > 3, 'Next is described by the feedback text');
  const before = await counterText(page);
  await page.keyboard.press('Enter');
  await afterNext(page, before);
}

/** Mouse or touch: click/tap the first open answer until Next appears. */
async function answerByPointer(page, touch) {
  await waitForOpenAnswer(page);
  for (let tries = 0; tries < 4 && !(await nextButton(page).isVisible()); tries++) {
    const open = page.locator('[aria-label="Answers"] button:not([disabled])').first();
    if (touch) await open.tap();
    else await open.click();
  }
  const before = await counterText(page);
  if (touch) await nextButton(page).tap();
  else await nextButton(page).click();
  await afterNext(page, before);
}

async function playLevel(page, title, how, shot) {
  const bed = page.getByRole('button', { name: new RegExp(title.replace(/[?]/g, '\\?')) });
  if (how === 'touch') await bed.tap();
  else await bed.click();
  const letsPlay = page.getByRole('button', { name: "Let's play" });
  if (how === 'touch') await letsPlay.tap();
  else await letsPlay.click();
  let count = 0;
  while (await page.getByText(/^Question \d+ of \d+$/).isVisible().catch(() => false)) {
    if (count === 0 && shot) await shot();
    await answerByPointer(page, how === 'touch');
    count++;
    if (count > 10) throw new Error('level did not finish');
  }
  await heading(page).filter({ hasText: /Amazing|Great work|You finished/ }).waitFor();
  return count;
}

async function targetsAtLeast48(page, label) {
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('button, a[href], label')]
      .filter((el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden' && !el.closest('dialog:not([open])'))
      .map((el) => ({ text: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30), w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height }))
      .filter((r) => r.w < 48 || r.h < 48)
  );
  assert.deepEqual(small, [], `targets under 48px on ${label}`);
}

async function stored(page) {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key) || 'null'), KEY);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    // 1. Desktop, keyboard only: load, finish level 1, mute, reset.
    const { context, page } = await newPage(browser);
    const response = await page.goto(route);
    assert.equal(response.status(), 200);
    await heading(page).filter({ hasText: 'Note Garden' }).waitFor();
    pass('AC1 /play/note-garden returns 200 without sign-in');
    assert.equal(await page.evaluate(() => window.__audioContexts), 0, 'no AudioContext before a gesture');
    await axe(page, 'title');
    await targetsAtLeast48(page, 'title');
    await shoot(page, 'desktop-1-title.png');

    await tabTo(page, /^Play$/);
    await page.keyboard.press('Enter');
    await heading(page).filter({ hasText: "Hi! I'm Pip" }).waitFor();
    await tabTo(page, /^Let's go$/);
    await page.keyboard.press('Enter');
    await heading(page).filter({ hasText: 'Pick a garden bed!' }).waitFor();
    assert.equal(await page.evaluate(() => window.__audioContexts), 1, 'one AudioContext, created by the Let\'s go key press');
    pass('AC3 AudioContext created only after a user gesture');
    await axe(page, 'map');
    await targetsAtLeast48(page, 'map');
    assert.equal(await page.getByRole('button', { name: /Note Names/ }).isDisabled(), true, 'level 2 starts locked');
    await shoot(page, 'desktop-2-map.png');

    await tabTo(page, /High or Low\?/);
    await page.keyboard.press('Enter');
    await heading(page).filter({ hasText: 'Level 1: High or Low?' }).waitFor();
    await axe(page, 'learn L1');
    await tabTo(page, /^Let's play$/);
    await page.keyboard.press('Enter');
    let questions = 0;
    while (await page.getByText(/^Question \d+ of 6$/).isVisible().catch(() => false)) {
      if (questions === 0) {
        await waitForOpenAnswer(page);
        await axe(page, 'question');
        await targetsAtLeast48(page, 'question');
        await shoot(page, 'desktop-3-question.png');
        // Help me: focus stays on the button and the hint is announced through the status region.
        await tabTo(page, /^Help me$/);
        await page.keyboard.press('Enter');
        await page.getByRole('status').filter({ hasText: "Let's listen slowly." }).waitFor();
        assert.equal(await page.evaluate(() => document.activeElement?.textContent?.replace(/[^A-Za-z ]/g, '').trim()), 'Help me', 'focus stays on Help me');
        await axe(page, 'question with hint');
        await tabTo(page, /^(Same|Different)$/, 10, 'Shift+Tab');
        await answerByKeyboard(page, { fromPrompt: false });
        pass('M1/M2 Help me keeps focus and the hint is announced');
        questions++;
        continue;
      }
      await answerByKeyboard(page);
      questions++;
      assert.ok(questions <= 6);
    }
    assert.equal(questions, 6);
    await heading(page).filter({ hasText: /Amazing|Great work|You finished/ }).waitFor();
    await axe(page, 'level done');
    const afterL1 = await stored(page);
    assert.equal(afterL1.done['1'], true);
    assert.ok(afterL1.best['1'] >= 1);
    await shoot(page, 'desktop-4-level-done.png');
    pass('AC2/AC6 level 1 completed with the keyboard only (6 questions), progress saved locally');

    await tabTo(page, /^Garden map$/);
    await page.keyboard.press('Enter');
    assert.equal(await page.getByRole('button', { name: /Note Names/ }).isDisabled(), false, 'level 2 unlocked');
    await tabTo(page, /^Grown-ups$/);
    await page.keyboard.press('Enter');
    await heading(page).filter({ hasText: 'For grown-ups' }).waitFor();
    await axe(page, 'grown-ups');
    await targetsAtLeast48(page, 'grown-ups');
    const soundToggle = page.getByRole('button', { name: /^Sound (on|off)$/ });
    assert.equal(await soundToggle.getAttribute('aria-pressed'), 'true');
    assert.equal((await soundToggle.textContent()).replace(/[^A-Za-z ]/g, '').trim(), 'Sound on');
    await tabTo(page, /^Sound on$/);
    await page.keyboard.press('Enter');
    assert.equal(await soundToggle.getAttribute('aria-pressed'), 'false');
    assert.equal((await soundToggle.textContent()).replace(/[^A-Za-z ]/g, '').trim(), 'Sound off', 'state is visible as text');
    assert.equal((await stored(page)).muted, true);
    pass('AC6 mute toggled by keyboard and persisted');

    await tabTo(page, /^Reset progress$/);
    await page.keyboard.press('Enter');
    await page.getByRole('dialog').waitFor();
    await axe(page, 'reset dialog');
    await tabTo(page, /^Delete$/, 4);
    await page.keyboard.press('Enter');
    await page.getByRole('status').filter({ hasText: 'Progress deleted' }).waitFor();
    const afterReset = await stored(page);
    assert.deepEqual(afterReset.best, { 1: 0, 2: 0, 3: 0, 4: 0 });
    assert.deepEqual(afterReset.done, { 1: false, 2: false, 3: false, 4: false });
    assert.equal(afterReset.muted, true, 'the sound choice survives a reset');
    await tabTo(page, /^Back$/);
    await page.keyboard.press('Enter');
    await heading(page).filter({ hasText: 'Pick a garden bed!' }).waitFor();
    assert.equal(await page.getByRole('button', { name: /Note Names/ }).isDisabled(), true, 'level 2 locked again');
    pass('AC4/AC6 reset progress deletes stars and relocks levels');

    // Muted play still works with pictures.
    await page.getByRole('button', { name: /High or Low\?/ }).click();
    await page.getByRole('button', { name: "Let's play" }).click();
    await page.getByText('Sound is off. Here is a picture of the sound.').waitFor();
    await page.getByRole('img', { name: /Picture of the sound/ }).waitFor();
    await waitForOpenAnswer(page);
    pass('AC3 muted questions show a picture of the sound and stay answerable');
    await page.getByRole('button', { name: 'Back' }).click();
    await page.getByRole('button', { name: 'Leave' }).click();
    await context.close();

    // 2. Mouse (L2, L3) and touch (L4) on all levels, sound on. Grown-ups opens all levels.
    const desktop = await newPage(browser);
    await desktop.page.goto(route);
    await desktop.page.getByRole('button', { name: 'Grown-ups' }).click();
    await desktop.page.getByRole('button', { name: 'Open all levels' }).click();
    await desktop.page.getByRole('button', { name: 'Open', exact: true }).click();
    assert.equal((await stored(desktop.page)).allOpen, true);
    await desktop.page.getByRole('button', { name: 'Back', exact: true }).click();
    await desktop.page.getByRole('button', { name: 'Play' }).click();
    await desktop.page.getByRole('button', { name: "Let's go" }).click();
    // Overlap guard: replaying mid-sound and leaving mid-sound never leave earlier notes ringing.
    await desktop.page.getByRole('button', { name: /High or Low\?/ }).click();
    await desktop.page.getByRole('button', { name: "Let's play" }).click();
    await desktop.page.waitForFunction(() => window.__oscLog.length > 0);
    // First-play lock: answers look normal and stay enabled, the group is busy, a "Listen…" cue shows, taps are ignored.
    const group = desktop.page.getByRole('group', { name: 'Answers' });
    assert.equal(await group.getAttribute('aria-busy'), 'true');
    // (Playwright treats aria-disabled as disabled, so read the DOM property and force the tap.)
    assert.equal(await answers(desktop.page).first().evaluate((b) => b.disabled || getComputedStyle(b).opacity !== '1'), false, 'not greyed out while listening');
    await desktop.page.getByText('Listen…').waitFor();
    await answers(desktop.page).first().click({ force: true });
    assert.equal(await desktop.page.getByText('Tried').count(), 0, 'a tap while listening is not an answer');
    assert.equal(await nextButton(desktop.page).count(), 0);
    pass('M7 first sound: answers keep their look, Listen… cue, aria-busy, taps ignored');
    await peakSince(desktop.page, true);
    const replay = await supersedes(desktop.page, () => desktop.page.getByRole('button', { name: 'Hear it again' }).click(), 'replay');
    assert.ok(replay.started > 0, 'the replay itself plays');
    // A child mashing "Hear it again", then answering and going straight on: the worst overlap case.
    for (let i = 0; i < 5; i++) {
      await desktop.page.getByRole('button', { name: 'Hear it again' }).click();
      await desktop.page.waitForTimeout(120);
    }
    await waitForOpenAnswer(desktop.page);
    while (!(await nextButton(desktop.page).isVisible())) await desktop.page.locator('[aria-label="Answers"] button:not([disabled])').first().click();
    await nextButton(desktop.page).click();
    await desktop.page.waitForTimeout(250);
    await supersedes(
      desktop.page,
      async () => {
        await desktop.page.getByRole('button', { name: 'Back' }).click();
        await desktop.page.getByRole('button', { name: 'Leave' }).click();
      },
      'leave level'
    );
    pass('AC3 a replay or leaving cancels earlier sound (one schedule at a time)');
    await desktop.page.waitForTimeout(500);
    const mashPeak = await peakSince(desktop.page);
    // Longest and densest sounds: the L3 learn card's whole note, then two eighth notes over clicks.
    await peakSince(desktop.page, true);
    await desktop.page.getByRole('button', { name: /Long and Short/ }).click();
    await desktop.page.getByRole('button', { name: /Whole note/ }).click();
    await desktop.page.waitForTimeout(3300);
    await desktop.page.getByRole('button', { name: /Two eighth notes/ }).click();
    await desktop.page.getByRole('button', { name: /Quarter note/ }).click();
    await desktop.page.waitForTimeout(1500);
    const learnPeak = await peakSince(desktop.page);
    report.loudness = { mashReplayAnswerNext_dBFS: +mashPeak.toFixed(1), learnL3_dBFS: +learnPeak.toFixed(1) };
    assert.ok(Number.isFinite(mashPeak) && Number.isFinite(learnPeak), 'sound was actually measured');
    assert.ok(mashPeak <= -6, `replay mash + answer + next peaked at ${mashPeak.toFixed(1)} dBFS (limit -6)`);
    assert.ok(learnPeak <= -6, `L3 learn sounds peaked at ${learnPeak.toFixed(1)} dBFS (limit -6)`);
    pass(`M3 loudness after the limiter: mash ${mashPeak.toFixed(1)} dBFS, L3 learn ${learnPeak.toFixed(1)} dBFS (limit -6)`);
    await desktop.page.getByRole('button', { name: 'Back', exact: true }).click();
    assert.equal(await playLevel(desktop.page, 'Note Names', 'mouse'), 8);
    await desktop.page.getByRole('button', { name: 'Garden map' }).click();
    assert.equal(
      await playLevel(desktop.page, 'Long and Short', 'mouse', async () => {
        await shoot(desktop.page, 'desktop-5-long-and-short.png');
      }),
      6
    );
    await axe(desktop.page, 'level 3 done');
    pass('AC2 levels 2 and 3 completed with the mouse');
    await desktop.context.close();

    const phone = await newPage(browser, { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 });
    await phone.page.goto(route);
    await shoot(phone.page, 'phone-1-title.png');
    await phone.page.getByRole('button', { name: 'Grown-ups' }).tap();
    await phone.page.getByRole('button', { name: 'Open all levels' }).tap();
    await phone.page.getByRole('button', { name: 'Open', exact: true }).tap();
    await phone.page.getByRole('button', { name: 'Back', exact: true }).tap();
    await phone.page.getByRole('button', { name: 'Play' }).tap();
    await phone.page.getByRole('button', { name: "Let's go" }).tap();
    await shoot(phone.page, 'phone-2-map.png', true);
    await targetsAtLeast48(phone.page, 'phone map');
    assert.equal(
      await playLevel(phone.page, 'Step or Skip', 'touch', async () => {
        await waitForOpenAnswer(phone.page);
        await phone.page.getByRole('button', { name: 'Help me' }).tap();
        const hintBox = await phone.page.getByRole('status').filter({ hasText: /\w/ }).locator('p').boundingBox();
        assert.ok(hintBox && hintBox.y >= 0 && hintBox.y + hintBox.height <= 844 + 1, `hint scrolled into view on phone (${JSON.stringify(hintBox)})`);
        pass('M2 hint scrolls into view on a phone');
        await targetsAtLeast48(phone.page, 'phone question');
        await axe(phone.page, 'phone question');
        await shoot(phone.page, 'phone-3-step-or-skip.png', true);
      }),
      6
    );
    await shoot(phone.page, 'phone-4-level-done.png', true);
    pass('AC2 level 4 completed by touch on a phone viewport');
    await phone.context.close();

    if (shots) {
      const tablet = await newPage(browser, { viewport: { width: 768, height: 1024 } });
      await tablet.page.goto(route);
      await tablet.page.getByRole('button', { name: 'Play' }).click();
      await tablet.page.getByRole('button', { name: "Let's go" }).click();
      await tablet.page.getByRole('button', { name: /High or Low\?/ }).click();
      await shoot(tablet.page, 'tablet-1-learn-card.png');
      await tablet.context.close();
    }

    // 3. Reduced motion: no looping or entrance animation.
    for (const reducedMotion of ['reduce', 'no-preference']) {
      const motion = await newPage(browser, { reducedMotion });
      await motion.page.goto(route);
      const name = await motion.page.evaluate(() => getComputedStyle(document.querySelector('main svg')).animationName);
      if (reducedMotion === 'reduce') assert.equal(name, 'none', 'Pip does not bob with reduced motion');
      else assert.notEqual(name, 'none', 'Pip bobs gently by default');
      await motion.context.close();
    }
    pass('AC8 prefers-reduced-motion respected');

    assert.deepEqual(report.offOrigin, [], 'every request stays on the local origin');
    pass(`AC4 ${report.requests} requests, 0 off-origin`);
    assert.deepEqual(report.consoleErrors, [], 'no console errors');
    pass('AC6 0 console errors');
    console.log(JSON.stringify({ loudness: report.loudness, requests: report.requests, offOrigin: report.offOrigin.length, consoleErrors: report.consoleErrors.length, axeScreens: report.axe.length, moderateOrMinor: report.axe.flatMap((s) => s.violations.map((v) => `${s.screen}:${v.id}:${v.impact}`)) }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  console.error(JSON.stringify({ offOrigin: report.offOrigin, consoleErrors: report.consoleErrors }, null, 1));
  process.exit(1);
});
