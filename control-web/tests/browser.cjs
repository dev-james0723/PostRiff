/** Production Next -> Control WSGI -> real restricted PostgreSQL; synthetic identity only. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {readFileSync,mkdirSync,writeFileSync}=require('node:fs');
const {resolve}=require('node:path');
const base='http://localhost:4449';
async function main(){
 const browser=await chromium.launch({headless:true});const checks=[];
 try {
  const denied=await browser.newContext();const page=await denied.newPage();await page.goto(base+'/control/command');assert.match(page.url(),/sign-in/);assert.equal((await denied.request.get(base+'/api/control/v2/session')).status(),401);await denied.close();checks.push('unauthenticated route/API denied');
  for(const width of [390,1440]){
   const context=await browser.newContext({viewport:{width,height:950}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
   const exchange=await context.request.post(base+'/api/control/v2/session/exchange',{headers:{Origin:base,Authorization:'Bearer synthetic-founder-aal2','X-Control-Exchange':'1'},data:{}});assert.equal(exchange.status(),200,await exchange.text());
   const csrf=(await exchange.json()).data.csrfToken;
   await page.goto(base+'/control/command');await page.getByRole('heading',{name:'Command',exact:true,level:1}).waitFor();await page.getByRole('heading',{name:'Investigation queue'}).waitFor();assert.equal(await page.locator('p.metric').filter({hasText:'Unavailable'}).count(),6);
   await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'Skip to content');await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>document.activeElement.id),'main');
   await page.getByRole('link',{name:'Customers',exact:true}).click();await page.getByRole('button',{name:/Open User 360/}).first().click();await page.getByText('Private customer content: suppressed. A scoped support grant is required.').waitFor();assert.equal((await page.locator('body').innerText()).includes('DO_NOT_DISCLOSE_CUSTOMER_SECRET'),false);
   await page.getByRole('link',{name:'Browse Workspaces'}).click();await page.getByRole('heading',{name:'Workspaces',exact:true}).waitFor();await page.getByRole('table').waitFor();
   await page.getByRole('link',{name:'Engineering',exact:true}).click();await page.getByText('Code-check dispatch, patch creation, and deployment controls require later qualification and approval.').waitFor();
   await page.getByRole('link',{name:'Founder Rafii',exact:true}).click();await page.getByLabel('Business question').fill('Inspect activation; do not execute a refund');await page.getByRole('button',{name:'Inspect evidence'}).click();await page.getByRole('heading',{name:'Evidence & limitations'}).waitFor();await page.getByText(/Query receipt:/).waitFor();
   await page.getByRole('link',{name:'Revenue',exact:true}).click();await page.getByText('Definitions are versioned proposals.',{exact:false}).waitFor();await page.getByText('Definition and limitations',{exact:true}).first().click();await page.getByRole('button',{name:'Inspect last 28 days'}).first().click();await page.getByText(/Receipt:/).waitFor();await page.getByText('No qualified values to plot.',{exact:false}).waitFor();
   for(const route of ['product','infrastructure','support','settings']){await page.goto(base+'/control/'+route);await page.getByRole('heading',{level:1}).waitFor();}
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.evaluate(source=>{const script=document.createElement('script');script.nonce=document.querySelector('script[nonce]')?.nonce||'';script.textContent=source;document.head.appendChild(script);},readFileSync(require.resolve('axe-core/axe.min.js'),'utf8'));
   const violations=await page.evaluate(async()=>{const results=await window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return results.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}));});assert.deepEqual(violations,[]);
   const forbidden=await context.request.post(base+'/api/control/v2/actions/refund',{headers:{Origin:base,'X-CSRF-Token':csrf},data:{}});assert.equal(forbidden.status(),404);
   const sibling=await context.request.post(base+'/api/control/v2/session/logout',{headers:{Origin:'http://sibling.localhost:4449','X-CSRF-Token':csrf},data:{}});assert.equal(sibling.status(),403);
   assert.equal(await page.evaluate(()=>Object.keys(localStorage).some(key=>/supabase|auth-token/i.test(key))),false);
   const evidence=resolve(__dirname,'../../docs/rafii-control-v2/evidence');mkdirSync(evidence,{recursive:true});await page.screenshot({path:resolve(evidence,'control-settings-'+width+'.png'),fullPage:true});
   await page.getByRole('button',{name:'Sign out',exact:true}).click();await page.waitForURL('**/sign-in');assert.equal((await context.request.get(base+'/api/control/v2/session')).status(),401);assert.deepEqual(errors,[]);await context.close();checks.push('width '+width+': navigation/User360/canary/receipts/copilot/CSRF/axe/logout passed');
  }
  writeFileSync(resolve(__dirname,'../../docs/rafii-control-v2/evidence/browser.json'),JSON.stringify({execution:'local synthetic identity; real Next/API/restricted PostgreSQL',status:'passed',checks},null,2));console.log(JSON.stringify({status:'passed',checks}));
 } finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
