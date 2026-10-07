'use strict';
// Creates a temporary local-only Next page. Never sends a conversation, authenticates,
// publishes, or writes workspace data. The fixture route is removed in finally.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const web = path.resolve(__dirname, '..');
const route = path.join(web, 'src/app/preview-window-acceptance');
const evidence = process.env.PREVIEW_EVIDENCE_DIR || '/tmp/preview-window-evidence';
const url = 'http://127.0.0.1:3129/preview-window-acceptance';
assert.ok(!fs.existsSync(route), 'Refusing to overwrite an existing route');
fs.mkdirSync(route);
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(route, 'page.tsx'), `
'use client';
import { useState } from 'react';
import { PreviewWindow } from '@/components/application/post-preview/preview-window';
export default function Fixture() {
  const [active, setActive] = useState(true);
  return <main id='main-content'>
    <header style={{position:'sticky',top:0,height:60,zIndex:20,background:'white'}}>Preview interaction fixture</header>
    <div data-conversation-layout style={{display:'grid',gridTemplateColumns:'minmax(0,1fr) 336px',gap:24,padding:24}}>
      <div><h1>Conversation scroll fixture</h1>{Array.from({length:60},(_,i)=><p key={i} style={{height:50}}>Conversation turn {i+1}</p>)}</div>
      <aside><div style={{position:'sticky',top:72}}>
        <button data-test-preview onClick={()=>setActive(true)}>Preview tab</button>
        <button data-test-sources onClick={()=>setActive(false)}>Sources tab</button>
        <PreviewWindow active={active} available label='Threads · English' onDock={()=>setActive(true)}>
          {(scale)=><div data-test-preview-content><input aria-label='State probe' defaultValue='Retained draft'/><div style={{width:393*scale,height:852*scale,border:'8px solid',borderRadius:36}}>Actual PreviewWindow, isolated content fixture</div></div>}
        </PreviewWindow>
        {!active && <p data-test-sources-content>Sources remain usable beside the floating preview.</p>}
      </div></aside>
    </div>
  </main>;
}
`);
const log = fs.openSync(path.join(evidence, 'next-dev.log'), 'w');
const server = spawn(process.execPath, [require.resolve('next/dist/bin/next'), 'dev', '--hostname', '127.0.0.1', '-p', '3129'], {
  cwd: web, env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1', NEXT_PUBLIC_SENTRY_DISABLED: '1' }, stdio: ['ignore', log, log]
});
const results = [];
let browser;
async function waitForServer() {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error('Next server exited before acceptance testing');
    try { const response = await fetch(url, { signal: AbortSignal.timeout(15000) }); if (response.ok) return; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error('Local fixture did not become ready');
}
(async () => {
  try {
    await waitForServer();
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(url);
    const panel = page.locator('[data-preview-window]');
    await panel.waitFor({ state: 'visible' });
    const handle = page.locator('[data-preview-drag-handle]');
    async function settle() { await page.waitForTimeout(300); }
    async function mode(expected) {
      await page.waitForFunction((value) => document.querySelector('[data-preview-window]')?.getAttribute('data-mode') === value, expected);
    }
    async function bounded() {
      const rect = await panel.boundingBox(); const viewport = page.viewportSize();
      assert.ok(rect && rect.x >= 0 && rect.y >= 60);
      assert.ok(rect.x + rect.width <= viewport.width + 1 && rect.y + rect.height <= viewport.height + 1);
      return rect;
    }
    async function moveHandle(x, y, release = true) {
      const grip = await handle.boundingBox();
      await page.mouse.move(grip.x + 30, grip.y + 20); await page.mouse.down();
      await page.mouse.move(x, y, { steps: 12 });
      if (release) await page.mouse.up();
      await settle();
    }
    await page.getByRole('textbox', { name: 'State probe' }).fill('State survives docking');
    await page.evaluate(() => { window.__previewNode = document.querySelector('[data-test-preview-content]'); });
    await mode('docked');
    await page.mouse.move(350, 500); await page.mouse.wheel(0, 1100); await settle();
    await bounded();
    results.push('docked preview remains visible during conversation scroll');
    await moveHandle(180, 200); await mode('floating');
    const first = await bounded();
    await page.mouse.move(600, 500); await page.mouse.wheel(0, 600); await settle();
    const afterScroll = await bounded();
    assert.ok(Math.abs(first.x - afterScroll.x) < 1 && Math.abs(first.y - afterScroll.y) < 1);
    results.push('drag outside dock stays floating and fixed while scrolling');
    await page.locator('[data-test-sources]').click(); await settle();
    await mode('floating'); assert.ok(await panel.isVisible());
    assert.ok(await page.locator('[data-test-sources-content]').isVisible());
    results.push('Sources selection does not hide or remount a floating preview');
    const beforeResize = await bounded();
    const corner = await page.locator('[data-preview-resize-handle]').boundingBox();
    await page.mouse.move(corner.x + 20, corner.y + 20); await page.mouse.down();
    await page.mouse.move(corner.x - 30, corner.y - 95, { steps: 12 }); await page.mouse.up(); await settle();
    await mode('floating'); assert.ok((await bounded()).width < beforeResize.width);
    results.push('corner resizing decreases proportional size and never docks');
    await moveHandle(250, 230, false);
    const target = await page.locator('[data-preview-dock-target]').boundingBox();
    assert.ok(target);
    await page.mouse.move(target.x + target.width / 2, target.y + 30, { steps: 12 }); await page.mouse.up(); await settle();
    await mode('docked'); await bounded();
    assert.equal(await page.getByRole('textbox', { name: 'State probe' }).inputValue(), 'State survives docking');
    assert.ok(await page.evaluate(() => window.__previewNode === document.querySelector('[data-test-preview-content]')));
    results.push('release inside original dock reattaches the same DOM subtree and selects Preview');
    await panel.getByRole('button', { name: 'Float', exact: true }).click(); await settle(); await mode('floating');
    const beforeCancel = await bounded();
    await moveHandle(320, 300, false); await page.keyboard.press('Escape'); await page.mouse.up(); await settle();
    const afterCancel = await bounded(); await mode('floating');
    assert.ok(Math.abs(beforeCancel.x - afterCancel.x) < 1 && Math.abs(beforeCancel.y - afterCancel.y) < 1);
    results.push('Escape restores the pre-gesture floating position without docking');
    await handle.focus(); await page.keyboard.press('Shift+ArrowLeft'); await mode('floating');
    await page.locator('summary[aria-label="Preview size and position"]').click();
    await panel.getByRole('button', { name: 'Preview size S', exact: true }).click();
    await panel.getByRole('button', { name: 'top left', exact: true }).click(); await settle(); await bounded();
    await page.locator('summary[aria-label="Preview size and position"]').click();
    results.push('keyboard movement and click-based size/corner controls work');
    for (const viewport of [{width:820,height:1180},{width:1180,height:820}]) {
      await page.setViewportSize(viewport); await settle(); await mode('floating'); await bounded();
    }
    results.push('portrait/landscape tablet viewports clamp without auto-docking');
    await page.setViewportSize({width:390,height:844}); await settle(); assert.equal(await panel.isVisible(), false);
    await page.setViewportSize({width:1440,height:1000}); await settle(); await mode('floating');
    assert.ok(await page.evaluate(() => window.__previewNode === document.querySelector('[data-test-preview-content]')));
    results.push('mobile hides the additional window while retaining session state');
    await page.emulateMedia({ reducedMotion: 'reduce' }); await settle();
    await panel.getByRole('button', { name: 'Dock', exact: true }).click(); await mode('docked');
    assert.equal(await panel.evaluate((element) => getComputedStyle(element).transitionProperty), 'none');
    results.push('reduced motion disables movement transitions');
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(evidence, 'preview-docked.png'), fullPage: false });
    fs.writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify({ status: 'PASS', fixture: 'isolated actual PreviewWindow component; not authenticated production', checks: results }, null, 2));
    console.log(JSON.stringify({ status: 'PASS', checks: results }, null, 2));
  } catch (error) {
    fs.writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify({ status: 'FAIL', completed: results, error: String(error) }, null, 2));
    console.error(error); process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM'); fs.closeSync(log);
    fs.rmSync(route, { recursive: true, force: true });
  }
})();
