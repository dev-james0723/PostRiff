/** Actual Channels screen and hosted endpoint on disposable PG. Synthetic identities/providers/status seeds only. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const base = process.env.RAFII_WEB_URL || 'http://127.0.0.1:3386';
assert.equal(new URL(base).hostname, '127.0.0.1');
const localPython = path.join(root, '.venv/bin/python');
const python = process.env.RAFII_FIXTURE_PYTHON || (fs.existsSync(localPython) ? localPython : 'python3');
const out = process.env.RAFII_HISTORY_REPORT_DIR || path.join(root, '.token-pilot/reports/history-import-browser');
const pgPort = process.env.RAFII_HISTORY_PG_PORT || '55836';
fs.mkdirSync(out, { recursive: true });
const principal = randomUUID();
const headers = { 'Content-Type':'application/json', 'X-PostRiff-Request':'founder-alpha', Authorization:'Bearer dev:'+principal, Origin:base };
async function api(method, url, body) {
  const response = await fetch(base+url, { method, headers, ...(body === undefined ? {} : {body:JSON.stringify(body)}) });
  assert.ok(response.ok, `${url} ${response.status}: ${await response.clone().text()}`);
  return response.json();
}
(async () => {
  assert.equal((await api('GET','/api/auth/config')).execution, 'dev-synthetic');
  const { workspaceId:wid } = await api('POST','/api/auth/verify',{plan:'studio'});
  const start = await api('POST',`/api/workspaces/${wid}/channels/threads/oauth/start`,{capability:'analytics'});
  const connected = await api('POST',`/api/workspaces/${wid}/channels/threads/oauth/complete`,{state:new URL(start.authorizeUrl).searchParams.get('state'),code:'good-code'});
  const conn = connected.connectionId;
  assert.ok(conn);
  const endpoint = `/api/workspaces/${wid}/channels/${encodeURIComponent(conn)}/history-import`;
  assert.equal((await api('GET',endpoint)).status, 'none');
  const fixture = (kind) => execFileSync(python, ['tests/phase2/history_import_browser_fixture.py',kind,pgPort,principal,wid,conn], {cwd:root,encoding:'utf8'});
  fixture('ready');
  const tours = Object.fromEntries([...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>[m[1],1]));
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1280,height:960},reducedMotion:'reduce',locale:'en-US'});
  await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
  await context.addInitScript(({principal,wid,tours}) => {
    localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-workspace',wid);
    localStorage.setItem('postriff-onboarding:'+principal,JSON.stringify({completed:{},dismissed:tours,nudged:tours}));
    // Development inspector overlays are absent from the production bundle.
    document.addEventListener('DOMContentLoaded',()=>{const style=document.createElement('style');style.textContent='.tsqd-parent-container,nextjs-portal{display:none!important}';document.head.appendChild(style);});
  }, {principal,wid,tours});
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let posts=0;page.on('request',r=>{if(new URL(r.url()).pathname===endpoint && r.method()==='POST')posts++;});
  const checks=[];
  async function visit() { await page.goto(base+'/app/channels',{waitUntil:'domcontentloaded',timeout:120000});await page.getByRole('button',{name:'Past analytics',exact:true}).waitFor({timeout:120000}); }
  async function open() { await page.getByRole('button',{name:'Past analytics',exact:true}).click();return page.getByRole('dialog').filter({has:page.getByText('Import past analytics',{exact:true})}); }
  async function shot(name) {await page.screenshot({path:path.join(out,name+'.png')});}
  try {
    await visit();let dialog=await open();
    await dialog.getByText('No import requested',{exact:true}).waitFor();
    const confirm=dialog.getByRole('checkbox');assert.equal(await confirm.isChecked(),false);
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).isDisabled(),true);
    await dialog.getByText(/300 posts and 12 pages/).waitFor();
    await dialog.getByText(/Caption text and caption hashes/).waitFor();
    assert.equal(posts,0);await shot('review-desktop');
    await confirm.check();await dialog.getByRole('button',{name:'Confirm import',exact:true}).click();
    await dialog.getByText('Import queued',{exact:true}).waitFor();assert.equal(posts,1);
    assert.equal((await api('GET',endpoint)).status,'pending');
    checks.push('opening/review does not POST; unchecked explicit metadata/analytics consent; real 202 request and queued status');
    fixture('retry');await dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('Rafii will retry automatically with the same progress.',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).count(),0);assert.equal(posts,1);
    checks.push('running automatic retry preserves progress and offers no duplicate submission');
    fixture('done');await dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('Metadata import finished. Analytics are collected separately.',{exact:true}).waitFor();
    await dialog.getByText('Retained history: 0 analytics reads finished · 1 waiting',{exact:true}).waitFor();
    await dialog.getByRole('button',{name:'Review another import',exact:true}).click();
    assert.equal(await dialog.getByRole('checkbox').isChecked(),false);
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).isDisabled(),true);
    checks.push('metadata completion remains separate from pending metrics; repeat requires new review and consent');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    fixture('failed');dialog=await open();
    await dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('The platform did not return a usable next-page cursor. Coverage is incomplete.',{exact:true}).waitFor();
    checks.push('incomplete pagination is a failed/partial coverage state');
    fixture('cancelled');await dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('Import cancelled because access changed.',{exact:true}).waitFor();
    checks.push('cancelled import is explicitly labelled rather than reported complete');
    fixture('purge');await dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('Removing earlier imported data. New imports are blocked until removal finishes.',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Review another import',exact:true}).count(),0);
    checks.push('pending purge visibly blocks new imports');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    fixture('none');fixture('viewer');await visit();dialog=await open();
    await dialog.getByText('An owner or admin with connection permissions must confirm the import. You can read its status.',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).isDisabled(),true);
    checks.push('viewer can read status but cannot consent or request');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    fixture('owner');fixture('analytics-off');await visit();dialog=await open();
    await dialog.getByText('This account needs verified Direct analytics access before importing.',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).isDisabled(),true);
    checks.push('non-Direct analytics blocked with reconnect action');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    fixture('analytics-on');await visit();dialog=await open();fixture('viewer');
    await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'Confirm import',exact:true}).click();
    await dialog.getByText('Your workspace permissions do not allow this action.',{exact:true}).waitFor();
    assert.equal((await api('GET',endpoint)).status,'none');
    checks.push('permission revoked after review is denied by the real endpoint');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();fixture('owner');
    // Delayed/unavailable reads are deliberately injected browser faults, never real provider responses.
    let releaseRead;const delayed=new Promise(resolve=>{releaseRead=resolve;});
    await page.route('**/history-import',async route=>{await delayed;await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'synthetic unavailable'})});});
    dialog=await open();const refreshing=dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('Loading import status…',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).isDisabled(),true);
    releaseRead();await refreshing;
    await dialog.getByText('The request could not be confirmed. Refresh the status before requesting again.',{exact:true}).waitFor();
    await page.unroute('**/history-import');await dialog.getByRole('button',{name:'Refresh status',exact:true}).click();
    await dialog.getByText('No import requested',{exact:true}).waitFor();
    checks.push('loading and unavailable status disable requests; explicit refresh recovers');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    fixture('analytics-on');fixture('throttle');await visit();dialog=await open();
    await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'Confirm import',exact:true}).click();
    await dialog.getByText('Five requests per hour are allowed. Wait for this hour’s window before requesting again.',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('button',{name:'Confirm import',exact:true}).isDisabled(),true);
    assert.equal((await api('GET',endpoint)).status,'none');
    checks.push('real backend hourly throttle is localized and cannot report a queued run');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();fixture('none');
    // An uncertain network response is a browser-only fault; status reconciliation is still the actual hosted GET.
    await page.route('**/history-import',route=>route.request().method()==='POST'?route.abort('failed'):route.continue());
    dialog=await open();await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'Confirm import',exact:true}).click();
    await dialog.getByText('The request could not be confirmed. Refresh the status before requesting again.',{exact:true}).waitFor();
    assert.equal(await dialog.getByRole('checkbox').isChecked(),false);
    await page.unroute('**/history-import');
    checks.push('lost POST response triggers GET reconciliation and resets confirmation; no automatic POST retry');
    await dialog.getByRole('button',{name:'Close',exact:true}).click();
    await api('PATCH','/api/me',{locale:'zh-Hant-HK'});await page.reload({waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:'過往數據',exact:true}).click();dialog=page.getByRole('dialog').filter({has:page.getByText('匯入過往數據',{exact:true})});
    await dialog.getByText(/最近 90 天/).waitFor();
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No mobile overflow');
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const violations=await page.evaluate(async()=> (await window.axe.run('[data-testid="history-import-review"]',{resultTypes:['violations']})).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id));
    assert.deepEqual(violations,[]);await shot('review-mobile-hant');
    await page.keyboard.press('Escape');await page.getByRole('button',{name:'過往數據',exact:true}).waitFor();
    await page.getByRole('button',{name:'過往數據',exact:true}).click();assert.equal(await page.getByRole('dialog').getByRole('checkbox').isChecked(),false);
    checks.push('saved Hong Kong display locale, mobile layout, dialog keyboard close/reopen, consent reset and axe checks');
    await page.keyboard.press('Escape');await api('PATCH','/api/me',{locale:'en'});
    // Feature-OFF response is deliberately mocked here; the WSGI gate itself is also covered by unit tests.
    await page.route('**/history-import',route=>route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'off',code:'feature_disabled'})}));
    const offResponse=page.waitForResponse(r=>new URL(r.url()).pathname===endpoint && r.status()===404);
    await page.reload({waitUntil:'domcontentloaded'});await offResponse;
    assert.equal(await page.getByRole('button',{name:'Past analytics',exact:true}).count(),0);
    checks.push('OFF-gate response hides the entry point');
    await page.unroute('**/history-import');await visit();
    await page.getByRole('button',{name:'Disconnect',exact:true}).click();
    const alert=page.getByRole('alertdialog');await alert.getByText(/removes imported metadata/).waitFor();
    await alert.getByRole('button',{name:'Disconnect',exact:true}).click();
    await page.getByText('Threads disconnected',{exact:true}).waitFor();
    // The server receipt toast precedes the awaited channel-query refresh.
    // Check the eventual rendered state, not the race between those updates.
    await page.getByRole('button',{name:'Past analytics',exact:true}).waitFor({state:'hidden',timeout:10_000});
    checks.push('disconnect review includes imported-data purge; actual disconnect removes import control');
    assert.deepEqual(errors,[]);
    const report={execution:'actual local browser/UI/API/disposable DB; synthetic providers and seeded status data; OFF/network fault responses explicitly mocked',checks,screenshots:['review-desktop.png','review-mobile-hant.png'],pageErrors:errors};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
