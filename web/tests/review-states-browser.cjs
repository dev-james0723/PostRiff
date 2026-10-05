/* DOM acceptance of design states. Synthetic response overlays are only UI evidence. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {randomUUID}=require('node:crypto'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),base=process.env.POSTRIFF_REVIEW_WEB_ORIGIN||'http://127.0.0.1:33404';
const out=process.env.POSTRIFF_REVIEW_EVIDENCE_DIR||path.join(root,'docs/design/rafii-insights-growth/evidence');
const python=process.env.POSTRIFF_TEST_PYTHON||'python3',principal=randomUUID();
const headers={'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Authorization:'Bearer dev:'+principal,Origin:base};
async function api(method,url,body){let response;try{response=await fetch(base+url,{method,headers,...(body?{body:JSON.stringify(body)}:{})});}catch(e){throw new Error(method+' '+url+' transport failed',{cause:e});}assert.ok(response.ok,await response.clone().text());return response.json();}
(async()=>{
  assert.equal((await api('GET','/api/auth/config')).execution,'dev-synthetic');
  const {workspaceId:wid}=await api('POST','/api/auth/verify',{plan:'studio'});
  execFileSync(python,['tests/phase2/review_fixture.py','55404',principal,wid],{cwd:root});
  const workspace=await api('GET',`/api/workspaces/${wid}`),channel=workspace.state.phase2.channels[0].id;
  const at=Date.now(),scope={channelIds:[channel],publicationPeriod:{start:new Date(at-7*86400000).toISOString(),end:new Date(at).toISOString(),timezone:'America/Indiana/Indianapolis'},horizon:'24h'};
  const baseline=await api('GET',`/api/workspaces/${wid}/coworker/review?scope=${encodeURIComponent(JSON.stringify(scope))}`);
  assert.equal(baseline.coverage.eligible,12);
  const tours=Object.fromEntries([...fs.readFileSync(path.join(root,'web/src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>[m[1],1]));
  const browser=await chromium.launch({headless:true,...(process.env.POSTRIFF_TEST_BROWSER_CHANNEL?{channel:process.env.POSTRIFF_TEST_BROWSER_CHANNEL}:{})}),context=await browser.newContext({viewport:{width:390,height:900},reducedMotion:'reduce'});
  await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
  await context.addInitScript(({principal,wid,tours})=>{localStorage.setItem('postriff-dev-principal',principal);localStorage.setItem('postriff-workspace',wid);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:tours,nudged:{}}));},{principal,wid,tours});
  const page=await context.newPage(),panel=page.getByRole('region',{name:'Evidence review',exact:true}),checks=[],errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/coworker/'))writes.push(r.url());});
  let mode='measured',release,notifyPending,loaded=false,lastMode='';
  const states=[
    ['not_authorized','Analytics permission is unavailable'],['unsupported','This platform does not provide this metric'],
    ['disabled','Collection is off in this workspace'],['unscheduled','No read scheduled for this window'],
    ['pending_horizon','Waiting for the post-age window'],['scheduled','Read scheduled'],['pending','Waiting for a reading'],
    ['measured','Native measurement'],['measured_zero','Measured zero'],['unavailable','No qualified reading'],
    ['stale','Earlier reading; a later attempt failed'],['disconnected','Account disconnected'],
    ['expired','Source or result expired'],['deleted','Source unavailable'],['revoked','Current source permission revoked'],
    ['legacy_period_unavailable','Legacy evidence period unavailable'],['incompatible_readings','Numerator and denominator readings differ']
  ];
  await page.route('**/coworker/review?*',async route=>{
    if(mode==='error')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Current read unavailable. Retry this scope.'})});
    if(mode==='loading')await new Promise(resolve=>{release=resolve;notifyPending?.();});
    const p=structuredClone(baseline),e=structuredClone(p.nativeResults.find(e=>e.nativeName==='views'));
    const requested=JSON.parse(new URL(route.request().url()).searchParams.get('scope'));
    p.resolvedContext.horizon=requested.horizon;
    p.groups=[];p.comparisons=[];p.takeaways=[];p.reuseCandidates=[];p.trendLearning=null;p.trendProvenance=[];
    e.value=null;e.valueState='missing';e.reason=mode;e.eligible=false;e.freshnessState='unknown';e.accessState='allowed';e.displayPermission='allowed';e.collectionState='unavailable';e.observationId=null;e.sourceRef=null;e.observedAt=null;e.ingestedAt=null;e.readOffset=null;
    if(['measured','measured_zero','stale'].includes(mode)){e.value=mode==='measured_zero'?0:100;e.valueState='measured';e.observedAt=baseline.nativeResults[0].observedAt;e.ingestedAt=baseline.nativeResults[0].ingestedAt;e.sourceRef=baseline.nativeResults[0].sourceRef;e.readOffset=requested.horizon;e.collectionState='measured';e.freshnessState=mode==='stale'?'stale':'current';e.reason=mode==='stale'?'stale_reading':null;e.eligible=mode!=='stale';}
    if(['not_authorized','disconnected','revoked','expired'].includes(mode)){e.accessState=mode==='expired'?'not_authorized':mode;e.displayPermission='restricted';}
    if(mode==='unsupported')e.valueState='unsupported';
    if(['disabled','unscheduled','pending_horizon','scheduled','pending'].includes(mode))e.collectionState=mode;
    const due=Date.now()/1000+12*3600;
    p.postTracking={enabled:true,as_of:Date.now()/1000,truncated:false,posts:[{job_id:e.publicationBinding.jobId,provider:e.provider,account:channel,horizons:[{window:requested.horizon,state:e.collectionState,due_at:due,reason:null}]}]};
    p.nativeResults=[e];p.coverage={...p.coverage,publications:1,eligible:e.eligible?1:0,measured:e.eligible?1:0,missing:e.eligible?0:1};
    if(mode==='no_account'){p.nativeResults=[];p.coverage={...p.coverage,publications:0,eligible:0,measured:0,missing:0};p.resolvedContext.channelIds=[];}
    if(mode==='partial'){const zero=structuredClone(baseline.nativeResults.find(e=>e.value===0));p.nativeResults.push(zero);p.coverage={...p.coverage,publications:2,eligible:1,measured:1,missing:1};}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(p)});
  });
  async function open(name){
    mode=name;
    if(!loaded||name==='no_account'||lastMode==='no_account'){
      await page.goto(base+'/app/analytics?reviewScope='+encodeURIComponent(JSON.stringify({...scope,channelIds:name==='no_account'?[]:[channel]})),{waitUntil:'domcontentloaded',timeout:120000});loaded=true;
    }else{
      const request=page.waitForRequest(r=>r.url().includes('/coworker/review?'));
      const age=panel.getByLabel('Post age',{exact:true});await age.selectOption((await age.inputValue())==='24h'?'7d':'24h');await request;
    }
    lastMode=name;
  }
  try{
    for(const [name,label] of states){
      await open(name);const sources=panel.locator('summary').filter({hasText:'Metric sources, missing values and exact reading times'});await sources.waitFor();if(!(await sources.locator('..').evaluate(e=>e.open)))await sources.click();
      const summary=panel.locator('summary').filter({hasText:'views:'});await summary.waitFor();assert.ok((await summary.innerText()).includes(label),name+' label');await summary.click();
      const detail=summary.locator('..'),text=await detail.innerText();
      if(!['measured','measured_zero','stale'].includes(name)){assert.ok((await summary.innerText()).includes('views: —'),name+' missing');assert.ok(!text.includes('views: 100'),name+' no old value');}
      if(['pending_horizon','scheduled','pending'].includes(name)){assert.ok(text.includes('Read due:')&&text.includes('(America/Indiana/Indianapolis)'),name+' due and timezone');}
      if(['not_authorized','unsupported','disabled','disconnected','revoked'].includes(name))assert.equal(await detail.getByRole('link',{name:'Open Channels',exact:true}).getAttribute('href'),'/app/channels');
      assert.ok(text.length>label.length+100,name+' inspectable evidence and recovery');checks.push({state:name,status:'pass',value:eValue(name),dueVisible:['pending_horizon','scheduled','pending'].includes(name)});console.log('PASS UI state: '+name);
    }
    for(const [name,label] of [['no_account','No connected account.'],['partial','Partial coverage.'],['insufficient_sample','Too few comparable publications for a takeaway.'],['method_unavailable','Personalized timing, format and frequency: method unavailable.']]){
      await open(name);await panel.getByText(label,{exact:false}).waitFor();checks.push({state:name,status:'pass'});
    }
    await open('measured');await panel.getByText('Metric sources, missing values and exact reading times',{exact:false}).waitFor();
    const pendingStarted=new Promise(resolve=>{notifyPending=resolve;});await open('loading');await pendingStarted;await panel.getByRole('status').filter({hasText:'Loading the current scope'}).waitFor();
    assert.equal(await panel.locator('summary').filter({hasText:'views: 100'}).count(),0);assert.equal(await panel.getByRole('button',{name:'Save fixed report',exact:true}).count(),0);checks.push({state:'loading',status:'pass'});
    assert.ok(release,'The pending response was actually intercepted');release();await panel.getByText('Metric sources, missing values and exact reading times',{exact:false}).waitFor();
    await open('error');await panel.getByRole('alert').waitFor();assert.ok(await panel.getByRole('button',{name:'Retry current reading',exact:true}).isEnabled());assert.equal(await panel.getByRole('button',{name:'Save fixed report',exact:true}).count(),0);checks.push({state:'error',status:'pass'});
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.equal(new Set(checks.map(c=>c.state)).size,23);
    await page.screenshot({path:path.join(out,'review-states-error.png'),fullPage:true});
    const evidence={status:'PASS',execution:'real browser DOM; actual local server projection as baseline; explicitly synthetic response overlays for design states only',sourceSha:process.env.POSTRIFF_SOURCE_SHA,checks,realProviderCalls:0,realModelCalls:0,nativeAcceptance:false,consoleErrors:errors};
    fs.writeFileSync(path.join(out,'ui-states-browser.json'),JSON.stringify(evidence,null,2)+'\n');console.log(JSON.stringify(evidence));
  }finally{release?.();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
function eValue(mode){return mode==='measured_zero'?0:['measured','stale'].includes(mode)?100:null;}
