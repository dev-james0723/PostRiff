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
   const inlineVideo=page.locator('[data-library-media-player="video"]').first();
   const previewVideo=inlineVideo.locator('video');await inlineVideo.scrollIntoViewIfNeeded();
   if(engine==='chromium'){
    // Reduced motion never starts moving previews. The same actual MP4 must start
    // silently when the user allows motion, without a click on its card.
    await previewVideo.waitFor({state:'attached'});
    assert.ok(await previewVideo.evaluate(video=>video.paused),'reduced motion disables automatic video preview');
    await page.emulateMedia({reducedMotion:'no-preference'});
    const waitForSilentVideo=async()=>{
     try{await page.waitForFunction(()=>{const video=document.querySelector('[data-library-media-player="video"] video');return video instanceof HTMLVideoElement&&!video.paused&&video.currentTime>0&&video.muted;},null,{timeout:20000});}
     catch(error){
      const diagnostic=await previewVideo.evaluate(video=>({paused:video.paused,muted:video.muted,time:video.currentTime,duration:Number.isFinite(video.duration)?video.duration:null,readyState:video.readyState,networkState:video.networkState,error:video.error?{code:video.error.code,message:video.error.message}:null,hasSource:Boolean(video.currentSrc),visible:document.visibilityState,motionReduced:matchMedia('(prefers-reduced-motion: reduce)').matches,bounds:{top:video.getBoundingClientRect().top,bottom:video.getBoundingClientRect().bottom},playerText:video.closest('[data-library-media-player]')?.textContent}));
      throw new Error(`${error.message}\nActual video diagnostics: ${JSON.stringify(diagnostic)}`);
     }
    };
    await waitForSilentVideo();
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>document.querySelector('[data-library-media-player="video"] video')?.paused===true,null,{timeout:5000});
    await page.emulateMedia({reducedMotion:'no-preference'});
    await waitForSilentVideo();
    await inlineVideo.getByRole('button',{name:'Pause video preview',exact:true}).click();
    const videoTimeline=inlineVideo.getByRole('slider',{name:'Video preview timeline',exact:true});
    const seekVideoHandle=await previewVideo.elementHandle();
    await page.waitForFunction(video=>video.paused,seekVideoHandle,{timeout:5000});
    await videoTimeline.focus();await videoTimeline.press('Home');
    await page.waitForFunction(video=>!video.seeking&&video.currentTime<0.075,seekVideoHandle,{timeout:5000});
    await previewVideo.evaluate(video=>{delete video.dataset.acceptanceSeeked;video.addEventListener('seeked',()=>{video.dataset.acceptanceSeeked='yes';},{once:true});});
    await videoTimeline.press('ArrowRight');
    await page.waitForFunction(video=>video.dataset.acceptanceSeeked==='yes'&&!video.seeking,seekVideoHandle,{timeout:5000});
    assert.ok(await previewVideo.evaluate(video=>video.currentTime>0&&video.currentTime<0.25),'video timeline keyboard seeks actual MP4 after the native seeked event: '+JSON.stringify(await previewVideo.evaluate(video=>({time:video.currentTime,seeking:video.seeking,paused:video.paused,range:video.closest('[data-library-media-player]')?.querySelector('input[type="range"]')?.value}))));
    await inlineVideo.getByRole('combobox',{name:'Video playback speed',exact:true}).selectOption('1.5');
    assert.equal(await previewVideo.evaluate(video=>video.playbackRate),1.5);
    await page.emulateMedia({reducedMotion:'reduce'});
    checks.push({engine,width,format:'mp4',inline:'actual silent autoplay; reduced-motion pause; timeline; speed',execution:'real original MP4/UI; synthetic identity/storage'});
   }else checks.push({engine,width,format:'mp4',inline:'actual captured poster verified; H264 playback unavailable in Linux WebKit harness',execution:'real captured Chromium source frame; synthetic identity/storage; no WebKit video-playback claim'});
   await page.getByRole('button',{name:/Document rehearsal/}).first().click();
   await page.getByRole('button',{name:'Open document viewer',exact:true}).click();
   const markdownReader=page.locator('[data-document-viewer]');
   await markdownReader.locator('img[data-document-page="1"]').waitFor({state:'visible',timeout:90000});
   await markdownReader.getByRole('button',{name:'Read page text',exact:true}).click();
   assert.match(await markdownReader.getByRole('article',{name:'Extracted text of page 1'}).innerText(),/Finger exercises/,'Markdown viewer must read original typeset source text');
   await page.keyboard.press('Escape');
   await markdownReader.waitFor({state:'hidden'});
   const returnedViewerTrigger=page.getByRole('button',{name:'Open document viewer',exact:true});
   assert.ok(await returnedViewerTrigger.evaluate(element=>element===document.activeElement),'Escape closes only the nested reader and restores its launcher focus');
   await page.getByLabel('Title',{exact:true}).fill('Brahms browser notes');await page.getByLabel('Tags, separated by commas').fill('music, rehearsal');
   await page.getByRole('button',{name:'Save details',exact:true}).click();
   await page.getByRole('button',{name:'Use as a source',exact:true}).click();
   const sourceReviewLink=page.getByRole('link',{name:'Review source in Ideas',exact:true});await sourceReviewLink.waitFor();
   assert.match(await sourceReviewLink.getAttribute('href'),/^\/app\/ideas\?source=[a-f0-9]{32}$/,'source review must target the real source inspector');
   await sourceReviewLink.click();await page.waitForURL(/\/app\/ideas\?source=/);
   await page.locator('[data-tour="ideas-facts"]').getByText('Finger exercises',{exact:false}).waitFor({timeout:15000});
   await page.getByRole('heading',{name:'How it may be used',exact:true}).waitFor();
   checks.push({engine,width,source:'actual Library import opens its source facts and sharing review',execution:'real UI/API/DB; synthetic identity/storage; no model call'});
   await page.goto(base+'/app/library');await page.getByRole('button',{name:/Document Brahms browser notes/}).first().click();
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
   for(const ext of ['docx','xlsx','pptx','pdf','md']){
    await search.fill(ext==='md'?'Brahms browser notes':'sample.'+ext);
    const raster=page.locator(`[data-library-thumbnail="${ext}"][data-thumbnail-preview="first-page-raster"] img`).first();
    await raster.waitFor({state:'visible',timeout:90000});
    await raster.evaluate(image=>image.decode());
    assert.ok(await raster.evaluate(image=>image.naturalWidth>500&&image.naturalHeight>500),ext+' must display a real page raster');
    await page.screenshot({path:resolve(out,`page-${ext}-${engine}-${width}.png`),fullPage:true});
    checks.push({engine,width,format:ext,preview:'actual source-page JPEG',execution:'real source bytes and renderer; synthetic identity/storage'});
   }
   await search.fill('sample.pdf');
   const pdfCard=page.getByRole('button',{name:/Document sample, first-page preview/}).first();await pdfCard.waitFor({timeout:15000});
   assert.ok(storageTrace.some(item=>item.method==='GET'&&item.mime==='image/jpeg'&&item.status===200),'Preview must fetch private raster bytes');
   const view=page.getByRole('radiogroup',{name:'Library view'});
   await view.getByRole('radio',{name:'List'}).click();
   await page.locator('[data-library-thumbnail="pdf"][data-thumbnail-preview="first-page-raster"] img').first().waitFor({timeout:15000});
   await page.getByRole('button',{name:/Document sample, first-page preview/}).first().click();
   await page.getByRole('button',{name:'Close asset details'}).waitFor();
   assert.ok(await page.locator('[data-library-thumbnail="pdf"][data-thumbnail-preview="first-page-raster"] img').count()>=2,'Actual PDF page must also appear in asset details');
   await page.getByRole('button',{name:'Close asset details'}).click();
   // Real two-page PDF: the reader must navigate source pages, not reuse its thumbnail.
   const viewerBytes=readFileSync(resolve(__dirname,'../../.codex/library-samples/archive-viewer.pdf'));
   const viewerTicketResponse=await context.request.post(path+'/files',{headers,data:{filename:'archive-viewer.pdf',mime:'application/pdf',bytes:viewerBytes.length}});
   assert.equal(viewerTicketResponse.status(),201,await viewerTicketResponse.text());
   const viewerTicket=(await viewerTicketResponse.json()).upload;
   assert.equal((await context.request.put(base+'/dev/upload/'+new URL(viewerTicket.url).searchParams.get('token'),{data:viewerBytes,headers:{'Content-Type':'application/pdf'}})).status(),200);
   assert.ok((await context.request.post(path+'/files/'+viewerTicket.assetId+'/commit',{headers,data:{}})).ok());
   await context.request.post(base+'/dev/library/tick?workspace='+ws+'&assetId='+viewerTicket.assetId);
   await page.reload();await search.fill('archive-viewer.pdf');
   await page.getByRole('button',{name:/Document archive-viewer, first-page preview/}).first().click();
   await page.getByRole('button',{name:'Open document viewer',exact:true}).click();
   const reader=page.locator('[data-document-viewer]');await reader.waitFor({state:'visible'});
   const firstPage=reader.locator('img[data-document-page="1"]');await firstPage.waitFor({state:'visible',timeout:90000});await firstPage.evaluate(image=>image.decode());
   assert.ok(await firstPage.evaluate(image=>image.naturalWidth>500&&image.naturalHeight>500),'reader must load actual first-page raster');
   const firstPageSrc=await firstPage.getAttribute('src');
   assert.ok(await reader.getByRole('button',{name:'Previous page',exact:true}).isDisabled(),'first page has no previous page');
   assert.match(await reader.locator('#document-page-total').innerText(),/2/,'actual page count');
   await reader.getByRole('button',{name:'Show page sidebar',exact:true}).click();
   await reader.getByRole('button',{name:'Go to page 2',exact:true}).waitFor();
   await reader.getByRole('button',{name:'Go to page 2',exact:true}).click();
   const secondPage=reader.locator('img[data-document-page="2"]');await secondPage.waitFor({state:'visible',timeout:90000});await secondPage.evaluate(image=>image.decode());
   assert.notEqual(firstPageSrc,await secondPage.getAttribute('src'),'source pages have distinct images');
   assert.ok(await reader.getByRole('button',{name:'Next page',exact:true}).isDisabled(),'last page has no next page');
   await reader.getByRole('button',{name:'Read page text',exact:true}).click();
   assert.match(await reader.getByRole('article',{name:'Extracted text of page 2'}).innerText(),/Viewer second page/);
   await reader.getByRole('button',{name:'Find text on current page',exact:true}).click();
   await reader.getByLabel('Find on this page',{exact:true}).fill('second');
   await reader.locator('mark').first().waitFor();assert.ok(await reader.locator('mark').count()>0,'current-page search must highlight actual extracted text');
   await reader.getByRole('button',{name:'Close page search',exact:true}).click();
   await reader.getByRole('button',{name:'Show original page layout',exact:true}).click();
   await reader.getByLabel('Document zoom',{exact:true}).selectOption('100');
   assert.match(await reader.locator('footer').innerText(),/100%/);
   await reader.getByRole('button',{name:'Rotate page clockwise',exact:true}).click();
   assert.match(await secondPage.getAttribute('style'),/rotate\(90deg\)/);
   await reader.getByRole('button',{name:'Rotate page clockwise',exact:true}).click();
   await reader.getByRole('button',{name:'Rotate page clockwise',exact:true}).click();
   await reader.getByRole('button',{name:'Rotate page clockwise',exact:true}).click();
   await reader.getByLabel('Document zoom',{exact:true}).selectOption('width');
   const readerStage=reader.getByRole('slider',{name:'Page navigation',exact:true});await readerStage.focus();await readerStage.press('Home');
   await reader.locator('img[data-document-page="1"]').waitFor({state:'visible',timeout:90000});
   await reader.getByLabel('Page number',{exact:true}).fill('2');await reader.getByLabel('Page number',{exact:true}).press('Enter');
   await reader.locator('img[data-document-page="2"]').waitFor({state:'visible',timeout:90000});
   await reader.getByLabel('Document zoom',{exact:true}).selectOption('page');
   assert.ok(await reader.evaluate(element=>element.getBoundingClientRect().width<=innerWidth+1),'reader controls fit the viewport');
   await page.addScriptTag({path:require.resolve('axe-core')});
   const viewerAccessibility=await page.evaluate(async()=>{const result=await axe.run(document.querySelector('[data-document-viewer]'));return result.violations.filter(item=>['critical','serious'].includes(item.impact)).map(item=>({id:item.id,impact:item.impact,nodes:item.nodes.map(node=>node.target)}));});
   assert.deepEqual(viewerAccessibility,[],'document viewer serious/critical accessibility violations');
   await page.screenshot({path:resolve(out,`document-viewer-${engine}-${width}.png`),fullPage:true});
   await reader.getByRole('button',{name:'Close document viewer',exact:true}).click();
   await reader.waitFor({state:'hidden'});await page.getByRole('button',{name:'Close asset details'}).click();
   checks.push({engine,width,format:'pdf',viewer:'two actual pages; source text; sidebar; page jump; keyboard; zoom; rotation; current-page find; responsive close',execution:'real source bytes/UI/API/renderer/DB; synthetic identity/storage'});
   await search.fill(videoName);
   const videoRow=page.getByRole('button',{name:new RegExp('Video '+videoName)}).first();await videoRow.waitFor({timeout:15000});
   const listPoster=page.locator('[data-thumbnail-preview="video-poster"] img').first();await listPoster.waitFor({state:'visible',timeout:15000});
   await page.waitForFunction(()=>{const image=document.querySelector('[data-thumbnail-preview="video-poster"] img');return image instanceof HTMLImageElement&&image.complete&&image.naturalWidth>0;},null,{timeout:15000});
   await videoRow.click();await page.locator('[data-library-thumbnail="video"][data-thumbnail-preview="video-poster"]').last().waitFor({timeout:15000});
   await page.getByRole('button',{name:'Close asset details'}).click();
   // A real four-second PCM file with changing amplitude must produce changing
   // waveform peaks. This is actual source decoding, not a drawn fixture cover.
   const audioRate=8000,audioSeconds=4,audioSamples=audioRate*audioSeconds,audioBytes=Buffer.alloc(44+audioSamples*2);
   audioBytes.write('RIFF',0);audioBytes.writeUInt32LE(audioBytes.length-8,4);audioBytes.write('WAVEfmt ',8);audioBytes.writeUInt32LE(16,16);audioBytes.writeUInt16LE(1,20);audioBytes.writeUInt16LE(1,22);audioBytes.writeUInt32LE(audioRate,24);audioBytes.writeUInt32LE(audioRate*2,28);audioBytes.writeUInt16LE(2,32);audioBytes.writeUInt16LE(16,34);audioBytes.write('data',36);audioBytes.writeUInt32LE(audioSamples*2,40);
   for(let index=0;index<audioSamples;index++){const amplitude=index<audioRate?0:index<audioRate*2?0.2:index<audioRate*3?0.8:0.4;audioBytes.writeInt16LE(Math.round(Math.sin(index/audioRate*440*Math.PI*2)*amplitude*32767),44+index*2);}
   const audioTicketResponse=await context.request.post(path+'/files',{headers,data:{filename:'inline-preview.wav',mime:'audio/wav',bytes:audioBytes.length}});assert.equal(audioTicketResponse.status(),201,await audioTicketResponse.text());
   const audioTicket=(await audioTicketResponse.json()).upload;
   assert.equal((await context.request.put(base+'/dev/upload/'+new URL(audioTicket.url).searchParams.get('token'),{data:audioBytes,headers:{'Content-Type':'audio/wav'}})).status(),200);
   assert.ok((await context.request.post(path+'/files/'+audioTicket.assetId+'/commit',{headers,data:{}})).ok());
   await context.request.post(base+'/dev/library/tick?workspace='+ws+'&assetId='+audioTicket.assetId);
   await page.reload();await search.fill('inline-preview.wav');
   await view.getByRole('radio',{name:'Gallery'}).click();
   const inlineAudio=page.locator('[data-library-media-player="audio"]').first();
   await inlineAudio.getByRole('button',{name:'Play audio preview',exact:true}).click();
   const audioWave=inlineAudio.locator('[data-waveform-source="original-audio"]');await audioWave.waitFor({state:'visible',timeout:20000});
   assert.ok(await audioWave.locator('rect').evaluateAll(rects=>new Set(rects.map(rect=>rect.getAttribute('height'))).size>3),'waveform must reflect changing amplitude in the original audio');
   assert.ok(await inlineAudio.locator('audio').evaluate(audio=>audio.currentTime>0),'actual WAV playback advances');
   const inlineAudioPause=inlineAudio.getByRole('button',{name:'Pause audio preview',exact:true});if(await inlineAudioPause.isVisible())await inlineAudioPause.click();
   await inlineAudio.getByRole('combobox',{name:'Audio playback speed',exact:true}).selectOption('2');
   assert.equal(await inlineAudio.locator('audio').evaluate(audio=>audio.playbackRate),2);
   const audioVolume=inlineAudio.getByRole('slider',{name:'Audio preview volume',exact:true});await audioVolume.focus();await audioVolume.press('Home');await audioVolume.press('ArrowRight');
   assert.ok(await inlineAudio.locator('audio').evaluate(audio=>audio.volume>0&&audio.volume<=0.1),'audio volume control updates the actual media element');
   const audioTimeline=inlineAudio.getByRole('slider',{name:'Audio preview timeline',exact:true}),seekAudio=inlineAudio.locator('audio'),seekAudioHandle=await seekAudio.elementHandle();
   await page.waitForFunction(audio=>audio.paused,seekAudioHandle,{timeout:5000});
   await audioTimeline.focus();await audioTimeline.press('Home');
   await page.waitForFunction(audio=>!audio.seeking&&audio.currentTime<0.075,seekAudioHandle,{timeout:5000});
   await seekAudio.evaluate(audio=>{delete audio.dataset.acceptanceSeeked;audio.addEventListener('seeked',()=>{audio.dataset.acceptanceSeeked='yes';},{once:true});});
   await audioTimeline.press('ArrowRight');
   await page.waitForFunction(audio=>audio.dataset.acceptanceSeeked==='yes'&&!audio.seeking,seekAudioHandle,{timeout:5000});
   assert.ok(await seekAudio.evaluate(audio=>audio.currentTime>0&&audio.currentTime<0.25),'audio timeline keyboard seeks actual source after the native seeked event');
   assert.equal(await inlineAudio.locator('button button').count(),0,'media controls cannot be nested inside details buttons');
   assert.ok(await inlineAudio.evaluate(element=>element.getBoundingClientRect().right<=innerWidth+1),'inline audio controls fit viewport');
   await page.addScriptTag({path:require.resolve('axe-core')});
   const mediaAccessibility=await page.evaluate(async()=>{const result=await axe.run(document.querySelector('[data-library-media-player="audio"]'));return result.violations.filter(item=>['critical','serious'].includes(item.impact)).map(item=>({id:item.id,impact:item.impact,nodes:item.nodes.map(node=>node.target)}));});
   assert.deepEqual(mediaAccessibility,[],'inline audio serious/critical accessibility violations');
   await page.screenshot({path:resolve(out,`inline-audio-${engine}-${width}.png`),fullPage:true});
   checks.push({engine,width,format:'wav',inline:'actual varying-amplitude waveform; play/pause; keyboard seek; speed; volume; responsive',execution:'real original WAV/UI/decode; synthetic identity/storage'});
   if(engine==='chromium'){
    for(const [ext,codecMime] of Object.entries({mp3:'audio/mpeg',m4a:'audio/mp4; codecs="mp4a.40.2"',ogg:'audio/ogg; codecs="vorbis"',oga:'audio/ogg; codecs="vorbis"',flac:'audio/flac',aac:'audio/aac',webm:'audio/webm; codecs="opus"'})){
     await search.fill('sample.'+ext);
     const formatPlayer=page.locator(`[data-library-media-player="audio"][data-library-thumbnail="${ext}"]`).first();await formatPlayer.waitFor({state:'visible',timeout:15000});
     const formatAudio=formatPlayer.locator('audio'),nativeHint=await formatAudio.evaluate((audio,mime)=>audio.canPlayType(mime),codecMime);
     await formatPlayer.getByRole('button',{name:'Play audio preview',exact:true}).click();
     const handle=await formatAudio.elementHandle();
     await page.waitForFunction(audio=>audio.currentTime>0||Boolean(audio.error),handle,{timeout:15000});
     const actual=await formatAudio.evaluate(audio=>({time:audio.currentTime,readyState:audio.readyState,error:audio.error?{code:audio.error.code,message:audio.error.message}:null}));
     if(actual.time>0&&!actual.error){
      const pause=formatPlayer.getByRole('button',{name:'Pause audio preview',exact:true});if(await pause.isVisible())await pause.click();
      checks.push({engine,width,format:ext,nativeHint,playback:'actual original encoded audio decoded and played',execution:'real ffmpeg-generated and independently decoded source/UI; synthetic identity/storage'});
     }else{
      assert.ok(actual.error&&[3,4].includes(actual.error.code),ext+' must either decode/play or report a codec error; network/source failures are not accepted: '+JSON.stringify(actual));
      await formatPlayer.getByRole('status').filter({hasText:'Playback unavailable in this browser. Open the original to use another player.'}).waitFor({timeout:15000});
      checks.push({engine,width,format:ext,nativeHint,playback:'unsupported browser decoder; explicit original-file fallback verified',mediaError:actual.error.code,execution:'real source bytes/UI; synthetic identity/storage; no playback claim'});
     }
    }
    await search.fill('');
    const movName=`rafii-release-${engine}-${width}.mov`,movBytes=readFileSync(resolve(__dirname,'../../.codex/library-samples/archive-acceptance.mov'));
    await picker.setInputFiles({name:movName,mimeType:'video/quicktime',buffer:movBytes});
    const movButton=page.getByRole('button',{name:new RegExp('Video '+movName)}).first();await movButton.waitFor({timeout:30000});
    const movCard=page.getByRole('listitem').filter({has:movButton}),movPlayer=movCard.locator('[data-library-media-player="video"]');
    await movPlayer.scrollIntoViewIfNeeded();
    const movPoster=movPlayer.locator('img');await movPoster.waitFor({state:'visible',timeout:15000});await movPoster.evaluate(image=>image.decode());
    assert.ok(await movPoster.evaluate(image=>image.naturalWidth>0),'MOV must have a captured actual source frame');
    const movVideo=movPlayer.locator('video'),movHint=await movVideo.evaluate(video=>video.canPlayType('video/quicktime'));
    await movPlayer.getByRole('button',{name:'Play video preview',exact:true}).click();
    await page.waitForFunction(video=>video.currentTime>0||Boolean(video.error),await movVideo.elementHandle(),{timeout:15000});
    const movActual=await movVideo.evaluate(video=>({time:video.currentTime,muted:video.muted,error:video.error?{code:video.error.code,message:video.error.message}:null}));
    if(movActual.time>0&&!movActual.error){
     assert.equal(movActual.muted,true,'MOV explicit preview remains silent by default');
     await movPlayer.getByRole('button',{name:'Pause video preview',exact:true}).click();
     checks.push({engine,width,format:'mov',nativeHint:movHint,playback:'actual QuickTime/H264 upload, captured frame and silent playback',execution:'real remuxed source/UI/API; synthetic identity/storage'});
    }else{
     assert.ok(movActual.error&&[3,4].includes(movActual.error.code),'MOV failure must be an explicit unsupported decoder, not a storage/network error');
     await movPlayer.getByRole('status').filter({hasText:'Playback unavailable in this browser. Open the original to use another player.'}).waitFor({timeout:15000});
     checks.push({engine,width,format:'mov',nativeHint:movHint,playback:'unsupported browser decoder; actual captured frame and explicit fallback verified',mediaError:movActual.error.code,execution:'real source bytes/UI; synthetic identity/storage; no MOV playback claim'});
    }
    await page.screenshot({path:resolve(out,`inline-formats-${engine}-${width}.png`),fullPage:true});
   }
   await view.getByRole('radio',{name:'List'}).click();
   await search.fill('sample.wav');
   await page.locator('[data-library-media-player="audio"]').first().waitFor({state:'visible'});
   await page.getByRole('button',{name:/Audio sample/}).first().click();
   await page.getByRole('button',{name:'Play audio in Now Playing'}).click();
   await page.getByLabel('Now Playing',{exact:true}).waitFor();
   await page.getByText('Add or replace transcript',{exact:true}).click();await page.getByLabel('Transcript',{exact:true}).fill('Searchable audio bowing lesson.');await page.getByRole('button',{name:'Save transcript',exact:true}).click();
   await page.getByRole('button',{name:'Close asset details'}).click();
   await page.getByRole('button',{name:'Close player',exact:true}).click();
   await search.fill('');
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
