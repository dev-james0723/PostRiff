const {_electron:electron}=require('playwright');
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');const evidence=path.join(root,'docs/postriff-phase-3/evidence');
const data=fs.mkdtempSync(path.join(os.tmpdir(),'postriff-desktop-acceptance-'));
const executable=path.join(root,'desktop/artifacts/PostRiff-darwin-arm64/PostRiff.app/Contents/MacOS/PostRiff');
(async()=>{
 let app;let saved;let errors=[];
 async function launch(){const a=await electron.launch({executablePath:executable,cwd:os.tmpdir(),env:{...process.env,POSTRIFF_TEST_DATA:data,POSTRIFF_TEST_PORT:'4337'},timeout:20000});return a;}
 try{
 app=await launch();let page=await app.firstWindow();page.on('pageerror',e=>errors.push(e.message));await page.waitForLoadState('domcontentloaded');page.setDefaultTimeout(10000);
 const security=await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];const p=w.webContents.getLastWebPreferences();return {sandbox:p.sandbox,contextIsolation:p.contextIsolation,nodeIntegration:p.nodeIntegration};});assert.deepEqual(security,{sandbox:true,contextIsolation:true,nodeIntegration:false});
 assert.equal(await page.evaluate(()=>typeof window.require),'undefined');
 // Synthetic account plus approved source through the real packaged HTTP API.
 saved=await page.evaluate(async()=>{
 const request=async(url,body,token)=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body)});const b=await r.json();if(!r.ok)throw Error(JSON.stringify(b));return b;};
 const auth={principalKey:'phase3-fictional-desktop-'+crypto.randomUUID(),provider:'google',proof:'postriff-fixture-verified',requestId:crypto.randomUUID(),verifier:'a'.repeat(64),plan:'studio'};
 Object.assign(auth,await request('/api/auth/challenge',auth));let snap=await request('/api/auth/verify',auth);const access={workspaceId:snap.workspaceId,token:snap.token};
 const act=async(action,payload)=>{snap=await request('/api/workspaces/'+access.workspaceId+'/actions',{expectedRevision:snap.revision,action,payload},access.token);};
 await act('mode',{mode:'niche'});await act('context',{purpose:'Teach gardening',audience:'Curious beginners',subject:'Community workshop'});await act('source',{kind:'sample'});let source=snap.state.sources[0];await act('approve_source',{sourceId:source.id,factIds:source.facts.map(f=>f.id)});await act('profile_propose',{writing:'A clear short example.',tone:'warm'});await act('profile_decide',{decision:'approve'});await act('runtime',{selected:'deterministic-preview'});await act('idea',{idea:'Share the seed swap as a learning opportunity'});
 localStorage.setItem('postriff-alpha-access-v1',JSON.stringify(access));return access;
 });
 await page.reload();await page.getByText('Writing runtime & devices').click();
 await page.getByRole('checkbox').filter({visible:true}).first().check();
 await page.getByRole('button',{name:'Review two-draft request',exact:true}).click();
 await page.getByRole('button',{name:'Start synthetic preview · $0',exact:true}).click();
 await page.getByRole('heading',{name:'Candidate ready for review'}).waitFor({timeout:12000});
 await page.getByRole('button',{name:'Keep candidate for review',exact:true}).click();
 await page.getByText('Candidate saved for editorial review',{exact:true}).waitFor();
 await page.getByText('Offline edits & conflict recovery',{exact:true}).click();
 const area=page.locator('.p3-body textarea').first();await area.fill('独立編輯：保留這段文字。');await page.getByRole('button',{name:'Synchronize this edit',exact:true}).click();
 await page.screenshot({path:path.join(evidence,'desktop-runtime.png'),fullPage:true});await page.screenshot({path:path.join(evidence,'desktop-viewport.png')});
 await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),true);
 await page.screenshot({path:path.join(evidence,'mobile-runtime.png'),fullPage:true});await page.screenshot({path:path.join(evidence,'mobile-viewport.png')});
 await area.fill('Unsent local edit after network loss');await page.context().setOffline(true);await page.getByText('Offline · unsent edits stay',{exact:false}).waitFor();await page.context().setOffline(false);
 await page.getByText('Devices · local pairing',{exact:true}).click();await page.getByRole('button',{name:'Create five-minute enrollment'}).click();
 // Native confirmation is supplied only inside this synthetic acceptance harness.
 await app.evaluate(({dialog})=>{dialog.showMessageBox=async()=>({response:1,checkboxChecked:false});});
 await page.getByRole('button',{name:'Confirm in desktop',exact:true}).click();await page.getByText('Paired locally.',{exact:false}).waitFor();
 const device=await page.evaluate(()=>window.postriffDesktop.status());assert.ok(device.deviceId);assert.equal(device.protectedStorage,true);
 assert.equal(await page.evaluate(()=>Object.keys(window.postriffDesktop).sort().join(',')),'pair,status');
 await app.close();app=null;
 app=await launch();page=await app.firstWindow();await page.waitForLoadState('domcontentloaded');page.setDefaultTimeout(10000);
 await page.getByText('Writing runtime & devices').click();await page.getByText('Offline edits & conflict recovery',{exact:true}).click();
 assert.equal(await page.locator('.p3-body textarea').first().inputValue(),'Unsent local edit after network loss');
 assert.equal((await page.evaluate(()=>window.postriffDesktop.status())).deviceId,device.deviceId);
 await page.getByText('Devices · local pairing',{exact:true}).click();await page.getByRole('button',{name:'Revoke',exact:true}).click();await page.getByText('My desktop · revoked',{exact:false}).waitFor();
 await page.keyboard.press('Tab');assert.notEqual(await page.evaluate(()=>document.activeElement.tagName),'BODY');
 await app.close();app=null;
 let orphan=false;try{await fetch('http://127.0.0.1:4337/api/health',{signal:AbortSignal.timeout(1000)});orphan=true;}catch{}assert.equal(orphan,false);
 fs.writeFileSync(path.join(evidence,'desktop-acceptance.json'),JSON.stringify({status:'pass',execution:'packaged-macos-arm64-outside-development-cwd',security,nativePairing:'synthetic dialog acceptance injected only by test',restart:true,noOrphanSidecar:true,offlineEditRetained:true,deviceVaultPersisted:true,revocation:true,mobile:'390x844',errors,hostedAcceptance:false,dataDirectory:data},null,2));
 assert.equal(errors.length,0);console.log('Desktop acceptance passed');
 }finally{if(app)await app.close();}
})().catch(e=>{console.error(e);process.exit(1)});
