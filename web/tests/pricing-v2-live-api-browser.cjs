/** Prepared Task 13: REAL Next proxies -> HostedApplication -> parent-owned PG.
 * Run only with the opt-in /dev/pricing-v2-local-synthetic adapter. Customer
 * responses are never fulfilled/intercepted. Injected model/payment transports
 * are local-synthetic; this is NOT a Stripe test-mode or provider-quality test.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID, createHash } = require('node:crypto');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
function boundedTimeoutMs(name) {
  const value=Number(process.env[name] ?? 120000);
  assert.ok(Number.isInteger(value)&&value>=1000&&value<=300000,`${name}: finite 1000..300000ms required`);
  return value;
}
const ACTION_TIMEOUT_MS=boundedTimeoutMs('PRICING_V2_ACTION_TIMEOUT_MS');
const NAVIGATION_TIMEOUT_MS=boundedTimeoutMs('PRICING_V2_NAVIGATION_TIMEOUT_MS');
const MODEL = 'google/gemini-2.5-flash-lite';
const scenarios = ['free-new','creator-49','creator-59','creator-79','creator-held',
  'creator-pending','creator-settled','creator-over-max','creator-failed',
  'legacy-19','legacy-39','trial-active','trial-expired','creator-ended-free'];
// Authenticated retained prices, separate from the public Creator $59 reference.
// Expectations only: never sent to bootstrap or substituted into API responses.
const effectiveSubscriptionCents = Object.freeze({
  'creator-49':4900, 'creator-59':5900, 'creator-79':7900, 'legacy-19':1900, 'legacy-39':3900
});
const origin = new URL(process.env.PRICING_V2_WEB_URL || 'http://127.0.0.1:4439');
assert.equal(origin.protocol, 'http:'); assert.equal(origin.hostname, '127.0.0.1');
assert.equal(origin.pathname, '/'); assert.equal(origin.username + origin.password + origin.search + origin.hash, '');
const base = origin.origin;
const out = process.env.PRICING_V2_EVIDENCE_DIR;
assert.ok(out && path.isAbsolute(out), 'Explicit evidence directory required');
const secret = process.env.PRICING_V2_FIXTURE_TOKEN;
assert.ok(secret && secret.length >= 32, 'Parent adapter capability required');
const cached = process.env.BROWSER_EXECUTABLE;
assert.ok(cached && path.isAbsolute(cached) && fs.existsSync(cached), 'Explicit already cached Chromium required; no download');
const results = [], traffic = [], failures = [];
let browser;
function pass(name, detail) { results.push({ name, pass: true, detail }); process.stdout.write('PASS ' + name + '\n'); }
async function parsed(response, status=200) {
  assert.equal(response.status(), status, await response.text());
  return response.json();
}
async function control(request, action, data={}) {
  return parsed(await request.post(base + '/dev/pricing-v2-local-synthetic/' + action,
    { headers: { Origin: base, 'X-Pricing-V2-Fixture': secret }, data, timeout:ACTION_TIMEOUT_MS }));
}
function api(request, principal) {
  return async (method, endpoint, data, status=200) => {
    assert.ok(endpoint.startsWith('/api/') && !endpoint.includes('://'), 'Fixed local customer API path');
    const response = await request.fetch(base + endpoint, { method, maxRedirects: 0, timeout:ACTION_TIMEOUT_MS,
      headers: { Authorization: 'Bearer dev:' + principal, Origin: base, 'X-PostRiff-Request': 'founder-alpha' },
      ...(data === undefined ? {} : { data }) });
    traffic.push({ method, path: endpoint.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/g,'<workspace>'), status: response.status(), channel: 'real-http' });
    return parsed(response,status);
  };
}
async function contextFor(row, width, motion, member=false) {
  const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: motion,
    serviceWorkers: 'block' });
  context.setDefaultTimeout(ACTION_TIMEOUT_MS);
  context.setDefaultNavigationTimeout(NAVIGATION_TIMEOUT_MS);
  const external = [], errors = [];
  // Egress guard only; same-origin requests ALWAYS continue to the real server.
  // APIRequestContext uses fixed same-origin URLs separately (no generic URL input).
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.origin === base) return route.continue();
    external.push(u.origin); return route.abort();
  });
  if (row) {
    const principal = member ? row.memberPrincipal : row.principal;
    await context.addCookies([{ name:'postriff_dev',value:'1',url:base },
      { name:'postriff_dev_principal',value:principal,url:base }, {name:'postriff_theme',value:'rafii',url:base}]);
    // Authentication and tour preference only. No API/cost/plan/workspace fixtures
    // are injected into browser storage or the DOM.
    const toursFile = process.env.PRICING_V2_TOURS_FILE || path.join(__dirname,'../src/features/onboarding/tours.ts');
    assert.ok(fs.existsSync(toursFile), 'Parent must supply actual committed onboarding tour source');
    const tours = [...fs.readFileSync(toursFile,'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
    await context.addInitScript(({principal,tours}) => {
      localStorage.setItem('postriff-dev-principal',principal);
      const s=JSON.stringify({completed:{},dismissed:Object.fromEntries(tours.map(t=>[t,1])),nudged:Object.fromEntries(tours.map(t=>[t,1]))});
      localStorage.setItem('postriff-onboarding',s);localStorage.setItem('postriff-onboarding:'+principal,s);
    }, {principal,tours});
  }
  const page = await context.newPage();
  page.on('pageerror', e=>errors.push(e.message));
  page.on('console', m=>{if(m.type()==='error') errors.push(m.text());});
  page.on('response', r=>{
    const u=new URL(r.url()); if(u.origin===base && u.pathname.startsWith('/api/'))
      traffic.push({method:r.request().method(),path:u.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/g,'<workspace>'),status:r.status(),channel:'browser'});
  });
  return {context,page,external,errors};
}
async function visual(scene, url, label, width, motion) {
  const {page}=scene;
  await page.goto(base+url); await page.locator('main').first().waitFor();
  await page.waitForFunction(()=>document.fonts.status==='loaded',null,{timeout:ACTION_TIMEOUT_MS});
  const main=page.locator('main').first();
  assert.ok((await main.innerText()).trim().length>0, 'Actual product content must be present');
  // Wait for source-defined data surfaces rather than a sleep or a static fixture.
  if(url.includes('/billing')) {
    await page.getByRole('heading',{name:'Usage & plan',exact:true}).waitFor();
    await page.getByRole('status',{name:'Loading usage and plan',exact:true}).waitFor({state:'hidden'});
  }
  const overflow=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  assert.ok(overflow.scroll<=overflow.width+1, `${label}: horizontal overflow ${JSON.stringify(overflow)}`);
  const actualMotion=await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
  assert.equal(actualMotion,motion==='reduce');
  await page.screenshot({path:path.join(out,`${label}-${width}-${motion}.png`),fullPage:true});
  assert.deepEqual(scene.external,[], `${label}: browser external request attempt`);
  assert.deepEqual(scene.errors,[], `${label}: runtime/console errors`);
  return main;
}
async function publicScene(width,motion) {
  const scene=await contextFor(null,width,motion);
  try {
    const main=await visual(scene,'/pricing','public-pricing',width,motion);
    const text=await main.innerText();assert.match(text,/Free/);assert.match(text,/Creator/);
    assert.match(text,/\$59|US\$59|USD 59/);assert.match(text,/3,500|3500/);
    assert.doesNotMatch(text,/\$(19|39)(?:\D|$)/,'No legacy new-sale prices');
    for(const name of ['Starter','Studio']) assert.equal(await main.getByRole('heading',{name,exact:true}).count(),0);
    const catalog=await parsed(await scene.context.request.get(base+'/api/plans',{timeout:ACTION_TIMEOUT_MS}));
    assert.equal(catalog.pricing,'v2');assert.deepEqual(catalog.plans.map(p=>p.plan).sort(),['creator','free']);
    const creator=catalog.plans.find(p=>p.plan==='creator');
    assert.equal(creator.priceCents,5900);assert.equal(creator.entitlements.monthlyCredits,3500);
    assert.equal(creator.checkout,'not_yet_available');assert.equal(catalog.topUps.available,false);
    // The existing public JSON-LD is published by Home, using the same pricing catalog.
    await scene.page.goto(base+'/');
    const ld=await scene.page.locator('script[type="application/ld+json"]').allTextContents();
    assert.ok(ld.length,'Actual public JSON-LD must be present');
    const structured=ld.map(v=>JSON.parse(v));
    assert.doesNotMatch(JSON.stringify(structured),/studio-v1|assist-v1|price_local_synthetic/);
    pass(`public ${width} ${motion}: Free + Creator $59 / 3500, inactive checkout, no overflow/errors`);
  } finally {await scene.context.close();}
}

// Runs in the real page, as both a bounded RAF wait predicate and evidence read.
// Reads styles/animations only: no style injection, cancelled animation or sleep.
function mobileMenuSnapshot(requireSettled=false) {
  const popup=document.querySelector('[data-slot="sheet-content"]');
  const backdrop=document.querySelector('[data-slot="sheet-overlay"]');
  if(!popup||!backdrop) return requireSettled?false:{settled:false,popup:null,backdrop:null};
  const viewport={width:innerWidth,height:innerHeight,reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches};
  function inspect(element) {
    const style=getComputedStyle(element),r=element.getBoundingClientRect();
    const rect={left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
    const transform=new DOMMatrixReadOnly(style.transform==='none'?undefined:style.transform);
    const translation={x:transform.m41,y:transform.m42,z:transform.m43};
    const translateZero=style.translate==='none'||style.translate.split(/\s+/).every(v=>/^-?0(?:\.0+)?(?:px|%)?$/.test(v));
    const animations=element.getAnimations().map(a=>({playState:a.playState,
      endTime:Number.isFinite(a.effect?.getComputedTiming().endTime)?a.effect.getComputedTiming().endTime:'nonfinite'}));
    return {rect,opacity:style.opacity,filter:style.filter,translate:style.translate,translation,translateZero,
      transform:style.transform,display:style.display,visibility:style.visibility,pointerEvents:style.pointerEvents,
      backgroundColor:style.backgroundColor,backdropFilter:style.backdropFilter,zIndex:style.zIndex,
      transitionDuration:style.transitionDuration,animations,
      starting:element.hasAttribute('data-starting-style'),ending:element.hasAttribute('data-ending-style'),
      inViewport:r.width>0&&r.height>0&&r.left>=-1&&r.top>=-1&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1};
  }
  const p=inspect(popup),b=inspect(backdrop);
  const links=[...popup.querySelectorAll('a')].map(a=>({text:a.innerText.trim(),href:a.getAttribute('href'),...inspect(a)}));
  const point={x:p.rect.left/2,y:innerHeight/2};
  const hit=document.elementFromPoint(point.x,point.y);
  const pointHitsBackdrop=point.x>0&&(hit===backdrop||backdrop.contains(hit));
  const stopped=e=>!e.starting&&!e.ending&&e.animations.every(a=>a.endTime!=='nonfinite'&&['finished','idle'].includes(a.playState));
  const visible=e=>e.display!=='none'&&e.visibility==='visible'&&Number(e.opacity)===1;
  const zero=e=>e.translateZero&&Object.values(e.translation).every(v=>Math.abs(v)<=.001);
  const settled=stopped(p)&&stopped(b)&&visible(p)&&visible(b)&&p.filter==='none'&&zero(p)&&p.inViewport&&
    b.rect.left<=1&&b.rect.top<=1&&b.rect.right>=innerWidth-1&&b.rect.bottom>=innerHeight-1&&
    b.pointerEvents!=='none'&&pointHitsBackdrop&&links.length===6&&links.every(a=>visible(a)&&a.inViewport);
  const snapshot={settled,viewport,popup:{role:popup.getAttribute('role'),...p},backdrop:b,links,
    backdropPoint:point,pointHitsBackdrop,scrollWidth:document.documentElement.scrollWidth};
  return requireSettled?settled:snapshot;
}

async function mobileNavigation320(motion) {
  const scene=await contextFor(null,320,motion),{page}=scene;
  const evidence={width:320,motion,execution:'real-browser-public-navigation',states:[]};
  const prefix=`public-navigation-320-${motion}`;
  async function openAndSettle(label) {
    await page.getByRole('button',{name:'Open menu',exact:true}).click();
    const initial=await page.evaluate(mobileMenuSnapshot,false),started=Date.now();
    const ready=await page.waitForFunction(mobileMenuSnapshot,true,{polling:'raf',timeout:ACTION_TIMEOUT_MS});
    await ready.dispose();
    const settled=await page.evaluate(mobileMenuSnapshot,false);
    assert.equal(settled.settled,true);assert.equal(settled.popup.role,'dialog');
    assert.equal(settled.viewport.width,320);assert.equal(settled.viewport.reducedMotion,motion==='reduce');
    assert.equal(Number(settled.popup.opacity),1);assert.equal(settled.popup.filter,'none');
    assert.equal(settled.popup.translateZero,true);assert.equal(settled.popup.inViewport,true);
    if(motion==='no-preference') assert.ok(settled.popup.transitionDuration.split(',').some(v=>parseFloat(v)>0),
      'Normal sheet motion remains enabled; wait for its actual settled state');
    assert.ok(settled.scrollWidth<=321);assert.equal(settled.pointHitsBackdrop,true);
    assert.notEqual(settled.backdrop.backgroundColor,'rgba(0, 0, 0, 0)');
    assert.notEqual(settled.backdrop.backgroundColor,'transparent');
    assert.deepEqual(settled.links.map(l=>({text:l.text,href:l.href})),[
      {text:'Product',href:'/#how-it-works'},{text:'Channels',href:'/channels'},
      {text:'Pricing',href:'/pricing'},{text:'Docs',href:'/docs'},
      {text:'Sign in',href:'/auth/sign-in'},{text:'Start free',href:'/auth/sign-up'}
    ]);
    evidence.states.push({label,elapsedMs:Date.now()-started,initial,settled});
    await page.screenshot({path:path.join(out,`${prefix}-${label}.png`),fullPage:false});
    return settled;
  }
  try {
    await visual(scene,'/','public-home-320',320,motion);
    await openAndSettle('open-before-link');
    await page.locator('[data-slot="sheet-content"]').getByRole('link',{name:'Pricing',exact:true}).click();
    await page.waitForURL(base+'/pricing',{timeout:NAVIGATION_TIMEOUT_MS});
    await page.locator('[data-slot="sheet-content"]').waitFor({state:'hidden'});
    await page.locator('[data-slot="sheet-overlay"]').waitFor({state:'hidden'});
    const reopened=await openAndSettle('open-before-backdrop');
    await page.mouse.click(reopened.backdropPoint.x,reopened.backdropPoint.y);
    await page.locator('[data-slot="sheet-content"]').waitFor({state:'hidden'});
    await page.locator('[data-slot="sheet-overlay"]').waitFor({state:'hidden'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=321));
    evidence.linkDestination=page.url();evidence.linkClosedPopup=true;evidence.backdropClosedPopup=true;
    await page.screenshot({path:path.join(out,`${prefix}-closed-after-backdrop.png`),fullPage:false});
    assert.deepEqual(scene.external,[]);assert.deepEqual(scene.errors,[]);
    pass(`Q-M1 320 ${motion}: actual settled popup styles, viewport, six links, navigation and backdrop dismissal`);
  } catch(error) {
    evidence.failure=String(error.stack);
    evidence.failureState=await page.evaluate(mobileMenuSnapshot,false).catch(()=>null);
    throw error;
  } finally {
    fs.writeFileSync(path.join(out,`${prefix}.json`),JSON.stringify(evidence,null,2)+'\n');
    await scene.context.close();
  }
}
async function billingScene(row,width,motion,member=false,work=false) {
  const scene=await contextFor(row,width,motion,member);
  const principal=member?row.memberPrincipal:row.principal;
  const send=api(scene.context.request,principal); const ws='/api/workspaces/'+row.workspaceId;
  try {
    const usage=await send('GET',ws+'/usage');
    assert.equal(usage.aiUsageExempt,false,'No guessed developer exemption');
    assert.equal(usage.billingMode,row.expectedMode);assert.equal(usage.billing.checkoutAvailable,false);
    assert.ok(usage.planTerms.every(p=>!p.checkoutAvailable));
    if(member) {
      assert.equal(usage.budget,null);assert.equal(usage.billing.portalAvailable,false);
      for(const entry of usage.ledger) {assert.equal(entry.estimatedUsdMicro,undefined);assert.equal(entry.actualUsdMicro,undefined);}
    }
    const main=await visual(scene,'/app/account/billing',row.scenario+(member?'-member':''),width,motion);
    const expectedCents=effectiveSubscriptionCents[row.scenario];
    if(expectedCents!==undefined) {
      assert.equal(usage.subscription.priceCents,expectedCents,`${row.scenario}: retained effective subscription amount`);
      assert.equal(usage.subscription.currency.toUpperCase(),'USD');
      // Same formatting contract as PlanCard/cents; bind visible account text to
      // the real authenticated amount after independently checking that amount.
      const renderedPrice=new Intl.NumberFormat('en-US',{style:'currency',currency:usage.subscription.currency,
        minimumFractionDigits:0}).format(usage.subscription.priceCents/100)+' / month';
      await scene.page.locator('[data-tour="billing-plan"]').getByText(renderedPrice,{exact:true}).waitFor({state:'visible'});
    }
    if(row.expectedMode==='managed_credits') {
      await scene.page.getByRole('region',{name:'Managed credits',exact:true}).waitFor();
      const credit=scene.page.getByRole('region',{name:'Managed credits',exact:true});
      assert.match(await credit.innerText(),/Current-period grant[\s\S]*3,500|Current-period grant[\s\S]*3500/);
      assert.match(await credit.innerText(),/No silent overage/);
      assert.equal(usage.credits.currentPeriodGrantMilliCredits,3500000);
      assert.ok(usage.credits.currentPeriodExpiresAt>0);
      assert.doesNotMatch(await main.innerText(),/AI writing batches|writing batches left/);
    } else if(row.expectedMode==='free_preview') {
      await scene.page.getByText('Free preview',{exact:true}).first().waitFor();
      assert.equal(usage.credits,null);assert.doesNotMatch(await main.innerText(),/AI writing batches|writing batches left/);
    } else {
      assert.match(await main.innerText(),/batch|allowance/i,'Truthful grandfathered allowances remain');
      assert.equal(usage.credits,null);
    }
    assert.equal(await scene.page.getByText('Advanced usage · USD costs',{exact:true}).count(),member?0:usage.budget||usage.ledger.length?1:0);
    const packs=await send('GET',ws+'/billing/credit-packs');assert.deepEqual(packs,{available:false,packs:[]});
    if(work) {
      for(const [href,label] of [['/app/overview','overview'],['/app/ideas','ideas'],['/app','writing-now'],['/app/growth','growth'],['/app/workspace/brand','genome']]) {
        const body=await visual(scene,href,row.scenario+'-'+label,width,motion);
        if(row.expectedMode!=='legacy_allowances') assert.doesNotMatch(await body.innerText(),/AI writing batches|writing batches left/i);
        if(label==='genome') {
          await scene.page.locator('[aria-label="Creator Genome"]').waitFor();
          const g=await send('GET',ws+'/growth/catalog');
          // Current server flags keep legacy rewrite availability true even when
          // managed/Free policies are off. Unsupported synthetic legacy AI still
          // refuses before dispatch; do not forge the catalog to hide that fence.
          const legacy=usage.billingMode==='legacy_allowances';
          assert.equal(g.rewriteCredits.billingMode,legacy?'legacy':usage.billingMode==='free_preview'?'free':'managed_credits');
          assert.equal(g.rewriteCredits.available,legacy);
          if(row.expectedMode==='managed_credits'||row.expectedMode==='free_preview') assert.equal(g.genomeAnalysis.available,false);
          const button=scene.page.getByRole('button',{name:'Propose my Genome',exact:true});
          if(await button.count()) assert.equal(await button.isEnabled(),false);
        }
      }
    }
    pass(`${row.scenario} ${member?'member':'owner'} ${width} ${motion}: actual Usage/plan and ${work?'work/Growth UI':'billing UI'}`);
    assert.deepEqual(scene.errors,[]);assert.deepEqual(scene.external,[]);
  } catch(e) {
    fs.writeFileSync(path.join(out,`failure-${row.scenario}-${width}-${motion}.txt`),String(e.stack)+'\n'+await scene.page.locator('body').innerText().catch(()=>''));
    throw e;
  } finally {await scene.context.close();}
}
async function fundingUIScene(request,row,width,motion,mode,enabled) {
  await control(request,'policy',{mode});
  const scene=await contextFor(row,width,motion);
  try {
    await scene.page.goto(base+'/app/workspace/brand');
    const genome=scene.page.locator('[aria-label="Creator Genome"]');await genome.waitFor();
    const g=await api(scene.context.request,row.principal)('GET','/api/workspaces/'+row.workspaceId+'/growth/catalog');
    assert.equal(g.genomeAnalysis.available,enabled);
    const csv=genome.getByLabel('Owned history CSV',{exact:true});
    if(enabled) {
      await scene.page.waitForFunction(()=>document.querySelector('[aria-label="Creator Genome"] input[aria-label="Owned history CSV"]')?.disabled===false);
      assert.equal(await csv.isEnabled(),true);
      await csv.setInputFiles({name:'owned-history.csv',mimeType:'text/csv',buffer:Buffer.from('text,platform,language,post_id,published_at\nOwn idea.,Threads,en,synthetic-ui,2026-09-01\n')});
      await genome.getByLabel('CSV account',{exact:true}).fill('local-synthetic-owned');
      await genome.getByLabel('Confirm owned history retention and analysis',{exact:true}).check();
    } else {
      assert.equal(await csv.isEnabled(),false,'Unfunded CSV input stays disabled; no forced input');
    }
    assert.equal(await genome.getByRole('button',{name:'Propose my Genome',exact:true}).isEnabled(),enabled);
    const overflow=await scene.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);assert.ok(overflow);
    await scene.page.screenshot({path:path.join(out,`${row.scenario}-genome-${mode}-${width}-${motion}.png`),fullPage:true});
    assert.deepEqual(scene.errors,[]);assert.deepEqual(scene.external,[]);
    pass(`${row.scenario} Genome ${mode} ${width} ${motion}: actual catalog and UI funding gates agree; funded input and consent are explicit`);
  } finally {await scene.context.close();}
}
async function contracts(request, rows) {
  for(const [name,expectedCents] of Object.entries(effectiveSubscriptionCents)) {
    const row=rows.find(r=>r.scenario===name);const send=api(request,row.principal);
    const usage=await send('GET','/api/workspaces/'+row.workspaceId+'/usage');
    assert.equal(usage.subscription.priceCents,expectedCents,`${name}: effective API amount, not public reference`);
    assert.equal(usage.subscription.currency.toUpperCase(),'USD');
    assert.equal(usage.planTerms.find(t=>t.id===usage.subscription.planTermsId).priceCents,expectedCents);
    if(name.startsWith('creator-')) {
      assert.equal(usage.credits.currentPeriodGrantMilliCredits,3500000);
      assert.equal(usage.subscription.priceVariantId,row.priceVariantId);
    } else {
      assert.equal(usage.billingMode,'legacy_allowances');assert.equal(usage.credits,null);
    }
  }
  const row=rows.find(r=>r.scenario==='free-new'); const send=api(request,row.principal);const ws='/api/workspaces/'+row.workspaceId;
  for(const terms of ['creator-v1','starter-v1','studio-v2','studio-v1','assist-v1'])
    await send('POST',ws+'/billing/checkout',{planTermsId:terms},409);
  await send('POST',ws+'/billing/credit-checkout',{packId:'credits-1000-v2',requestId:randomUUID()},503);
  // Owner/member and foreign-tenant protections use actual authenticated APIs.
  const other=rows.find(r=>r.scenario==='creator-59');
  const deniedUsage=await api(request,other.principal)('GET',ws+'/usage',undefined,403);
  assert.deepEqual(deniedUsage,{error:'Workspace unavailable.',code:'permission_denied'},'Foreign workspace denial returns no usage or identity data');
  await api(request,other.memberPrincipal)('POST','/api/workspaces/'+other.workspaceId+'/billing/checkout',{planTermsId:'creator-v1'},403);
  const signing=await control(request,'webhook-replay',{scenario:'creator-59'});
  const unsigned=await request.post(base+'/api/billing/webhook',{headers:{'Stripe-Signature':'t=1,v1=bad'},data:signing.body,timeout:ACTION_TIMEOUT_MS});
  assert.equal(unsigned.status(),401);
  assert.deepEqual(await unsigned.json(),{error:'Webhook signature rejected.',code:'unauthenticated'},'Invalid signature is rejected by the actual Stripe authentication gate');
  const webhook=await request.post(base+'/api/billing/webhook',{headers:{'Content-Type':'application/json','Stripe-Signature':signing.signature},data:signing.body,timeout:ACTION_TIMEOUT_MS});
  assert.equal(webhook.status(),200,await webhook.text());
  const before=await control(request,'snapshot');
  for(const scene of before.scenes) {
    if(scene.scenario.startsWith('creator-')) assert.deepEqual(scene.periodGrants,[1,3500000],'Verified invoice grants exactly once');
    if(scene.scenario==='free-new') assert.equal(scene.wallet.availableMilliCredits,0);
    if(scene.scenario==='creator-settled') assert.equal(scene.wallet.usedMilliCredits,3000);
    if(scene.scenario==='creator-failed') assert.equal(scene.wallet.usedMilliCredits,0);
    if(['creator-held','creator-pending'].includes(scene.scenario)) assert.ok(scene.wallet.heldMilliCredits>0);
    if(scene.scenario==='creator-pending') assert.ok(scene.ledger.some(r=>r[1]==='estimated_unknown'));
    if(scene.scenario==='creator-over-max') assert.ok(scene.ledger.some(r=>r[3]?.absorbed>0));
  }
  assert.equal(before.externalIO,0);assert.equal(before.syntheticStripeTransportAttempts,0);
  assert.ok(before.syntheticModelAttempts.every(a=>a.committedHold?.committedSeenViaSeparateConnection===true));
  // The committed Coworker source-campaign caller does not forward MAX yet.
  // Keep it off and verify real HTTP refusal. Positive paid Coworker admission
  // requires the parent's quote-aware contract; never invent a guard exemption.
  const coworker=await api(request,other.principal)('GET','/api/workspaces/'+other.workspaceId+'/coworker/status');
  assert.equal(coworker.flags.RAFII_WEEKLY_OPERATOR_ENABLED,false);
  assert.equal(coworker.flags.RAFII_RESEARCH_BROKER_ENABLED,false);
  await api(request,other.principal)('POST','/api/workspaces/'+other.workspaceId+'/coworker/source-campaigns',
    {format:'text',text:'A local-synthetic owned idea.',model:MODEL},404);
  assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,before.syntheticModelAttempts.length);
  pass('real Coworker off: source-campaign HTTP refuses before physical IO; positive MAX integration pending parent');
  fs.writeFileSync(path.join(out,'real-http-contract-state.json'),JSON.stringify(before,null,2)+'\n');
  pass('actual HTTP contracts: variants, grant-once, failed/held/pending/over-MAX, checkout gates, privacy, signed webhook');
}
async function writerAndGrowth(request,rows) {
  const row=rows.find(r=>r.scenario==='creator-59');const ws='/api/workspaces/'+row.workspaceId;const send=api(request,row.principal);
  const conversation=await send('POST',ws+'/ideas/conversations',{title:'local-synthetic actual writer'},201);
  const cid=conversation.conversationId;
  // Material is already handed in; no unquoted manager/research interpretation is
  // needed. The real turn path reserves/commits MAX then invokes the real writer.
  const payload={text:'Make this clear.',material:'One local-synthetic idea. Keep one practical takeaway.',model:MODEL,
    research:false,reasoning:'quick',language:'en',destinations:[{platform:'Threads',language:'en'}],idempotencyKey:randomUUID()};
  const baseline=await control(request,'snapshot');
  await send('POST',ws+'/ideas/conversations/'+cid+'/turns',payload,402);
  const noIO=await control(request,'snapshot');assert.equal(noIO.syntheticModelAttempts.length,baseline.syntheticModelAttempts.length);
  const estimate=await send('POST',ws+'/ideas/credit-estimates',{operation:'turn',conversationId:cid,request:payload});
  const quote=await send('POST',ws+'/ideas/credit-quotes',{operation:'turn',conversationId:cid,request:payload,
    expectedRevision:estimate.stateRevision,maxMilliCredits:Math.max(6000,estimate.ceilingMilliCredits)},201);
  const generated=await send('POST',ws+'/ideas/conversations/'+cid+'/turns',{...payload,creditQuoteId:quote.quoteId,expectedRevision:estimate.stateRevision},201);
  assert.ok(generated.runId,'Real writer saves an actual run');
  const after=await control(request,'snapshot');assert.ok(after.syntheticModelAttempts.length>baseline.syntheticModelAttempts.length);
  const wallet=after.scenes.find(r=>r.workspaceId===row.workspaceId).wallet;
  assert.equal(wallet.usedMilliCredits,3000,'$0.01 settles 3 credits once per real task');assert.equal(wallet.heldMilliCredits,0);
  await send('POST',ws+'/ideas/conversations/'+cid+'/turns',payload,201);
  assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,after.syntheticModelAttempts.length,'Replay never sends a second physical request');
  for(const width of [1440,390]) for(const motion of ['no-preference','reduce']) {
    const scene=await contextFor(row,width,motion);
    try {
      await scene.page.goto(base+'/app/agent/'+cid);
      await scene.page.getByText('A local-synthetic draft for this bounded browser check.',{exact:true}).first().waitFor();
      assert.ok(await scene.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await scene.page.screenshot({path:path.join(out,`actual-writing-result-${width}-${motion}.png`),fullPage:true});
      assert.deepEqual(scene.errors,[]);assert.deepEqual(scene.external,[]);
      pass(`actual saved writer result ${width} ${motion}`);
    } finally {await scene.context.close();}
  }
  pass('real writer HTTP: missing MAX refuses, quote/authorize/committed reserve precedes physical synthetic writer, settles actual 3 credits, replay');

  // Qualified/off/unavailable and independent platform-funded Genome/base checks.
  await control(request,'policy',{mode:'off'});
  assert.equal((await send('GET',ws+'/growth/catalog')).rewriteCredits.available,false);
  await control(request,'policy',{mode:'qualified'});
  const qualified=await send('GET',ws+'/growth/catalog');
  assert.equal(qualified.rewriteCredits.available,true);assert.equal(qualified.genomeAnalysis.available,true);
  const check=await send('POST',ws+'/growth/check',{text:'One practical idea. Another practical idea.',platform:'Threads',language:'en',confirmed:true,requestKey:randomUUID()});
  const rewrite={checkId:check.runId,model:MODEL,facts:{},confirmed:true,requestKey:randomUUID()};
  const attempts=(await control(request,'snapshot')).syntheticModelAttempts.length;
  const current=await send('GET',ws);
  await send('POST',ws+'/growth/rewrite',{...rewrite,expectedRevision:current.revision},402);
  assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,attempts);
  const re=await send('POST',ws+'/ideas/credit-estimates',{operation:'post-doctor-rewrite',request:rewrite});
  const rq=await send('POST',ws+'/ideas/credit-quotes',{operation:'post-doctor-rewrite',request:rewrite,
    expectedRevision:re.stateRevision,maxMilliCredits:re.ceilingMilliCredits},201);
  const actual=await send('POST',ws+'/growth/rewrite',{...rewrite,expectedRevision:re.stateRevision,creditQuoteId:rq.quoteId});
  assert.ok(actual.userMilliCreditsCharged>0);assert.ok(actual.userMilliCreditsCharged<=rq.maxMilliCredits);
  const finished=(await control(request,'snapshot')).syntheticModelAttempts.length;
  await send('POST',ws+'/growth/rewrite',rewrite);assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,finished);
  await control(request,'policy',{mode:'unavailable'});
  assert.equal((await send('GET',ws+'/growth/catalog')).rewriteCredits.available,false);
  pass('real Growth: qualified positive, off, expired safe unavailable; full pipeline MAX includes every physical task; exact replay');

  const free=rows.find(r=>r.scenario==='free-new');const fw='/api/workspaces/'+free.workspaceId;const freeAPI=api(request,free.principal);
  await control(request,'policy',{mode:'free-preview'});
  const freeStart=await control(request,'snapshot');
  const input={text:'My own local-synthetic preview idea.',platform:'Threads',language:'en',confirmed:true,requestKey:randomUUID()};
  const checked=await freeAPI('POST',fw+'/growth/check',input);assert.equal(checked.userCreditsCharged,0);
  const once=(await control(request,'snapshot')).syntheticModelAttempts.length;
  await freeAPI('POST',fw+'/growth/check',input);assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,once);
  const second=await request.post(base+fw+'/growth/check',{headers:{Authorization:'Bearer dev:'+free.principal,Origin:base,'X-PostRiff-Request':'founder-alpha'},data:{...input,requestKey:randomUUID()},timeout:ACTION_TIMEOUT_MS});
  assert.equal(second.status(),402,await second.text());
  assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,once);
  const csv='text,platform,language,post_id,published_at\n'+Array.from({length:20},(_,i)=>`Own idea ${i}.,Threads,en,synthetic-${i},2026-09-${String(i+1).padStart(2,'0')}\n`).join('');
  const genomeInput={data:csv,account:'local-synthetic-own',ownContent:true,retainText:true,confirmed:true,requestKey:randomUUID()};
  const genome=await freeAPI('POST',fw+'/growth/history',genomeInput);
  assert.equal(genome.genome.postCount,20);assert.equal(genome.userCreditsCharged,0);
  const genomeOnce=(await control(request,'snapshot')).syntheticModelAttempts.length;
  await freeAPI('POST',fw+'/growth/history',genomeInput);assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,genomeOnce);
  const genomeAgain=await request.post(base+fw+'/growth/history',{headers:{Authorization:'Bearer dev:'+free.principal,Origin:base,'X-PostRiff-Request':'founder-alpha'},data:{...genomeInput,requestKey:randomUUID()},timeout:ACTION_TIMEOUT_MS});
  assert.equal(genomeAgain.status(),402,await genomeAgain.text());
  assert.equal((await control(request,'snapshot')).syntheticModelAttempts.length,genomeOnce);
  const state=await control(request,'snapshot');assert.equal(state.scenes.find(r=>r.workspaceId===free.workspaceId).wallet.availableMilliCredits,0);
  assert.ok(state.syntheticModelAttempts.length>freeStart.syntheticModelAttempts.length);
  pass('real Free first value: one replay-safe Post Doctor and recent-20 Genome, independent finite platform funding, zero fungible credits');
}
async function main() {
  fs.mkdirSync(out,{recursive:true});
  browser=await chromium.launch({headless:true,executablePath:cached,timeout:NAVIGATION_TIMEOUT_MS});
  const setup=await browser.newContext();
  try {
    for(const motion of ['no-preference','reduce']) await mobileNavigation320(motion);
    const rows=[];
    for(const scenario of scenarios) rows.push(await control(setup.request,'bootstrap',{scenario}));
    assert.ok(rows.every(r=>r.execution==='local-synthetic-real-http-pg'&&r.stripeTestMode==='NOT_RUN'));
    await control(setup.request,'policy',{mode:'off'});
    await contracts(setup.request,rows);
    for(const width of [1440,390]) for(const motion of ['no-preference','reduce']) {
      await publicScene(width,motion);
      for(const row of rows) await billingScene(row,width,motion,false,
        ['free-new','creator-59','legacy-19'].includes(row.scenario));
      await billingScene(rows.find(r=>r.scenario==='creator-59'),width,motion,true,false);
      for(const row of rows.filter(r=>['free-new','creator-59'].includes(r.scenario))) {
        await fundingUIScene(setup.request,row,width,motion,'off',false);
        await fundingUIScene(setup.request,row,width,motion,'qualified',true);
      }
      await control(setup.request,'policy',{mode:'off'});
    }
    await writerAndGrowth(setup.request,rows);
    const final=await control(setup.request,'snapshot');
    assert.equal(final.externalIO,0);assert.equal(final.syntheticStripeTransportAttempts,0);
    fs.writeFileSync(path.join(out,'final-local-synthetic-state.json'),JSON.stringify(final,null,2)+'\n');
  } catch(e) {failures.push(String(e.stack));throw e;}
  finally {
    await setup.close();await browser.close();
    const receipts={execution:'local-synthetic-real-http-pg',customerApiMocks:false,stripeTestMode:'NOT_RUN',
      configuredTimeouts:{actionMs:ACTION_TIMEOUT_MS,navigationMs:NAVIGATION_TIMEOUT_MS},
      status:failures.length?'FAIL':'PASS',results,failures,traffic};
    fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(receipts,null,2)+'\n');
    const files=fs.readdirSync(out).filter(f=>fs.statSync(path.join(out,f)).isFile());
    fs.writeFileSync(path.join(out,'browser-sha256.json'),JSON.stringify(Object.fromEntries(files.map(f=>[f,createHash('sha256').update(fs.readFileSync(path.join(out,f))).digest('hex')])),null,2)+'\n');
  }
}
main().catch(e=>{console.error(e.stack);process.exitCode=1;});
