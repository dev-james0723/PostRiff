/** Local performance observations: genuine API/DB, synthetic identity, no external requests. */
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {writeFileSync}=require('node:fs');
const {resolve}=require('node:path');
const os=require('node:os');
const host=()=>({platform:os.platform(),cpuCount:os.cpus().length,loadAverage:os.loadavg(),freeMemoryBytes:os.freemem(),totalMemoryBytes:os.totalmem()});
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base='http://127.0.0.1:4439';
const quantile=(arr,q)=>[...arr].sort((a,b)=>a-b)[Math.ceil(arr.length*q)-1];
// Rafii v9 Home is server-rendered, so a visible, enabled Message field is not yet usable: "ready" means React has
// attached its handlers to that field.
// The slow profile only waits for it before reading LCP/CLS, so it gets longer; the thresholds below are unchanged.
const homeReady=(page,timeout=30000)=>page.waitForFunction(()=>{const el=document.querySelector('textarea[aria-label="Message"]');return !!el&&el.disabled===false&&Object.keys(el).some(k=>k.startsWith('__reactProps'));},null,{timeout});
(async()=>{
 const hostBefore=host();
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try {
  const id=randomUUID(), context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:id,url:base}]);
  await context.addInitScript(id=>{localStorage.setItem('postriff-dev-principal',id);localStorage.setItem('postriff-onboarding:'+id,JSON.stringify({completed:{},dismissed:{welcome:1},nudged:{}}));},id);
  await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
  const page=await context.newPage();
  await page.goto(base+'/app');await homeReady(page);
  const warm=[];
  for(let i=0;i<20;i++) {const start=performance.now();await page.reload();await homeReady(page);warm.push(performance.now()-start);}
  const headers={Authorization:'Bearer dev:'+id,Origin:base};
  const spaces=await (await context.request.get(base+'/api/workspaces',{headers})).json();
  const wid=spaces.workspaces[0].workspaceId;const reads=[];let index=0;
  await Promise.all(Array.from({length:20},async()=>{while(index++<100){const start=performance.now();const r=await context.request.get(base+'/api/workspaces/'+wid,{headers});assert.equal(r.status(),200);const s=await r.json();assert.equal(s.state.workspace.id,wid);reads.push(performance.now()-start);}}));
  const foreign=await context.request.get(base+'/api/workspaces/'+wid,{headers:{...headers,Authorization:'Bearer dev:'+randomUUID()}});assert.equal(foreign.status(),403);
  // Each layout shift keeps its sources (element, text, rect before and after) so a CLS failure names what moved.
  await context.addInitScript(()=>{window.__consumerVitals={lcp:0,cls:0,shifts:[]};const describe=s=>{const n=s.node,d=n&&n.nodeType===1?n:n?.parentElement;return {node:d?(d.tagName+(d.id?'#'+d.id:'')+(d.getAttribute('aria-label')?'['+d.getAttribute('aria-label')+']':'')+'.'+String(d.className).split(' ').slice(0,4).join('.')).slice(0,160):'?',text:(d?.textContent||'').trim().slice(0,60),prev:[s.previousRect.x,s.previousRect.y,s.previousRect.width,s.previousRect.height].map(Math.round),cur:[s.currentRect.x,s.currentRect.y,s.currentRect.width,s.currentRect.height].map(Math.round)};};new PerformanceObserver(l=>{for(const e of l.getEntries()){window.__consumerVitals.lcp=e.startTime;window.__consumerVitals.element=e.element?.outerHTML?.slice(0,500);window.__consumerVitals.size=e.size;}}).observe({type:'largest-contentful-paint',buffered:true});new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput){window.__consumerVitals.cls+=e.value;window.__consumerVitals.shifts.push({value:+e.value.toFixed(4),at:Math.round(e.startTime),sources:(e.sources||[]).slice(0,3).map(describe)});}}).observe({type:'layout-shift',buffered:true});});
  await page.setViewportSize({width:390,height:844});
  const cdp=await context.newCDPSession(page);
  await cdp.send('Network.enable');await cdp.send('Network.setCacheDisabled',{cacheDisabled:true});
  await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:1_600_000/8,uploadThroughput:750_000/8,connectionType:'cellular4g'});
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
  const slow=[];
  for(let i=0;i<5;i++){await page.reload({timeout:120000});await homeReady(page,90000);await page.waitForTimeout(1000);slow.push(await page.evaluate(()=>({...window.__consumerVitals,navigation:performance.getEntriesByType("navigation")[0]?.toJSON(),scripts:[...document.scripts].map(s=>s.src.replace(location.origin,"")),resources:performance.getEntriesByType("resource").map(r=>({url:r.name.replace(location.origin,""),bytes:r.encodedBodySize,initiator:r.initiatorType,start:r.startTime,end:r.responseEnd})).sort((a,b)=>b.bytes-a.bytes)})));}
  const metrics={hostBefore,hostAfter:host(),execution:'local production Next/API/PostgreSQL; synthetic identity; no paid or social calls',browser:browser.version(),warm:{samples:20,milliseconds:warm,p95:quantile(warm,.95)},reads:{concurrency:20,samples:reads.length,milliseconds:reads,p95:quantile(reads,.95),foreignStatus:foreign.status()},slow:{viewport:'390x844',cache:'disabled',latencyMs:150,downloadMbps:1.6,uploadMbps:.75,cpuSlowdown:4,samples:slow,lcpP75:quantile(slow.map(s=>s.lcp),.75),clsMax:Math.max(...slow.map(s=>s.cls))},fieldINP:'AWAITING_EXTERNAL'};
  const failures=[];if(metrics.warm.p95>3000)failures.push('warm p95 exceeds 3 seconds');if(metrics.reads.p95>1000)failures.push('read p95 exceeds 1 second');if(metrics.slow.lcpP75>2500 || metrics.slow.lcpP75===0)failures.push('slow LCP p75 exceeds 2.5 seconds or unavailable');if(metrics.slow.clsMax>.1)failures.push('CLS exceeds .1');
  writeFileSync(resolve(__dirname,'../../docs/consumer-ready/evidence/browser-performance-metrics.json'),JSON.stringify({...metrics,failures,status:failures.length?'FAIL':'PASS'},null,2));
  console.log(JSON.stringify({warmP95:metrics.warm.p95,readP95:metrics.reads.p95,lcpP75:metrics.slow.lcpP75,hostBefore,hostAfter:metrics.hostAfter,clsMax:metrics.slow.clsMax,largestShifts:slow.flatMap(s=>s.shifts||[]).sort((a,b)=>b.value-a.value).slice(0,3),failures}));assert.deepEqual(failures,[]);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
