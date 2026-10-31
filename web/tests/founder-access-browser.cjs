/** Cloud synthetic UI regression. All API traffic is intercepted; no real grants, spend, or posts. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { readFileSync, mkdirSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');
assert.equal(process.platform, 'linux', 'Use JCB cloud validation');
assert.equal(process.env.CI, 'true', 'Cloud CI required');
const base = 'http://127.0.0.1:4439';
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures/wp04a-workspace.json'), 'utf8'));
const wid = fixture.snapshot.state.workspace.id;
const actor = '00000000-0000-0000-0000-000000000001';
const out = join(__dirname, '../../.jcb-artifacts/founder-access');
mkdirSync(out, { recursive: true });
const app = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '-p', '4439', '-H', '127.0.0.1'], { cwd: join(__dirname, '..'), env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
app.stdout.on('data', b => process.stdout.write(b));
app.stderr.on('data', b => process.stderr.write(b));
const trialTerms = { id: 'trial-v1', plan: 'trial', label: 'Trial', version: 1, status: 'active', currency: 'usd', priceCents: 0, entitlements: { writingBatches: 10, mediaCredits: 1, connectedAccounts: 2, members: 1, storageMb: 200 } };
const studioTerms = { ...trialTerms, id: 'studio-v1', plan: 'studio', label: 'Studio', priceCents: 1000 };
const customerEntitlement = { planTermsId: trialTerms.id, writingBatchesRemaining: 10, mediaCreditsRemaining: 1, connectedAccounts: 2, members: 1, storageMb: 200, resetsAt: Date.now()/1000+864000, source: 'trial', version: 1 };
const founderEntitlement = { planTermsId: null, writingBatchesRemaining: null, mediaCreditsRemaining: null, connectedAccounts: null, members: null, storageMb: null, resetsAt: null, source: 'internal', unlimited: true, version: 1 };
const checks = [];
(async () => {
  let browser;
  try {
    let ready = false;
    for (let n=0;n<120;n++) {
      if (await fetch(base).then(r=>r.status<500).catch(()=>false)) { ready=true; break; }
      await new Promise(r=>setTimeout(r,500));
    }
    assert.ok(ready, 'Next application started');
    browser = await chromium.launch({ headless: true });
    for (const width of [1440,390]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
      await context.addCookies([{name:'postriff_dev',value:'1',url:base}]);
      await context.addInitScript(({actor,wid})=>{ localStorage.setItem('postriff-dev-principal',actor); localStorage.setItem('postriff-workspace',wid); },{actor,wid});
      const page = await context.newPage();
      page.setDefaultTimeout(30000);
      const errors = [];
      page.on('pageerror', e=>errors.push(e.message));
      let currentEntitlement = founderEntitlement;
      let apiWrites = 0;
      await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url()), p = url.pathname;
        if (url.origin !== base) return route.abort();
        if (!p.startsWith('/api/')) return route.continue();
        assert.equal(request.method(),'GET','Rendering founder billing never performs mutations');
        const send = body=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
        if (p==='/api/catalog') return send({authMode:'dev',execution:'cloud-synthetic',platforms:[]});
        if (p==='/api/me') return send({ userId:actor,displayName:'Synthetic owner',preferences:{timeZone:'UTC',locale:'en'},mfa:{} });
        if (p==='/api/workspaces') return send({workspaces:[{workspaceId:wid,name:'Synthetic founder workspace',plan:'studio',membership:fixture.snapshot.membership,memberCounts:{owner:1}}]});
        if (p===`/api/workspaces/${wid}`) return send(fixture.snapshot);
        if (p.endsWith('/usage')) return send({entitlement:currentEntitlement,subscription:null,budget:null,overage:'stop',ledger:[],planTerms:[trialTerms,studioTerms],note:'Synthetic UI proof',lifecycle:{status:currentEntitlement===founderEntitlement?'internal':'trial',canPublish:true},billing:{provider:'fixture',checkoutAvailable:true,portalAvailable:true},membership:fixture.snapshot.membership});
        if (p.endsWith('/channels')) return send({channels:[],providers:[]});
        if (p.endsWith('/members')) return send({members:[fixture.snapshot.membership]});
        return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'Unneeded synthetic endpoint'})});
      });
      await page.goto(base+'/app/account/billing',{waitUntil:'domcontentloaded'});
      try { await page.getByRole('heading',{name:'Founder access',exact:true}).waitFor(); } catch (error) { console.error('FOUNDER_BROWSER_DIAGNOSTIC '+JSON.stringify({url:page.url(),text:(await page.locator('body').innerText()).slice(0,1800),errors})); throw error; }
      const region = page.getByRole('region',{name:'Founder access',exact:true});
      assert.equal(await region.getByText('Unlimited',{exact:true}).count(),5);
      for (const label of ['Writing','Media','Connected accounts','Members','Storage']) assert.equal(await region.getByText(label,{exact:true}).count(),1);
      await region.getByText('Your spending limits and post approvals still apply.',{exact:false}).waitFor();
      assert.equal(await page.locator('main').getByRole('heading',{name:'Plans',exact:true}).count(),0);
      assert.equal(await page.locator('main').getByText('Choose a plan',{exact:true}).count(),0);
      assert.equal(await page.getByRole('heading',{name:'Something went wrong',exact:true}).count(),0);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
      await page.screenshot({path:join(out,`CLOUD-SYNTHETIC-founder-${width}.png`),fullPage:true});
      const pixels=readFileSync(join(out,`CLOUD-SYNTHETIC-founder-${width}.png`));
      assert.ok(pixels.length<1024*1024);
      process.stdout.write('FOUNDER_ACCESS_IMAGE '+JSON.stringify({name:`CLOUD-SYNTHETIC-founder-${width}.png`,base64:pixels.toString('base64')})+'\n');
      checks.push({scene:'founder-null-allowances',width,unlimitedAllowances:5,customerCheckoutShown:false,passed:true});
      currentEntitlement = customerEntitlement;
      await page.reload({waitUntil:'domcontentloaded'});
      await page.locator('[data-tour="billing-plan"]').getByRole('heading',{name:'Trial',exact:true}).waitFor();
      await page.locator('main').getByRole('heading',{name:'Usage',exact:true}).waitFor();
      await page.locator('main').getByRole('heading',{name:'Plans',exact:true}).waitFor();
      assert.equal(await page.getByRole('heading',{name:'Founder access',exact:true}).count(),0);
      checks.push({scene:'customer-trial-preserved',width,passed:true});
      currentEntitlement = {...customerEntitlement,source:'internal',unlimited:false,storageMb:null};
      await page.reload({waitUntil:'domcontentloaded'});
      await page.locator('main').getByRole('heading',{name:'Usage',exact:true}).waitFor();
      assert.equal(await page.getByRole('heading',{name:'Founder access',exact:true}).count(),0);
      assert.equal(await page.getByRole('heading',{name:'Something went wrong',exact:true}).count(),0);
      await page.locator('main').getByText('Unavailable',{exact:true}).first().waitFor();
      assert.deepEqual(errors,[]);
      assert.equal(apiWrites,0);
      checks.push({scene:'no-unlimited-without-explicit-server-grant',width,passed:true});
      await context.close();
    }
    const result={execution:'CLOUD_SYNTHETIC_UI',checks,externalRequestsAllowed:false,productionWrites:0};
    writeFileSync(join(out,'CLOUD-SYNTHETIC-founder-access.json'),JSON.stringify(result,null,2)+'\n');
    process.stdout.write('FOUNDER_ACCESS_RESULT '+JSON.stringify(result)+'\n');
  } catch (error) {
    process.stderr.write(error.stack+'\n');process.exitCode=1;
  } finally {
    if (browser) await browser.close();
    app.kill('SIGTERM');
  }
})();
