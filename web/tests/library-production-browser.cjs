/** Real Next/API/disposable PostgreSQL + real sample bytes. Identity/storage are synthetic. */
const assert=require('node:assert/strict');
const {createHash,randomUUID}=require('node:crypto');
const {readFileSync,mkdirSync,writeFileSync}=require('node:fs');
const {resolve}=require('node:path');
const {chromium,webkit}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base='http://127.0.0.1:4439';
const out=process.env.RAFII_LIBRARY_EVIDENCE||resolve(__dirname,'../../docs/consumer-ready/evidence/library');
mkdirSync(out,{recursive:true});
const checks=[];
// Observation only: no extra requests, waits, retries, or error filtering.
const DIAGNOSTIC_LIMITS=Object.freeze({contexts:4,events:256,pageErrors:16,precedingEvents:16,trackedPreviews:128,activePreviews:64,fixtures:128,text:4096,url:512});
const browserDiagnostics=[];let diagnosticContextsDropped=0;
function diagnosticUrl(value){
 if(typeof value!=='string')return null;
 if(value==='about:blank')return value;
 try{
  const url=new URL(value,base);
  if(!['http:','https:'].includes(url.protocol))return '[non-http-url]';
  // Drop userinfo, every query value, fragments, and external object paths.
  const path=url.origin===base?url.pathname.replace(/\/dev\/upload\/[^/]+/g,'/dev/upload/[redacted]'):'/[path-redacted]';
  return (url.origin+path).slice(0,DIAGNOSTIC_LIMITS.url);
 }catch{return '[invalid-url]'}
}
function diagnosticText(value,limit=DIAGNOSTIC_LIMITS.text){
 return String(value??'').slice(0,limit)
  .replace(/https?:\/\/[^\s"'<>]+/gi,diagnosticUrl)
  .replace(/\b(?:data|blob):[^\s"'<>]+/gi,'[inline-url-redacted]')
  .replace(/\?[^\s"'<>)]*/g,'?[redacted]')
  .replace(/\bBearer\s+[^\s"'<>;]+/gi,'Bearer [redacted]')
  .replace(/\b(authorization|cookie|set-cookie|x-signature|(?:access|refresh)[_-]?token|token|password|secret|api[_-]?key)\b["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;}\]]+)/gi,'$1=[redacted]')
  .replace(/\/dev\/upload\/[^/\s"'<>?]+/g,'/dev/upload/[redacted]')
  .slice(0,limit);
}
function diagnosticOrigin(value){
 try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.origin.slice(0,DIAGNOSTIC_LIMITS.url):null}catch{return null}
}
// Observe the current locator on every poll: signed-source renewal may replace
// an image while decode() is pending, even when its replacement loads correctly.
async function waitForLoadedRaster(locator,minimumDimension,timeout){
 const deadline=Date.now()+timeout;
 await locator.waitFor({state:'visible',timeout});
 let observed;
 while(Date.now()<deadline){
  observed=await locator.evaluate(image=>({connected:image.isConnected,complete:image.complete,width:image.naturalWidth,height:image.naturalHeight}),undefined,{timeout:Math.max(1,deadline-Date.now())});
  if(observed.connected&&observed.complete&&observed.width>minimumDimension&&observed.height>minimumDimension)return;
  await locator.page().waitForTimeout(Math.min(50,Math.max(1,deadline-Date.now())));
 }
 assert.fail(`Current source image did not load within ${timeout}ms: ${JSON.stringify(observed)}`);
}
(async()=>{
 let generatedPoster=null;
 for(const [engine,browserType] of Object.entries({chromium,webkit})){
  const browser=await browserType.launch({headless:true});
  try{for(const width of [1440,390]){
   const principal=randomUUID(),context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   const headers={Authorization:'Bearer dev:'+principal,'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',Origin:base};
   await context.addCookies([{name:'postriff_dev',value:'1',url:base},{name:'postriff_dev_principal',value:principal,url:base}]);
   await context.addInitScript(id=>localStorage.setItem('postriff-dev-principal',id),principal);
   await context.addInitScript(()=>{
    const nativeInterval=window.setInterval.bind(window),nativeClear=window.clearInterval.bind(window),refreshIntervals=new Map();
    window.setInterval=(callback,delay,...args)=>{
     const id=nativeInterval(callback,delay,...args);
     if(delay===240000&&typeof callback==='function')refreshIntervals.set(id,()=>callback(...args));
     return id;
    };
    window.clearInterval=id=>{refreshIntervals.delete(id);nativeClear(id)};
    // Invoke only the application's existing four-minute callbacks, once per
    // acceptance step. Native clock/polling schedules remain unchanged.
    window.__rafiiRefreshAcceptanceEnabled=false;
    window.__rafiiRefreshAcceptance=()=>{
     if(!window.__rafiiRefreshAcceptanceEnabled||!refreshIntervals.size)throw new Error('No enabled source refresh interval');
     [...refreshIntervals.values()].forEach(callback=>callback());
    };
   });
   const boot=await context.request.post(base+'/api/auth/verify',{headers,data:{plan:'studio'}});assert.equal(boot.status(),201,await boot.text());
   const ws=(await boot.json()).workspaceId,path=base+'/api/workspaces/'+ws+'/library';
   const storageTrace=[],thumbnailFormats=new Set(['md']),markdownBytes=Buffer.from('Browser Brahms acceptance '+engine+' '+width+'\nFinger exercises and rehearsal notes.');
   await context.route('https://devharness.storage.supabase.co/**',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    const cors={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'POST,HEAD,PATCH,OPTIONS',
     'Access-Control-Allow-Headers':'Tus-Resumable,Upload-Length,Upload-Metadata,Upload-Offset,Content-Type,x-signature',
     'Access-Control-Expose-Headers':'Location,Upload-Offset,Upload-Length,Tus-Resumable,Tus-Version,Tus-Extension'};
    if(!/^\/storage\/v1\/upload\/resumable(?:\/[0-9a-f]{32})?$/.test(url.pathname)||url.search)return route.fulfill({status:404,headers:cors});
    if(method==='OPTIONS')return route.fulfill({status:204,headers:cors});
    const sourceHeaders=request.headers(),forward={};
    for(const name of ['tus-resumable','upload-length','upload-metadata','upload-offset','content-type','x-signature']){
     if(sourceHeaders[name]!==undefined)forward[name]=sourceHeaders[name];
    }
    const raw=request.postDataBuffer();
    const response=await context.request.fetch(base+url.pathname.replace('/storage/v1/upload/resumable','/dev/resumable'),{
     method,headers:forward,...(method==='HEAD'?{}:{data:raw||undefined}),maxRedirects:0,failOnStatusCode:false});
    const supplied=response.headers(),headers={...cors};
    for(const name of ['location','upload-offset','upload-length','tus-resumable','tus-version','tus-extension','cache-control']){
     if(supplied[name]!==undefined)headers[name]=supplied[name];
    }
    storageTrace.push({protocol:'tus',method,status:response.status(),bytes:raw?.length||0,
     requestedOffset:sourceHeaders['upload-offset']||null,acceptedOffset:supplied['upload-offset']||null,
     uploadLength:supplied['upload-length']||sourceHeaders['upload-length']||null});
    return route.fulfill({status:response.status(),headers,body:method==='HEAD'?Buffer.alloc(0):await response.body()});
   });
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
    const request=route.request(),u=new URL(request.url());
    const deliveryHeaders={'Access-Control-Allow-Origin':'*','Access-Control-Expose-Headers':'Content-Range,Accept-Ranges','Accept-Ranges':'bytes'};
    if(request.method()==='OPTIONS')return route.fulfill({status:204,headers:{...deliveryHeaders,'Access-Control-Allow-Methods':'GET,HEAD,OPTIONS','Access-Control-Allow-Headers':'Range'}});
    const r=await context.request.get(base+'/dev/storage'+u.pathname),body=await r.body(),mime=r.headers()['content-type']||'application/octet-stream';
    const range=request.headers().range;
    let status=r.status(),delivered=body,headers={...deliveryHeaders,'Content-Type':mime,'Content-Length':String(body.length)};
    // Real Supabase signed delivery supports single byte ranges. Preserve this
    // behavior at the synthetic storage boundary so native media can seek.
    if(status===200&&range){
     const match=/^bytes=(\d*)-(\d*)$/.exec(range);
     let start=0,end=body.length-1;
     if(match&&(match[1]||match[2])){
      if(match[1]){start=Number(match[1]);if(match[2])end=Math.min(end,Number(match[2]));}
      else start=Math.max(0,body.length-Number(match[2]));
     }else start=NaN;
     if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>=body.length||start<0||end<start){
      status=416;delivered=Buffer.alloc(0);headers={...headers,'Content-Range':`bytes */${body.length}`,'Content-Length':'0'};
     }else{
      status=206;delivered=body.subarray(start,end+1);headers={...headers,'Content-Range':`bytes ${start}-${end}/${body.length}`,'Content-Length':String(delivered.length)};
     }
    }
    storageTrace.push({method:request.method(),status,mime,range:range||null,deliveredBytes:delivered.length,object:u.pathname.split('/').slice(-2).join('/')});
    return route.fulfill({status,body:request.method()==='HEAD'?Buffer.alloc(0):delivered,headers});
   });
   const page=await context.newPage(),errors=[],uploadTrace=[],rscFailures=[],activeRsc=new Set();
   let navigationPhase='initial library load',lastRscActivity=Date.now();
   const diagnosticState={engine,width,events:[],pageErrors:[],fixtures:[],activePreviews:[],dropped:{events:0,pageErrors:0,trackedPreviews:0,activePreviews:0,fixtures:0}};
   if(browserDiagnostics.length===DIAGNOSTIC_LIMITS.contexts){browserDiagnostics.shift();diagnosticContextsDropped++}
   browserDiagnostics.push(diagnosticState);
   const previewRequests=new Map(),activePreviews=new Map(),fixtureAssets=new Map();
   let diagnosticSequence=0,previewSequence=0,navigationSequence=0,diagnosticPhase='initial library load';
   const pushDiagnostic=(list,value,key,limit)=>{if(list.length===limit){list.shift();diagnosticState.dropped[key]++}list.push(value)};
   const recordDiagnostic=(event,details={})=>{
    const documentUrl=diagnosticUrl(page.url());
    const entry={sequence:++diagnosticSequence,atMs:Date.now(),event,phase:diagnosticText(diagnosticPhase,160),harnessPhase:diagnosticText(navigationPhase,160),navigationId:navigationSequence,documentUrl,documentOrigin:diagnosticOrigin(page.url()),...details};
    diagnosticState.activePreviews=[...activePreviews.values()];
    pushDiagnostic(diagnosticState.events,entry,'events',DIAGNOSTIC_LIMITS.events);
    return entry;
   };
   const markDiagnosticNavigation=(action,target,label=navigationPhase)=>{
    diagnosticPhase=label;navigationSequence++;
    recordDiagnostic('navigation:start',{action,target:diagnosticUrl(target),activePreviewIds:[...activePreviews.keys()]});
   };
   const rememberFixtureAssets=assets=>{
    for(const asset of assets||[]){
     const assetId=String(asset?.id||'');
     if(!/^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(assetId))continue;
     const previous=fixtureAssets.get(assetId);
     if(!previous&&fixtureAssets.size===DIAGNOSTIC_LIMITS.fixtures){fixtureAssets.delete(fixtureAssets.keys().next().value);diagnosticState.dropped.fixtures++}
     fixtureAssets.set(assetId,{assetId,filename:diagnosticText(asset.originalFilename??previous?.filename,160),extension:diagnosticText(asset.extension??previous?.extension,24),processing:diagnosticText(asset.processing??asset.indexingStatus??previous?.processing,32)});
    }
    diagnosticState.fixtures=[...fixtureAssets.values()];
   };
   const observePreviewRequest=request=>{
    let info=previewRequests.get(request);if(info)return info;
    const url=new URL(request.url()),match=url.origin===base&&/^\/api\/workspaces\/[^/]+\/library\/files\/([a-f0-9]{32})\/preview\/?$/i.exec(url.pathname);
    const redirectedFrom=request.redirectedFrom(),previous=redirectedFrom&&previewRequests.get(redirectedFrom);
    if(!match&&!previous)return null;
    info={requestId:++previewSequence,assetId:match?match[1]:previous.assetId,url:diagnosticUrl(request.url()),method:diagnosticText(request.method(),16),startedAtMs:Date.now(),startedPhase:diagnosticText(diagnosticPhase,160),startedNavigationId:navigationSequence,redirectedFromId:previous?.requestId||null};
    if(previewRequests.size===DIAGNOSTIC_LIMITS.trackedPreviews){
     const oldest=previewRequests.keys().next().value,removed=previewRequests.get(oldest);
     previewRequests.delete(oldest);diagnosticState.dropped.trackedPreviews++;
     if(activePreviews.delete(removed.requestId))diagnosticState.dropped.activePreviews++;
    }
    previewRequests.set(request,info);
    if(activePreviews.size===DIAGNOSTIC_LIMITS.activePreviews){activePreviews.delete(activePreviews.keys().next().value);diagnosticState.dropped.activePreviews++}
    activePreviews.set(info.requestId,info);
    return info;
   };
   const finishPreviewRequest=(request,event)=>{
    const info=previewRequests.get(request);if(!info)return;
    activePreviews.delete(info.requestId);
    recordDiagnostic(event,{requestId:info.requestId,assetId:info.assetId,url:info.url,failure:diagnosticText(request.failure()?.errorText,256),redirectedTo:diagnosticUrl(request.redirectedTo()?.url()),activePreviewIds:[...activePreviews.keys()]});
   };
   page.on('framenavigated',frame=>{if(frame===page.mainFrame())recordDiagnostic('navigation:commit',{target:diagnosticUrl(frame.url()),activePreviewIds:[...activePreviews.keys()]})});
   page.on('close',()=>recordDiagnostic('page:close',{activePreviewIds:[...activePreviews.keys()]}));
   const isRscRequest=request=>new URL(request.url()).searchParams.has('_rsc');
   const finishRsc=request=>{if(activeRsc.delete(request))lastRscActivity=Date.now()};
   // Let real RSC prefetches finish before the harness destroys their document.
   // Track current requests explicitly; an earlier load-state event is not readiness.
   // Ignore periodic Library polling here, while keeping every runtime error below.
   const settleBeforeNavigation=async phase=>{
    navigationPhase='settling before '+phase;
    const deadline=Date.now()+15000;
    while(activeRsc.size||Date.now()-lastRscActivity<500){
     assert.ok(Date.now()<deadline,`RSC did not settle before ${phase}: ${JSON.stringify([...activeRsc].map(request=>request.url()))}`);
     await new Promise(resolve=>setTimeout(resolve,100));
    }
    navigationPhase=phase;
   };
   const relevantUploadUrl=value=>{try{const u=new URL(value);if(u.searchParams.has('token'))u.searchParams.set('token','[redacted]');return u.origin+u.pathname+(u.search?'?'+u.searchParams.toString():'')}catch{return value}};
   const isUploadRequest=request=>/\/library\/files(?:\/|\?|$)|\/media\/videos(?:\/|\?|$)|devharness\.(?:storage\.)?supabase\.co|\/dev\/(?:upload|resumable)(?:\/|$)/.test(request.url());
   page.on('pageerror',error=>{
    errors.push(error.message);
    const precedingEvents=diagnosticState.events.slice(-DIAGNOSTIC_LIMITS.precedingEvents);
    const entry=recordDiagnostic('pageerror',{message:diagnosticText(error.message),stack:diagnosticText(error.stack),activePreviewIds:[...activePreviews.keys()]});
    pushDiagnostic(diagnosticState.pageErrors,{...entry,activePreviews:[...activePreviews.values()],precedingEvents},'pageErrors',DIAGNOSTIC_LIMITS.pageErrors);
   });
   page.on('request',request=>{
    const preview=observePreviewRequest(request);if(preview)recordDiagnostic('preview:start',preview);
    if(isUploadRequest(request))uploadTrace.push({event:'request',method:request.method(),url:relevantUploadUrl(request.url())});
    if(isRscRequest(request)){activeRsc.add(request);lastRscActivity=Date.now()}
   });
   page.on('requestfinished',request=>{finishRsc(request);finishPreviewRequest(request,'preview:finished')});
   page.on('response',response=>{
    const preview=previewRequests.get(response.request());if(preview)recordDiagnostic('preview:response',{requestId:preview.requestId,assetId:preview.assetId,url:diagnosticUrl(response.url()),status:response.status()});
    if(isUploadRequest(response.request()))uploadTrace.push({event:'response',method:response.request().method(),url:relevantUploadUrl(response.url()),status:response.status()})
   });
   page.on('requestfailed',request=>{
    finishPreviewRequest(request,'preview:failed');
    if(isUploadRequest(request))uploadTrace.push({event:'requestfailed',method:request.method(),url:relevantUploadUrl(request.url()),failure:request.failure()?.errorText});
    finishRsc(request);
    if(isRscRequest(request))rscFailures.push({url:relevantUploadUrl(request.url()),method:request.method(),prefetch:request.headers()['next-router-prefetch']||null,failure:request.failure()?.errorText,phase:navigationPhase});
   });
   markDiagnosticNavigation('goto',base+'/app/library');
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
    rememberFixtureAssets(listing.assets);
    if(doc&&doc.indexingStatus!=='pending')break;
    await new Promise(resolve=>setTimeout(resolve,250));
   }
   const visibleUploadState=await page.locator('body').innerText().catch(()=> '');
   assert.ok(doc,`uploaded Markdown asset missing from Library listing: ${JSON.stringify(listing)}\nUpload requests: ${JSON.stringify(uploadTrace)}\nStorage proxy: ${JSON.stringify(storageTrace)}\nVisible page: ${visibleUploadState.slice(0,2500)}`);
   assert.equal(doc.indexingStatus,'ready',`Markdown indexing did not become ready: ${JSON.stringify(doc)}\nUpload requests: ${JSON.stringify(uploadTrace)}\nStorage proxy: ${JSON.stringify(storageTrace)}\nVisible page: ${visibleUploadState.slice(0,2500)}`);
   await page.locator('[data-library-thumbnail="md"]').first().waitFor({timeout:15000});
   const videoName=`rafii-release-${engine}-${width}.mp4`,videoBytes=readFileSync(resolve(__dirname,'../public/onboarding/welcome-loop-dark.mp4')),videoTraceStart=storageTrace.length;
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
    await settleBeforeNavigation('show uploaded WebKit video');markDiagnosticNavigation('reload',page.url());await page.reload();
   }
   const videoCard=page.getByRole('button',{name:new RegExp('Video '+videoName)}).first();
   try{await videoCard.waitFor({timeout:30000});}
   catch(error){
    const response=await context.request.get(path,{headers}),listing=await response.text();
    const visibleBody=await page.locator('body').innerText().catch(()=> '');
    const diagnostics={engine,width,error:String(error),libraryStatus:response.status(),listing:listing.slice(0,3000),
     visibleBody:visibleBody.slice(0,4000),uploadTrace:uploadTrace.slice(-40),storageTrace:storageTrace.slice(-40)};
    writeFileSync(resolve(out,`video-upload-failure-${engine}-${width}.json`),JSON.stringify(diagnostics,null,2));
    await page.screenshot({path:resolve(out,`video-upload-failure-${engine}-${width}.png`),fullPage:true,timeout:5000}).catch(()=>{});
    throw new Error(`${error.message}\nVideo upload diagnostics: ${JSON.stringify(diagnostics)}`);
   }
   const videoPoster=page.locator('[data-thumbnail-preview="video-poster"] img').first();await videoPoster.waitFor({state:'visible',timeout:15000});
   await page.waitForFunction(()=>{const image=document.querySelector('[data-thumbnail-preview="video-poster"] img');return image instanceof HTMLImageElement&&image.complete&&image.naturalWidth>0;},null,{timeout:15000});
   if(engine==='chromium'){
    const videoListing=await (await context.request.get(path,{headers})).json();
    const videoAsset=videoListing.assets.find(asset=>asset.originalFilename===videoName||asset.displayTitle===videoName);
    assert.ok(videoAsset,`uploaded video missing from Library listing: ${JSON.stringify(videoListing)}`);
    const tusTrace=storageTrace.slice(videoTraceStart).filter(entry=>entry.protocol==='tus');
    assert.ok(tusTrace.some(entry=>entry.method==='POST'&&entry.status===201),'real Chromium client must create its signed TUS session');
    assert.ok(tusTrace.some(entry=>entry.method==='HEAD'&&[200,204].includes(entry.status)),'real Chromium client must reconcile its TUS offset');
    assert.ok(tusTrace.some(entry=>entry.method==='PATCH'&&entry.status===204&&Number(entry.acceptedOffset)===videoAsset.bytes),
     `real Chromium client must complete the exact committed video bytes: ${JSON.stringify(tusTrace)}`);
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
    const rangeDelivery=await previewVideo.evaluate(async(video,totalBytes)=>{
     const partial=await fetch(video.currentSrc,{headers:{Range:'bytes=4-7'}});
     const bytes=Array.from(new Uint8Array(await partial.arrayBuffer()));
     const invalid=await fetch(video.currentSrc,{headers:{Range:`bytes=${totalBytes}-`}});
     return {status:partial.status,range:partial.headers.get('Content-Range'),bytes,invalidStatus:invalid.status,invalidRange:invalid.headers.get('Content-Range')};
    },videoBytes.length);
    assert.equal(rangeDelivery.status,206,'native playback delivery supports actual partial byte reads');
    assert.equal(rangeDelivery.range,`bytes 4-7/${videoBytes.length}`);
    assert.deepEqual(rangeDelivery.bytes,Array.from(videoBytes.subarray(4,8)),'Range response must contain those original MP4 bytes');
    assert.equal(rangeDelivery.invalidStatus,416,'out-of-bounds byte range must be refused');
    assert.equal(rangeDelivery.invalidRange,`bytes */${videoBytes.length}`);
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>document.querySelector('[data-library-media-player="video"] video')?.paused===true,null,{timeout:5000});
    await page.emulateMedia({reducedMotion:'no-preference'});
    await waitForSilentVideo();
    await inlineVideo.getByRole('button',{name:'Pause video preview',exact:true}).click();
    const videoTimeline=inlineVideo.getByRole('slider',{name:'Video preview timeline',exact:true});
    const seekVideoHandle=await previewVideo.elementHandle();
    await page.waitForFunction(video=>video.paused&&video.seekable.length>0,seekVideoHandle,{timeout:5000});
    await videoTimeline.focus();await videoTimeline.press('Home');
    await page.waitForFunction(video=>!video.seeking&&video.currentTime<0.075,seekVideoHandle,{timeout:5000});
    await previewVideo.evaluate(video=>{delete video.dataset.acceptanceSeeked;video.addEventListener('seeked',()=>{video.dataset.acceptanceSeeked='yes';},{once:true});});
    await videoTimeline.press('ArrowRight');
    await page.waitForFunction(video=>video.dataset.acceptanceSeeked==='yes'&&!video.seeking,seekVideoHandle,{timeout:5000});
    assert.ok(await previewVideo.evaluate(video=>video.currentTime>0&&video.currentTime<0.25),'video timeline keyboard seeks actual MP4 after the native seeked event: '+JSON.stringify(await previewVideo.evaluate(video=>({time:video.currentTime,seeking:video.seeking,paused:video.paused,seekable:Array.from({length:video.seekable.length},(_,index)=>[video.seekable.start(index),video.seekable.end(index)]),buffered:Array.from({length:video.buffered.length},(_,index)=>[video.buffered.start(index),video.buffered.end(index)]),range:video.closest('[data-library-media-player]')?.querySelector('input[type="range"]')?.value}))));
    await inlineVideo.getByRole('combobox',{name:'Video playback speed',exact:true}).selectOption('1.5');
    assert.equal(await previewVideo.evaluate(video=>video.playbackRate),1.5);
    await page.emulateMedia({reducedMotion:'reduce'});
    checks.push({engine,width,format:'mp4',inline:'actual silent autoplay; reduced-motion pause; byte-range206/416; native keyboard seek; speed',execution:'real original MP4/UI; synthetic identity/storage'});
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
   // Base UI restores focus after the popup's exit transition and a cleanup microtask.
   // Observe that exact target; never move focus on behalf of the application.
   await page.waitForFunction(element=>element===document.activeElement,await returnedViewerTrigger.elementHandle(),{timeout:5000});
   assert.ok(await returnedViewerTrigger.evaluate(element=>element===document.activeElement),'Escape closes only the nested reader and restores its launcher focus');
   await page.getByLabel('Title',{exact:true}).fill('Brahms browser notes');await page.getByLabel('Tags, separated by commas').fill('music, rehearsal');
   await page.getByRole('button',{name:'Save details',exact:true}).click();
   await page.getByRole('button',{name:'Use as a source',exact:true}).click();
   const sourceReviewLink=page.getByRole('link',{name:'Review source in Ideas',exact:true});await sourceReviewLink.waitFor();
   assert.match(await sourceReviewLink.getAttribute('href'),/^\/app\/ideas\?source=[a-f0-9]{32}$/,'source review must target the real source inspector');
   markDiagnosticNavigation('link',base+'/app/ideas','open source review');
   await sourceReviewLink.click();await page.waitForURL(/\/app\/ideas\?source=/);
   await page.locator('[data-tour="ideas-facts"]').getByText('Finger exercises',{exact:false}).waitFor({timeout:15000});
   await page.getByRole('heading',{name:'How it may be used',exact:true}).waitFor();
   await page.getByText(doc.sha256,{exact:true}).waitFor();
   await page.getByText('Source fingerprint',{exact:false}).waitFor();
   checks.push({engine,width,source:'actual Library import opens its source facts and sharing review',execution:'real UI/API/DB; synthetic identity/storage; no model call'});
   await settleBeforeNavigation('return from source review');markDiagnosticNavigation('goto',base+'/app/library');await page.goto(base+'/app/library');await page.getByRole('button',{name:/Document Brahms browser notes/}).first().click();
   await page.getByRole('button',{name:'Close asset details'}).click();
   // The portal wrapper can have no bounding box while its fixed modal children
   // are still open. Observe the actual hit-blocking viewport after dismissal;
   // hidden also allows DOM removal when the exit transition completes.
   if(width===390)await page.locator('[data-slot="drawer-viewport"]').waitFor({state:'hidden',timeout:5000});
   await page.getByText('Manage collections',{exact:true}).click();await page.getByLabel('New collection name').fill('Practice');
   const collectionForm=page.locator('form').filter({has:page.getByLabel('New collection name')});await collectionForm.getByRole('button',{name:'Create',exact:true}).click();
   await page.getByRole('button',{name:/Document Brahms browser notes/}).first().click();await page.getByRole('checkbox',{name:'Add to collection Practice'}).check();await page.getByRole('button',{name:'Save details',exact:true}).click();
   await page.getByRole('button',{name:'Close asset details'}).click();
   // Search only words inside the file; server full-text results drive the UI.
   const search=page.getByRole('searchbox');await search.fill('Finger exercises');await page.getByRole('button',{name:/Document Brahms browser notes/}).first().waitFor();
   await search.fill('');
   const restoredDocument=page.getByRole('button',{name:/Document Brahms browser notes/}).first();
   const missingQuery='no-matching-asset-'+principal;
   await search.fill(missingQuery);
   await page.getByText(`No asset matches “${missingQuery}”`,{exact:true}).waitFor({timeout:15000});
   assert.ok(await search.isVisible(),'unmatched query must retain its editable search control');
   assert.ok(await page.getByRole('button',{name:/^Filters(?:,|$)/}).isVisible(),'unmatched query must retain filters');
   await page.getByRole('button',{name:'Clear search',exact:true}).last().click();
   await restoredDocument.waitFor({state:'visible',timeout:15000});assert.equal(await search.inputValue(),'');
   assert.match(doc.sha256,/^[a-f0-9]{64}$/,'use the real normalized document fingerprint');
   const hashPrefix=doc.sha256.slice(0,12);
   for(const [hashIndex,hashQuery] of [hashPrefix,hashPrefix.toUpperCase()].entries()){
    const actualHashSearch=await context.request.get(path+'?q='+hashQuery,{headers});
    assert.equal(actualHashSearch.status(),200,await actualHashSearch.text());
    assert.ok((await actualHashSearch.json()).assets.some(asset=>asset.id===doc.id),'real API must retrieve this document by case-insensitive SHA prefix');
    const browserHashResponse=hashIndex===0?page.waitForResponse(response=>response.url().startsWith(path+'?')&&new URL(response.url()).searchParams.get('q')===hashPrefix&&response.ok(),{timeout:15000}):null;
    await search.fill(hashQuery);
    if(browserHashResponse)assert.ok((await (await browserHashResponse).json()).assets.some(asset=>asset.id===doc.id),'browser query must receive the normalized document');
    await restoredDocument.waitFor({state:'visible',timeout:15000});
    assert.equal(await search.inputValue(),hashQuery);
   }
   await search.fill('');
   await page.getByRole('button',{name:/^Filters(?:,|$)/}).click();
   const kindFilterControl=page.locator('#library-kind');await kindFilterControl.waitFor({state:'visible'});
   const primedPhotos=page.waitForResponse(response=>response.url().startsWith(path+'?')&&new URL(response.url()).searchParams.get('kind')==='image'&&response.request().method()==='GET'&&response.ok(),{timeout:15000});
   await kindFilterControl.selectOption('image');
   await page.getByRole('button',{name:'Done',exact:true}).click();
   assert.equal((await (await primedPhotos).json()).assets.length,0,'prime the actual normalized Photos query before uploading');
   await page.getByText('No photos match these filters',{exact:true}).waitFor({timeout:15000});
   assert.ok(await search.isVisible(),'unmatched type must retain search');
   // The cached, empty normalized Photos result must refresh after the legacy
   // image mutation. Keep this filter active for both upload and deletion.
   const photoBytes=readFileSync(resolve(__dirname,'../public/raffi/full-512.png'));
   assert.ok(photoBytes.readUInt32BE(16)>=320&&photoBytes.readUInt32BE(20)>=320,'real PNG fixture must meet the image decoder dimensions');
   const photoUpload=page.waitForResponse(response=>response.url()===base+'/api/workspaces/'+ws+'/actions'&&response.request().method()==='POST'&&response.request().postDataJSON().action==='p2_media_upload',{timeout:30000});
   await picker.setInputFiles({name:`photo-cache-${engine}-${width}.png`,mimeType:'image/png',buffer:photoBytes});
   const photoUploadResponse=await photoUpload;
   assert.equal(photoUploadResponse.status(),200,await photoUploadResponse.text());
   const photoSnapshot=await photoUploadResponse.json();
   const uploadedPhoto=photoSnapshot.state.phase2.assets.find(asset=>asset.sourceHash===createHash('sha256').update(photoBytes).digest('hex')&&!asset.deleted);
   assert.ok(uploadedPhoto,'actual image upload must return the original source fingerprint');
   const photoCard=page.getByRole('button',{name:/^Photo /}).first();
   await photoCard.waitFor({state:'visible',timeout:15000});
   await waitForLoadedRaster(photoCard.locator('img'),319,15000);
   assert.equal(await page.getByRole('button',{name:/^Photo /}).count(),1,'new photo appears under the existing Photos filter without reload');
   await photoCard.click();
   await page.getByRole('button',{name:'Delete…',exact:true}).click();
   const photoDeletion=page.waitForResponse(response=>response.url()===base+'/api/workspaces/'+ws+'/actions'&&response.request().method()==='POST'&&response.request().postDataJSON().action==='p2_media_delete'&&response.request().postDataJSON().payload.assetId===uploadedPhoto.id,{timeout:30000});
   await page.getByRole('alertdialog').getByRole('button',{name:'Delete',exact:true}).click();
   const photoDeleteResponse=await photoDeletion;
   assert.equal(photoDeleteResponse.status(),200,await photoDeleteResponse.text());
   await photoCard.waitFor({state:'detached',timeout:15000});
   await page.getByText('No photos match these filters',{exact:true}).waitFor({timeout:15000});
   const photosAfterDelete=await context.request.get(path+'?kind=image',{headers});
   assert.equal(photosAfterDelete.status(),200,await photosAfterDelete.text());
   assert.ok(!(await photosAfterDelete.json()).assets.some(asset=>asset.id===uploadedPhoto.id),'deleted photo is absent from the normalized Photos API');
   checks.push({engine,width,photoCache:'primed normalized Photos query; actual512px PNG UI upload appears; same asset UI deletion disappears; no reload or filter change',execution:'real source/UI/API/DB/decoder; synthetic identity/storage'});
   await page.getByRole('button',{name:'Show all',exact:true}).click();
   await restoredDocument.waitFor({state:'visible',timeout:15000});
   const emptyCollectionName='Empty acceptance '+width;
   if(!await page.getByLabel('New collection name').isVisible())await page.getByText('Manage collections',{exact:true}).click();
   await page.getByLabel('New collection name').fill(emptyCollectionName);
   await collectionForm.getByRole('button',{name:'Create',exact:true}).click();
   await page.getByRole('button',{name:'Remove collection '+emptyCollectionName,exact:true}).waitFor();
   await page.getByRole('button',{name:/^Filters(?:,|$)/}).click();
   const collectionFilterControl=page.locator('#library-collection');await collectionFilterControl.waitFor({state:'visible'});
   await collectionFilterControl.selectOption({label:emptyCollectionName});
   await page.getByRole('button',{name:'Done',exact:true}).click();
   await page.getByText('No assets match these filters',{exact:true}).waitFor({timeout:15000});
   assert.ok(await search.isVisible(),'empty collection must retain search');
   await page.getByRole('button',{name:'Show all',exact:true}).click();
   await restoredDocument.waitFor({state:'visible',timeout:15000});
   checks.push({engine,width,search:'unmatched query/type/empty collection remain recoverable; actual normalized SHA prefix lower/uppercase',execution:'real UI/API/DB; synthetic identity/storage'});
   for(const ext of ['pdf','docx','xlsx','pptx','txt','markdown','html','htm','json','csv','bin','wav','mp3','m4a','ogg','oga','flac','aac','webm']){
    const bytes=readFileSync(resolve(__dirname,'../../.codex/library-samples/archive-acceptance.'+ext));
    const mime={pdf:'application/pdf',docx:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',pptx:'application/vnd.openxmlformats-officedocument.presentationml.presentation',wav:'audio/wav',mp3:'audio/mpeg',m4a:'audio/mp4',ogg:'audio/ogg',oga:'audio/ogg',flac:'audio/flac',aac:'audio/aac',webm:'audio/webm',txt:'text/plain',markdown:'text/markdown',html:'text/html',htm:'text/html',json:'application/json',csv:'text/csv',bin:'application/octet-stream'}[ext];
    const ticketResponse=await context.request.post(path+'/files',{headers,data:{filename:'sample.'+ext,mime,bytes:bytes.length}});assert.equal(ticketResponse.status(),201,await ticketResponse.text());
    const ticket=(await ticketResponse.json()).upload;
    assert.equal((await context.request.put(base+'/dev/upload/'+new URL(ticket.url).searchParams.get('token'),{data:bytes,headers:{'Content-Type':mime}})).status(),200);
    const committed=await context.request.post(path+'/files/'+ticket.assetId+'/commit',{headers,data:{}});assert.ok(committed.ok(),await committed.text());
    await context.request.post(base+'/dev/library/tick?workspace='+ws+'&assetId='+ticket.assetId);
    const d=await (await context.request.get(path+'/files/'+ticket.assetId,{headers})).json();
    rememberFixtureAssets([d.asset]);
    assert.ok(['ready','unsupported','duplicate'].includes(d.asset.processing),JSON.stringify(d));
    if(d.asset.processing!=='duplicate')thumbnailFormats.add(ext);
    if(d.asset.processing==='ready')assert.match(d.extractedText,/Rafii archive acceptance/);
    checks.push({engine,width,format:ext,status:d.asset.processing,execution:'real file/API/DB; synthetic identity/storage'});
   }
   await settleBeforeNavigation('show uploaded sample formats');markDiagnosticNavigation('reload',page.url());await page.reload();
   for(const ext of thumbnailFormats){
    await page.locator(`[data-library-thumbnail="${ext}"]`).first().waitFor({timeout:15000});
   }
   for(const ext of ['docx','xlsx','pptx','pdf','md']){
    await search.fill(ext==='md'?'Brahms browser notes':'sample.'+ext);
    const rasterSelector=`[data-library-thumbnail="${ext}"][data-thumbnail-preview="first-page-raster"] img`;
    const rasterAlt='First page of '+(ext==='md'?'rehearsal-'+width+'.md':'sample.'+ext);
    const raster=page.getByRole('img',{name:rasterAlt,exact:true}).first();
    await raster.waitFor({state:'visible',timeout:90000});
    // Filter transitions and private URL renewal can replace src during decode().
    // Observe the current original's successfully loaded raster instead.
    await page.waitForFunction(({selector,alt})=>[...document.querySelectorAll(selector)].some(image=>image.alt===alt&&image.isConnected&&image.complete&&image.naturalWidth>500&&image.naturalHeight>500),{selector:rasterSelector,alt:rasterAlt},{timeout:90000});
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
   await settleBeforeNavigation('show uploaded multipage PDF');markDiagnosticNavigation('reload',page.url());await page.reload();await search.fill('archive-viewer.pdf');
   await page.getByRole('button',{name:/Document archive-viewer, first-page preview/}).first().click();
   await page.getByRole('button',{name:'Open document viewer',exact:true}).click();
   const reader=page.locator('[data-document-viewer]');await reader.waitFor({state:'visible'});
   const firstPage=reader.locator('img[data-document-page="1"]');await waitForLoadedRaster(firstPage,500,90000);
   assert.ok(await firstPage.evaluate(image=>image.naturalWidth>500&&image.naturalHeight>500),'reader must load actual first-page raster');
   const firstPageSrc=await firstPage.getAttribute('src');
   assert.ok(await reader.getByRole('button',{name:'Previous page',exact:true}).isDisabled(),'first page has no previous page');
   assert.match(await reader.locator('#document-page-total').innerText(),/2/,'actual page count');
   await reader.getByRole('button',{name:'Show page sidebar',exact:true}).click();
   await reader.getByRole('button',{name:'Go to page 2',exact:true}).waitFor();
   await reader.getByRole('button',{name:'Go to page 2',exact:true}).click();
   const secondPage=reader.locator('img[data-document-page="2"]');await waitForLoadedRaster(secondPage,500,90000);
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
   const pageNumber=reader.getByLabel('Page number',{exact:true});
   await pageNumber.fill('2');assert.equal(await pageNumber.inputValue(),'2','page navigation must preserve the entered page before submission');
   await pageNumber.press('Enter');
   try{await reader.locator('img[data-document-page="2"]').waitFor({state:'visible',timeout:90000});}
   catch(error){
    const navigationState=await reader.evaluate(element=>{const input=element.querySelector('#document-page-number');const slider=element.querySelector('input[type="range"]');return{pageInput:input?.value,inputValid:input?.checkValidity(),validationMessage:input?.validationMessage,slider:slider?.value,footer:element.querySelector('footer')?.innerText,alerts:[...element.querySelectorAll('[role="alert"],[role="status"]')].map(node=>node.textContent?.slice(0,400)),images:[...element.querySelectorAll('img[data-document-page]')].map(image=>({page:image.dataset.documentPage,complete:image.complete,width:image.naturalWidth,height:image.naturalHeight})),text:element.innerText.slice(0,1200)};}).catch(diagnosticError=>({diagnosticError:String(diagnosticError)}));
    error.message+=`\nDocument page-jump state (${engine} ${width}): ${JSON.stringify(navigationState)}`;throw error;
   }
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
   let audioUrlRevision=0;
   await context.route(path+'/files/'+audioTicket.assetId+'/url',async route=>{
    const response=await route.fetch();assert.ok(response.ok(),await response.text());
    const payload=await response.json(),url=new URL(payload.url);
    // The same original private bytes/Range route receive a distinct source URL.
    url.searchParams.set('acceptance-refresh',String(++audioUrlRevision));
    await route.fulfill({response,json:{...payload,url:url.href}});
   });
   await settleBeforeNavigation('show uploaded waveform WAV');markDiagnosticNavigation('reload',page.url());await page.reload();await search.fill('inline-preview.wav');
   await view.getByRole('radio',{name:'Gallery'}).click();
   const inlineAudio=page.locator('[data-library-media-player="audio"]').first();
   await inlineAudio.getByRole('button',{name:'Play audio preview',exact:true}).click();
   const audioWave=inlineAudio.locator('[data-waveform-source="original-audio"]');await audioWave.waitFor({state:'visible',timeout:20000});
   assert.ok(await audioWave.locator('rect').evaluateAll(rects=>new Set(rects.map(rect=>rect.getAttribute('height'))).size>3),'waveform must reflect changing amplitude in the original audio');
   // WebAudio decoding and the native playback clock complete independently.
   // Observe actual playback; do not play or seek on behalf of the controls.
   const playingAudio=inlineAudio.locator('audio');
   try{await page.waitForFunction(audio=>audio.currentTime>0&&!audio.error,await playingAudio.elementHandle(),{timeout:10000});}
   catch(error){
    const diagnostic=await playingAudio.evaluate(audio=>({paused:audio.paused,ended:audio.ended,time:audio.currentTime,duration:Number.isFinite(audio.duration)?audio.duration:null,readyState:audio.readyState,networkState:audio.networkState,error:audio.error?{code:audio.error.code,message:audio.error.message}:null,hasSource:Boolean(audio.currentSrc),visibility:document.visibilityState,playerText:audio.closest('[data-library-media-player]')?.textContent}));
    throw new Error(`${error.message}\nActual WAV diagnostics (${engine} ${width}): ${JSON.stringify(diagnostic)}`);
   }
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
   // Exercise actual signed-source rotation through the query's existing timer.
   await audioTimeline.press('Home');
   for(let step=0;step<20;step++)await audioTimeline.press('ArrowRight');
   await page.waitForFunction(audio=>!audio.seeking&&Math.abs(audio.currentTime-1)<0.025,seekAudioHandle,{timeout:5000});
   const pausedRefresh=await seekAudio.evaluate(audio=>({url:audio.currentSrc,time:audio.currentTime,rate:audio.playbackRate,volume:audio.volume}));
   await page.evaluate(()=>{window.__rafiiRefreshAcceptanceEnabled=true;window.__rafiiRefreshAcceptance()});
   try{
    await page.waitForFunction(({audio,before})=>audio.currentSrc!==before.url&&audio.readyState>=1&&!audio.seeking&&Math.abs(audio.currentTime-before.time)<0.025,{audio:seekAudioHandle,before:pausedRefresh},{timeout:10000});
    assert.deepEqual(await seekAudio.evaluate(audio=>({paused:audio.paused,rate:audio.playbackRate,volume:audio.volume,error:audio.error?.code||null})),{paused:true,rate:pausedRefresh.rate,volume:pausedRefresh.volume,error:null},'paused refresh preserves offset, rate and volume');
    await inlineAudio.getByRole('combobox',{name:'Audio playback speed',exact:true}).selectOption('0.5');
    await inlineAudio.getByRole('button',{name:'Play audio preview',exact:true}).click();
    await page.waitForFunction(audio=>!audio.paused&&audio.currentTime>1.05,seekAudioHandle,{timeout:10000});
    const playingRefresh=await seekAudio.evaluate(audio=>({url:audio.currentSrc,time:audio.currentTime,volume:audio.volume}));
    await page.evaluate(()=>window.__rafiiRefreshAcceptance());
    await page.waitForFunction(({audio,before})=>audio.currentSrc!==before.url&&!audio.paused&&!audio.seeking&&!audio.error&&audio.currentTime>before.time+0.05,{audio:seekAudioHandle,before:playingRefresh},{timeout:10000});
    assert.deepEqual(await seekAudio.evaluate(audio=>({rate:audio.playbackRate,volume:audio.volume})),{rate:0.5,volume:playingRefresh.volume},'playing refresh retains preferences and advances from the saved offset');
    assert.ok(audioUrlRevision>=3,'both refreshes must fetch fresh source URLs from the real API');
    await inlineAudio.getByRole('button',{name:'Pause audio preview',exact:true}).click();
   }finally{await page.evaluate(()=>{window.__rafiiRefreshAcceptanceEnabled=false})}

   assert.equal(await inlineAudio.locator('button button').count(),0,'media controls cannot be nested inside details buttons');
   assert.ok(await inlineAudio.evaluate(element=>element.getBoundingClientRect().right<=innerWidth+1),'inline audio controls fit viewport');
   await page.addScriptTag({path:require.resolve('axe-core')});
   const mediaAccessibility=await page.evaluate(async()=>{const result=await axe.run(document.querySelector('[data-library-media-player="audio"]'));return result.violations.filter(item=>['critical','serious'].includes(item.impact)).map(item=>({id:item.id,impact:item.impact,nodes:item.nodes.map(node=>node.target)}));});
   assert.deepEqual(mediaAccessibility,[],'inline audio serious/critical accessibility violations');
   await page.screenshot({path:resolve(out,`inline-audio-${engine}-${width}.png`),fullPage:true});
   checks.push({engine,width,format:'wav',inline:'actual varying-amplitude waveform; play/pause; keyboard seek; speed; volume; paused/playing signed-source refresh; responsive',execution:'real original WAV/UI/decode; synthetic identity/storage'});
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
    const movPoster=movPlayer.locator('img');await waitForLoadedRaster(movPoster,0,15000);
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
   rememberFixtureAssets(beforeDelete.assets);
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
   recordDiagnostic('runtime:guard',{errorCount:errors.length,activePreviewIds:[...activePreviews.keys()]});
   assert.deepEqual(errors,[],`browser runtime errors (${engine} ${width}); RSC request failures: ${JSON.stringify(rscFailures)}`);
   checks.push({engine,width,status:'pass',flows:['upload','rename','tags','collection','search','source-review','audio-player','transcript','delete','responsive'],execution:'real UI/API/DB; synthetic storage/identity'});
   recordDiagnostic('context:close-requested',{activePreviewIds:[...activePreviews.keys()]});
   await context.close();
  }}finally{await browser.close();}
 }
 writeFileSync(resolve(out,'browser.json'),JSON.stringify({status:'pass',checks},null,2));console.log(JSON.stringify({status:'pass',checks}));
})().catch(error=>{writeFileSync(resolve(out,'browser-failure.json'),JSON.stringify({status:'fail',error:diagnosticText(String(error)),checks,diagnostics:{schemaVersion:1,limits:DIAGNOSTIC_LIMITS,contextsDropped:diagnosticContextsDropped,contexts:browserDiagnostics}},null,2));console.error(error);process.exitCode=1;});
