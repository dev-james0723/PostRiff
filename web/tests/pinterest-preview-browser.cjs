const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:4440';

(async () => {
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:390,height:900},reducedMotion:'reduce'});
  const externalBlocked=[];
  await context.route('**/*', async route => {
    const u=new URL(route.request().url());
    if(u.origin !== base || u.pathname.startsWith('/api/')) {
      externalBlocked.push({origin:u.origin,path:u.pathname});
      return route.abort();
    }
    return route.continue();
  });
  const page=await context.newPage();
  page.setDefaultTimeout(90000);
  try {
    let ready=false;
    for(let i=0;i<60;i++) {
      try {const r=await context.request.get(base+'/dev/post-previews',{timeout:2000}); if(r.status()===200){ready=true;break;}} catch {}
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    assert.ok(ready,'Cloud preview server did not become ready');
    const query='/dev/post-previews?channel=pinterest&media=one&at=2026-10-14T12%3A00%3A00Z&tz=UTC&appearance=light';
    await page.goto(base+query);
    const pin=page.locator('[role="img"][aria-label^="Pinterest preview"]');
    await pin.waitFor();
    assert.equal(await pin.locator('p').filter({hasText:/^Exact approved mock title$/}).count(),1);
    assert.equal(await pin.locator('p').filter({hasText:/^Rafii draft · Board ID 1234567$/}).count(),1);
    assert.equal(await pin.locator('p').filter({hasText:/^https:\/\/example.com\/approved-destination$/}).count(),1);
    assert.equal(await pin.locator('span').filter({hasText:/^Destination link$/}).count(),1);
    const png=await pin.screenshot();
    console.log('PINTEREST_PREVIEW_PNG_BASE64:'+png.toString('base64'));
    await page.goto(base+query+'&emptyTitle=1');
    await pin.waitFor();
    assert.equal(await pin.locator('p').filter({hasText:/^Exact approved mock title$/}).count(),0);
    assert.equal(await pin.locator('p').evaluateAll(ps=>ps.filter(p=>getComputedStyle(p).fontSize==='23px').length),0,'Description must not become an inferred title');
    await page.goto(base+query+'&unsafeLink=1');
    await pin.waitFor();
    assert.equal(await pin.locator('span').filter({hasText:/^Destination link$/}).count(),0);
    assert.equal(await pin.locator('p').filter({hasText:/javascript:/}).count(),0);
    await page.goto(base+'/dev/pinterest-fields');
    const choices=page.getByTestId('pin-options');
    assert.equal(await choices.textContent(),'null');
    await page.getByRole('combobox',{name:'Board',exact:true}).click();
    const secret=page.getByRole('option',{name:'Secret Mock Board (unavailable)',exact:true});
    assert.equal(await secret.getAttribute('aria-disabled'),'true');
    await page.getByRole('option',{name:'Public Mock Board',exact:true}).click();
    await page.getByRole('combobox',{name:'Board section (optional)',exact:true}).click();
    await page.getByRole('option',{name:'Mock section',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-testid="pin-options"]')?.textContent.includes('6543210'));
    assert.equal(JSON.parse(await choices.textContent()).boardSectionId,'6543210');
    await page.getByLabel('Link (optional)',{exact:true}).fill('http://example.com');
    await page.waitForFunction(()=>document.querySelector('[data-testid="pin-options"]')?.textContent==='null');
    await page.getByLabel('Link (optional)',{exact:true}).fill('https://example.com/reviewed');
    await page.waitForFunction(()=>document.querySelector('[data-testid="pin-options"]')?.textContent.includes('https://example.com/reviewed'));
    await page.getByRole('button',{name:'Switch mock account',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('[data-testid="pin-options"]')?.textContent==='null');
    const fieldsPng=await page.screenshot();
    console.log('PINTEREST_FIELDS_PNG_BASE64:'+fieldsPng.toString('base64'));
    console.log('PINTEREST_FIELDS_BROWSER_RESULT:'+JSON.stringify({execution:'synthetic_actual_component',boardSelection:true,secretBoardDisabled:true,sectionSelection:true,httpLinkRejected:true,httpsLinkAccepted:true,accountSwitchClearsApprovalOptions:true,realProviderRequests:0}));
    console.log('PINTEREST_PREVIEW_BROWSER_RESULT:'+JSON.stringify({classification:'Mock PASS',
      fixtureOverlay:true,realPinterestApiRequests:0,realIdentityVerified:false,exactTitle:true,boardVisible:true,
      exactDestination:true,noTitleInference:true,unsafeLinkNoCTA:true,externalRequestsBlocked:externalBlocked.length}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
