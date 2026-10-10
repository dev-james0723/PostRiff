/**
 * Real WebKit/Chromium regression for the intermittent Library acceptance failure
 * `browser runtime errors (webkit 1440)`: "…/library/files/<id>/preview due to access control checks."
 *
 * WebKit refuses a fetch that a document starts after its own navigation has begun (reload or goto,
 * while the next document is still loading) and reports it as that `pageerror`; the request never
 * reaches the server. A fetch already in flight is merely cancelled ("Load request cancelled").
 * Library document previews retry every 3 s on 409/429 and refresh on timers, so a retry that fires
 * during the acceptance harness's reload/goto produced the error at random.
 *
 * This drives the application's real API client (web/src/lib/api/client.ts, transpiled unchanged) in
 * both engines. The raw-fetch control proves each run still reproduces the WebKit behaviour.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const http=require('node:http');
const path=require('node:path');
const ts=require('typescript');
const {chromium,webkit}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const clientPath=process.env.LIBRARY_PREVIEW_CLIENT||path.resolve(__dirname,'../src/lib/api/client.ts');
const compiled=ts.transpileModule(fs.readFileSync(clientPath,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const clientScript=`window.__client=(function(){const exports={};const require=name=>{throw new Error('client.ts must not import '+name+' at runtime')};${compiled}\nreturn exports;})();`;
const ASSET='a'.repeat(32);
const PREVIEW=/^\/api\/workspaces\/w\/library\/files\/[a-f0-9]{32}\/preview$/;
const ACCESS_CONTROL=/\/api\/workspaces\/w\/library\/files\/[a-f0-9]{32}\/preview due to access control checks\.$/;
const NEXT_DOCUMENT_DELAY_MS=1500;
// A request the page started just before navigation can reach the server just after the next
// document request; anything later than this was started after navigation began.
const IN_FLIGHT_GRACE_MS=200;
// Retry/refresh shapes of the preview query: a short retry loop, a one-shot retry timer, and a
// timer followed by the client's own awaits (token, headers) before fetch.
const START_PREVIEWS={
 control:`(function loop(){fetch('/api/workspaces/w/library/files/${ASSET}/preview',{headers:{Authorization:'Bearer dev:acceptance','X-PostRiff-Request':'founder-alpha'},cache:'no-store',signal:AbortSignal.timeout(90000)}).catch(()=>{});setTimeout(loop,100)})()`,
 client:`(function(){const api=window.__client.createApi(async()=>'dev:acceptance');const preview=()=>api.libraryPreviewUrl('w','${ASSET}').catch(()=>{});(function loop(){preview();setTimeout(loop,100)})();setTimeout(preview,300);setTimeout(async()=>{await Promise.resolve();preview()},600)})()`
};
(async()=>{
 const state={previews:0,documentRequests:0,documentDelay:0,navigationAt:0,previewsDuringNavigation:0};
 const server=http.createServer((request,response)=>{
  if(PREVIEW.test(new URL(request.url,'http://local').pathname)){
   state.previews++;if(state.navigationAt&&Date.now()-state.navigationAt>IN_FLIGHT_GRACE_MS)state.previewsDuringNavigation++;
   response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});
   return response.end(JSON.stringify({url:'https://storage.invalid/page.jpg',mime:'image/jpeg',page:1}));
  }
  state.documentRequests++;
  if(state.documentDelay)state.navigationAt=Date.now();
  setTimeout(()=>{response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});response.end('<!doctype html><meta charset="utf-8"><title>Library preview teardown</title><main>Library</main>')},state.documentDelay);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${server.address().port}`;
 const results=[],failures=[];
 try{
  for(const [engine,browserType] of Object.entries({webkit,chromium})){
   const browser=await browserType.launch({headless:true});
   try{
    for(const action of ['reload','goto'])for(const subject of ['control','client']){
     const context=await browser.newContext();
     // The acceptance harness intercepts storage hosts; keep request interception enabled here as well.
     await context.route('https://storage.invalid/**',route=>route.fulfill({status:204}));
     await context.addInitScript({content:clientScript});
     const page=await context.newPage(),pageErrors=[];
     page.on('pageerror',error=>pageErrors.push(error.message));
     Object.assign(state,{documentDelay:0,navigationAt:0,previewsDuringNavigation:0});
     await page.goto(base+'/library');
     const before=state.previews;
     await page.evaluate(code=>(0,eval)(code),START_PREVIEWS[subject]);
     const deadline=Date.now()+5000;while(state.previews===before&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,20));
     const previewsBeforeNavigation=state.previews-before;
     await page.waitForTimeout(250);
     state.documentDelay=NEXT_DOCUMENT_DELAY_MS;
     if(action==='reload')await page.reload();else await page.goto(base+'/library/next');
     state.documentDelay=0;state.navigationAt=0;await page.waitForTimeout(300);
     const result={engine,action,subject,previewsBeforeNavigation,previewsDuringNavigation:state.previewsDuringNavigation,pageErrors:pageErrors.map(message=>message.replace(/127\.0\.0\.1:\d+/,'127.0.0.1:[port]'))};
     results.push(result);console.log('LIBRARY_PREVIEW_TEARDOWN '+JSON.stringify(result));
     await context.close();
     const check=(condition,message)=>{if(!condition)failures.push(`${engine} ${action} ${subject}: ${message} ${JSON.stringify(result)}`)};
     check(previewsBeforeNavigation>0,'the preview loop must reach the server before navigation');
     if(subject==='control'){
      if(engine==='webkit')check(pageErrors.some(message=>ACCESS_CONTROL.test(message)),'raw fetch started during navigation no longer reproduces the WebKit access-control pageerror; re-evaluate this regression');
     }else{
      check(pageErrors.length===0,'the Library client produced a browser runtime error during navigation');
      check(state.previewsDuringNavigation===0,'the Library client started a preview request after navigation began');
     }
    }
   }finally{await browser.close()}
  }
 }finally{server.close()}
 assert.deepEqual(failures,[],'Library preview requests during page navigation');
 console.log('LIBRARY_PREVIEW_TEARDOWN pass '+results.length+' cases');
})().then(()=>process.exit(0),error=>{console.error(error);process.exit(1)});
