/** Real Next/API/disposable PostgreSQL + real sample bytes. Identity/storage are synthetic. */
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {readFileSync,mkdirSync,writeFileSync}=require('node:fs');
const {resolve}=require('node:path');
const {chromium,webkit}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base='http://127.0.0.1:4439';
const out=process.env.RAFII_LIBRARY_EVIDENCE||resolve(__dirname,'../../docs/consumer-ready/evidence/library');
mkdirSync(out,{recursive:true});
const checks=[];
(async()=>{
 for(const [engine,browserType] of Object.entries({chromium,webkit})){
  const browser=await browserType.launch({headless:true});
  try{for(const width of [1440,390]){
   const principal=randomUUID(),context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   const headers={Authorization:'Bearer dev:'+principal,'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Origin:base};
   await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base}]);
   await context.addInitScript(id=>localStorage.setItem('postriff-dev-principal',id),principal);
   const boot=await context.request.post(base+'/api/auth/verify',{headers,data:{plan:'studio'}});assert.equal(boot.status(),201,await boot.text());
   const ws=(await boot.json()).workspaceId,path=base+'/api/workspaces/'+ws+'/library';
   await context.route('https://devharness.supabase.co/**',async route=>{
    const req=route.request(),u=new URL(req.url());
    if(req.method()==='OPTIONS')return route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'PUT,POST,OPTIONS','Access-Control-Allow-Headers':'*'}});
    const result=await context.request.put(base+'/dev/upload/'+u.searchParams.get('token'),{data:req.postDataBuffer(),headers:{'Content-Type':req.headers()['content-type']}});
    return route.fulfill({status:result.status(),body:await result.body(),headers:{'Content-Type':'application/json','Access-Control-Allow-Origin':'*'}});
   });
   await context.route('https://dev.invalid/**',async route=>{
    const u=new URL(route.request().url()),r=await context.request.get(base+'/dev/storage'+u.pathname);
    return route.fulfill({status:r.status(),body:await r.body(),headers:{'Content-Type':r.headers()['content-type'],'Access-Control-Allow-Origin':'*'}});
   });
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
   await page.goto(base+'/app/library');
   const welcome=page.getByRole('button',{name:'Not now',exact:true});
   try{await welcome.waitFor({state:'visible',timeout:5000});await welcome.click();await welcome.waitFor({state:'hidden',timeout:5000});}
   catch(error){if(await welcome.isVisible().catch(()=>false))throw error;}
   const picker=page.getByLabel('Choose assets');await picker.waitFor({state:'attached'});
   await picker.setInputFiles({name:'rehearsal-'+width+'.md',mimeType:'text/markdown',buffer:Buffer.from('Browser Brahms acceptance '+engine+' '+width+'\nFinger exercises and rehearsal notes.')});
   try{await page.getByRole('button',{name:/Document rehearsal/}).first().waitFor({timeout:30000});}
   catch(error){
    const response=await context.request.get(path,{headers}),listing=await response.text();
    const body=await page.locator('body').innerText().catch(()=>''),buttons=await page.getByRole('button').allTextContents({timeoutMs:3000}).catch(()=>[]);
    throw new Error(`${error.message}\nLibrary API ${response.status()}: ${listing.slice(0,3000)}\nVisible page: ${body.slice(0,2000)}\nButtons: ${JSON.stringify(buttons.slice(0,40))}`);
   }
   let listing,doc;const indexDeadline=Date.now()+30000;
   while(Date.now()<indexDeadline){
    listing=await (await context.request.get(path,{headers})).json();doc=listing.assets.find(a=>a.originalFilename==='rehearsal-'+width+'.md');
    if(doc&&doc.indexingStatus!=='pending')break;
    await new Promise(resolve=>setTimeout(resolve,250));
   }
   assert.ok(doc,`uploaded Markdown asset missing from Library listing: ${JSON.stringify(listing)}`);assert.equal(doc.indexingStatus,'ready',`Markdown indexing did not become ready: ${JSON.stringify(doc)}`);
   await page.getByRole('button',{name:/Document rehearsal/}).first().click();
   await page.getByLabel('Title',{exact:true}).fill('Brahms browser notes');await page.getByLabel('Tags, separated by commas').fill('music, rehearsal');
   await page.getByRole('button',{name:'Save details',exact:true}).click();
   await page.getByRole('button',{name:'Use as a source',exact:true}).click();await page.getByRole('link',{name:'Review source in Memory'}).waitFor();
   await page.getByRole('button',{name:'Close asset details'}).click();
   await page.getByText('Manage collections',{exact:true}).click();await page.getByLabel('New collection name').fill('Practice');
   const collectionForm=page.locator('form').filter({has:page.getByLabel('New collection name')});await collectionForm.getByRole('button',{name:'Create',exact:true}).click();
   await page.getByRole('button',{name:/Document Brahms browser notes/}).first().click();await page.getByRole('checkbox',{name:'Add to collection Practice'}).check();await page.getByRole('button',{name:'Save details',exact:true}).click();
   await page.getByRole('button',{name:'Close asset details'}).click();
   // Search only words inside the file; server full-text results drive the UI.
   const search=page.getByRole('searchbox');await search.fill('Finger exercises');await page.getByRole('button',{name:/Document Brahms browser notes/}).first().waitFor();
   await search.fill('');
   for(const ext of ['pdf','docx','xlsx','pptx','txt','markdown','html','htm','json','csv','bin','wav','mp3','m4a','ogg','oga','flac','aac','webm']){
    const bytes=readFileSync(resolve(__dirname,'../../.codex/library-samples/archive-acceptance.'+ext));
    const mime={pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',pptx:'application/vnd.openxmlformats-officedocument.presentationml.presentation',wav:'audio/wav',mp3:'audio/mpeg',m4a:'audio/mp4',ogg:'audio/ogg',oga:'audio/ogg',flac:'audio/flac',aac:'audio/aac',webm:'audio/webm',txt:'text/plain',markdown:'text/markdown',html:'text/html',htm:'text/html',json:'application/json',csv:'text/csv',bin:'application/octet-stream'}[ext];
    const ticketResponse=await context.request.post(path+'/files',{headers,data:{filename:'sample.'+ext,mime,bytes:bytes.length}});assert.equal(ticketResponse.status(),201,await ticketResponse.text());
    const ticket=(await ticketResponse.json()).upload;
    assert.equal((await context.request.put(base+'/dev/upload/'+new URL(ticket.url).searchParams.get('token'),{data:bytes,headers:{'Content-Type':mime}})).status(),200);
    const committed=await context.request.post(path+'/files/'+ticket.assetId+'/commit',{headers,data:{}});assert.ok(committed.ok(),await committed.text());
    await context.request.post(base+'/dev/library/tick?workspace='+ws+'&assetId='+ticket.assetId);
    const d=await (await context.request.get(path+'/files/'+ticket.assetId,{headers})).json();
    assert.ok(['ready','unsupported','duplicate'].includes(d.asset.processing),JSON.stringify(d));
    if(d.asset.processing==='ready')assert.match(d.extractedText,/Rafii archive acceptance/);
    checks.push({engine,width,format:ext,status:d.asset.processing,execution:'real file/API/DB; synthetic identity/storage'});
   }
   await page.reload();
   await page.getByRole('button',{name:/Audio sample/}).first().click();
   await page.getByRole('button',{name:'Play audio in Now Playing'}).click();
   await page.getByLabel('Now Playing',{exact:true}).waitFor();
   await page.getByText('Add or replace transcript',{exact:true}).click();await page.getByLabel('Transcript',{exact:true}).fill('Searchable audio bowing lesson.');await page.getByRole('button',{name:'Save transcript',exact:true}).click();
   await page.getByRole('button',{name:'Close asset details'}).click();
   await page.screenshot({path:resolve(out,`library-${engine}-${width}.png`),fullPage:true});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow');
   const beforeDelete=await (await context.request.get(path,{headers})).json();
   const target=beforeDelete.assets.find(a=>a.id===doc.id);
   assert.ok(target,`delete target ${doc.id} missing from current library`);
   assert.equal(target.displayTitle,'Brahms browser notes',`delete target changed: ${JSON.stringify(target)}`);
   await page.getByRole('button',{name:/Document Brahms browser notes/}).first().click();await page.getByRole('button',{name:'Delete…',exact:true}).click();
   const dialog=page.getByRole('alertdialog');
   const deletionResponse=page.waitForResponse(r=>r.request().method()==='DELETE'&&r.url().includes('/library/files/'),{timeout:10000});
   await dialog.getByRole('button',{name:/^Delete/}).click();
   const deletion=await deletionResponse;
   const deletionBody=await deletion.text();
   assert.equal(deletion.status(),200,`DELETE ${deletion.url()} returned ${deletion.status()}: ${deletionBody}`);
   const deletionResult=JSON.parse(deletionBody);
   assert.equal(deletionResult.assetId,doc.id,`DELETE targeted a different asset: ${JSON.stringify(deletionResult)}`);
   assert.equal(deletionResult.status,'deleted',`DELETE did not report deletion: ${JSON.stringify(deletionResult)}`);
   await page.getByRole('button',{name:/Document Brahms browser notes/}).waitFor({state:'detached',timeout:15000});
   const afterDelete=await context.request.get(path+'/files/'+doc.id,{headers});
   assert.equal(afterDelete.status(),404,`deleted asset ${doc.id} still resolves: ${await afterDelete.text()}`);
   assert.deepEqual(errors,[],'browser runtime errors');
   checks.push({engine,width,status:'pass',flows:['upload','rename','tags','collection','search','source-review','audio-player','transcript','delete','responsive'],execution:'real UI/API/DB; synthetic storage/identity'});
   await context.close();
  }}finally{await browser.close();}
 }
 writeFileSync(resolve(out,'browser.json'),JSON.stringify({status:'pass',checks},null,2));console.log(JSON.stringify({status:'pass',checks}));
})().catch(error=>{writeFileSync(resolve(out,'browser-failure.json'),JSON.stringify({status:'fail',error:String(error),checks},null,2));console.error(error);process.exitCode=1;});
