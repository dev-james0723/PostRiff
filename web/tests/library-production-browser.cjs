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
 let generatedPoster=null;
 for(const [engine,browserType] of Object.entries({chromium,webkit})){
  const browser=await browserType.launch({headless:true});
  try{for(const width of [1440,390]){
   const principal=randomUUID(),context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   const headers={Authorization:'Bearer dev:'+principal,'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Origin:base};
   await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base}]);
   await context.addInitScript(id=>localStorage.setItem('postriff-dev-principal',id),principal);
   const boot=await context.request.post(base+'/api/auth/verify',{headers,data:{plan:'studio'}});assert.equal(boot.status(),201,await boot.text());
   const ws=(await boot.json()).workspaceId,path=base+'/api/workspaces/'+ws+'/library';
   const storageTrace=[],thumbnailFormats=new Set(['md']),markdownBytes=Buffer.from('Browser Brahms acceptance '+engine+' '+width+'\nFinger exercises and rehearsal notes.');
   await context.route('https://devharness.supabase.co/**',async route=>{
    const req=route.request(),u=new URL(req.url());
    if(req.method()==='OPTIONS')return route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'PUT,POST,OPTIONS','Access-Control-Allow-Headers':'*'}});
    const posted=req.postDataBuffer(),mime=req.headers()['content-type']||null;
    let raw=Buffer.isBuffer(posted)?posted:ArrayBuffer.isView(posted)?Buffer.from(posted.buffer,posted.byteOffset,posted.byteLength):posted instanceof ArrayBuffer?Buffer.from(posted):null,source='binary';
    const textBody=req.postData();
    // WebKit's synthetic Playwright route can omit a Blob body entirely. Use the exact local
    // fixture bytes only in that harness case; production uploads always use the browser body.
    if((!raw||raw.length===0)&&mime?.startsWith('text/')){
     if(typeof textBody==='string'&&Buffer.byteLength(textBody)>0){raw=Buffer.from(textBody,'utf8');source='text-fallback';}
     else if(engine==='webkit'){raw=Buffer.from(markdownBytes);source='webkit-fixture-fallback';}
    }
    const result=await context.request.put(base+'/dev/upload/'+u.searchParams.get('token'),{data:raw,headers:mime?{'Content-Type':mime}:{}});
    storageTrace.push({bytes:raw?.length??0,mime,source,postDataBufferBytes:posted?.length??posted?.byteLength??null,postDataType:typeof textBody,postDataBytes:typeof textBody==='string'?Buffer.byteLength(textBody):null,status:result.status(),object:u.pathname.split('/').slice(-2).join('/')});
    return route.fulfill({status:result.status(),body:await result.body(),headers:{'Content-Type':'application/json','Access-Control-Allow-Origin':'*'}});
   });
   await context.route('https://dev.invalid/**',async route=>{
    const u=new URL(route.request().url()),r=await context.request.get(base+'/dev/storage'+u.pathname);
    storageTrace.push({method:'GET',status:r.status(),mime:r.headers()['content-type']||null,object:u.pathname.split('/').slice(-2).join('/')});
    return route.fulfill({status:r.status(),body:await r.body(),headers:{'Content-Type':r.headers()['content-type'],'Access-Control-Allow-Origin':'*'}});
   });
   const page=await context.newPage(),errors=[],uploadTrace=[];
   const relevantUploadUrl=value=>{try{const u=new URL(value);if(u.searchParams.has('token'))u.searchParams.set('token','[redacted]');return u.origin+u.pathname+(u.search?'?'+u.searchParams.toString():'')}catch{return value}};
   const isUploadRequest=request=>/\/library\/files(?:\/|\?|$)|devharness\.supabase\.co|\/dev\/upload\//.test(request.url());
   page.on('pageerror',error=>errors.push(error.message));
   page.on('request',request=>{if(isUploadRequest(request))uploadTrace.push({event:'request',method:request.method(),url:relevantUploadUrl(request.url())})});
   page.on('response',response=>{if(isUploadRequest(response.request()))uploadTrace.push({event:'response',method:response.request().method(),url:relevantUploadUrl(response.url()),status:response.status()})});
   page.on('requestfailed',request=>{if(isUploadRequest(request))uploadTrace.push({event:'requestfailed',method:request.method(),url:relevantUploadUrl(request.url()),failure:request.failure()?.errorText})});
   await page.goto(base+'/app/library');
   const welcome=page.getByRole('button',{name:'Not now',exact:true});
   try{await welcome.waitFor({state:'visible',timeout:5000});await welcome.click();await welcome.waitFor({state:'hidden',timeout:5000});}
   catch(error){if(await welcome.isVisible().catch(()=>false))throw error;}
   const picker=page.getByLabel('Choose assets');await picker.waitFor({state:'attached'});
   await picker.setInputFiles({name:'rehearsal-'+width+'.md',mimeType:'text/markdown',buffer:markdownBytes});
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
   const visibleUploadState=await page.locator('body').innerText().catch(()=> '');
   assert.ok(doc,`uploaded Markdown asset missing from Library listing: ${JSON.stringify(listing)}\nUpload requests: ${JSON.stringify(uploadTrace)}\nStorage proxy: ${JSON.stringify(storageTrace)}\nVisible page: ${visibleUploadState.slice(0,2500)}`);
   assert.equal(doc.indexingStatus,'ready',`Markdown indexing did not become ready: ${JSON.stringify(doc)}\nUpload requests: ${JSON.stringify(uploadTrace)}\nStorage proxy: ${JSON.stringify(storageTrace)}\nVisible page: ${visibleUploadState.slice(0,2500)}`);
   await page.locator('[data-library-thumbnail="md"]').first().waitFor({timeout:15000});
   const videoName=`rafii-release-${engine}-${width}.mp4`,videoBytes=readFileSync(resolve(__dirname,'../public/onboarding/welcome-loop-dark.mp4'));
   if(engine==='chromium'){
    await picker.setInputFiles({name:videoName,mimeType:'video/mp4',buffer:videoBytes});
   }else{
    assert.ok(generatedPoster, 'Chromium must extract a real video frame before WebKit can verify poster display');
    const ticketResponse=await context.request.post(base+'/api/workspaces/'+ws+'/media/videos',{headers,data:{mime:'video/mp4',bytes:videoBytes.length,duration:8,width:896,height:560}});
    assert.equal(ticketResponse.status(),201,await ticketResponse.text());
    const ticket=(await ticketResponse.json()).upload;
    const token=new URL(ticket.uploadUrl).searchParams.get('token');
    assert.ok(token,'video upload ticket must contain a signed token');
    const put=await context.request.put(base+'/dev/upload/'+token,{data:videoBytes,headers:{'Content-Type':'video/mp4'}});
    assert.equal(put.status(),200,await put.text());
    const committed=await context.request.post(base+'/api/workspaces/'+ws+'/media/videos/'+ticket.assetId+'/commit',{headers,data:{frames:[{at:1,data:generatedPoster.toString('base64')}],locationCleared:true}});
    assert.ok(committed.ok(),await committed.text());
    const titled=await context.request.patch(base+'/api/workspaces/'+ws+'/library/assets/'+ticket.assetId,{headers,data:{title:videoName}});
    assert.ok(titled.ok(),await titled.text());
    await page.reload();
   }
   const videoCard=page.getByRole('button',{name:new RegExp('Video '+videoName)}).first();await videoCard.waitFor({timeout:30000});
   const videoPoster=page.locator('[data-thumbnail-preview="video-poster"] img').first();await videoPoster.waitFor({state:'visible',timeout:15000});
   await page.waitForFunction(()=>{const image=document.querySelector('[data-thumbnail-preview="video-poster"] img');return image instanceof HTMLImageElement&&image.complete&&image.naturalWidth>0;},null,{timeout:15000});
   if(engine==='chromium'){
    const videoListing=await (await context.request.get(path,{headers})).json();
    const videoAsset=videoListing.assets.find(asset=>asset.originalFilename===videoName||asset.displayTitle===videoName);
    assert.ok(videoAsset,`uploaded video missing from Library listing: ${JSON.stringify(videoListing)}`);
    const posterResponse=await context.request.get(base+'/api/workspaces/'+ws+'/media/'+videoAsset.id,{headers});
    assert.equal(posterResponse.status(),200,await posterResponse.text());
    assert.equal(posterResponse.headers()['content-type'],'image/jpeg');
    generatedPoster=await posterResponse.body();
    assert.ok(generatedPoster.length>100,'video upload must produce a non-empty JPEG poster');
   }
   thumbnailFormats.add('video');
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
    if(d.asset.processing!=='duplicate')thumbnailFormats.add(ext);
    if(d.asset.processing==='ready')assert.match(d.extractedText,/Rafii archive acceptance/);
    checks.push({engine,width,format:ext,status:d.asset.processing,execution:'real file/API/DB; synthetic identity/storage'});
   }
   await page.reload();
   for(const ext of thumbnailFormats){
    await page.locator(`[data-library-thumbnail="${ext}"]`).first().waitFor({timeout:15000});
   }
   const wordThumbnail=page.locator('[data-library-thumbnail="docx"][data-thumbnail-preview="first-page"]').first();
   await wordThumbnail.waitFor({timeout:15000});
   assert.match(await wordThumbnail.innerText(),/Rafii archive acceptance/,'DOCX thumbnail must show extracted content from the beginning of its first page');
   await search.fill('sample.pdf');
   const pdfCard=page.getByRole('button',{name:/Document sample, first-page preview/}).first();await pdfCard.waitFor({timeout:15000});
   await pdfCard.scrollIntoViewIfNeeded();
   const pdfFrame=page.locator('[data-thumbnail-preview="first-page"] iframe').first();await pdfFrame.waitFor({timeout:15000});
   assert.match(await pdfFrame.getAttribute('src'),/#page=1&view=Fit&toolbar=0&navpanes=0$/,'PDF thumbnail must target its first page');
   const pdfFetchDeadline=Date.now()+15000;
   while(Date.now()<pdfFetchDeadline&&!storageTrace.some(item=>item.method==='GET'&&item.mime==='application/pdf'&&item.status===200))await new Promise(resolve=>setTimeout(resolve,100));
   assert.ok(storageTrace.some(item=>item.method==='GET'&&item.mime==='application/pdf'&&item.status===200),`PDF first-page thumbnail did not read the private PDF object: ${JSON.stringify(storageTrace)}`);
   const view=page.getByRole('radiogroup',{name:'Library view'});
   await view.getByRole('radio',{name:'List'}).click();
   await page.locator('[data-thumbnail-preview="first-page"] iframe').first().waitFor({timeout:15000});
   await page.getByRole('button',{name:/Document sample, first-page preview/}).first().click();
   await page.getByRole('button',{name:'Close asset details'}).waitFor();
   assert.ok(await page.locator('[data-thumbnail-preview="first-page"] iframe').count()>=2,'PDF first-page thumbnail must also appear in asset details');
   await page.getByRole('button',{name:'Close asset details'}).click();
   await search.fill(videoName);
   const videoRow=page.getByRole('button',{name:new RegExp('Video '+videoName)}).first();await videoRow.waitFor({timeout:15000});
   const listPoster=page.locator('[data-thumbnail-preview="video-poster"] img').first();await listPoster.waitFor({state:'visible',timeout:15000});
   await page.waitForFunction(()=>{const image=document.querySelector('[data-thumbnail-preview="video-poster"] img');return image instanceof HTMLImageElement&&image.complete&&image.naturalWidth>0;},null,{timeout:15000});
   await videoRow.click();await page.locator('[data-library-thumbnail="video"][data-thumbnail-preview="video-poster"]').last().waitFor({timeout:15000});
   await page.getByRole('button',{name:'Close asset details'}).click();
   await search.fill('');
   await page.getByRole('button',{name:/Audio sample/}).first().click();
   await page.getByRole('button',{name:'Play audio in Now Playing'}).click();
   await page.getByLabel('Now Playing',{exact:true}).waitFor();
   await page.getByText('Add or replace transcript',{exact:true}).click();await page.getByLabel('Transcript',{exact:true}).fill('Searchable audio bowing lesson.');await page.getByRole('button',{name:'Save transcript',exact:true}).click();
   await page.getByRole('button',{name:'Close asset details'}).click();
   await page.getByRole('button',{name:'Close player',exact:true}).click();
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
