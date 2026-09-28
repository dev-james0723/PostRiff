/** Explicit synthetic Learning fixtures only; never imported by production.
 * Default/--offline runs schema + authenticated adapter checks without a browser/API.
 * --browser requires an explicitly started loopback web server; it intercepts APIs.
 * These checks are not real API/PostgreSQL integration evidence.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const t = require('./trend-contract.cjs').loadTypes();
const { fixtures } = require('./trend-fixtures.cjs');
const workspaceFixture = require('./fixtures/wp04a-workspace.json');
const results = [];
const findings = [];
const responsive = [];
const pass = name => { results.push({ name, pass: true }); console.log('PASS', name); };
function learningFixture() {
 const stamp = new Date().toISOString();
 const choice = {selection_digest:'synthetic-selection',channel_id:'synthetic-channel',provider:'threads',metric:'views',definition_version:'synthetic-native-v1',window:'24h',objective:'reach'};
 const option = {selection_digest:choice.selection_digest,source_id:'synthetic-source',source_label:'Saved trend idea',channel_id:choice.channel_id,channel_label:'Demo data: private account 🎵',provider:choice.provider,metrics:['views','likes','replies'],definition_version:choice.definition_version,windows:['1h','24h','7d'],objectives:['reach','shareability','conversation','custom_metric'],saved_choice:null};
 const report = {
  schema_version:'rafii.trend-learning.v1',as_of:stamp,window:'24h',
  denominator:{exposures:8,accepted:4,dismissed:1,unaccepted:2,unknown:1,accepted_without_exposure:2,dismissed_without_exposure:1,unknown_without_exposure:1},
  coverage:{exposure_page_truncated:true,independent_analytics_views:1,decisions_truncated:false,job_history_truncated:true,suppressed_in_page:{opportunity_unavailable:2},scope:'current_permitted_retained_client_views',historical_denominator_complete:false},
  outcome_states:{measured:1,delayed:1,objective_unselected:1,unavailable:1,pending_horizon:1},
  exposures:[
   {exposure_id:'synthetic-view-a',opportunity_id:'synthetic-op-a',opportunity_revision:1,measurement:'client_reported_view',eligible_candidate_count:3,candidate_scope:'returned_page',decision:'accepted',outcomes:[
    {job_id:'synthetic-zero-measured',state:'measured',value:0,unit:'count',native_values:{views:0},observed_at:1800000000,available_at:1800000000,metric_receipts:['synthetic-receipt'],treatment_state:'unknown',causal:false,metric:'views',baseline:{count:0,median:null,mad:null,state:'unknown',reason:'incomplete_comparison_cohort'}},
    {job_id:'synthetic-delayed',state:'delayed',value:null,treatment_state:'unknown',causal:false,reason:'native_observation_not_yet_available'},
    {job_id:'synthetic-unselected',state:'objective_unselected',value:null,treatment_state:'unknown',causal:false},
    {job_id:'synthetic-divisor',state:'unavailable',value:null,treatment_state:'unknown',causal:false,reason:'zero_denominator'},
    {job_id:'synthetic-pending',state:'pending_horizon',value:null,treatment_state:'unknown',causal:false}
   ],retention_basis:'current_source_dependencies',source_rights_extended:false,publication_coverage:'observed_jobs'},
   {exposure_id:'synthetic-view-b',opportunity_id:'synthetic-op-b',opportunity_revision:1,measurement:'client_reported_view',eligible_candidate_count:2,candidate_scope:'returned_page',decision:'accepted',outcomes:[],retention_basis:'current_source_dependencies',source_rights_extended:false,publication_coverage:'not_published'},
   {exposure_id:'synthetic-view-c',opportunity_id:'synthetic-op-c',opportunity_revision:1,measurement:'client_reported_view',eligible_candidate_count:2,candidate_scope:'returned_page',decision:'accepted',outcomes:[],retention_basis:'independent_reviewed_metadata',source_rights_extended:false,publication_coverage:'accepted_source_unavailable'}
  ],causal:false,durable_strategy:false,limitations:['Explicit synthetic fixture — no real performance claims.','Unavailable outcomes are not zero engagement.'],choice_options:[option]
 };
 return {choice,report,option,saved:{...choice,confirmed:true,selected_by:'synthetic-editor',selected_at:stamp,id:'synthetic-choice-id'}};
}
function loadApi() {
 const file = path.join(__dirname,'../src/features/trends/api.ts');
 const js=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 class ApiError extends Error { constructor(message,status,code){super(message);this.status=status;this.code=code;} }
 const output={exports:{}};
 new Function('require','exports','module',js)(name=>name==='@/lib/coworker/trend-types'?t:name==='@/lib/api/client'?{ApiError,APP_GUARD_HEADER:{'X-PostRiff-Request':'founder-alpha'}}:require(name),output.exports,output);
 return output.exports;
}
async function offline() {
 const {report,choice,saved}=learningFixture();
 t.trendLearningSchema.parse(report);t.trendMetricChoiceSchema.parse(saved);
 pass('strict canonical descriptor and saved-choice fixtures');
 for(const input of [{...choice,goal:'never infer from this'}, {...choice,denominator:'views'}, {...choice,text:'private text'}, {...choice,objective:'improve things'}, {...choice,window:'48h'}, {...choice,definition_version:''}]) assert.equal(t.trendMetricChoiceInputSchema.safeParse(input).success,false);
 pass('strict mutation rejects free goal, raw text, unknown keys/window/objective');
 assert.equal(t.trendMetricChoiceInputSchema.safeParse({...choice,denominator_metric:'likes'}).success,true);
 for(const bad of [{...report,causal:true},{...report,denominator:{...report.denominator,exposures:null}},{...report,outcome_states:{invented:1}},{...report,choice_options:[{...report.choice_options[0],extra:true}]}]) assert.equal(t.trendLearningSchema.safeParse(bad).success,false);
 pass('no causal claim, null counts, unknown states or extra option fields');
 const measured=report.exposures[0].outcomes[0], delayed=report.exposures[0].outcomes[1];
 assert.equal(t.trendLearningOutcomeSchema.safeParse(measured).success,true);
 assert.equal(t.trendLearningOutcomeSchema.safeParse({...delayed,value:0}).success,false);
 assert.equal(t.trendLearningOutcomeSchema.safeParse({...measured,value:null}).success,false);
 assert.deepEqual(t.trendLearningSchema.parse({...report,outcome_states:{}}).outcome_states,{});
 pass('measured zero retained; missing/sparse/unavailable never coerced to zero');
 const original=global.fetch,calls=[];
 try {
  let response=fixtures().envelope(saved), status=200;
  global.fetch=async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(response),{status,headers:{'content-type':'application/json'}});};
  const api=loadApi().createTrendApi(async()=> 'synthetic-session');
  assert.equal(calls.length,0);
  await api.recordMetricChoice('synthetic/workspace',choice);
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/workspaces/synthetic%2Fworkspace/coworker/trends/learning/metric-choices');
  assert.equal(calls[0].options.method,'POST');assert.equal(calls[0].options.cache,'no-store');
  assert.equal(calls[0].options.headers.Authorization,'Bearer synthetic-session');
  assert.equal(calls[0].options.headers['X-PostRiff-Request'],'founder-alpha');
  assert.deepEqual(JSON.parse(calls[0].options.body),choice);
  pass('adapter sends only explicit strict payload with session/guard/no-store');
  await assert.rejects(async()=>api.recordMetricChoice('w',{...choice,goal:'no'}));assert.equal(calls.length,1);
  await assert.rejects(loadApi().createTrendApi(async()=>null).recordMetricChoice('w',choice));assert.equal(calls.length,1);
  pass('invalid input and missing session cause no dispatch');
  status=409;response={code:'selection_unavailable'};await assert.rejects(api.recordMetricChoice('w',choice),e=>e.status===409);assert.equal(calls.length,2);
  status=200;response=fixtures().envelope({...saved,confirmed:false});await assert.rejects(api.recordMetricChoice('w',choice),e=>e.code==='invalid_response');assert.equal(calls.length,3);
  pass('stale refusal and malformed success fail closed without automatic retry');
 } finally {global.fetch=original;}
}
async function headerChecks(page,out,scenario='normal') {
   for(const headerWidth of [1440,820,390,195]) {
    await page.setViewportSize({width:headerWidth,height:1000});
    const header=page.locator('header').first();
    // Measure the settled responsive layout, including existing button padding transitions.
    await header.evaluate(async el=>{await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));await Promise.all(el.getAnimations({subtree:true}).filter(a=>a.effect?.getComputedTiming().endTime!==Infinity).map(a=>a.finished.catch(()=>{})));});
    const geometry=await header.evaluate(el=>{const box=n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,header:box(el),actions:[...el.querySelectorAll('button,a')].filter(n=>n.getBoundingClientRect().width>0&&getComputedStyle(n).visibility!=='hidden').map(n=>({label:n.getAttribute('aria-label')||n.textContent.trim(),bbox:box(n),font:getComputedStyle(n).fontSize,inlineBreadcrumb:Boolean(n.closest('nav'))}))};});
    geometry.scenario=scenario;responsive.push(geometry);fs.writeFileSync(path.join(out,'responsive-header.json'),JSON.stringify(responsive,null,2)+'\n');
    assert.ok(geometry.scroll<=headerWidth+1,`Full page reflows at ${headerWidth} CSS pixels`);
    assert.ok(geometry.actions.every(a=>a.bbox.x>=-1&&a.bbox.right<=headerWidth+1&&(a.inlineBreadcrumb||(a.bbox.width>=24&&a.bbox.height>=24))),`Header actions retain visible click targets at ${headerWidth}`);
    for(let i=0;i<geometry.actions.length;i++)for(let j=i+1;j<geometry.actions.length;j++){if(geometry.actions[i].inlineBreadcrumb||geometry.actions[j].inlineBreadcrumb)continue;const a=geometry.actions[i].bbox,b=geometry.actions[j].bbox;assert.ok(Math.min(a.right,b.right)-Math.max(a.x,b.x)<=1||Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)<=1,'Header action targets do not overlap');}
    for(const crumb of geometry.actions.filter(a=>a.inlineBreadcrumb)){assert.ok(crumb.bbox.width>=24,'Breadcrumb links retain at least24px width');for(const action of geometry.actions.filter(a=>!a.inlineBreadcrumb)){const a=crumb.bbox,b=action.bbox;assert.ok(Math.min(a.right,b.right)-Math.max(a.x,b.x)<=1||Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)<=1,'Breadcrumbs do not overlap header actions');}}
    if(scenario==='normal'&&process.env.TREND_HEADER_BASELINE){
     const before=JSON.parse(fs.readFileSync(process.env.TREND_HEADER_BASELINE,'utf8')).find(v=>v.viewport===headerWidth);
     assert.ok(before,`Historical header geometry exists at ${headerWidth}`);
     const currentActions=geometry.actions.filter(a=>!a.inlineBreadcrumb),priorActions=before.actions.filter(a=>!a.inlineBreadcrumb);
     assert.deepEqual(currentActions.map(({bbox:_bbox,...rest})=>rest),priorActions.map(({bbox:_bbox,...rest})=>rest),'Action labels/order/font sizes remain exact');
     const deltas=[...Object.keys(geometry.header).map(k=>Math.abs(geometry.header[k]-before.header[k])),...currentActions.flatMap((a,i)=>Object.keys(a.bbox).map(k=>Math.abs(a.bbox[k]-priorActions[i].bbox[k])))];
     geometry.baselineMaxDelta=Math.max(...deltas);
     // Historical captures did not wait for the existing responsive padding transition.
     // Retain their measured delta; compare settled geometry with the prior classes below.
    }
    if(scenario==='normal'){
     const prior=await header.evaluate(async el=>{
      const box=n=>{const b=n.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,right:b.right,bottom:b.bottom};};
      const saved=new Map();const remove=(n,...classes)=>{if(!saved.has(n))saved.set(n,n.getAttribute('class'));n.classList.remove(...classes);};
      const nav=el.querySelector('[data-slot=breadcrumb]');
      // Explicit before-class fixture from the reviewed W-only diff; no product state changes.
      try{
       remove(nav.parentElement,'md:max-lg:gap-1','md:max-lg:pr-0');remove(nav.parentElement.querySelector('[data-slot=separator]'),'md:max-lg:mr-1');
       remove(nav.querySelector('[data-slot=breadcrumb-list]'),'min-w-0','md:max-lg:gap-1');
       for(const item of nav.querySelectorAll('[data-slot=breadcrumb-item]')){remove(item,'min-w-6');if(item.querySelector('[aria-current=page]'))item.classList.add('min-w-0');}
       for(const link of nav.querySelectorAll('a'))remove(link,'block','truncate');
       for(const separator of nav.querySelectorAll('[data-slot=breadcrumb-separator]'))remove(separator,'shrink-0');
       await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));await Promise.all(el.getAnimations({subtree:true}).filter(a=>a.effect?.getComputedTiming().endTime!==Infinity).map(a=>a.finished.catch(()=>{})));
       return {header:box(el),actions:[...el.querySelectorAll('button,a')].filter(n=>!n.closest('nav')&&n.getBoundingClientRect().width>0&&getComputedStyle(n).visibility!=='hidden').map(n=>({label:n.getAttribute('aria-label')||n.textContent.trim(),bbox:box(n),font:getComputedStyle(n).fontSize,inlineBreadcrumb:false}))};
      }finally{for(const [n,value]of saved)n.setAttribute('class',value);}
     });
     const current=geometry.actions.filter(a=>!a.inlineBreadcrumb);assert.deepEqual(current.map(({bbox:_bbox,...a})=>a),prior.actions.map(({bbox:_bbox,...a})=>a),'Prior-class fixture preserves every action/label/order/font');
     geometry.settledBeforeClassMaxDelta=Math.max(...Object.keys(geometry.header).map(k=>Math.abs(geometry.header[k]-prior.header[k])),...current.flatMap((a,i)=>Object.keys(a.bbox).map(k=>Math.abs(a.bbox[k]-prior.actions[i].bbox[k]))));
     assert.ok(geometry.settledBeforeClassMaxDelta<=0.1,'Settled action geometry matches reviewed prior classes within 0.1 CSS px');
    }
    const breadcrumb=header.getByRole('navigation',{name:'breadcrumb'});
    const crumbs=await breadcrumb.locator('a,[aria-current=page]').evaluateAll(nodes=>nodes.map(n=>({text:n.textContent,title:n.getAttribute('title'),href:n.getAttribute('href'),visible:n.getBoundingClientRect().width>0,client:n.clientWidth,scroll:n.scrollWidth,ellipsis:getComputedStyle(n).textOverflow,bbox:{x:n.getBoundingClientRect().x,right:n.getBoundingClientRect().right}})));
    geometry.breadcrumbs=crumbs;geometry.breadcrumbBox=await breadcrumb.boundingBox();fs.writeFileSync(path.join(out,'responsive-header.json'),JSON.stringify(responsive,null,2)+'\n');assert.ok(crumbs.at(-1).visible&&crumbs.at(-1).client>=24,'Current-page breadcrumb retains visible truncation space');
    for(const crumb of crumbs){assert.equal(crumb.title,crumb.text,'Full label retained for tooltip/accessibility');if(crumb.visible){assert.ok(crumb.bbox.right<=geometry.actions.find(a=>a.label==='Create a new draft').bbox.x||headerWidth<320);if(crumb.scroll>crumb.client)assert.equal(crumb.ellipsis,'ellipsis');}}
    assert.ok(await breadcrumb.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'Breadcrumb children stay within their allocated width');if(scenario==='long'){const normal=responsive.find(r=>r.scenario==='normal'&&r.viewport===headerWidth);assert.deepEqual(crumbs.map(c=>c.href),normal.breadcrumbs.map(c=>c.href),'Long-label fixture preserves original destinations');assert.deepEqual(geometry.actions.filter(a=>!a.inlineBreadcrumb),normal.actions.filter(a=>!a.inlineBreadcrumb),'Long breadcrumbs preserve settled action labels/order/geometry');assert.ok(crumbs.at(-1).text.length>150);assert.ok(crumbs.at(-1).scroll>crumbs.at(-1).client,'Long current-page label truncates');}
    for(const link of await breadcrumb.locator('a:visible').all())await link.click({trial:true});
    const controls=header.locator('button:visible,a:visible');
    for(let i=0;i<await controls.count()-1;i++){await controls.nth(i).focus();await page.keyboard.press('Tab');assert.equal(await controls.nth(i+1).evaluate(e=>e===document.activeElement),true,`Header keyboard order ${headerWidth}/${i}`);}
    const help=header.getByRole('button',{name:'Help',exact:true});await help.focus();await page.keyboard.press('Enter');await page.getByRole('menu').waitFor();const menuBox=await page.getByRole('menu').boundingBox();assert.ok(menuBox.x>=0&&menuBox.x+menuBox.width<=headerWidth+1,'Open Help menu stays within viewport');const menuItems=page.getByRole('menuitem').filter({visible:true});for(let i=0;i<await menuItems.count();i++){const b=await menuItems.nth(i).boundingBox();assert.ok(b.x>=0&&b.x+b.width<=headerWidth+1&&b.height>=24);await menuItems.nth(i).click({trial:true});}assert.deepEqual(await page.getByRole('menu').evaluate(el=>[...el.querySelectorAll('[role=menuitem]')].filter(n=>n.getBoundingClientRect().width>0&&n.scrollWidth>n.clientWidth+1).map(n=>n.textContent)),[],'Menu text is not clipped');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Open menu preserves full-page width');geometry.helpMenu={bbox:menuBox,labels:await menuItems.allTextContents()};const menuAxe=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('[role=menu]'));return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id);});assert.deepEqual(menuAxe,[]);if(headerWidth===195)await page.screenshot({path:path.join(out,`help-menu-${scenario}-195.png`)});await page.keyboard.press('ArrowDown');assert.ok(await page.getByRole('menu').evaluate(el=>el.contains(document.activeElement)));await page.keyboard.press('Escape');await page.getByRole('menu').waitFor({state:'hidden'});assert.ok(await help.evaluate(el=>el===document.activeElement));
    const bell=header.getByRole('button',{name:/^Notifications,/});await bell.click({trial:true});await bell.focus();await page.keyboard.press('Enter');await page.getByText('Needs attention',{exact:true}).waitFor();const popover=page.locator('[data-slot=popover-content]').filter({visible:true});const noticeBox=await popover.boundingBox();assert.ok(noticeBox.x>=0&&noticeBox.x+noticeBox.width<=headerWidth+1);assert.ok(await popover.evaluate(el=>el.scrollWidth<=el.clientWidth+1));geometry.notifications={bbox:noticeBox};const notificationAxe=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('[data-slot=popover-content]'));return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id);});assert.deepEqual(notificationAxe,[]);if(headerWidth===195)await page.screenshot({path:path.join(out,`notifications-${scenario}-195.png`)});await page.keyboard.press('Escape');await page.getByText('Needs attention',{exact:true}).waitFor({state:'hidden'});assert.ok(await bell.evaluate(el=>el===document.activeElement));
    const headerAxe=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('header'));return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id);});assert.deepEqual(headerAxe,[]);
    await header.screenshot({path:path.join(out,`header-${scenario}-${headerWidth}.png`)});pass(`${scenario} ${headerWidth} page width, no breadcrumb overlap, action targets, keyboard/Help/notifications and axe`);
   }
}

async function browserChecks() {
 const base=process.env.TREND_WEB_URL,out=process.env.TREND_EVIDENCE_DIR;
 assert.ok(base&&new URL(base).hostname==='127.0.0.1'&&out,'Explicit loopback URL + evidence directory required');
 fs.mkdirSync(out,{recursive:true});
 const {chromium}=require('playwright');const browser=await chromium.launch({headless:true});
 try {
 for(const width of [1440,390]) {
  const context=await browser.newContext({viewport:{width,height:1000},reducedMotion:'reduce'});
  const f=learningFixture(),snapshot=structuredClone(workspaceFixture.snapshot),wid=snapshot.state.workspace.id;
  const report=f.report, prefix=`/api/workspaces/${wid}/coworker`, calls=[],errors=[],egress=[];
  let flags={},mode='normal',delay=false;
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_theme',value:'rafii',url:base}]);
  const tours=[...fs.readFileSync(path.join(__dirname,'../src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
  await context.addInitScript(({tours})=>{
   const principal='00000000-0000-0000-0000-000000000001';localStorage.setItem('postriff-dev-principal',principal);
   const s=JSON.stringify({completed:{},dismissed:Object.fromEntries(tours.map(id=>[id,1])),nudged:Object.fromEntries(tours.map(id=>[id,1]))});
   localStorage.setItem('postriff-onboarding',s);localStorage.setItem('postriff-onboarding:'+principal,s);
  },{tours});
  await context.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url()),p=url.pathname;
   if(url.origin!==base){egress.push(url.origin);return route.abort();}
   if(!p.startsWith('/api/'))return route.continue();
   const body=req.method()==='POST'?req.postDataJSON():null;calls.push({path:p,method:req.method(),body});
   const send=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
   if(p===prefix+'/performance') {
    if(delay)await new Promise(r=>setTimeout(r,1200));
    if(mode==='error')return send({error:'Synthetic report unavailable'},503);
    const payload={posts:2,measured:1,unavailable:1,hypotheses:[],rules:{minimumPerGroup:5,minimumDifference:'20%',causal:false,note:'Existing strategy evidence remains unchanged.'}};
    if(mode!=='missing')payload.trend_learning=mode==='malformed'?{...report,causal:true}:report;
    return send(payload);
   }
   if(p===prefix+'/trends/learning/metric-choices') {
    t.trendMetricChoiceInputSchema.parse(body);
    if(mode==='stale')return send({code:'selection_unavailable'},409);
    if(mode==='denied')return send({code:'permission_denied'},403);
    const result={...body,confirmed:true,selected_by:'synthetic-editor',selected_at:new Date().toISOString(),id:'synthetic-saved-choice'};
    if(mode==='mismatch')return send(fixtures().envelope({...result,metric:'likes'}));
    report.choice_options[0].saved_choice=result;snapshot.revision++;
    return send(fixtures().envelope(result));
   }
   if(p===prefix+'/overlays')return send({voice:[],brand:[],strategy:[]});
   if(p===prefix+'/status')return send({flags,trend_beta:{state:'stored_radar',radar_available:true,acquisition:'none',metric_reads_enabled:false,follower_conversion:'unavailable'},weekly:{recipes:0,weeks:0},notifications:{enabled:false}});
   if(p==='/api/auth/config')return send({provider:'dev',execution:'dev-synthetic',flow:'dev'});
   if(p==='/api/bootstrap')return send({workspaceId:wid});
   if(p==='/api/catalog')return send({authMode:'dev',execution:'dev-synthetic',platforms:['Threads'],languages:['en'],presets:[],voices:[],phase2:true,templates:[],routes:[],profileMetadata:{}});
   if(p==='/api/me')return send({userId:'00000000-0000-0000-0000-000000000001',displayName:'Synthetic owner',preferences:{timeZone:'UTC',locale:'en',alertNewDevice:false},mfa:{}});
   if(p==='/api/workspaces')return send({workspaces:[{workspaceId:wid,membership:snapshot.membership,name:'Demo learning workspace',plan:'studio',memberCounts:{owner:1}}]});
   if(p===`/api/workspaces/${wid}`)return send(snapshot);
   if(p.endsWith('/usage'))return send({subscription:{plan:'studio',status:'active'},trial:{},balances:[]});
   if(p.endsWith('/memory'))return send(workspaceFixture.memory);
   if(p.endsWith('/memory/proposals'))return send({pending:[],recent:[],learning:{items:[]}});
   if(p.endsWith('/channels'))return send({channels:snapshot.state.phase2.channels,providers:[]});
   if(p.endsWith('/time-savings'))return send({});
   return send({error:'Unrelated synthetic route'},404);
  });
  const page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));
  const load=async()=>{await page.goto(base+'/app/workspace/personalization',{timeout:180000});await page.getByRole('heading',{name:'Personalization',exact:true}).waitFor();};
  const panel=()=>page.locator('[data-trend-learning]');
  const posts=()=>calls.filter(c=>c.path===prefix+'/trends/learning/metric-choices');
  if(process.argv.includes('--header-only')) {
   await load();await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
   await headerChecks(page,out);
   const label='Synthetic-long-breadcrumb-'+('非常長的原生標籤🎹-'.repeat(18));
   // Explicit DOM content fixture: exercises the real breadcrumb elements/classes and anchors.
   // No hidden production route or server behavior is added.
   await page.locator('header').first().getByRole('navigation',{name:'breadcrumb'}).locator('a,[aria-current=page]').evaluateAll((nodes,label)=>nodes.forEach((n,i)=>{n.textContent=label+' '+i;n.setAttribute('title',label+' '+i);}),label);
   await headerChecks(page,out,'long');
   assert.deepEqual(errors,[]);assert.deepEqual(egress,[]);assert.equal(calls.some(c=>c.path.includes('/trends/')||c.path===prefix+'/performance'||c.method==='POST'),false);pass('focused header-only fixture: zero Performance/trend calls or mutations, no runtime errors/egress');
   await context.close();break;
  }
  const enabled={RAFII_PERFORMANCE_LEARNING_ENABLED:true,RAFII_TREND_INTELLIGENCE_ENABLED:true,RAFII_TREND_TRUST_RECEIPTS_ENABLED:true,RAFII_TREND_RADAR_ENABLED:true};
  await load();await page.getByRole('heading',{name:'Strategy',exact:true}).waitFor();
  assert.equal(calls.some(c=>c.path===prefix+'/performance'||c.path.includes('/trends/')),false);pass(`${width} flags OFF: no performance/trend calls`);
  flags=enabled;delay=true;await load();await page.getByText('Loading trend activity…',{exact:true}).waitFor();await panel().waitFor();delay=false;
  assert.equal(posts().length,0);assert.equal(await panel().getByText('8',{exact:true}).count(),1);pass(`${width} loading and descriptive denominator without mutation`);
  await panel().getByText('Coverage and outcome details',{exact:true}).focus();await page.keyboard.press('Enter');
  await panel().getByText('Accepted idea · 5 publication records',{exact:true}).click();
  assert.ok(await panel().getByText('Measured outcomes: 0 count · views',{exact:true}).isVisible());
  assert.ok(await panel().getByText('Waiting for platform metrics · No measured value',{exact:true}).isVisible());
  assert.ok(await panel().getByText('1 accepted idea has no linked publication yet.',{exact:true}).isVisible());
  assert.ok(await panel().getByText('1 accepted source is unavailable for checking publication.',{exact:true}).isVisible());pass(`${width} measured zero distinct from missing/unpublished/source unavailable`);
  const choose=async()=>{await panel().getByLabel('Saved idea and account',{exact:true}).selectOption({index:1});await page.getByRole('form',{name:'Trend metric choice'}).waitFor();};
  await choose();const form=()=>page.getByRole('form',{name:'Trend metric choice'});
  assert.equal(await form().getByLabel('Objective',{exact:true}).inputValue(),'');assert.equal(await form().getByLabel('Native metric',{exact:true}).inputValue(),'');assert.equal(await form().getByLabel('Measurement window',{exact:true}).inputValue(),'');
  assert.equal(await form().getByRole('button',{name:'Save metric choice',exact:true}).isEnabled(),false);
  const select=async()=>{await form().getByLabel('Objective',{exact:true}).selectOption('conversation');await form().getByLabel('Native metric',{exact:true}).selectOption('replies');await form().getByLabel('Measurement window',{exact:true}).selectOption('7d');await form().getByLabel('Divide by another metric (optional)',{exact:true}).selectOption('views');};
  await select();assert.equal(posts().length,0);assert.deepEqual(await form().getByLabel('Native metric',{exact:true}).locator('option').evaluateAll(nodes=>nodes.map(n=>n.value)),['','views','likes','replies']);pass(`${width} explicit blank choices; only server metrics and no selection POST`);
  const before=calls.length;await form().getByRole('button',{name:'Save metric choice',exact:true}).focus();await page.keyboard.press('Enter');await page.getByText('Metric choice saved for future publications. Past results are unchanged.',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('[data-trend-learning]')?.textContent.includes('Saved metric choices'));
  assert.equal(posts().length,1);assert.deepEqual(posts()[0].body,{...f.choice,metric:'replies',window:'7d',objective:'conversation',denominator_metric:'views'});
  assert.ok(calls.slice(before).some(c=>c.path===prefix+'/performance'));assert.ok(calls.slice(before).some(c=>c.path===`/api/workspaces/${wid}`));
  assert.equal(await form().getByRole('button',{name:'Save metric choice',exact:true}).isEnabled(),false);pass(`${width} explicit keyboard Save preserves exact bindings and refreshes canonical queries`);
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const violations=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('[aria-labelledby="trend-learning-heading"]')||document.querySelector('main'));return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}));});
  assert.deepEqual(violations,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.ok(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches));
  await panel().screenshot({path:path.join(out,`learning-${width}.png`)});pass(`${width} axe/reduced motion/no overflow`);
  if(width===1440){await headerChecks(page,out);await page.setViewportSize({width,height:1000});}

  await load();await panel().getByText('Saved metric choices',{exact:true}).click();assert.ok(await panel().getByText(/replies \/ views · Conversation · 7 days/).isVisible());pass(`${width} saved choice survives reload`);
  for(const failure of ['stale','denied','mismatch']) {
   mode=failure;await load();await panel().waitFor();await choose();await select();const n=posts().length;
   await form().getByRole('button',{name:'Save metric choice',exact:true}).click();await form().getByRole('alert').waitFor();
   assert.equal(posts().length,n+1);assert.equal(await form().getByRole('status').count(),0);pass(`${width} ${failure} has no success or automatic retry`);
  }
  for(const state of ['missing','malformed','error']) {mode=state;await load();await page.getByText(state==='error'?'Trend activity is unavailable right now.':'Trend activity is unavailable.',{exact:true}).waitFor();assert.equal(await panel().count(),0);pass(`${width} ${state} report has no invented counts`);}
  mode='normal';snapshot.membership.role='viewer';await load();await panel().waitFor();assert.ok(await panel().getByText('An editor can save a metric choice. You can read the current choices below.',{exact:true}).isVisible());assert.equal(await panel().getByLabel('Saved idea and account',{exact:true}).count(),0);pass(`${width} viewer can read but cannot submit choices`);
  snapshot.membership.role='owner';flags={...enabled,RAFII_TREND_RADAR_ENABLED:false};await load();await panel().waitFor();assert.ok(await panel().getByText('Metric choices are not enabled for this workspace.',{exact:true}).isVisible());pass(`${width} radar OFF retains permitted descriptor but hides mutation`);
  flags={...enabled,RAFII_TREND_TRUST_RECEIPTS_ENABLED:false};await load();await page.getByRole('heading',{name:'Strategy',exact:true}).waitFor();assert.equal(await panel().count(),0);pass(`${width} receipt flag OFF hides report and controls`);
  flags=enabled;report.choice_options[0].channel_label='Demo long account '+('界'.repeat(150));await load();await panel().waitFor();await choose();
  await page.evaluate(()=>document.documentElement.classList.add('dark'));
  await panel().getByText('Coverage and outcome details',{exact:true}).click();
  const clipped=await panel().evaluate(el=>{const outer=el.getBoundingClientRect();return [...el.querySelectorAll('p,form,dl,select')].filter(n=>n.getBoundingClientRect().right>outer.right+1).map(n=>({tag:n.tagName,text:n.textContent.slice(0,90),width:n.getBoundingClientRect().width,outer:outer.width}));});
  assert.deepEqual(clipped,[],'No clipped content within panel');
  await panel().screenshot({path:path.join(out,`learning-dark-long-${width}.png`)});
  await page.setViewportSize({width:Math.floor(width/2),height:500});
  await panel().screenshot({path:path.join(out,`learning-zoom-${width}.png`)});
  const zoom=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('main *,header *,aside *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,bbox:{x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,right:e.getBoundingClientRect().right},text:e.textContent.slice(0,65)}))}));
  if(zoom.scroll>zoom.width+1){findings.push({width,kind:'page-reflow-overflow',zoom});console.log('FINDING',JSON.stringify({width,zoom}));}
  assert.ok(zoom.scroll<=zoom.width+1,'Full page fits the observed 200-percent-equivalent CSS viewport');
  const panelOverflow=await panel().evaluate(el=>{const r=el.getBoundingClientRect();return [...el.querySelectorAll('p,button,select,dl,form')].filter(n=>{const b=n.getBoundingClientRect();return b.right>r.right+1||b.left<r.left-1;}).map(n=>({tag:n.tagName,text:n.textContent.slice(0,80),width:n.getBoundingClientRect().width,container:r.width}));});assert.deepEqual(panelOverflow,[],'New section controls remain inside its reflowed width');
  const textOverflow=await panel().locator('p').evaluateAll(nodes=>nodes.filter(n=>n.scrollWidth>n.clientWidth+1).map(n=>({text:n.textContent.slice(0,70),width:n.clientWidth,scroll:n.scrollWidth})));assert.deepEqual(textOverflow,[],'Reflowed text remains readable');
  await page.setViewportSize({width,height:1000});await page.evaluate(()=>document.documentElement.classList.remove('dark'));pass(`${width} dark long labels and 200 percent equivalent viewport retain content`);
  mode='normal';report.choice_options=[];report.exposures=[];report.outcome_states={};report.denominator={...report.denominator,exposures:0,accepted:0,dismissed:0,unaccepted:0,unknown:0};
  await load();await panel().waitFor();assert.ok(await panel().getByText('No publication outcomes are available in this report.',{exact:true}).isVisible());assert.equal(await panel().getByRole('button',{name:'Save metric choice',exact:true}).count(),0);pass(`${width} legitimate empty report has no fabricated measurement or action`);
  assert.deepEqual(errors,[]);assert.deepEqual(egress,[]);pass(`${width} no runtime errors or unexpected egress`);
  await context.close();
 }
 } finally {await browser.close();}
 fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({execution:'explicit synthetic API interception; not real API/DB',status:findings.length?'passed_with_findings':'passed',findings,responsive,results},null,2)+'\n');
}
module.exports={learningFixture};
if(require.main===module)(async()=>{if(!process.argv.includes('--header-only'))await offline();if(process.argv.includes('--browser')||process.argv.includes('--header-only'))await browserChecks();console.log(JSON.stringify({passed:results.length,browser:process.argv.includes('--browser')||process.argv.includes('--header-only')}));})().catch(e=>{console.error(e);process.exitCode=1;});
