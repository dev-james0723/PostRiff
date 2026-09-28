/** Tier C: real loopback Next -> Python -> PostgreSQL. No API response interception.
 * Identity, observations, destination and saved Lab draft fixtures are explicitly synthetic.
 * Lab diagnostics, linkage, edits, revisions and conflicts use the real service and database.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { chromium } = require('playwright');
const { z } = require('zod');
const t = require('./trend-contract.cjs').loadTypes();
const base = process.env.TREND_WEB_URL;
assert.ok(base && new URL(base).hostname === '127.0.0.1', 'Explicit loopback web origin required');
const out = process.env.TREND_EVIDENCE_DIR;
assert.ok(out && process.env.TREND_LIVE_SEED, 'Explicit isolated seed/evidence paths required');
const seed = JSON.parse(fs.readFileSync(process.env.TREND_LIVE_SEED, 'utf8'));
assert.equal(seed.execution, 'real_api_postgresql_synthetic_identity_and_seed');
const results = [],
  traffic = [];
const pass = (name, detail) => {
  results.push({ name, pass: true, detail });
  process.stdout.write('PASS ' + name + '\n');
};
async function checkPool({page,row,root,api,headers,other}) {
 const tag=`${row.scenario} ${row.width}`;
 const ws=`/api/workspaces/${row.workspace_id}`;
 const read=async route=>{const r=await api('GET',route);assert.equal(r.status(),200,await r.text());assert.match(r.headers()['cache-control'],/no-store/);return r.json();};
 const before=await read(ws);
 const weeklyBefore=await read(ws+'/coworker/weekly');
 for(const pool of ['home','weekly']){
  const route=root+`/opportunities?pool=${pool}&limit=3`;
  for(const [custom,status] of [[{'X-PostRiff-Request':'founder-alpha'},401],[{...headers,Authorization:'Bearer dev:'+other.principal},404]]){
   const denied=await api('GET',route,undefined,custom);assert.equal(denied.status(),status);assert.match(denied.headers()['cache-control'],/no-store/);
  }
 }
 pass(tag+' actual pool requires token and tenant membership');
 const home=t.opportunitiesResponseSchema.parse(await read(root+'/opportunities?pool=home&limit=3'));
 assert.deepEqual(home.data,[]);assert.equal(home.exposure_token,null);assert.equal(home.next_cursor,null);
 await page.goto(base+'/app');
 const homePreview=page.locator('[data-trend-pool="home"]');
 await homePreview.getByText('No fresh conversations to suggest right now.').waitFor();
 assert.equal(await homePreview.locator('[data-pool-opportunity]').count(),0);
 await homePreview.scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(out,`real-home-empty-${row.scenario}-${row.width}.png`),fullPage:false});
 pass(tag+' shadow inference abstains on Home, without invented qualification');
 const listed=t.opportunitiesResponseSchema.parse(await read(root+'/opportunities?pool=weekly&limit=3'));
 assert.deepEqual(listed.data.map(o=>o.id),[row.opportunity_id]);assert.equal(listed.data[0].workspace_fit.sufficient,true);assert.equal(listed.next_cursor,null);
 assert.ok(listed.exposure_token);assert.match(listed.data[0].uncertainty,/Unqualified interpretation/);
 const exposed=page.waitForResponse(r=>r.url().endsWith(root+'/exposures')&&r.status()===200);
 await page.goto(base+'/app/weekly');
 const pool=page.locator('[data-trend-pool="weekly"]');
 const card=pool.getByRole('region',{name:'Original contribution'});
 await card.waitFor();await card.scrollIntoViewIfNeeded();
 await page.getByLabel('What did you notice?',{exact:true}).waitFor();
 await card.getByText('Keep in mind: '+listed.data[0].uncertainty,{exact:true}).waitFor();
 const exposureResponse=await exposed;
 const exposure=t.envelopeSchema(t.exposureSchema).parse(await exposureResponse.json()).data;
 const body=t.exposureInputSchema.parse(exposureResponse.request().postDataJSON());
 assert.deepEqual(body.eligible_candidates,[{opportunity_id:row.opportunity_id,revision:1}]);
 assert.equal(exposure.measurement,'client_reported_view');
 assert.equal(exposure.opportunity_id,row.opportunity_id);
 pass(tag+' real Weekly shows executable unqualified option and signed visible exposure');
 const quiet=t.opportunitiesResponseSchema.parse(await read(root+'/opportunities?pool=weekly&limit=3'));
 assert.deepEqual(quiet.data,[]);assert.equal(quiet.exposure_token,null);
 assert.equal((await read(root+'/opportunities')).data.length,1);
 await card.waitFor();
 pass(tag+' real exposure cooldown suppresses future pool delivery but leaves current form and Radar');
 await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
 const violations=await page.evaluate(async()=>(await axe.run(document.querySelector('[data-trend-pool="weekly"]'))).violations.filter(v=>['serious','critical'].includes(v.impact)));
 assert.deepEqual(violations,[]);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
 await page.screenshot({path:path.join(out,`real-weekly-${row.scenario}-${row.width}.png`),fullPage:false});
 if(row.scenario==='pool_accept'){
  await card.locator('summary').filter({hasText:'Develop this idea'}).click();
  await card.getByLabel('Destination account').selectOption(row.channel_id);
  await card.getByLabel('Your goal').fill('Synthetic weekly opportunity browser check only');
  const accepted=page.waitForResponse(r=>r.url().endsWith('/opportunities/'+row.opportunity_id+'/accept'));
  await card.getByRole('button',{name:'Save to Ideas',exact:true}).click();
  const response=await accepted;assert.equal(response.status(),200,await response.text());
  const result=t.envelopeSchema(t.acceptedOpportunitySchema).parse(await response.json()).data;
  assert.equal(response.request().postDataJSON().exposure_id,exposure.exposure_id);
  await pool.getByText('No fresh opportunities for this week.').waitFor();
  const link=pool.getByRole('link',{name:'Review source and create original post'});
  await link.waitFor();assert.equal(await link.getAttribute('href'),result.href);
  const stored=await read(ws);
  const source=stored.state.sources.find(s=>s.id===result.source_id);
  assert.equal(source.origin.trendLineage.opportunity_id,row.opportunity_id);
  assert.equal(source.origin.trendLineage.trust_receipt_id,row.receipt_id);
  await link.click();await page.waitForURL('**/app/ideas?source='+result.source_id);
  const inspector=row.width===390?page.getByRole('dialog'):page.getByRole('complementary',{name:'Source inspector'});
  await inspector.getByText(source.title,{exact:true}).first().waitFor();
  await page.reload();await inspector.getByText(source.title,{exact:true}).first().waitFor();
  pass(tag+' existing accept refreshes snapshot and preserves Ideas link after pool removal, immediate and reload');
 }else{
  const pending=page.waitForResponse(r=>r.url().endsWith('/opportunities/'+row.opportunity_id+'/dismiss'));
  await card.getByRole('button',{name:'Not relevant'}).focus();await page.keyboard.press('Enter');
  const response=await pending;assert.equal(response.status(),200,await response.text());
  const dismissed=t.envelopeSchema(t.dismissedOpportunitySchema).parse(await response.json()).data;
  assert.equal(dismissed.exposure_id,exposure.exposure_id);assert.equal(dismissed.revision,1);
  await pool.getByText('No fresh opportunities for this week.').waitFor();
  assert.equal(await page.evaluate(()=>document.activeElement?.textContent),'Ideas for this week');
  await page.reload();await pool.getByText('No fresh opportunities for this week.').waitFor();
  const stored=await read(ws);assert.deepEqual(stored.state.sources,[]);assert.deepEqual(stored.state.variants,[]);
  pass(tag+' existing dismissal persists after reload, restores focus, creates no source or draft');
 }
 assert.deepEqual(await read(ws+'/coworker/weekly'),weeklyBefore);
 const after=await read(ws);assert.deepEqual(after.state.coworker.weekly,before.state.coworker.weekly);assert.deepEqual(after.state.variants,[]);
 assert.ok(!traffic.some(r=>r.path===ws+'/actions'));
 pass(tag+' paused existing plan/slot unchanged; axe/viewport passes; no draft mutation');
}
async function main() {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {})
  });
  try {
    for (const row of [...seed.seeds, ...seed.lab_seeds, ...seed.dismiss_seeds]) {
      const context = await browser.newContext({
        viewport: { width: row.width, height: 1000 },
        reducedMotion: 'reduce'
      });
      const other = seed.seeds.find((s) => s.principal !== row.principal);
      const root = `/api/workspaces/${row.workspace_id}/coworker/trends`;
      const headers = {
        Authorization: 'Bearer dev:' + row.principal,
        'X-PostRiff-Request': 'founder-alpha',
        Origin: base
      };
      const external = [],
        errors = [];
      // This guard only blocks external navigation. Every same-origin request continues unchanged.
      await context.route('**/*', (route) => {
        const url = new URL(route.request().url());
        if (url.origin === base) return route.continue();
        external.push(url.origin);
        return route.abort();
      });
      await context.addCookies([
        { name: 'postriff_dev', value: '1', url: base },
        { name: 'postriff_dev_principal', value: row.principal, url: base },
        { name: 'postriff_theme', value: 'rafii', url: base }
      ]);
      const tours = [
        ...fs
          .readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8')
          .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
      ].map((m) => m[1]);
      await context.addInitScript(
        ({ principal, tours }) => {
          localStorage.setItem('postriff-dev-principal', principal);
          const state = JSON.stringify({
            completed: {},
            dismissed: Object.fromEntries(tours.map((t) => [t, 1])),
            nudged: Object.fromEntries(tours.map((t) => [t, 1]))
          });
          localStorage.setItem('postriff-onboarding', state);
          localStorage.setItem('postriff-onboarding:' + principal, state);
        },
        { principal: row.principal, tours }
      );
      const page = await context.newPage();
      page.setDefaultTimeout(25000);
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('response', (response) => {
        const url = new URL(response.url());
        if (url.pathname.includes('/coworker/trends') || url.pathname.endsWith('/actions'))
          traffic.push({
            width: row.width,
            method: response.request().method(),
            path: url.pathname,
            status: response.status(),
            cache: response.headers()['cache-control']
          });
      });
      const api = async (method, route, data, custom = headers) =>
        context.request.fetch(base + route, { method, headers: custom, data });
      try {
        await checkPool({page,row,root,api,headers,other});
        assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
        pass(`${row.scenario} ${row.width} zero browser egress or runtime errors`);
      } catch (error) {
        fs.writeFileSync(
          path.join(out, `real-failure-${row.scenario}-${row.width}.txt`),
          JSON.stringify({ error: String(error), errors, traffic }, null, 2) +
            '\n' +
            (await page
              .locator('body')
              .innerText()
              .catch(() => ''))
        );
        await page
          .screenshot({
            path: path.join(out, `real-failure-${row.scenario}-${row.width}.png`),
            fullPage: false
          })
          .catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(out, 'browser-results.json'),
      JSON.stringify(
        { execution: seed.execution, trend_api_interception: false, results, traffic },
        null,
        2
      )
    );
  }
}
main().catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
