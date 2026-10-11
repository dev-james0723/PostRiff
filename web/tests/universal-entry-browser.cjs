/** Real disposable identity, workspace, conversation and app. No model turn or external provider. */
const { chromium, webkit }=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{randomUUID}=require('node:crypto');
const args=Object.fromEntries(process.argv.slice(2).map(x=>x.replace(/^--/,'').split('='))),name=args.browser||'chromium',base=process.env.RAFII_WEB_URL||'http://127.0.0.1:4439',out=path.resolve(args.out||'.');
if(!['127.0.0.1','localhost'].includes(new URL(base).hostname))throw Error('Disposable harness only');
fs.mkdirSync(out,{recursive:true});const id=randomUUID(),headers={Authorization:`Bearer dev:${id}`,'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Origin:base},checks=[];
const check=(label,ok)=>{checks.push({name:label,ok:Boolean(ok)});console.log(`${ok?'PASS':'FAIL'} ${label}`);assert(ok,label);};
async function api(route,body){const r=await fetch(base+route,{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error(`${route} ${r.status}`);return r.json();}
const tours=[...fs.readFileSync(path.join(__dirname,'../src/features/onboarding/tours.ts'),'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map(m=>m[1]);
(async()=>{
 const {workspaceId:w}=await api('/api/auth/verify',{}),conversation=await api(`/api/workspaces/${w}/ideas/conversations`,{title:'Entry continuity'});const cid=conversation.conversationId||conversation.id;assert(cid);
 const browser=await(name==='webkit'?webkit:chromium).launch({headless:true});
 try {for(const width of[1440,390]){
  const ctx=await browser.newContext({viewport:{width,height:1000},locale:'en-US',reducedMotion:'reduce'});
  await ctx.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:id,url:base}]);
  await ctx.addInitScript(({id,w,cid,tours})=>{localStorage.setItem('postriff-dev-principal',id);sessionStorage.setItem(`rafii.panel.conversation.${w}`,cid);localStorage.setItem('postriff-onboarding',JSON.stringify({completed:{},dismissed:Object.fromEntries(tours.map(x=>[x,1])),nudged:Object.fromEntries(tours.map(x=>[x,1]))}));},{id,w,cid,tours});
  const page=await ctx.newPage();let turns=0;page.on('request',r=>{if(r.method()==='POST'&&/\/(turns?|compose)$/.test(new URL(r.url()).pathname))turns++;});
  await page.goto(`${base}/app/help`,{waitUntil:'domcontentloaded'});await page.locator('#rafii-launcher').waitFor({timeout:180000});
  if(width===1440){await page.keyboard.press('Control+k');const search=page.getByPlaceholder('Jump to a conversation or turn…');await search.fill('Ask Rafii');await page.keyboard.press('Enter');}else await page.locator('#rafii-launcher').click();
  const composer=page.locator('#rafii-panel').getByLabel('Ask Rafii',{exact:true});await composer.waitFor();await composer.fill('My unfinished question');
  // A fixed native help route contains ordinary visible page copy, not a second assistant surface.
  if(width===390){await page.locator('#rafii-panel').getByRole('button',{name:/close/i}).first().click();}
  const select=async(privateText=false)=>page.evaluate(({privateText})=>{const main=document.querySelector('main');if(!main)throw Error('No native main');let p=main.querySelector('[data-entry-test]');if(!p){p=document.createElement('p');p.setAttribute('data-entry-test','');main.prepend(p);}p.textContent='Selected visible passage';if(privateText)p.setAttribute('data-private','');else p.removeAttribute('data-private');const range=document.createRange();range.selectNodeContents(p);const selection=document.getSelection();selection.removeAllRanges();selection.addRange(range);document.dispatchEvent(new Event('selectionchange'));},{privateText});
  await select(true);await page.waitForFunction(()=>!document.querySelector('[data-rafii-selection-action]'));check(`${width}: private selection has no entry`,await page.locator('[data-rafii-selection-action]').count()===0);
  await select();await page.getByRole('button',{name:'Ask Rafii about selection',exact:true}).click();await composer.waitFor();
  await page.waitForFunction(()=>document.querySelector('#rafii-panel textarea')?.value.includes('Selected visible passage'));
  const text=await composer.inputValue();check(`${width}: selected text is quoted for review`,text.includes(JSON.stringify('Selected visible passage')));if(width===1440)check(`${width}: an already-open composer preserves unfinished text`,text.startsWith('My unfinished question'));
  check(`${width}: entry sends no model request`,turns===0);check(`${width}: underlying conversation preserved`,await page.evaluate(({w})=>sessionStorage.getItem(`rafii.panel.conversation.${w}`),{w})===cid);
  await page.evaluate(()=>document.getSelection()?.removeAllRanges());check(`${width}: selection changes do not silently replace reviewed quote`,await composer.inputValue()===text);
  check(`${width}: no horizontal overflow`,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});const violations=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('#rafii-panel'));return r.violations.filter(x=>['serious','critical'].includes(x.impact)).map(x=>x.id);});check(`${width}: accessible panel`,violations.length===0);
  await page.locator('#rafii-panel').waitFor({state:'visible'});
  await page.screenshot({path:path.join(out,`${name}-${width}-entry.png`),fullPage:width>=1000,animations:'disabled'});await ctx.close();
 }}finally{await browser.close();fs.writeFileSync(path.join(out,`${name}-receipt.json`),JSON.stringify({kind:'disposable-native-entry-no-model-calls',checks},null,2));}
})().catch(error=>{console.error(error);process.exitCode=1;});
