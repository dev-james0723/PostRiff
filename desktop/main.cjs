'use strict';
const {app,BrowserWindow,ipcMain,dialog,safeStorage,session}=require('electron');
const {spawn}=require('node:child_process');
const path=require('node:path');
const fs=require('node:fs');
const crypto=require('node:crypto');
const boundary=require('./boundary.cjs');
app.enableSandbox();
app.setName('PostRiff');
if(process.env.POSTRIFF_TEST_DATA)app.setPath('userData',process.env.POSTRIFF_TEST_DATA);
let child,window,origin,closing=false,poll;
const shellSecret=crypto.randomBytes(32).toString('hex');
const directory=app.getPath('userData');
const vault=path.join(directory,'device-vault.bin');
function loadDevice(){
 if(!fs.existsSync(vault))return null;
 if(!safeStorage.isEncryptionAvailable())throw new Error('OS protected storage is unavailable.');
 return JSON.parse(safeStorage.decryptString(fs.readFileSync(vault)));
}
async function post(route,token,body,desktop=false){
 const response=await fetch(origin+route,{method:'POST',headers:{'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha','Authorization':'Bearer '+token,...(desktop?{'X-PostRiff-Desktop':shellSecret}:{})},body:JSON.stringify(body),signal:AbortSignal.timeout(8000)});
 if(!response.ok)throw new Error('The local device operation was rejected. Reload the workspace and review its status.');
 return response.json();
}
function boot(){return new Promise((resolve,reject)=>{
 const base=path.join(app.getAppPath(),'bundle');
 const executable=path.join(base,'sidecar','postriff-sidecar'+(process.platform==='win32'?'.exe':''));
 const env={PATH:process.platform==='win32'?(process.env.SystemRoot+'\\System32'):'/usr/bin:/bin',LANG:'en_US.UTF-8',POSTRIFF_DESKTOP_SECRET:shellSecret};
 if(process.platform==='win32')env.SystemRoot=process.env.SystemRoot;
 child=spawn(executable,['--port',process.env.POSTRIFF_TEST_PORT||'4330','--data',path.join(directory,'local.sqlite3'),'--static',path.join(base,'web'),'--parent-watch'],{env,stdio:['pipe','pipe','pipe'],windowsHide:true});
 let buffer='';let settled=false;
 const timer=setTimeout(()=>{child.kill();reject(new Error('Sidecar startup timed out.'));},15000);
 child.stdout.on('data',raw=>{
  buffer+=raw.toString();if(buffer.length>4096){child.kill();return;}
  if(!buffer.includes('\n')||settled)return;
  try{const info=JSON.parse(buffer.split('\n')[0]);if(!Number.isInteger(info.port)||info.port<1||info.port>65535)throw Error();origin='http://127.0.0.1:'+info.port;settled=true;clearTimeout(timer);resolve();}catch{reject(new Error('Invalid sidecar handshake.'));}
 });
 child.stderr.on('data',()=>{});
 child.on('error',()=>{clearTimeout(timer);reject(new Error('Bundled sidecar could not start.'));});
 child.on('exit',()=>{clearTimeout(timer);if(!settled)reject(new Error('Local port unavailable or sidecar failed.'));else if(!closing){dialog.showErrorBox('PostRiff host stopped','Saved work remains on this device. Restart PostRiff to recover.');app.quit();}});
});}
app.whenReady().then(async()=>{
 fs.mkdirSync(directory,{recursive:true,mode:0o700});
 await boot();
 session.defaultSession.setPermissionRequestHandler((_web,_permission,callback)=>callback(false));
 session.defaultSession.setPermissionCheckHandler(()=>false);
 session.defaultSession.on('will-download',(event,item)=>{if(!item.getURL().startsWith('blob:'+origin+'/')&&!item.getURL().startsWith(origin+'/api/workspaces/'))event.preventDefault();});
 window=new BrowserWindow({width:1320,height:930,minWidth:390,minHeight:600,title:'PostRiff · Local Phase 3',webPreferences:{preload:path.join(__dirname,'preload.cjs'),sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,webviewTag:false}});
 window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 window.webContents.on('will-navigate',(event,url)=>{if(url!==origin+'/')event.preventDefault();});
 window.webContents.on('will-attach-webview',event=>event.preventDefault());
 ipcMain.handle('postriff:status',event=>{boundary.sender(event,window,origin);const d=loadDevice();return {desktop:true,protectedStorage:safeStorage.isEncryptionAvailable(),deviceId:d?.deviceId||null,workspaceId:d?.workspaceId||null,execution:'local-contracts',hostedPairing:'pending'};});
 ipcMain.handle('postriff:pair',async(event,input)=>{
  boundary.sender(event,window,origin);const p=boundary.pairInput(input);
  if(!safeStorage.isEncryptionAvailable())throw new Error('OS protected storage required for pairing.');
  const choice=await dialog.showMessageBox(window,{type:'question',buttons:['Cancel','Pair this device'],defaultId:0,cancelId:0,title:'Confirm local device pairing',message:p.name,detail:'Workspace: '+p.workspaceId+'\nThis local pairing grants draft/profile work only. Hosted pairing is not configured.'});
  if(choice.response!==1)return {canceled:true};
  const result=await post('/api/desktop/pair',p.token,{workspaceId:p.workspaceId,expectedRevision:p.expectedRevision,payload:{enrollmentId:p.enrollmentId,code:p.code,confirmedWorkspace:p.workspaceId,confirmedName:p.name}},true);
  if(result.runtimeResult.pairingRejected)throw new Error('Enrollment expired, was used, or did not match.');
  const device={workspaceId:p.workspaceId,deviceId:result.runtimeResult.deviceId,credential:result.runtimeResult.deviceCredential};
  fs.writeFileSync(vault,safeStorage.encryptString(JSON.stringify(device)),{mode:0o600});
  delete result.runtimeResult.deviceCredential;
  return result;
 });
 await window.loadURL(origin+'/');
 poll=setInterval(async()=>{
  try{const d=loadDevice();if(d)await post('/api/device/action',d.credential,{workspaceId:d.workspaceId,deviceId:d.deviceId,action:'heartbeat',payload:{}});}catch{/* Offline/revoked status comes from authoritative state; no login/retry mutation. */}
 },15000);
}).catch(error=>{dialog.showErrorBox('PostRiff could not start',error.message);app.quit();});
app.on('window-all-closed',()=>app.quit());
app.on('before-quit',event=>{
 if(closing)return;
 closing=true;clearInterval(poll);
 if(child&&child.exitCode===null){event.preventDefault();child.stdin.end();const timer=setTimeout(()=>child.kill('SIGKILL'),3000);child.once('exit',()=>{clearTimeout(timer);app.quit();});}
});
