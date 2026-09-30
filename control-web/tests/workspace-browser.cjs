/** Actual Next/API/PostgreSQL business workflow; synthetic identity, no hosted account access. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {readFileSync,mkdirSync,writeFileSync}=require('node:fs');
const {resolve}=require('node:path');
const base='http://localhost:4549';
const evidence=resolve(__dirname,'../../docs/rafii-control-v2/evidence/business-workspace');
async function axe(page){
 await page.evaluate(source=>{const script=document.createElement('script');script.nonce=document.querySelector('script[nonce]')?.nonce||'';script.textContent=source;document.head.appendChild(script);},readFileSync(require.resolve('axe-core/axe.min.js'),'utf8'));
 const violations=await page.evaluate(async()=>{const r=await window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}));});
 assert.deepEqual(violations,[]);
}
async function login(context,token='synthetic-founder-aal2'){
 const r=await context.request.post(base+'/api/control/v2/session/exchange',{headers:{Origin:base,Authorization:'Bearer '+token,'X-Control-Exchange':'1'},data:{}});
 assert.equal(r.status(),200,await r.text());return (await r.json()).data.csrfToken;
}
async function main(){
 mkdirSync(evidence,{recursive:true});const browser=await chromium.launch({headless:true});const checks=[],expectedCancellations=[];
 try{
  const denied=await browser.newContext();const deniedPage=await denied.newPage();await deniedPage.goto(base+'/control/command');assert.match(deniedPage.url(),/sign-in/);
  assert.equal((await denied.request.get(base+'/api/control/v2/workspace/live')).status(),401);
  assert.equal((await denied.request.post(base+'/api/control/v2/session/exchange',{headers:{Origin:base,Authorization:'Bearer synthetic-non-founder-aal2','X-Control-Exchange':'1'},data:{}})).status(),403);
  await denied.close();checks.push('Unauthenticated UI/API and non-founder AAL2 exchange rejected');
  for(const width of [1440,390]){
   const context=await browser.newContext({viewport:{width,height:950},...(width===1440?{recordVideo:{dir:resolve(evidence,'recordings'),size:{width:1440,height:950}}}:{})});
   const page=await context.newPage(),errors=[];const unexpected=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('requestfailed',r=>{if(r.failure()?.errorText==='net::ERR_ABORTED'&&r.url().includes('_rsc='))expectedCancellations.push(r.url());else unexpected.push(r.failure()?.errorText+' '+r.url());});
   page.on('response',r=>{if(r.status()>=400&&r.url().includes('/api/control/'))unexpected.push(r.status()+' '+r.url());});
   const csrf=await login(context,width===390?'synthetic-founder-mobile-aal2':'synthetic-founder-aal2');
   await page.goto(base+'/control/command?mode=demo');await page.getByRole('heading',{name:'Your founder workspace',exact:true}).waitFor();await page.getByText('A few things need your attention.',{exact:true}).waitFor();
   await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Skip to content');await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>document.activeElement.id),'main');
   await axe(page);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});await page.screenshot({path:resolve(evidence,'founder-demo-'+width+'.png'),fullPage:true});
   for(const [route,heading] of [['customers','Customers'],['workspaces','Workspaces'],['billing','Billing & credits'],['support','Support'],['product','Product'],['settings','Connections'],['advanced','Advanced']]){
    await page.goto(base+'/control/'+route+'?mode=demo');await page.getByRole('heading',{name:heading,exact:true,level:1}).waitFor();await page.getByText('Demo workspace',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   }
   if(width===390){await page.locator('.fc-mobile-nav summary').click();await page.getByRole('navigation',{name:'Mobile founder navigation'}).getByRole('link',{name:'Customers',exact:true}).click();await page.getByLabel('Search customers').waitFor();}
   else await page.goto(base+'/control/customers?mode=demo');
   await page.getByLabel('Search customers').fill('Maya');await page.waitForFunction(()=>document.querySelectorAll('tbody tr').length===1);
   await page.getByRole('button',{name:'Open Maya Chen',exact:true}).click();await page.getByRole('dialog').waitFor();await axe(page);await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);
   let releaseSearch;const waitingSearch=new Promise(resolve=>{releaseSearch=resolve;});let pendingSearch;
   await page.route('**/api/control/v2/workspace/demo/query',route=>{if(route.request().postDataJSON()?.search==='no-match'){pendingSearch=route;releaseSearch();}else return route.continue();});
   await page.getByLabel('Search customers').fill('no-match');await page.getByText('Searching records…',{exact:true}).waitFor();assert.equal(await page.locator('tbody tr').count(),0);await waitingSearch;await pendingSearch.continue();
   await page.getByRole('heading',{name:'No matching records'}).waitFor();await page.unroute('**/api/control/v2/workspace/demo/query');await page.getByRole('button',{name:'Clear filters'}).click();await page.waitForFunction(()=>document.querySelectorAll('tbody tr').length===3);
   await page.getByRole('link',{name:'Fern Studio',exact:true}).click();await page.getByRole('dialog').waitFor();await page.getByLabel('Workspace name').fill('Fern Demo Renamed');await page.getByRole('button',{name:'Save name',exact:true}).click();await page.getByRole('status').filter({hasText:'Demo updated'}).waitFor();
   await page.goto(base+'/control/workspaces?mode=demo');await page.getByRole('button',{name:'Open Fern Demo Renamed',exact:true}).waitFor();
   await page.goto(base+'/control/billing?mode=demo');await page.getByRole('button',{name:'Payments',exact:true}).click();await page.locator('tbody tr').filter({hasText:'Northline Stories'}).getByRole('button').click();await page.getByRole('button',{name:'Simulate successful payment'}).click();await page.getByRole('status').filter({hasText:'Demo updated'}).waitFor();
   await page.getByRole('button',{name:'Subscriptions',exact:true}).click();await page.locator('tbody tr').filter({hasText:'Northline Stories'}).getByText('active',{exact:true}).waitFor();
   await page.goto(base+'/control/support?mode=demo');await page.getByLabel('Status', {exact:true}).selectOption('open');await page.getByRole('button',{name:'Open Payment needs attention',exact:true}).click();await page.getByRole('button',{name:'Resolve sample request'}).click();await page.getByRole('status').filter({hasText:'Demo updated'}).waitFor();await page.waitForFunction(()=>document.querySelectorAll('tbody tr').length===1);
   await page.getByRole('button',{name:'Reset Demo'}).click();await page.getByRole('status').filter({hasText:'Demo updated'}).waitFor();await page.waitForFunction(()=>document.querySelectorAll('tbody tr').length===2);
   await page.goto(base+'/control/workspaces?mode=live');await page.getByRole('button',{name:'Open Fictional Browser Workspace',exact:true}).waitFor();assert.equal((await page.locator('body').innerText()).includes('Fern Studio'),false);
   const original=await (await context.request.get('http://127.0.0.1:4550/synthetic/rafii/workspace',{headers:{Authorization:'Bearer synthetic-owner'}})).json();
   await page.getByRole('button',{name:'Open Fictional Browser Workspace',exact:true}).click();await page.getByLabel('Workspace name').fill('Fictional UI Rename '+width);await page.getByRole('button',{name:'Save name',exact:true}).click();await page.getByRole('status').filter({hasText:'Workspace name saved in Rafii.'}).waitFor();
   const reflected=await (await context.request.get('http://127.0.0.1:4550/synthetic/rafii/workspace',{headers:{Authorization:'Bearer synthetic-owner'}})).json();assert.equal(reflected.state.workspace.name,'Fictional UI Rename '+width);assert.equal(reflected.revision,original.revision+1);
   await page.getByRole('button',{name:'Open Fictional UI Rename '+width,exact:true}).click();await page.getByLabel('Workspace name').fill('Fictional Browser Workspace');await page.getByRole('button',{name:'Save name',exact:true}).click();await page.getByRole('status').filter({hasText:'Workspace name saved in Rafii.'}).waitFor();
   const restored=await (await context.request.get('http://127.0.0.1:4550/synthetic/rafii/workspace',{headers:{Authorization:'Bearer synthetic-owner'}})).json();assert.equal(restored.state.workspace.name,'Fictional Browser Workspace');
   await page.goto(base+'/control/command');await page.getByText('Database connected',{exact:true}).waitFor();assert.equal((await page.locator('body').innerText()).includes('DO_NOT_DISCLOSE'),false);await page.screenshot({path:resolve(evidence,'founder-live-local-'+width+'.png'),fullPage:true});
   for(const route of ['evidence','engineering','founder','audit','infrastructure']){await page.goto(base+'/control/'+route);await page.getByRole('heading',{level:1}).waitFor();}
   await page.goto(base+'/control/settings');await page.getByRole('heading',{name:'Connections',exact:true}).waitFor();await axe(page);
   assert.equal((await context.request.post(base+'/api/control/v2/session/logout',{headers:{Origin:'http://sibling.localhost:4549','X-CSRF-Token':csrf},data:{}})).status(),403);
   const logoutResponse=page.waitForResponse(r=>r.url().endsWith('/api/control/v2/session/logout')&&r.request().method()==='POST');await page.getByRole('button',{name:'Sign out',exact:true}).click();const logout=await logoutResponse;const logoutBody=logout.status()===200?{}:await logout.json().catch(()=>({}));assert.equal(logout.status(),200,JSON.stringify({stage:'logout',status:logout.status(),code:logoutBody.code||null}));await page.waitForURL('**/sign-in');assert.equal((await context.request.get(base+'/api/control/v2/session')).status(),401);
   assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);const video=page.video();await context.close();if(width===1440&&video)await video.saveAs(resolve(evidence,'workflow.webm'));checks.push(width+': all destinations, search/status filters, details/keyboard, linked Demo mutations/reset, canonical UI rename/reflection/restore, privacy, axe, logout passed');
  }
  const errors=await browser.newContext();await login(errors,'synthetic-founder-error-aal2');const page=await errors.newPage();
  await page.route('**/api/control/v2/workspace/live',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({code:'SOURCE_UNAVAILABLE'})}));
  await page.goto(base+'/control/command');await page.getByRole('heading',{name:'Workspace could not be loaded'}).waitFor();assert.equal(await page.locator('.metric-grid').count(),0);
  await page.getByRole('link',{name:'Demo',exact:true}).click();await page.getByText('A few things need your attention.',{exact:true}).waitFor();await errors.close();checks.push('Explicit database failure hides Live records; Demo requires explicit selection');
  writeFileSync(resolve(evidence,'browser.json'),JSON.stringify({execution:'local synthetic identities; real Next/API/restricted PostgreSQL and canonical Rafii repository',status:'passed',checks,expectedPrefetchCancellations:expectedCancellations.length},null,2));console.log(JSON.stringify({status:'passed',checks}));
 }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
