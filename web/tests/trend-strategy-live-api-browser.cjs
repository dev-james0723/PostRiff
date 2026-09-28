/** Real browser -> API -> SQL; only synthetic fixture history, no API mocking. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = process.env.TREND_WEB_URL, out = process.env.TREND_EVIDENCE_DIR;
assert.equal(new URL(base).hostname, '127.0.0.1');
const rows = JSON.parse(fs.readFileSync(path.join(out, 'seed.json'), 'utf8'));
const results=[];const pass=(name,detail)=>{results.push({name,detail,pass:true});console.log('PASS',name);};
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try {for(const row of rows){
  const context=await browser.newContext({viewport:{width:row.width,height:1000},reducedMotion:'reduce'});
  const external=[],errors=[];await context.route('**/*',route=>{if(new URL(route.request().url()).origin===base)return route.continue();external.push(route.request().url());return route.abort();});
  await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:row.principal,url:base},{name:'postriff_theme',value:'rafii',url:base}]);
  const tours=[...fs.readFileSync(path.join(__dirname,'../src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
  await context.addInitScript(({principal,tours})=>{localStorage.setItem('postriff-dev-principal',principal);const s=JSON.stringify({completed:{},dismissed:Object.fromEntries(tours.map(t=>[t,1])),nudged:Object.fromEntries(tours.map(t=>[t,1]))});localStorage.setItem('postriff-onboarding',s);localStorage.setItem('postriff-onboarding:'+principal,s);},{principal:row.principal,tours});
  const headers={Authorization:'Bearer dev:'+row.principal,'X-PostRiff-Request':'founder-alpha',Origin:base};
  const root=`/api/workspaces/${row.workspace_id}/coworker`, endpoint=root+`/performance/hypotheses/${row.hypothesis_id}/decide`;
  const api=(method,url,data,h=headers)=>context.request.fetch(base+url,{method,headers:h,data});
  const current=async()=>{const r=await api('GET',root+'/performance');assert.equal(r.status(),200,await r.text());return r.json();};
  const h=(await current()).hypotheses.find(h=>h.id===row.hypothesis_id);assert.ok(h.canAcceptPlanning&&h.supportDigest);assert.equal(h.planningAccepted,false);
  for(const [label,payload,auth,status] of [['missing support',{decision:'accepted'},headers,409],['stale support',{decision:'accepted',expectedSupport:'stale'},headers,409],['foreign tenant',{decision:'accepted',expectedSupport:h.supportDigest},{...headers,Authorization:'Bearer dev:'+rows.find(x=>x.principal!==row.principal).principal},403]]){
   const r=await api('POST',endpoint,payload,auth);assert.equal(r.status(),status,label+':'+await r.text());
  }
  pass(`${row.width} current support bound; missing/stale support and foreign tenant rejected`);
  const page=await context.newPage();page.setDefaultTimeout(30000);page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/app/workspace/personalization');
  const item=page.locator(`[data-hypothesis-id="${row.hypothesis_id}"]`);const button=item.getByRole('button',{name:'Adopt strategy',exact:true});await button.waitFor();await button.focus();await page.keyboard.press('Enter');
  await item.getByText('Adopted strategy',{exact:true}).waitFor();await page.reload();await page.locator(`[data-hypothesis-id="${row.hypothesis_id}"]`).getByText('Adopted strategy',{exact:true}).waitFor();
  const saved=(await current()).hypotheses.find(h=>h.id===row.hypothesis_id);assert.ok(saved.planningAccepted);assert.equal(saved.experiment.supportDigest,h.supportDigest);
  pass(`${row.width} keyboard adoption persists through actual API, database and reload`);
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const a11y=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('[aria-labelledby="strategy-heading"]')||document);return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}));});assert.deepEqual(a11y,[]);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,`strategy-adopted-${row.width}.png`),fullPage:true});pass(`${row.width} no horizontal overflow or serious/critical axe findings`);
  fs.writeFileSync(path.join(out,`revoke-${row.width}.json`),'{}');const deadline=Date.now()+30000;while(!fs.existsSync(path.join(out,`revoked-${row.width}.json`))){assert.ok(Date.now()<deadline,'fixture revocation timeout');await new Promise(r=>setTimeout(r,50));}
  assert.equal((await current()).hypotheses.some(x=>x.id===row.hypothesis_id),false);
  const overlays=await api('GET',root+'/overlays');assert.equal(overlays.status(),200,await overlays.text());assert.equal((await overlays.json()).strategy.some(x=>x.id===row.hypothesis_id),false);
  for(const decision of ['accepted','experiment']){const r=await api('POST',endpoint,{decision,expectedSupport:h.supportDigest});assert.equal(r.status(),409,await r.text());}
  const remaining=(await current()).hypotheses.filter(h=>!h.dimension.startsWith('trend_'));
  assert.ok(remaining.length,'Independent owned-post performance hypotheses remain available');
  await page.reload();await page.locator(`[data-hypothesis-id="${remaining[0].id}"]`).waitFor();assert.equal(await page.locator(`[data-hypothesis-id="${row.hypothesis_id}"]`).count(),0);
  await page.screenshot({path:path.join(out,`strategy-revoked-${row.width}.png`),fullPage:true});
  assert.deepEqual(external,[]);assert.deepEqual(errors,[]);pass(`${row.width} revoked support disappears and cannot adopt or experiment; zero egress/runtime errors`);
  await context.close();
 }}finally{await browser.close();fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({execution:'real_API_SQL_synthetic_history',results},null,2)+'\n');}
})().catch(e=>{console.error(e);process.exitCode=1;});
