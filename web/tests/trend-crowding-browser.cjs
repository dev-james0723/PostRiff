/** Explicit synthetic Crowding fixtures. No production import, API/DB proof, or provider calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixtures } = require('./trend-fixtures.cjs');
const t = require('./trend-contract.cjs').loadTypes();
const workspaceFixture = require('./fixtures/wp04a-workspace.json');
const results = [];
const pass = name => { results.push({name,pass:true}); console.log('PASS',name); };
function crowdingFixture() {
 const f=fixtures(), sample={unclassified_count:20,classification_coverage:0.8,total_patterns:2,patterns_truncated:false,patterns:[
  {pattern_id:'native-pattern-練琴🎹-'+('a'.repeat(130)),count:20,classified_share:0.25,unique_creator_support:12,interval:{lower:0.1,upper:0.4,method:'creator_cluster_bootstrap_v1',level:0.95}},
  {pattern_id:'opposing-native-pattern',count:60,classified_share:0.75,unique_creator_support:0,interval:null}
 ],copy_support:'unassessed',redundant_count:null,creator:null};
 f.saturation.dimensions[0].sample_details=structuredClone(sample);
 f.saturation.dimensions[1].sample_details={...structuredClone(sample),classification_coverage:0,unclassified_count:0,patterns:[],total_patterns:0,copy_support:'assessed',redundant_count:0,creator:{known_author_count:0,author_coverage:0,largest_creator_share:0,effective_creator_count:0}};
 f.saturation.dimensions[1].eligible=0;f.saturation.dimensions[1].classified=0;f.saturation.dimensions[1].metric={...f.saturation.dimensions[1].metric,value:null,null_reason:'No classified observations',denominator:'No classified observations'};
 f.saturation.dimensions[2].sample_details={...structuredClone(sample),copy_support:'assessed',redundant_count:19};
 f.saturation.dimensions[2].metric={...f.saturation.dimensions[2].metric,value:0.2375,unit:'ratio',definition_id:'hook_copy_redundancy'};
 f.saturation.dimensions[4].sample_details={...structuredClone(sample),classification_coverage:null,total_patterns:25,patterns_truncated:true,creator:{known_author_count:80,author_coverage:null,largest_creator_share:null,effective_creator_count:null}};
 f.saturation.dimensions[4].sample_details.patterns[0].pattern_id=['threads','native-key-界🎹-'+('x'.repeat(140))];
 return f;
}
function offline() {
 const f=crowdingFixture(),d=f.saturation.dimensions[0].sample_details;
 const legacy=fixtures().saturation;assert.deepEqual(t.saturationSchema.parse(legacy),legacy);
 pass('legacy optional sample_details remains compatible');
 assert.deepEqual(t.saturationSampleDetailsSchema.parse(d),d);
 t.saturationSchema.parse(f.saturation);pass('native string/pair IDs, intervals, null uncertainty and zero creator values preserved');
 const exact20={...d,patterns:Array.from({length:20},()=>d.patterns[0])};t.saturationSampleDetailsSchema.parse(exact20);
 for(const bad of [{...d,patterns:[...exact20.patterns,d.patterns[0]]},{...d,unclassified_count:-1},{...d,copy_support:'inferred'},{...d,extra:true},{...d,patterns:[{...d.patterns[0],pattern_id:['a','b','c']}]},{...d,patterns:[{...d.patterns[0],interval:{lower:null,upper:0.4,method:'x',level:0.95}}]}])assert.equal(t.saturationSampleDetailsSchema.safeParse(bad).success,false);
 pass('strict bounded sample details reject invalid cardinality, invented state and extra fields');
 assert.equal(t.saturationSampleDetailsSchema.safeParse({...d,classification_coverage:null,redundant_count:null}).success,true);
 assert.equal(t.saturationSampleDetailsSchema.safeParse({...d,classification_coverage:0,redundant_count:0}).success,true);pass('unknown and numeric zero are distinct wire values');
}
async function browserChecks() {
 const base=process.env.TREND_WEB_URL,out=process.env.TREND_EVIDENCE_DIR;
 assert.ok(base&&new URL(base).hostname==='127.0.0.1'&&out,'Explicit loopback URL/evidence required');fs.mkdirSync(out,{recursive:true});
 const {chromium}=require('playwright'),browser=await chromium.launch({headless:true});
 try {for(const width of [1440,390]) {
  const f=crowdingFixture(),snapshot=structuredClone(workspaceFixture.snapshot),wid=snapshot.state.workspace.id,root=`/api/workspaces/${wid}/coworker/trends`;
  const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce',colorScheme:width===390?'dark':'light'});
  let flags={},mode='normal';const calls=[],egress=[],errors=[];
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_theme',value:'rafii',url:base}]);
  const tours=[...fs.readFileSync(path.join(__dirname,'../src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
  await context.addInitScript(({tours,dark})=>{const id='00000000-0000-0000-0000-000000000001';localStorage.setItem('postriff-dev-principal',id);localStorage.setItem('theme',dark?'dark':'light');const s=JSON.stringify({completed:{},dismissed:Object.fromEntries(tours.map(t=>[t,1])),nudged:Object.fromEntries(tours.map(t=>[t,1]))});localStorage.setItem('postriff-onboarding',s);localStorage.setItem('postriff-onboarding:'+id,s);},{tours,dark:width===390});
  await context.route('**/*',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname;if(u.origin!==base){egress.push(u.origin);return route.abort();}if(!p.startsWith('/api/'))return route.continue();
   calls.push({method:req.method(),path:p});const send=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
   if(p.startsWith(root)) {
    assert.equal(req.method(),'GET','Crowding never mutates');assert.match(req.headers().authorization,/^Bearer dev:/);assert.equal(req.headers()['x-postriff-request'],'founder-alpha');
    if(p===root)return send(f.envelope([f.trend]));
    if(p.endsWith('/opportunities'))return send(f.envelope([]));
    if(p.endsWith('/receipts/synthetic-receipt'))return mode==='revoked'?send({code:'evidence_unavailable'},410):send(f.envelope(f.receipt));
    if(p.endsWith('/saturation')){const data=structuredClone(f.saturation);if(mode==='legacy')data.dimensions.forEach(d=>delete d.sample_details);if(mode==='invalid')data.dimensions[0].sample_details.extra='forbidden';return send({...f.envelope(data),execution_state:mode==='unavailable'?'unavailable':'stored_result'});}
    return send(f.envelope([]));
   }
   if(p.endsWith('/coworker/status'))return send({flags,trend_beta:{state:flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED?'stored_radar':'feature_off',radar_available:flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED===true,acquisition:'none',metric_reads_enabled:false,follower_conversion:'unavailable'},weekly:{recipes:0,weeks:0},notifications:{enabled:false}});
   if(p==='/api/auth/config')return send({provider:'dev',execution:'dev-synthetic',flow:'dev'});
   if(p==='/api/catalog')return send({authMode:'dev',execution:'dev-synthetic',phase2:true,templates:[],routes:[],profileMetadata:{}});
   if(p==='/api/bootstrap')return send({workspaceId:wid});
   if(p==='/api/workspaces')return send({workspaces:[{workspaceId:wid,membership:snapshot.membership,name:'Demo crowding workspace',plan:'studio',memberCounts:{owner:1}}]});
   if(p===`/api/workspaces/${wid}`)return send(snapshot);
   if(p==='/api/me')return send({userId:'00000000-0000-0000-0000-000000000001',displayName:'Synthetic owner',preferences:{timeZone:'UTC',locale:'en',alertNewDevice:false},mfa:{}});
   if(p.endsWith('/usage'))return send({subscription:{plan:'studio',status:'active'},trial:{},balances:[]});
   if(p.endsWith('/memory'))return send(workspaceFixture.memory);
   if(p.endsWith('/memory/proposals'))return send({pending:[],recent:[],learning:{items:[]}});
   if(p.endsWith('/channels'))return send({channels:snapshot.state.phase2.channels,providers:[]});
   if(p.endsWith('/time-savings'))return send({});
   return send({error:'Unrelated explicit fixture route'},404);
  });
  const page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));
  const load=()=>page.goto(base+'/app/trends',{timeout:180000});
  await load();await page.getByText('Trend Beta is off',{exact:true}).waitFor();assert.equal(calls.some(c=>c.path.startsWith(root)),false);pass(`${width} flags OFF zero trend requests`);
  flags={RAFII_TREND_INTELLIGENCE_ENABLED:true,RAFII_TREND_RADAR_ENABLED:true,RAFII_TREND_TRUST_RECEIPTS_ENABLED:true,RAFII_TREND_SATURATION_ENABLED:true};
  const open=async()=>{await load();await page.getByRole('button',{name:'Why should I trust this?',exact:true}).click();const drawer=page.getByRole('dialog');await drawer.getByRole('tab',{name:'Crowding',exact:true}).focus();await page.keyboard.press('Enter');return drawer;};
  let drawer=await open();await drawer.getByRole('heading',{name:'Creative crowding',exact:true}).waitFor();assert.equal(await drawer.locator('.trend-crowding').count(),5);
  const cards=drawer.locator('.trend-crowding');
  for(let i=0;i<5;i++){const summary=cards.nth(i).locator('summary').filter({hasText:'Pattern counts and methodology'});await summary.focus();await page.keyboard.press('Enter');await cards.nth(i).locator('details[open]').waitFor();}
  const value=async(card,label)=>card.locator('dt').filter({hasText:new RegExp('^'+label+'$')}).locator('..').locator('dd').allTextContents();
  assert.deepEqual(await value(cards.nth(0),'Unclassified observations'),['20']);assert.deepEqual(await value(cards.nth(0),'Classification coverage'),['80% (ratio 0.8)']);
  assert.deepEqual(await value(cards.nth(0),'Share of classified observations'),['25% (ratio 0.25)','75% (ratio 0.75)']);assert.deepEqual(await value(cards.nth(0),'Unique creator support'),['12','0']);
  assert.ok((await cards.nth(0).innerText()).includes('0.1–0.4 (ratio)'));assert.ok((await cards.nth(0).innerText()).includes('creator_cluster_bootstrap_v1'));assert.ok((await cards.nth(0).innerText()).includes('95% (ratio 0.95)'));assert.deepEqual((await value(cards.nth(0),'Share interval')).slice(1),['Unknown']);
  pass(`${width} sample coverage, exact pattern counts/support and interval bounds/method/level visible via keyboard disclosure`);
  assert.deepEqual(await value(cards.nth(0),'Redundant observations'),['Unknown']);assert.deepEqual(await value(cards.nth(2),'Redundant observations'),['19']);assert.ok((await cards.nth(2).innerText()).includes('0.238 ratio'));assert.ok((await cards.nth(2).innerText()).includes('25% (ratio 0.25)'));assert.ok((await cards.nth(0).innerText()).includes('Pattern counts alone are not copy evidence.'));pass(`${width} pattern share remains distinct from assessed redundancy; no copying/fatigue inference`);
  for(const label of ['Redundant observations','Known-author observations','Effective creator count'])assert.deepEqual(await value(cards.nth(1),label),['0']);
  assert.deepEqual(await value(cards.nth(1),'Author coverage'),['0% (ratio 0)']);assert.deepEqual(await value(cards.nth(4),'Author coverage'),['Unknown']);assert.deepEqual(await value(cards.nth(4),'Largest creator share'),['Unknown']);assert.deepEqual(await value(cards.nth(4),'Effective creator count'),['Unknown']);
  assert.ok(await cards.nth(1).getByText('No pattern rows were stored.',{exact:true}).isVisible());assert.ok(await cards.nth(3).getByText('Pattern and sample details were not stored for this result.',{exact:true}).isVisible());pass(`${width} zero, unknown creator coverage and absent legacy details remain distinct`);
  assert.deepEqual(await cards.nth(4).locator('code').allTextContents(),f.saturation.dimensions[4].sample_details.patterns.map(p=>Array.isArray(p.pattern_id)?JSON.stringify(p.pattern_id):p.pattern_id));assert.ok((await cards.nth(4).innerText()).includes('2 of 25 stored patterns shown. The list is truncated.'));pass(`${width} native long/paired IDs and server ordering/truncation preserved`);
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});const violations=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('[role=dialog]'));return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}));});assert.deepEqual(violations,[]);
  assert.ok(await drawer.evaluate(el=>el.scrollWidth<=el.clientWidth+1));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.ok(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches));const shot=async(index,name,selector='summary')=>{await drawer.evaluate((el,{index,selector})=>{const target=el.querySelectorAll('.trend-crowding')[index].querySelector(selector);el.scrollTop+=target.getBoundingClientRect().top-el.getBoundingClientRect().top-16;},{index,selector});await page.screenshot({path:path.join(out,`${name}-${width}.png`),fullPage:false});};await shot(0,'crowding');await shot(4,'creator');await shot(4,'creator-details','[aria-label="Creator concentration details"]');pass(`${width} drawer axe, reduced motion and mobile/native-ID wrapping`);
  if(width===390){await page.setViewportSize({width:195,height:1000});assert.ok(await drawer.evaluate(el=>el.scrollWidth<=el.clientWidth+1));assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));const clipping=await drawer.locator('details[open] p,details[open] dd,details[open] code').evaluateAll(nodes=>nodes.filter(n=>n.clientWidth>0&&n.scrollWidth>n.clientWidth+1).map(n=>n.textContent));assert.deepEqual(clipping,[]);await shot(4,'creator-reflow195');await page.setViewportSize({width,height:1000});pass('195 CSS-pixel Crowding reflow retains native IDs and all detail text');}
  await page.keyboard.press('Escape');await drawer.waitFor({state:'hidden'});assert.ok(await page.getByRole('button',{name:'Why should I trust this?',exact:true}).evaluate(el=>el===document.activeElement));pass(`${width} drawer Escape restores trigger focus`);
  for(const scenario of ['legacy','invalid','unavailable']){mode=scenario;drawer=await open();if(scenario==='legacy'){await drawer.locator('.trend-crowding').first().getByText('Pattern counts and methodology',{exact:true}).click();await drawer.getByText('Pattern and sample details were not stored for this result.',{exact:true}).first().waitFor();}else{await drawer.getByText(scenario==='invalid'?'Trends could not load':'Evidence is unavailable',{exact:true}).waitFor();assert.equal(await drawer.getByText('Pattern counts and methodology',{exact:true}).count(),0);}pass(`${width} ${scenario} response never fabricates sample details`);}
  mode='normal';flags.RAFII_TREND_SATURATION_ENABLED=false;const start=calls.length;await load();await page.getByRole('button',{name:'Why should I trust this?',exact:true}).click();await page.getByRole('heading',{name:'1. What we saw',exact:true}).waitFor();assert.equal(await page.getByRole('tab',{name:'Crowding',exact:true}).count(),0);assert.equal(calls.slice(start).some(c=>c.path.endsWith('/saturation')),false);pass(`${width} Crowding flag OFF hides view and performs zero saturation calls`);
  assert.deepEqual(errors,[]);assert.deepEqual(egress,[]);assert.equal(calls.filter(c=>c.path.startsWith(root)&&c.method!=='GET').length,0);pass(`${width} no runtime errors, mutations or unexpected egress`);await context.close();
 }}finally{await browser.close();}
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({execution:'explicit synthetic intercepted fixtures; not real API/DB',results},null,2)+'\n');
}
module.exports={crowdingFixture};
if(require.main===module)(async()=>{offline();if(process.argv.includes('--browser'))await browserChecks();console.log(JSON.stringify({passed:results.length}));})().catch(e=>{console.error(e);process.exitCode=1;});
