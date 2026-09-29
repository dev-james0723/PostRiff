'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const web = path.resolve(__dirname, '..');
const route = path.join(web, 'src/app/preview-window-recording');
const evidence = process.env.PREVIEW_EVIDENCE_DIR || '/tmp/rafii-recordings';
const url = 'http://127.0.0.1:3129/preview-window-recording';
assert.ok(!fs.existsSync(route), 'Refusing to overwrite an existing route');
fs.mkdirSync(route); fs.mkdirSync(evidence, { recursive:true });
fs.copyFileSync(path.join(__dirname,'preview-window-recording.tsx'),path.join(route,'page.tsx'));
const log = fs.openSync(path.join(evidence,'next.log'),'w');
const server = spawn(process.execPath,[require.resolve('next/dist/bin/next'),'dev','--hostname','127.0.0.1','-p','3129'],{cwd:web,env:{...process.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SENTRY_DISABLED:'1'},stdio:['ignore',log,log]});
const results = [];
let browser;
const wait = (ms)=>new Promise(r=>setTimeout(r,ms));
async function ready(){const end=Date.now()+150000;while(Date.now()<end){if(server.exitCode!==null)throw Error('Next exited');try{if((await fetch(url,{signal:AbortSignal.timeout(15000)})).ok)return;}catch{}await wait(1000);}throw Error('Next did not start');}
async function record(name, viewport, touch=false){
 const ctx = await browser.newContext({viewport,recordVideo:{dir:evidence,size:viewport},deviceScaleFactor:1,isMobile:touch,hasTouch:touch,colorScheme:'light',reducedMotion:'no-preference'});
 await ctx.addInitScript(()=>{try{localStorage.setItem('theme','light');}catch{}document.addEventListener('DOMContentLoaded',()=>{const pointer=document.createElement('div');pointer.id='recording-pointer';pointer.style.cssText='position:fixed;left:-100px;top:-100px;width:22px;height:22px;border:2px solid #51457a;background:#b3a1f06e;border-radius:50%;z-index:2147483646;pointer-events:none;transform:translate(-50%,-50%);box-shadow:0 1px 6px #0003;';document.body.append(pointer);const update=e=>{pointer.style.left=e.clientX+'px';pointer.style.top=e.clientY+'px';};document.addEventListener('pointermove',update,true);document.addEventListener('pointerdown',e=>{update(e);pointer.style.background='#6b4be8aa';pointer.style.transform='translate(-50%,-50%) scale(1.45)';},true);document.addEventListener('pointerup',()=>{pointer.style.background='#b3a1f06e';pointer.style.transform='translate(-50%,-50%)';},true);});});
 const started=Date.now(); const page=await ctx.newPage(); const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',r=>r.abort());
 await page.goto(url,{waitUntil:'networkidle',timeout:120000});
 await page.waitForTimeout(1800);
 const panel=page.locator('[data-preview-window]'); const handle=page.locator('[data-preview-drag-handle]');
 const video=page.video(); const cues=[]; const checks=[];
 const trim=(Date.now()-started)/1000;
 await page.evaluate(n=>{document.getElementById('demo-device').textContent=n;},name==='mobile'?'PHONE · 390 × 844':name==='ipad'?'IPAD · 1024 × 900':'DESKTOP · 1440 × 1000');
 async function cue(text){cues.push({at:(Date.now()-started)/1000-trim,text});await page.evaluate(t=>{document.getElementById('demo-action').textContent=t;},text);await page.waitForTimeout(1100);}
 async function hold(ms=1800){await page.waitForTimeout(ms);}
 async function bounded(){const b=await panel.boundingBox();assert.ok(b&&b.x>=0&&b.y>=0&&b.x+b.width<=page.viewportSize().width+1&&b.y+b.height<=page.viewportSize().height+1);return b;}
 async function mode(m){await page.waitForFunction(m=>document.querySelector('[data-preview-window]')?.dataset.mode===m,m);await hold(450);}
 let point={x:60,y:160};
 async function move(x,y,ms=1000){const from={...point};for(let i=1;i<=25;i++){await page.mouse.move(from.x+(x-from.x)*i/25,from.y+(y-from.y)*i/25);await page.waitForTimeout(ms/25);}point={x,y};}
 async function click(loc){const b=await loc.boundingBox();assert.ok(b);await move(b.x+b.width/2,b.y+b.height/2,650);await page.mouse.down();await hold(110);await page.mouse.up();await hold(800);}
 async function dragTo(x,y,release=true){const b=await handle.boundingBox();await move(b.x+35,b.y+22,550);await page.mouse.down();await hold(250);await move(x,y,1500);if(release)await page.mouse.up();await hold(550);}
 async function scroll(x,y,delta){await move(x,y,400);for(let i=0;i<8;i++){await page.mouse.wheel(0,delta/8);await hold(110);}await hold(900);}
 const cdp=touch?await ctx.newCDPSession(page):null;
 async function touchDrag(x1,y1,x2,y2){await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:x1,y:y1,id:1}]});await hold(300);for(let i=1;i<=24;i++){await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:x1+(x2-x1)*i/24,y:y1+(y2-y1)*i/24,id:1}]});await hold(55);}await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await hold(1000);}
 try{
  if(name==='mobile'){
   assert.equal(await panel.isVisible(),false);checks.push('desktop floating inspector hidden at phone width');
   await cue('Phone: scroll naturally through the conversation.');await hold(2200);
   await touchDrag(200,670,200,470);await hold(1400);
   const trigger=page.locator('[data-tour="variant-card"]').getByRole('button',{name:'Preview',exact:true});await trigger.scrollIntoViewIfNeeded();await hold(800);
   await cue('Tap Preview on the draft card.');const b=await trigger.boundingBox();await page.touchscreen.tap(b.x+b.width/2,b.y+b.height/2);
   await page.locator('figure:visible').first().waitFor({state:'visible'});await hold(4000);
   await cue('The real phone mockup opens in the existing popover.');await hold(3200);
   await page.screenshot({path:path.join(evidence,'mobile-preview.png')});checks.push('actual VariantCard opens actual PostPreview on touch tap');
   await cue('Tap outside to close. No floating window covers the chat.');await page.touchscreen.tap(8,300);await hold(1500);
   await page.keyboard.press('Escape');await touchDrag(195,675,195,420);await hold(2200);
   assert.equal(await panel.isVisible(),false);checks.push('phone inspector stays hidden after closing preview and scrolling');
   await cue('Phone behaviour is intentionally different from desktop.');await hold(2500);
  }else if(name==='ipad'){
   await panel.waitFor({state:'visible'});await mode('docked');await bounded();
   await cue('iPad: keep the phone visible while reading.');await hold(2000);await touchDrag(350,650,350,340);await bounded();
   await cue('Drag the top handle with a finger to detach.');let b=await handle.boundingBox();await touchDrag(b.x+35,b.y+22,140,185);await mode('floating');await bounded();checks.push('real touch pointer detaches the actual PreviewWindow');
   await cue('Resize from the corner. The preview stays proportional.');b=await page.locator('[data-preview-resize-handle]').boundingBox();await touchDrag(b.x+20,b.y+20,b.x-25,b.y-90);await mode('floating');await hold(1800);
   await cue('Sources remain usable while the preview floats.');b=await page.locator('[data-demo-sources]').boundingBox();await page.touchscreen.tap(b.x+b.width/2,b.y+b.height/2);await hold(1800);await mode('floating');checks.push('tablet resizing and Sources preserve floating state');
   await cue('Tap Dock to return to the original position.');b=await panel.getByRole('button',{name:'Dock',exact:true}).boundingBox();await page.touchscreen.tap(b.x+b.width/2,b.y+b.height/2);await mode('docked');await hold(2400);await page.screenshot({path:path.join(evidence,'ipad-docked.png')});checks.push('explicit Dock returns to docked mode');
  }else{
   await panel.waitFor({state:'visible'});await mode('docked');await bounded();
   await page.evaluate(()=>{window.__recordedPreview=document.querySelector('[data-preview-window] figure');});
   await cue('Scroll the conversation. The phone stays visible.');await hold(1800);await scroll(680,680,900);await bounded();checks.push('docked phone visible during scroll');
   await cue('Drag the top handle out of the right-hand dock.');await dragTo(395,200);await mode('floating');const before=await bounded();await hold(1600);
   await cue('Let go anywhere else: it stays floating.');await scroll(790,690,600);const after=await bounded();assert.ok(Math.abs(before.x-after.x)<1&&Math.abs(before.y-after.y)<1);await hold(1300);checks.push('floating window stays fixed while the conversation scrolls');
   await cue('Move it to the position that suits you.');await dragTo(175,180);await mode('floating');await hold(1400);
   await cue('Drag the corner to make the phone smaller.');const old=await bounded();const b=await page.locator('[data-preview-resize-handle]').boundingBox();await move(b.x+20,b.y+20,700);await page.mouse.down();await move(b.x-35,b.y-100,1300);await page.mouse.up();await hold(1000);assert.ok((await bounded()).width<old.width);await mode('floating');checks.push('proportional resize does not dock');
   await cue('Switch to Sources. The floating preview remains.');await click(page.locator('[data-demo-sources]'));await mode('floating');assert.ok(await page.locator('[data-demo-source-content]').isVisible());await hold(2200);await page.screenshot({path:path.join(evidence,'desktop-floating.png')});checks.push('Sources and floating phone visible together');
   await cue('Only dropping into the original target docks it.');await dragTo(300,210,false);const target=await page.locator('[data-preview-dock-target]').boundingBox();assert.ok(target);await move(target.x+target.width/2,target.y+28,1800);await hold(850);await page.mouse.up();await mode('docked');await bounded();await hold(2200);checks.push('release inside the actual dock target reattaches');
   assert.ok(await page.evaluate(()=>window.__recordedPreview===document.querySelector('[data-preview-window] figure')));checks.push('same phone preview DOM retained throughout desktop interactions');
   await cue('Same draft. Same phone. No reset when it moves.');await hold(2200);await page.screenshot({path:path.join(evidence,'desktop-docked.png')});
  }
  assert.deepEqual(errors,[]);
  results.push({name,status:'PASS',trimStartSeconds:trim,cues,checks,viewport,source:'Actual PreviewWindow, PostPreview and VariantCard at 08bbd52; isolated sample-content page, not signed-in website; Chromium emulation, not physical hardware.'});
 }catch(e){await page.screenshot({path:path.join(evidence,name+'-error.png')}).catch(()=>{});results.push({name,status:'FAIL',error:String(e),errors,trimStartSeconds:trim,cues,checks,viewport});throw e;}
 finally{await ctx.close();await video.saveAs(path.join(evidence,name+'.webm'));const raw=await video.path();if(raw!==path.join(evidence,name+'.webm'))fs.rmSync(raw,{force:true});fs.writeFileSync(path.join(evidence,'recordings.json'),JSON.stringify(results,null,2));}
}
(async()=>{try{await ready();browser=await chromium.launch({headless:true});await record('desktop',{width:1440,height:1000});await record('mobile',{width:390,height:844},true);await record('ipad',{width:1024,height:900},true);console.log(JSON.stringify(results,null,2));}catch(e){console.error(e);process.exitCode=1;}finally{if(browser)await browser.close();server.kill('SIGTERM');fs.closeSync(log);fs.rmSync(route,{recursive:true,force:true});}})();
