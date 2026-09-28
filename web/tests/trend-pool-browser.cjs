/** Affected Home/Weekly checks only. Explicit synthetic API fixtures, native IntersectionObserver.
 * These results are separate from the frozen 201 layout / 46 Tier C / 30 exposure receipts.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { chromium } = require('playwright');
const { fixtures } = require('./trend-fixtures.cjs');
const workspaceFixture = require('./fixtures/wp04a-workspace.json');
const t = require('./trend-contract.cjs').loadTypes();
const base = process.env.TREND_WEB_URL, out = process.env.TREND_EVIDENCE_DIR;
assert.ok(base && new URL(base).hostname === '127.0.0.1' && out);
fs.mkdirSync(out, { recursive: true });
const results = [];
const pass = (width, name) => { results.push({ width, name, pass: true }); console.log(`PASS ${width} ${name}`); };
async function main() {
 const browser = await chromium.launch({ headless: true });
 try {
  for (const width of [1440, 390]) {
   const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
   const f=fixtures(), snapshot=structuredClone(workspaceFixture.snapshot), wid=snapshot.state.workspace.id;
   const ops = [3, 1, 2].map(n => ({ ...structuredClone(f.opportunity), id: randomUUID(), trend_id: randomUUID(), trust_receipt_id: randomUUID(), title: `Demo data: Original angle ${n} 🎵`, uncertainty: 'Audience response is unknown.' }));
   const root=`/api/workspaces/${wid}/coworker/trends`;
   let flags={}, mode='normal', dismissed=new Set(), accepted=new Set();
   const calls=[], errors=[], external=[];
   const slot={id:'synthetic-planned-slot', day:'2026-09-28', localTime:'09:00', platform:'Bluesky', account:'Demo destination', language:'en', contentType:'personal_reflection', goal:'Synthetic goal', angle:'Keep my independently planned post', status:'needs_input', reason:null, question:'What did you notice?', variantId:null, quality:null, creative:null};
   const recipe={id:'synthetic-recipe', name:'Existing weekly plan', status:'active', version:1, destinations:[], goals:[], contentMix:{}, timeZone:'UTC', planningDay:1, planningHour:9};
   const week={id:'synthetic-week',recipeId:recipe.id,weekOf:'2026-09-28',state:'ready_for_review',blockedReason:null,slots:[slot]};
   const weekBefore=JSON.stringify(week);
      await context.addCookies([
        { name: 'postriff_dev', value: '1', url: base },
        { name: 'postriff_theme', value: 'rafii', url: base }
      ]);
      const tours = [
        ...fs
          .readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8')
          .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
      ].map((m) => m[1]);
      await context.addInitScript(
        ({ tours }) => {
          const principal = '00000000-0000-0000-0000-000000000001';
          localStorage.setItem('postriff-dev-principal', principal);
          const state = JSON.stringify({
            completed: {},
            dismissed: Object.fromEntries(tours.map((id) => [id, 1])),
            nudged: Object.fromEntries(tours.map((id) => [id, 1]))
          });
          localStorage.setItem('postriff-onboarding', state);
          localStorage.setItem('postriff-onboarding:' + principal, state);
          window.syntheticVisibility = 'hidden';
          Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.syntheticVisibility });
        }, { tours }
      );
   await context.route('**/*', async route => {
    const req=route.request(), url=new URL(req.url()), p=url.pathname;
    if(url.origin!==base){external.push(url.origin);return route.abort();}
    if(!p.startsWith('/api/'))return route.continue();
    const body=req.method()==='POST'?req.postDataJSON():null;
    calls.push({path:p,query:url.search,method:req.method(),body});
    const send=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    if(p===root+'/opportunities'){
     assert.ok(['home','weekly'].includes(url.searchParams.get('pool')));
     assert.equal(url.searchParams.get('limit'),'3');
     if(mode==='error')return send({code:'source_unavailable'},503);
     const items=mode==='empty'?[]:ops.filter(o=>!dismissed.has(o.id)&&!accepted.has(o.id));
     const displayed=url.searchParams.get('pool')==='weekly'?items.map(o=>({...o,uncertainty:'Unqualified interpretation. Audience response is unknown.'})):items;
     return send({...f.envelope(displayed),execution_state:mode==='unavailable'?'unavailable':mode==='partial'?'partial':'stored_result',exposure_token:'explicit-synthetic-'+items.map(o=>o.id).join(',')});
    }
    if(p===root+'/exposures'){
     t.exposureInputSchema.parse(body);
     const ids=body.exposure_token.replace('explicit-synthetic-','').split(',');
     assert.deepEqual(body.eligible_candidates,ids.map(id=>({opportunity_id:id,revision:1})));
     return send(f.envelope({exposure_id:randomUUID(),event_id:body.event_id,opportunity_id:body.opportunity_id,opportunity_revision:body.opportunity_revision,trust_receipt_id:body.trust_receipt_id,context_digest:body.context_digest,measurement:'client_reported_view',eligible_candidate_count:ids.length,recorded_at:new Date().toISOString(),expires_at:new Date(Date.now()+120000).toISOString(),existing:false}));
    }
    if(p.endsWith('/dismiss')){
     t.dismissOpportunityInputSchema.parse(body);
     const id=p.split('/').at(-2);dismissed.add(id);
     return send(f.envelope({opportunity_id:id,revision:body.revision,state:'dismissed',exposure_id:body.exposure_id??null,existing:false}));
    }
    if(p.endsWith('/accept')){
     t.acceptOpportunitySchema.parse(body);
     const id=p.split('/').at(-2);accepted.add(id);snapshot.revision++;
     snapshot.state.sources.push({id:'explicit-synthetic-source',kind:'research',title:'Demo accepted opportunity',text:'Explicit synthetic source',selected:false,active:true,origin:{kind:'trend_opportunity',trendLineage:{opportunity_id:id}}});
     return send(f.envelope({source_id:'explicit-synthetic-source',href:'/app/ideas?source=explicit-synthetic-source',verified:true,existing:false}));
    }
    if(p.endsWith('/coworker/weekly'))return send({recipes:[recipe],weeks:[week]});
    if(p.endsWith('/coworker/weekly/weeks/'+week.id))return send({week,counts:{needs_input:1},queueHref:'/app/queue'});
    if(p==='/api/ideas/models')return send({models:[{id:'deterministic-preview',label:'Synthetic preview',qualified:true,costClass:'none',reasoning:[{id:'quick',available:true}]}],reasoning:[{id:'quick',available:true}],agents:[]});
        if (p === '/api/auth/config')
          return send({ provider: 'dev', execution: 'dev-synthetic', flow: 'dev' });
        if (p === '/api/bootstrap') return send({ workspaceId: wid });
        if (p === '/api/catalog')
          return send({
            authMode: 'dev',
            execution: 'dev-synthetic',
            platforms: ['Bluesky'],
            languages: ['en'],
            presets: [],
            voices: [],
            phase2: true,
            templates: [],
            routes: [],
            profileMetadata: {}
          });
        if (p === '/api/workspaces')
          return send({
            workspaces: [
              {
                workspaceId: wid,
                membership: snapshot.membership,
                name: 'Synthetic exposure fixture',
                plan: 'studio',
                memberCounts: { owner: 1 }
              }
            ]
          });
        if (p === '/api/me')
          return send({
            userId: '00000000-0000-0000-0000-000000000001',
            displayName: 'Synthetic owner',
            preferences: { timeZone: 'UTC', locale: 'en', alertNewDevice: false },
            mfa: {}
          });
        if (p === `/api/workspaces/${wid}`) return send(snapshot);
        if (p.endsWith('/coworker/status'))
          return send({
            flags,
            weekly: { recipes: 0, weeks: 0 },
            notifications: { enabled: false }
          });
        if (p.endsWith('/usage'))
          return send({
            subscription: { plan: 'studio', status: 'active' },
            trial: {},
            balances: []
          });
        if (p.endsWith('/memory')) return send(workspaceFixture.memory);
        if (p.endsWith('/memory/proposals'))
          return send({ pending: [], recent: [], learning: { items: [] } });
        if (p.endsWith('/ideas/conversations')) return send({ conversations: [] });
        if (p.endsWith('/channels'))
          return send({ channels: snapshot.state.phase2.channels, providers: [] });
        if (p.endsWith('/audit')) return send({ entries: [] });
        if (p.endsWith('/time-savings')) return send({});
    return send({error:'Unavailable unrelated synthetic route'},404);
   });
   const page=await context.newPage();page.setDefaultTimeout(20000);
   page.on('pageerror',e=>errors.push(e.message));
   const pool=p=>page.locator(`[data-trend-pool="${p}"]`);
   const trendCalls=()=>calls.filter(c=>c.path.startsWith(root));
   const exposures=()=>calls.filter(c=>c.path===root+'/exposures');
   const visibility=state=>page.evaluate(state=>{window.syntheticVisibility=state;document.dispatchEvent(new Event('visibilitychange'));},state);
   const load=async p=>{await page.goto(base+(p==='home'?'/app':'/app/weekly'),{timeout:180000});await pool(p).waitFor();await pool(p).scrollIntoViewIfNeeded();};
   const audit=async p=>{
    await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
    const violations=await page.evaluate(async selector=>(await axe.run(document.querySelector(selector))).violations.filter(v=>['serious','critical'].includes(v.impact)),`[data-trend-pool="${p}"]`);
    assert.deepEqual(violations,[]);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   };
   try {
    for(const route of ['/app','/app/weekly']){
     await page.goto(base+route,{timeout:180000});await page.locator('main').waitFor();await page.waitForTimeout(750);
     assert.equal(await page.locator('[data-trend-pool]').count(),0);
    }
    assert.equal(trendCalls().length,0);pass(width,'default OFF: both surfaces issue zero trend calls');
    flags={...f.flags,RAFII_TREND_TRUST_RECEIPTS_ENABLED:false};
    await page.goto(base+'/app');await page.waitForTimeout(750);
    assert.equal(trendCalls().length,0);pass(width,'receipt flag OFF: pool remains unmounted');
    flags=f.flags;await load('home');
    assert.deepEqual(await pool('home').locator('[data-pool-opportunity]').evaluateAll(els=>els.map(e=>e.dataset.poolOpportunity)),ops.map(o=>o.id));
    assert.equal(await pool('home').locator('h3').first().innerText(),ops[0].title);
    await page.waitForTimeout(650);assert.equal(exposures().length,0);
    pass(width,'Home uses exact bounded query and server order; hidden GET is not exposure');
    await visibility('visible');await pool('home').locator('h3').first().scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>document.visibilityState==='visible');
    await page.waitForTimeout(800);assert.ok(exposures().length>0);
    assert.equal(exposures()[0].body.eligible_candidates.length,3);
    pass(width,'Home visible native card reports signed three-candidate subset');
    await audit('home');await page.screenshot({path:path.join(out,`home-${width}.png`),fullPage:true});
    pass(width,'Home reduced-motion axe/viewport and native emoji');
    mode='empty';await load('home');await pool('home').getByText('No fresh conversations to suggest right now.').waitFor();
    pass(width,'Home legitimate empty has no synthetic fallback');
    mode='error';await load('home');await pool('home').getByText('Sources are unavailable',{exact:true}).waitFor();
    pass(width,'Home service error remains distinct from empty');
    mode='unavailable';await load('home');await pool('home').getByText('Evidence is unavailable',{exact:true}).waitFor();
    assert.equal(await pool('home').locator('[data-pool-opportunity]').count(),0);
    pass(width,'unavailable envelope suppresses delivered claims');
    mode='partial';await load('weekly');await pool('weekly').getByText('Some coverage is missing',{exact:true}).waitFor();
    assert.equal(await page.getByRole('tab',{name:'Opportunities',exact:true}).count(),0);
    await pool('weekly').getByText('Keep in mind: Unqualified interpretation. Audience response is unknown.',{exact:true}).first().waitFor();
    await page.getByLabel('What did you notice?',{exact:true}).waitFor();
    pass(width,'Weekly works with listening OFF; partial and unqualified uncertainty remain visible');
    const card=pool('weekly').getByRole('region',{name:'Original contribution'}).first();
    await visibility('visible');await card.getByRole('button',{name:'Not relevant'}).scrollIntoViewIfNeeded();await page.waitForTimeout(700);
    await audit('weekly');await page.screenshot({path:path.join(out,`weekly-${width}.png`),fullPage:true});
    pass(width,'Weekly reduced-motion axe/viewport preserves existing slot');
    const dismiss=card.getByRole('button',{name:'Not relevant'});await dismiss.focus();await page.keyboard.press('Enter');
    await page.waitForFunction(()=>document.querySelectorAll('[data-trend-pool="weekly"] [data-pool-opportunity]').length===2);
    await page.waitForFunction(()=>document.activeElement?.tagName==='H2'&&document.activeElement.textContent==='Ideas for this week');
    assert.equal(calls.filter(c=>c.path.endsWith('/dismiss')).length,1);
    pass(width,'Weekly explicit dismissal removes candidate and restores keyboard focus');
    const next=pool('weekly').getByRole('region',{name:'Original contribution'}).first();
    await next.locator('summary').filter({hasText:'Develop this idea'}).click();
    await next.getByLabel('Destination account').selectOption(snapshot.state.phase2.channels.find(c=>c.platform==='LinkedIn').id);
    await next.getByLabel('Your goal').fill('Explicit synthetic goal');
    await next.getByRole('button',{name:'Save to Ideas',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-trend-pool="weekly"] [data-pool-opportunity]').length===1);
    assert.equal(calls.filter(c=>c.path.endsWith('/accept')).length,1);
    assert.equal(snapshot.state.sources.at(-1).id,'explicit-synthetic-source');
    await pool('weekly').getByRole('link',{name:'Review source and create original post'}).waitFor();
    assert.ok(calls.some(c=>c.path===`/api/workspaces/${wid}`&&c.method==='GET'));
    assert.equal(JSON.stringify(week),weekBefore);
    assert.equal(calls.filter(c=>c.method==='POST'&&!c.path.startsWith(root)).length,0);
    pass(width,'Weekly reuses accept/snapshot refresh; no prepare/generate/slot mutation');
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    pass(width,'no runtime errors or unexpected egress');
   } catch(error) {
    fs.writeFileSync(path.join(out,`failure-${width}.json`),JSON.stringify({error:String(error),calls,errors,external,text:await page.locator('body').innerText()},null,2));
    await page.screenshot({path:path.join(out,`failure-${width}.png`),fullPage:true});throw error;
   } finally {await context.close();}
  }
 } finally {await browser.close();fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({execution:'explicit_synthetic_intercepted_pool_browser',results},null,2));}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
